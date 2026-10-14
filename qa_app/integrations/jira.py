"""Jira Cloud over its REST API with an email + API token.

Used when Jira is connected with "API token" instead of Atlassian sign-in: discover() reads the board from the
same pasted link, and the Testing board reads and moves tickets. Site-check findings become bugs (one per finding,
deduplicated across runs) whichever way Jira is connected: with Atlassian sign-in they go through the MCP server.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import requests

from ..models import Finding, RunResult, Severity

MAX_ISSUES_PER_RUN = 20
PRIORITY = {"critical": "Highest", "major": "High", "minor": "Medium", "info": "Low"}


class JiraError(Exception):
    """A message for the user."""


def _session(cfg: dict) -> requests.Session:
    s = requests.Session()
    s.auth = (cfg["email"], cfg["api_token"])
    s.headers["Accept"] = "application/json"
    return s


def _base(cfg: dict) -> str:
    return cfg["base_url"].rstrip("/")


def fingerprint(f: Finding) -> str:
    """Stable id for the same problem on the same page, stored as a Jira label."""
    return "qa-app-" + hashlib.sha1(f"{f.check}|{f.title}|{f.url}".encode()).hexdigest()[:12]


def _existing_open(s: requests.Session, cfg: dict, label: str) -> str | None:
    jql = f'project = "{cfg["project_key"]}" AND labels = "{label}" AND statusCategory != Done'
    r = s.post(f"{_base(cfg)}/rest/api/3/search/jql", json={"jql": jql, "fields": ["key"], "maxResults": 1}, timeout=20)
    r.raise_for_status()
    issues = r.json().get("issues", [])
    return issues[0]["key"] if issues else None


def _create(s: requests.Session, cfg: dict, f: Finding, result: RunResult, report_url: str | None) -> str:
    desc = (f"*Automated finding from QA App*\n\n"
            f"*Check:* {f.check}\n*Severity:* {f.severity.value}\n*Page:* {f.url}\n"
            f"*Run:* {result.run_id} on {result.config.url}\n\n{{noformat}}{f.details or '—'}{{noformat}}\n")
    if report_url:
        desc += f"\n[Full report|{report_url}]"
    fields = {"project": {"key": cfg["project_key"]},
              "summary": f"[QA][{f.check}] {f.title}"[:240],
              "description": desc,
              "issuetype": {"name": cfg.get("issue_type") or "Bug"},
              "labels": ["qa-app", fingerprint(f), f"qa-{f.check}"]}
    r = s.post(f"{_base(cfg)}/rest/api/2/issue", json={"fields": {**fields, "priority": {"name": PRIORITY[f.severity.value]}}},
               timeout=20)
    if r.status_code == 400 and "priority" in r.text:   # priority not on the create screen
        r = s.post(f"{_base(cfg)}/rest/api/2/issue", json={"fields": fields}, timeout=20)
    r.raise_for_status()
    key = r.json()["key"]
    if f.screenshot and Path(f.screenshot).exists():
        with open(f.screenshot, "rb") as fh:
            s.post(f"{_base(cfg)}/rest/api/2/issue/{key}/attachments", headers={"X-Atlassian-Token": "no-check"},
                   files={"file": (Path(f.screenshot).name, fh, "image/png")}, timeout=60)
    return key


def ready(cfg: dict) -> str:
    """'' when bugs can be filed, else what is missing."""
    if cfg.get("auth") == "mcp":
        return "" if cfg.get("cloud_id") and cfg.get("project_key") else "Connect Jira on the Integrations screen first"
    missing = [k for k in ("base_url", "email", "api_token", "project_key") if not str(cfg.get(k, "")).strip()]
    return "Connect Jira on the Integrations screen first (" + ", ".join(missing) + " missing)" if missing else ""


class _RestBugs:
    def __init__(self, cfg: dict) -> None:
        self.cfg, self.s = cfg, _session(cfg)

    def find_open(self, label: str) -> str | None:
        return _existing_open(self.s, self.cfg, label)

    def create(self, f: Finding, result: RunResult, report_url: str | None) -> str:
        return _create(self.s, self.cfg, f, result, report_url)


class _McpBugs:
    """The same through Atlassian's MCP server (markdown description, no screenshot upload)."""

    def __init__(self, cfg: dict) -> None:
        from .atlassian_mcp import AtlassianMcp
        self.cfg, self.mcp = cfg, AtlassianMcp.signed_in(cfg["cloud_id"])

    def find_open(self, label: str) -> str | None:
        jql = f'project = "{self.cfg["project_key"]}" AND labels = "{label}" AND statusCategory != Done'
        res = self.mcp.op("searchJiraIssuesUsingJql", jql=jql, fields=["summary"], maxResults=1)
        issues = res.get("issues", []) if isinstance(res, dict) else []
        return issues[0].get("key") if issues else None

    def create(self, f: Finding, result: RunResult, report_url: str | None) -> str:
        desc = (f"**Automated finding from QA Engineer App**\n\n- **Check:** {f.check}\n- **Severity:** {f.severity.value}\n"
                f"- **Page:** {f.url}\n- **Run:** {result.run_id} on {result.config.url}\n\n```\n{f.details or '-'}\n```\n")
        if report_url:
            desc += f"\n[Full report]({report_url})\n"
        res = self.mcp.op("createJiraIssue", projectKey=self.cfg["project_key"], issueTypeName=self.cfg.get("issue_type") or "Bug",
                          summary=f"[QA][{f.check}] {f.title}"[:240], description=desc, contentFormat="markdown",
                          additional_fields={"labels": ["qa-app", fingerprint(f), f"qa-{f.check}"]})
        key = res.get("key") if isinstance(res, dict) else ""
        if not key:
            raise JiraError("Jira didn't return the new issue's key")
        return key


