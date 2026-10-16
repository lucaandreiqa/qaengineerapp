"""TestRail: one test case per (check, page), auto-created, and a test run with results."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from ..models import RunResult, Severity

SECTION_NAME = "YourQA – automated website checks"
OLD_SECTION_NAMES = ("QA App – automated website checks",)  # keep using a section made under the old name
PASSED, FAILED = 1, 5


class TestRail:
    def __init__(self, cfg: dict):
        self.base = parse_link(cfg["base_url"])["base_url"] + "/index.php?/api/v2/"  # a pasted page link works too
        self.s = requests.Session()
        self.s.auth = (cfg["username"], cfg["api_key"])
        self.s.headers["Content-Type"] = "application/json"
        self.project = int(cfg["project_id"]) if str(cfg.get("project_id") or "").strip() else None
        self.suite = int(cfg["suite_id"]) if cfg.get("suite_id") else None

    def get(self, path: str):
        r = self.s.get(self.base + path, timeout=30); r.raise_for_status(); return r.json()

    def post(self, path: str, data: dict):
        r = self.s.post(self.base + path, json=data, timeout=30); r.raise_for_status(); return r.json()

    def paged(self, path: str, key: str) -> list:
        items, data = [], self.get(path)
        while True:
            items += data.get(key, []) if isinstance(data, dict) else data
            nxt = data.get("_links", {}).get("next") if isinstance(data, dict) else None
            if not nxt:
                return items
            data = self.get(nxt.removeprefix("/api/v2/"))

    def suite_q(self) -> str:
        return f"&suite_id={self.suite}" if self.suite else ""


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    tr = TestRail(cfg)
    sections = tr.paged(f"get_sections/{tr.project}{tr.suite_q()}", "sections")
    section = next((s for s in sections if s["name"] == SECTION_NAME), None) \
        or next((s for s in sections if s["name"] in OLD_SECTION_NAMES), None) \
        or tr.post(f"add_section/{tr.project}", {"name": SECTION_NAME, **({"suite_id": tr.suite} if tr.suite else {})})
    cases = {c["title"]: c["id"] for c in tr.paged(f"get_cases/{tr.project}{tr.suite_q()}&section_id={section['id']}", "cases")}

    results = []
    for check in result.config.checks:
        for page in result.pages:
            title = f"[{check}] {page.url}"[:250]
            if title not in cases:
                cases[title] = tr.post(f"add_case/{section['id']}", {"title": title})["id"]
            items = [f for f in result.findings if f.check == check and f.url == page.url]
            blocking = [f for f in items if f.severity in (Severity.CRITICAL, Severity.MAJOR)]
            comment = "\n".join(f"[{f.severity.value}] {f.title}: {f.details}" for f in items) or "No issues found."
            if shared.get("report_url"):
                comment += f"\n\nReport: {shared['report_url']}"
            refs = shared.get("jira_issues", [])
            results.append({"case_id": cases[title], "status_id": FAILED if blocking else PASSED,
                            "comment": comment[:4000], **({"defects": ",".join(refs[:10])} if blocking and refs else {})})

    run = tr.post(f"add_run/{tr.project}", {
        "name": f"YourQA {result.run_id} – {result.config.url}", "include_all": False,
        "case_ids": [r["case_id"] for r in results], **({"suite_id": tr.suite} if tr.suite else {})})
    tr.post(f"add_results_for_cases/{run['id']}", {"results": results})
    return f"run R{run['id']} with {len(results)} results"


class TestRailError(Exception):
    """A message for the user."""


ROUTES = {"projects/overview": "project_id", "suites/view": "suite_id", "cases/view": "case_id", "runs/view": "run_id"}


def parse_link(url: str) -> dict:
    """Any TestRail page link -> {base_url, and project_id / suite_id / case_id / run_id when the page names one}."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    u = urlparse(url)
    path = re.sub(r"/index\.php$", "", u.path.rstrip("/"))
    out = {"base_url": f"{u.scheme}://{u.netloc}{path}" if u.netloc else url.rstrip("/")}
    route = u.query.split("&")[0].lstrip("/")  # index.php?/suites/view/12&group_by=…
    for prefix, field in ROUTES.items():
        m = re.match(rf"{prefix}/(\d+)", route)
        if m:
            out[field] = m.group(1)
    return out


def _client(cfg: dict) -> "TestRail":
    return TestRail(cfg)


def resolve(cfg: dict) -> dict:
    """The settings with a clean base URL and the project (and suite) filled in: typed values win, then what the
    pasted link names, then TestRail itself (a suite, case or run page's project; or the only project there is)."""
    link = parse_link(cfg.get("base_url", ""))
    out = {**cfg, "base_url": link["base_url"]}
    for f in ("project_id", "suite_id"):
        if not str(out.get(f) or "").strip() and link.get(f):
            out[f] = link[f]
    if str(out.get("project_id") or "").strip():
        return out
    tr = _client({**out, "project_id": ""})
    if link.get("case_id"):
        out["suite_id"] = str(out.get("suite_id") or tr.get(f"get_case/{link['case_id']}").get("suite_id") or "")
    if link.get("run_id"):
        run = tr.get(f"get_run/{link['run_id']}")
        out["project_id"] = str(run.get("project_id") or "")
        out["suite_id"] = str(out.get("suite_id") or run.get("suite_id") or "")
    if not out.get("project_id") and out.get("suite_id"):
        out["project_id"] = str(tr.get(f"get_suite/{out['suite_id']}").get("project_id") or "")
    if not out.get("project_id"):
        data = tr.get("get_projects")
        projects = data.get("projects", []) if isinstance(data, dict) else data
        if len(projects) == 1:
            out["project_id"] = str(projects[0]["id"])
        else:
            names = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in projects[:12]) or "none visible to this account"
            raise TestRailError("Paste a link to a page of your project (its overview, a suite or a case), or type the "
                                f"Project ID. Projects: {names}")
    return out


