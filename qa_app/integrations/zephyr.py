"""Zephyr Scale Cloud: upload JUnit results as an automated test cycle."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import requests

from ..models import RunResult

API = "https://api.zephyrscale.smartbear.com/v2"


def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['api_token']}"}


def publish(result: RunResult, cfg: dict, shared: dict, log) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(Path(result.output_dir) / "junit.xml", "junit.xml")
    r = requests.post(f"{API}/automations/executions/junit", headers=_headers(cfg),
                      params={"projectKey": cfg["project_key"], "autoCreateTestCases": "true"},
                      files={"file": ("results.zip", buf.getvalue(), "application/zip")}, timeout=60)
    r.raise_for_status()
    cycle = r.json().get("testCycle", {})
    return f"test cycle {cycle.get('key', 'created')}"


def test_connection(cfg: dict) -> str:
    r = requests.get(f"{API}/projects/{cfg['project_key']}", headers=_headers(cfg), timeout=20)
    r.raise_for_status()
    return f"Connected — project {cfg['project_key']}"