def _bugs(cfg: dict):
    return _McpBugs(cfg) if cfg.get("auth") == "mcp" else _RestBugs(cfg)


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    if not cfg.get("bugs_on_runs"):
        return "off (turn on 'File bugs after each site check' on the Jira integration)"
    min_rank = Severity(cfg.get("min_severity") or "major").rank
    candidates = [f for f in sorted(result.findings, key=lambda f: f.severity.rank) if f.severity.rank <= min_rank]
    b = _bugs(cfg)
    created, existing = [], []
    for f in candidates[:MAX_ISSUES_PER_RUN]:
        key = b.find_open(fingerprint(f))
        if key:
            existing.append(key)
            continue
        key = b.create(f, result, shared.get("report_url"))
        created.append(key)
        log(f"  Jira {key}: {f.title}")
    shared["jira_issues"] = created + existing
    skipped = max(0, len(candidates) - MAX_ISSUES_PER_RUN)
    return f"{len(created)} created, {len(existing)} already open" + (f", {skipped} over limit" if skipped else "")


def test_connection(cfg: dict) -> str:
    s = _session(cfg)
    me = s.get(f"{_base(cfg)}/rest/api/2/myself", timeout=15)
    me.raise_for_status()
    proj = s.get(f"{_base(cfg)}/rest/api/2/project/{cfg['project_key']}", timeout=15)
    proj.raise_for_status()
    return f"Connected as {me.json().get('displayName')} — project {proj.json().get('name')}"


# ---------------------------------------------------------------------------------------------
# Ticket workflow (Testing board): read tickets, post the QA comment, move the ticket.
# ---------------------------------------------------------------------------------------------

def _components(fields: dict) -> list[str]:
    """Component names; the board maps them to FE / BE / FE+BE (Testing board settings)."""
    return [c.get("name", "") for c in fields.get("components") or [] if c.get("name")]


def search_column(cfg: dict, project: str, column: str, status_ids: list[str] | None = None) -> list[dict]:
    """Tickets in a board column: its statuses when known (a board column can hold several), else the status name."""
    from .atlassian_mcp import status_jql
    s = _session(cfg)
    where = f"status in ({status_jql(status_ids)})" if status_ids else f'status = "{column}"'
    jql = f'project = "{project}" AND {where} ORDER BY updated DESC'
    r = s.post(f"{_base(cfg)}/rest/api/3/search/jql", timeout=20,
               json={"jql": jql, "maxResults": 50, "fields": ["summary", "status", "components", "labels", "issuetype", "priority"]})
    r.raise_for_status()
    from ..workflow.ticket_context import brief
    return [brief(i) for i in r.json().get("issues", [])]


def _pull_requests(s: requests.Session, cfg: dict, issue_id: str) -> dict:
    """PR state from the development panel, when the Git integration exposes it."""
    for app in ("GitHub", "bitbucket", "GitLab"):
        try:
            r = s.get(f"{_base(cfg)}/rest/dev-status/latest/issue/detail", timeout=15,
                      params={"issueId": issue_id, "applicationType": app, "dataType": "pullrequest"})
            if not r.ok:
                continue
            prs = [pr for d in r.json().get("detail", []) for pr in d.get("pullRequests", [])]
        except (requests.RequestException, ValueError):
            continue
        if prs:
            return {"merged": any(pr.get("status") == "MERGED" for pr in prs), "pr_url": prs[0].get("url", "")}
    return {}