def check(cfg: dict) -> tuple[str, dict]:
    """Connection test: (message, the fields it filled in for the card)."""
    r = resolve(cfg)
    p = _client(r).get(f"get_project/{r['project_id']}")
    filled = {k: str(r.get(k) or "") for k in ("base_url", "project_id", "suite_id")}
    return f"Connected · project {p.get('name')} (ID {r['project_id']})" + (f", suite {r['suite_id']}" if r.get("suite_id") else ""), filled


def test_connection(cfg: dict) -> str:
    return check(cfg)[0]


# ---------------------------------------------------------------------------------------------
# Ticket workflow (Testing board): draft cases from PASS items, push on explicit go-ahead.
# Sections are addressed by path, e.g. "Finance › Gift cards".
# ---------------------------------------------------------------------------------------------

def section_paths(cfg: dict) -> dict[str, int]:
    tr = TestRail(cfg)
    secs = tr.paged(f"get_sections/{tr.project}{tr.suite_q()}", "sections")
    by_id = {s["id"]: s for s in secs}

    def path(s: dict) -> str:
        parts = [s["name"]]
        while s.get("parent_id") and s["parent_id"] in by_id:
            s = by_id[s["parent_id"]]
            parts.append(s["name"])
        return " › ".join(reversed(parts))

    return {path(s): s["id"] for s in secs}


def find_section(cfg: dict, path: str) -> int | None:
    return section_paths(cfg).get(path)


def ensure_section(cfg: dict, path: str) -> int:
    tr = TestRail(cfg)
    existing = section_paths(cfg)
    parent = None
    built: list[str] = []
    for name in [p.strip() for p in path.split("›")]:
        built.append(name)
        key = " › ".join(built)
        if key in existing:
            parent = existing[key]
            continue
        body = {"name": name, **({"suite_id": tr.suite} if tr.suite else {}), **({"parent_id": parent} if parent else {})}
        parent = existing[key] = tr.post(f"add_section/{tr.project}", body)["id"]
    return parent


def section_cases(cfg: dict, section_id: int | None) -> list[dict]:
    if section_id is None:
        return []
    tr = TestRail(cfg)
    return [{"id": c["id"], "title": c["title"]}
            for c in tr.paged(f"get_cases/{tr.project}{tr.suite_q()}&section_id={section_id}", "cases")]


def add_case(cfg: dict, section_id: int, title: str, steps: str, expected: str) -> int:
    tr = TestRail(cfg)
    try:
        return tr.post(f"add_case/{section_id}", {"title": title, "custom_steps": steps, "custom_expected": expected})["id"]
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 400:  # template without those fields
            return tr.post(f"add_case/{section_id}", {"title": title})["id"]
        raise


def search_cases(cfg: dict, text: str, limit: int = 30) -> list[dict]:
    """Read-only: cases whose title contains the text, across the project (and suite, when one is set)."""
    r = resolve(cfg)  # the project may only be known through the suite or the link
    suite = f"&suite_id={r['suite_id']}" if str(r.get("suite_id") or "").strip() else ""
    data = _client(r).get(f"get_cases/{r['project_id']}{suite}&filter={requests.utils.quote(text)}&limit={limit}")
    cases = data.get("cases", []) if isinstance(data, dict) else data
    return [{"id": c.get("id"), "title": c.get("title", ""), "section_id": c.get("section_id")} for c in cases[:limit]]


def _paths(secs: list[dict]) -> dict[int, str]:
    by_id = {x["id"]: x for x in secs}

    def path(x: dict) -> str:
        parts = [x["name"]]
        while x.get("parent_id") and x["parent_id"] in by_id:
            x = by_id[x["parent_id"]]
            parts.append(x["name"])
        return " › ".join(reversed(parts))
    return {x["id"]: path(x) for x in secs}


def sample(cfg: dict, limit: int = 150) -> dict:
    """Read-only, for onboarding: the section tree and the most recently updated cases with their steps."""
    r = resolve(cfg)
    tr = _client(r)
    suite = f"&suite_id={r['suite_id']}" if str(r.get("suite_id") or "").strip() else ""
    data = tr.get(f"get_sections/{r['project_id']}{suite}")
    secs = data.get("sections", []) if isinstance(data, dict) else data
    paths = _paths(secs)
    data = tr.get(f"get_cases/{r['project_id']}{suite}&limit=250")
    cases = data.get("cases", []) if isinstance(data, dict) else data
    cases = sorted(cases, key=lambda c: c.get("updated_on") or 0, reverse=True)[:limit]

    def steps_of(c: dict) -> tuple[str, str]:
        sep = c.get("custom_steps_separated") or []
        if sep:
            return ("\n".join(f"{i}. {s.get('content', '')}" for i, s in enumerate(sep, 1)),
                    "\n".join(s.get("expected", "") for s in sep if s.get("expected")))
        return str(c.get("custom_steps") or ""), str(c.get("custom_expected") or "")
    out = []
    for c in cases:
        steps, expected = steps_of(c)
        out.append({"id": c.get("id"), "title": c.get("title", ""), "section": paths.get(c.get("section_id"), ""),
                    "steps": steps[:1500], "expected": expected[:800], "type": c.get("type_id"), "priority": c.get("priority_id")})
    return {"sections": sorted(paths.values()), "cases": out}
