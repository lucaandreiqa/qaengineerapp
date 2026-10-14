"""Microsoft Teams notifications (Workflows / incoming webhook, Adaptive Card payload)."""
from __future__ import annotations

import requests

from ..models import RunResult, Severity


def _card(body: list, actions: list | None = None) -> dict:
    content = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
               "type": "AdaptiveCard", "version": "1.4", "body": body}
    if actions:
        content["actions"] = actions
    return {"type": "message", "attachments": [
        {"contentType": "application/vnd.microsoft.card.adaptive", "content": content}]}


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    if cfg.get("only_on_failure") and result.passed:
        return "skipped (run passed)"
    worst = [f for f in sorted(result.findings, key=lambda f: f.severity.rank) if f.severity != Severity.INFO][:5]
    body = [
        {"type": "TextBlock", "size": "Large", "weight": "Bolder",
         "color": "Good" if result.passed else "Attention",
         "text": f"QA run {'passed' if result.passed else 'failed'}"},
        {"type": "TextBlock", "wrap": True, "text": result.summary_line()},
    ] + [{"type": "TextBlock", "wrap": True, "spacing": "None",
          "text": f"- **{f.severity.value}** [{f.check}] {f.title} — {f.url}"} for f in worst]
    if shared.get("jira_issues"):
        body.append({"type": "TextBlock", "wrap": True, "text": "Jira: " + ", ".join(shared["jira_issues"][:10])})
    actions = [{"type": "Action.OpenUrl", "title": "Open report", "url": shared["report_url"]}] \
        if shared.get("report_url") else None
    resp = requests.post(cfg["webhook_url"], json=_card(body, actions), timeout=15)
    resp.raise_for_status()
    return "message sent"


def test_connection(cfg: dict) -> str:
    resp = requests.post(cfg["webhook_url"], json=_card(
        [{"type": "TextBlock", "text": "YourQA: connection test ✅"}]), timeout=15)
    resp.raise_for_status()
    return "Test message sent"