def get_issue(cfg: dict, key: str) -> dict:
    """Everything on the ticket: all fields (custom ones by name), comments, attachments, links, web links."""
    from ..workflow.ticket_context import build

    s = _session(cfg)
    r = s.get(f"{_base(cfg)}/rest/api/2/issue/{key}", timeout=30, params={"fields": "*all", "expand": "names"})
    r.raise_for_status()
    raw = r.json()
    comments = None
    cm = raw["fields"].get("comment") or {}
    if isinstance(cm, dict) and cm.get("total", 0) > len(cm.get("comments", [])):  # more than one page: read them all
        comments, start = [], 0
        while start < cm["total"] and start < 1000:
            p = s.get(f"{_base(cfg)}/rest/api/2/issue/{key}/comment", timeout=30, params={"startAt": start, "maxResults": 100})
            p.raise_for_status()
            page = p.json().get("comments", [])
            if not page:
                break
            comments += page
            start += len(page)
    try:
        rl = s.get(f"{_base(cfg)}/rest/api/2/issue/{key}/remotelink", timeout=20)
        links = rl.json() if rl.ok else []
    except (requests.RequestException, ValueError):
        links = []
    out = issue_dict(build(raw, comments, links))
    out.update(_pull_requests(s, cfg, raw.get("id", "")))
    return out


def issue_dict(ctx: dict) -> dict:
    """What the Testing board reads from a ticket, with the full context alongside."""
    bodies = [c["body"] for c in ctx["comments"]]
    return {"key": ctx["key"], "title": ctx["title"], "status": ctx["status"], "description": ctx["description"],
            "components": ctx["components"], "labels": ctx["labels"], "comments": bodies, "merged": False, "pr_url": "",
            "context": ctx}


def add_comment(cfg: dict, key: str, text: str) -> None:
    # The template uses **bold**; Jira wiki markup (API v2) uses *bold*.
    body = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    r = _session(cfg).post(f"{_base(cfg)}/rest/api/2/issue/{key}/comment", json={"body": body}, timeout=20)
    r.raise_for_status()


def get_transitions(cfg: dict, key: str) -> list[dict]:
    r = _session(cfg).get(f"{_base(cfg)}/rest/api/2/issue/{key}/transitions", timeout=20)
    r.raise_for_status()
    return [{"id": t["id"], "name": t["name"]} for t in r.json().get("transitions", [])]


def do_transition(cfg: dict, key: str, transition_id: str) -> str:
    s = _session(cfg)
    r = s.post(f"{_base(cfg)}/rest/api/2/issue/{key}/transitions", json={"transition": {"id": transition_id}}, timeout=20)
    r.raise_for_status()
    st = s.get(f"{_base(cfg)}/rest/api/2/issue/{key}", params={"fields": "status"}, timeout=20)
    st.raise_for_status()
    return st.json()["fields"]["status"]["name"]


def create_for_finding(cfg: dict, f: Finding, result: RunResult, report_url: str | None = None) -> str:
    """One issue for one finding (the Run screen's "Create Jira issue"), deduplicated like publish()."""
    b = _bugs(cfg)
    return b.find_open(fingerprint(f)) or b.create(f, result, report_url)


# ---------------------------------------------------------------------------------------------
# Connect with an API token: read the board from the pasted link (the token alternative to Atlassian sign-in).
# ---------------------------------------------------------------------------------------------

def _get(s: requests.Session, base: str, path: str, **params) -> dict | list:
    try:
        r = s.get(base + path, params=params or None, timeout=20)
    except requests.RequestException as e:
        raise JiraError(f"Can't reach {base}: {e.__class__.__name__}") from e
    if r.status_code in (401, 403) and path.endswith("/myself"):
        raise JiraError("Jira didn't accept that email and API token. Check both, and that the token belongs to this email "
                        "(create one at id.atlassian.com/manage-profile/security/api-tokens).")
    if r.status_code == 404:
        raise JiraError(f"Not found on {base}: {path.split('?')[0]}")
    if not r.ok:
        raise JiraError(f"Jira answered HTTP {r.status_code} for {path.split('?')[0]}: {r.text[:150]}")
    try:
        return r.json()
    except ValueError as e:
        raise JiraError(f"{base} didn't answer like Jira. Is the link right?") from e


