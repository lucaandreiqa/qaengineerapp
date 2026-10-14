"""Xray Cloud (Jira test management): import the JUnit results as a Test Execution."""
from __future__ import annotations

from pathlib import Path

import requests

from ..models import RunResult

API = "https://xray.cloud.getxray.app/api/v2"


def _token(cfg: dict) -> str:
    r = requests.post(f"{API}/authenticate", json={"client_id": cfg["client_id"],
                                                   "client_secret": cfg["client_secret"]}, timeout=20)
    r.raise_for_status()
    return r.json()


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    junit = (Path(result.output_dir) / "junit.xml").read_bytes()
    r = requests.post(f"{API}/import/execution/junit", params={"projectKey": cfg["project_key"]},
                      headers={"Authorization": f"Bearer {_token(cfg)}", "Content-Type": "text/xml"},
                      data=junit, timeout=60)
    r.raise_for_status()
    return f"Test Execution {r.json().get('key')}"


def test_connection(cfg: dict) -> str:
    _token(cfg)
    return "Authenticated with Xray Cloud"
