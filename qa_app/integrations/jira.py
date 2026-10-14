"""Jira Cloud: create one bug per finding (deduplicated across runs), with screenshot attached."""
from __future__ import annotations

import hashlib
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