def _count_jql(s: requests.Session, base: str, jql: str) -> int | None:
    try:
        r = s.post(f"{base}/rest/api/3/search/approximate-count", json={"jql": jql}, timeout=15)
        return int(r.json()["count"]) if r.ok else None
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def discover(cfg: dict, link: dict) -> dict:
    """The same picture as the Atlassian sign-in gives (site, you, project, board, columns), read with email + API token."""
    from ..workflow.models import status_category
    from .atlassian_mcp import STATUS_ORDER, status_jql

    base = link["base_url"]
    s = _session({**cfg, "base_url": base})
    me = _get(s, base, "/rest/api/2/myself")
    user = {"name": me.get("displayName", ""), "email": me.get("emailAddress", "") or cfg.get("email", ""), "account_id": me.get("accountId", "")}
    board_id, key = link.get("board_id", ""), link.get("project_key", "")
    boards: list[dict] = []
    if not board_id and key:
        try:
            res = _get(s, base, "/rest/agile/1.0/board", projectKeyOrId=key, maxResults=50)
            boards = [{"id": str(b.get("id")), "name": b.get("name", "")} for b in res.get("values", [])]
        except JiraError:
            boards = []
        board_id = boards[0]["id"] if boards else ""
    bcfg = None
    if board_id:
        try:
            board_info = _get(s, base, f"/rest/agile/1.0/board/{board_id}")
            bcfg = _get(s, base, f"/rest/agile/1.0/board/{board_id}/configuration")
        except JiraError as e:
            raise JiraError(f"Can't open board {board_id} on {link['site']}: {e}") from e
        key = key or (board_info.get("location") or {}).get("projectKey", "")
    if not key:
        raise JiraError("The link has no project in it. Paste the link of the board you test from (it contains /projects/KEY/boards/…).")
    try:
        p = _get(s, base, f"/rest/api/2/project/{key}")
    except JiraError as e:
        raise JiraError(f"Project {key} is not on {link['site']}, or this account can't see it.") from e
    project = {"key": key, "name": p.get("name", key),
               "style": "team-managed" if p.get("style") == "next-gen" else "company-managed" if p.get("style") else ""}
    all_status = {}
    try:
        all_status = {str(x.get("id")): x for x in _get(s, base, "/rest/api/2/status")}
    except JiraError:
        pass
    columns: list[dict] = []
    if bcfg:
        columns_from = "board"
        board = {"id": str(board_id), "name": bcfg.get("name", f"Board {board_id}"), "type": bcfg.get("type", "")}
        for c in (bcfg.get("columnConfig") or {}).get("columns") or []:
            ids = [str(x.get("id")) for x in c.get("statuses", []) if x.get("id")]
            if not c.get("name"):
                continue
            first = all_status.get(ids[0], {"name": c["name"]}) if ids else {"name": c["name"]}
            columns.append({"name": c["name"], "status_ids": ids, "statuses": [all_status.get(i, {}).get("name", i) for i in ids],
                            "category": status_category(first),
                            "count": _count_jql(s, base, f'project = "{key}" AND status in ({status_jql(ids)})') if ids else None})
    else:  # no board: the project's statuses, in workflow order
        columns_from = "statuses"
        board = {"id": "", "name": f"{project['name']} statuses", "type": "statuses"}
        seen: dict[str, dict] = {}
        for it in _get(s, base, f"/rest/api/2/project/{key}/statuses"):
            for st in it.get("statuses", []):
                seen.setdefault(str(st.get("id")), st)
        order = lambda st: STATUS_ORDER.get(str((st.get("statusCategory") or {}).get("key", "")).lower(), 1)  # noqa: E731
        for sid, st in sorted(seen.items(), key=lambda kv: order(kv[1])):
            columns.append({"name": st.get("name", sid), "status_ids": [sid], "statuses": [st.get("name", sid)],
                            "category": status_category(st), "count": _count_jql(s, base, f'project = "{key}" AND status = {sid}')})
    try:
        components = [c.get("name", "") for c in _get(s, base, f"/rest/api/2/project/{key}/components") if c.get("name")]
    except JiraError:
        components = []
    return {"site": link["site"], "base_url": base, "cloud_id": "", "user": user, "project": project, "board": board,
            "boards": boards, "columns": columns, "columns_from": columns_from, "components": components, "link": link}
