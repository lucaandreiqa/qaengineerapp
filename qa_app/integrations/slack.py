"""Slack incoming-webhook notifications."""
from __future__ import annotations

import requests

from ..models import RunResult, Severity


def _top(result: RunResult, n: int = 5) -> str:
    worst = sorted(result.findings, key=lambda f: f.severity.rank)[:n]
    return "\n".join(f"• *{f.severity.value}* [{f.check}] {f.title} — {f.url}" for f in worst
                     if f.severity != Severity.INFO) or "No blocking issues."


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    if cfg.get("only_on_failure") and result.passed:
        return "skipped (run passed)"
    icon = ":white_check_mark:" if result.passed else ":x:"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"QA run {'passed' if result.passed else 'failed'}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{icon} {result.summary_line()}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _top(result)}},
    ]
    if shared.get("jira_issues"):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": "Jira: " + ", ".join(shared["jira_issues"][:10])}]})
    if shared.get("report_url"):
        blocks.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text",
                       "text": "Open report"}, "url": shared["report_url"]}]})
    resp = requests.post(cfg["webhook_url"], json={"text": result.summary_line(), "blocks": blocks}, timeout=15)
    resp.raise_for_status()
    return "message sent"


def test_connection(cfg: dict) -> str:
    resp = requests.post(cfg["webhook_url"], json={"text": "YourQA: connection test ✅"}, timeout=15)
    resp.raise_for_status()
    return "Test message sent"
