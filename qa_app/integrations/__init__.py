"""Publishes a finished run to every enabled integration.

Order matters: AWS goes first so the report link can be shared in Slack/Teams/Jira.
"""
from __future__ import annotations

from typing import Callable

from ..models import RunResult
from . import aws_s3, jira, slack, teams, testrail, xray, zephyr

ORDER = [("aws", aws_s3), ("jira", jira), ("testrail", testrail), ("xray", xray),
         ("zephyr", zephyr), ("slack", slack), ("teams", teams)]


def publish(result: RunResult, settings: dict, log: Callable[[str], None] = print,
            only: list[str] | None = None) -> dict:
    """Return {integration: outcome-string}. Failures in one integration never stop the others."""
    shared: dict = {"report_url": None, "jira_issues": []}
    outcomes = {}
    for name, module in ORDER:
        cfg = settings.get(name, {})
        if not cfg.get("enabled") or (only and name not in only):
            continue
        try:
            outcomes[name] = module.publish(result, cfg, shared, log) or "ok"
            log(f"{name}: {outcomes[name]}")
        except Exception as e:
            outcomes[name] = f"error: {str(e).splitlines()[0]}"
            log(f"{name} failed: {e}")
    return outcomes


def test_connection(name: str, cfg: dict) -> str:
    module = dict(ORDER)[name]
    return module.test_connection(cfg)
