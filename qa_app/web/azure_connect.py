"""Connect Azure Boards from a pasted board link + personal access token, then pick the QA column.

Plain functions so they can be tested without the web server; server.py exposes them as /api/azure/*.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from ..config import load_settings, save_section
from ..integrations import azure_boards as ab


class ConnectError(Exception):
    pass


def connect(link_text: str, pat: str, http: Optional[requests.Session] = None) -> dict:
    try:
        link = ab.parse_azure_link(link_text)
    except ValueError as e:
        raise ConnectError(str(e)) from e
    pat = (pat or "").strip() or load_settings().get("azure", {}).get("pat", "")
    if not pat:
        raise ConnectError("Paste a personal access token (Azure DevOps → User settings → Personal access tokens, "
                           "scope Work Items: Read & write)")
    try:
        info = ab.discover(ab.Azure(link["org_url"], pat, http), link)
    except ab.AzureError as e:
        raise ConnectError(str(e)) from e
    _save(info, pat)
    return info


def _save(info: dict, pat: str) -> None:
    s = load_settings()
    b = info["board"]
    save_section("azure", {"enabled": True, "org_url": info["base_url"], "pat": pat, "project": info["project"]["name"],
                           "team": b["team"], "board": b["board"], "column_field": b["column_field"],
                           "link": info["link"], "connection": {**info, "connected_at": time.time()}})
    wf = s.get("workflow", {})
    if (wf.get("tracker") or "jira") == "azure":  # keep the column if it still exists
        names = {c["name"] for c in info["columns"]}
        if wf.get("jira_column") not in names:
            save_section("workflow", {"jira_column": ""})


def status() -> dict:
    s = load_settings()
    a, wf = s.get("azure", {}), s.get("workflow", {})
    conn = a.get("connection") or {}
    active = wf.get("tracker") == "azure"
    return {"connected": bool(conn) and bool(a.get("pat")), "signedIn": bool(a.get("pat")), "connection": conn or None,
            "column": wf.get("jira_column", "") if active else "", "demo": bool(wf.get("demo", True)), "active": active}


def choose_column(name: str, use_on_board: bool) -> dict:
    conn = load_settings().get("azure", {}).get("connection") or {}
    if not any(c["name"] == name for c in conn.get("columns", [])):
        raise ConnectError(f"'{name}' is not a column on {(conn.get('board') or {}).get('name', 'the board')}")
    values: dict[str, Any] = {"tracker": "azure", "jira_project": (conn.get("project") or {}).get("key", ""),
                              "jira_column": name, "jira_column_statuses": ""}
    if use_on_board:
        values["demo"] = False
    save_section("workflow", values)
    return status()


def refresh(http: Optional[requests.Session] = None) -> dict:
    a = load_settings().get("azure", {})
    link = a.get("link") or {}
    if not link:
        raise ConnectError("Azure Boards is not connected yet")
    try:
        info = ab.discover(ab.Azure(link["org_url"], a.get("pat", ""), http), link)
    except ab.AzureError as e:
        raise ConnectError(str(e)) from e
    _save(info, a.get("pat", ""))
    return status()


def disconnect() -> dict:
    save_section("azure", {"enabled": False, "pat": "", "connection": {}})
    wf = load_settings().get("workflow", {})
    if wf.get("tracker") == "azure":
        save_section("workflow", {"tracker": "jira", "demo": True})
    return status()
