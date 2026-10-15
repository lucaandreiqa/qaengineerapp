"""TestRail: one test case per (check, page), auto-created, and a test run with results."""
from __future__ import annotations

import requests

from ..models import RunResult, Severity

SECTION_NAME = "YourQA – automated website checks"
OLD_SECTION_NAMES = ("QA App – automated website checks",)  # keep using a section made under the old name
PASSED, FAILED = 1, 5


class TestRail:
    def __init__(self, cfg: dict):
        self.base = cfg["base_url"].rstrip("/") + "/index.php?/api/v2/"
        self.s = requests.Session()
        self.s.auth = (cfg["username"], cfg["api_key"])
        self.s.headers["Content-Type"] = "application/json"
        self.project = int(cfg["project_id"])
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


def test_connection(cfg: dict) -> str:
    tr = TestRail(cfg)
    p = tr.get(f"get_project/{tr.project}")
    return f"Connected — project {p['name']}"


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
    tr = TestRail(cfg)
    path = f"get_cases/{tr.project}{tr.suite_q()}&filter={requests.utils.quote(text)}&limit={limit}"
    data = tr.get(path)
    cases = data.get("cases", []) if isinstance(data, dict) else data
    return [{"id": c.get("id"), "title": c.get("title", ""), "section_id": c.get("section_id")} for c in cases[:limit]]
