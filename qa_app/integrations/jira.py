"""Jira Cloud: create one bug per finding (deduplicated across runs), with screenshot attached."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import requests

from ..models import Finding, RunResult, Severity

MAX_ISSUES_PER_RUN = 20
PRIORITY = {"critical": "Highest", "major": "High", "minor": "Medium", "info": "Low"}


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


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    min_rank = Severity(cfg.get("min_severity") or "major").rank
    candidates = [f for f in sorted(result.findings, key=lambda f: f.severity.rank) if f.severity.rank <= min_rank]
    s = _session(cfg)
    created, existing = [], []
    for f in candidates[:MAX_ISSUES_PER_RUN]:
        key = _existing_open(s, cfg, fingerprint(f))
        if key:
            existing.append(key)
            continue
        key = _create(s, cfg, f, result, shared.get("report_url"))
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

PR_ENV = re.compile(r"https?://pr-\d+\.ci-cd\.on-eva\.io/?", re.I)


def _components(fields: dict) -> list[str]:
    """Component names; the board maps them to FE / BE / FE+BE (Testing board settings)."""
    return [c.get("name", "") for c in fields.get("components") or [] if c.get("name")]


def search_column(cfg: dict, project: str, column: str) -> list[dict]:
    """Tickets in a board column (matched by status name)."""
    s = _session(cfg)
    jql = f'project = "{project}" AND status = "{column}" ORDER BY updated DESC'
    r = s.post(f"{_base(cfg)}/rest/api/3/search/jql", timeout=20,
               json={"jql": jql, "maxResults": 50, "fields": ["summary", "status", "components", "labels"]})
    r.raise_for_status()
    return [{"key": i["key"], "title": i["fields"].get("summary", ""),
             "status": (i["fields"].get("status") or {}).get("name", ""), "components": _components(i["fields"])}
            for i in r.json().get("issues", [])]


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
    s = _session(cfg)
    r = s.get(f"{_base(cfg)}/rest/api/2/issue/{key}", timeout=20,
              params={"fields": "summary,status,components,labels,description,comment"})
    r.raise_for_status()
    raw = r.json()
    f = raw["fields"]
    comments = [c.get("body", "") for c in (f.get("comment") or {}).get("comments", [])]
    out = {"key": raw["key"], "title": f.get("summary", ""), "status": (f.get("status") or {}).get("name", ""),
           "description": f.get("description") or "", "components": _components(f), "comments": comments,
           "merged": False, "pr_url": "", "preview_url": ""}
    out.update(_pull_requests(s, cfg, raw.get("id", "")))
    for c in reversed(comments):  # a frontend preview link posted on the ticket
        m = re.search(r"https://[\w.-]+\.(pages\.dev|on-eva\.io|eva-online\.cloud)/?\S*", c)
        if m and not PR_ENV.match(m.group(0)):
            out["preview_url"] = m.group(0)
            break
    return out


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


def find_pr_environment(comments: list[str]) -> str:
    for c in reversed(comments):
        m = PR_ENV.search(c)
        if m:
            return m.group(0).rstrip("/") + "/"
    return ""


def create_for_finding(cfg: dict, f: Finding, result: RunResult, report_url: str | None = None) -> str:
    """One issue for one finding (the Run screen's "Create Jira issue"), deduplicated like publish()."""
    s = _session(cfg)
    return _existing_open(s, cfg, fingerprint(f)) or _create(s, cfg, f, result, report_url)
