"""Connect Jira from a pasted link: sign in with Atlassian (MCP server), pick the board column, done.

Plain functions so they can be tested without the web server; server.py exposes them as /api/jira/*.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from ..config import load_settings, save_section
from ..integrations import atlassian_mcp as am
from ..integrations.mcp_client import McpAuthRequired, McpError, TokenStore

PENDING_TTL = 15 * 60


class ConnectError(Exception):
    pass


def _prune(pending: dict) -> None:
    for k in [k for k, v in pending.items() if time.time() - v["created"] > PENDING_TTL]:
        pending.pop(k, None)


def start(link_text: str, redirect_uri: str, pending: dict, store: Optional[TokenStore] = None) -> dict:
    """Read the link, then either connect straight away (already signed in) or return the Atlassian sign-in URL."""
    try:
        link = am.parse_jira_link(link_text)
    except ValueError as e:
        raise ConnectError(str(e)) from e
    o = am.oauth(store)
    if o.signed_in():
        try:
            return {"connected": _discover_and_save(link, store)}
        except McpAuthRequired:
            pass  # token gone stale: sign in again below
    try:
        flow = o.start(redirect_uri)
    except McpError as e:
        raise ConnectError(str(e)) from e
    _prune(pending)
    pending[flow["state"]] = {"verifier": flow["verifier"], "redirect_uri": redirect_uri, "link": link, "created": time.time()}
    return {"authorize_url": flow["url"], "link": link}


def finish(code: str, state: str, pending: dict, store: Optional[TokenStore] = None) -> dict:
    """The browser came back from Atlassian: swap the code for tokens, then read the board."""
    _prune(pending)
    p = pending.pop(state, None)
    if not p:
        raise ConnectError("This sign-in link has expired or was already used. Start again from the Integrations screen.")
    try:
        am.oauth(store).finish(code, p["verifier"], p["redirect_uri"])
    except McpError as e:
        raise ConnectError(str(e)) from e
    return _discover_and_save(p["link"], store)


def _discover_and_save(link: dict, store: Optional[TokenStore] = None, mcp: Optional[am.AtlassianMcp] = None) -> dict:
    o = am.oauth(store)
    mcp = mcp or am.AtlassianMcp(am.McpSession(am.ATLASSIAN_MCP_URL, o.access_token, o.refresh))
    try:
        info = am.discover(mcp, link)
    except McpAuthRequired:
        raise
    except McpError as e:
        raise ConnectError(str(e)) from e
    save_connection(info)
    return info


def save_connection(info: dict) -> None:
    s = load_settings()
    save_section("jira", {"enabled": True, "auth": "mcp", "base_url": info["base_url"], "cloud_id": info["cloud_id"],
                          "board_id": info["board"]["id"], "project_key": info["project"]["key"],
                          "link": info["link"].get("site", ""), "connection": {**info, "connected_at": time.time()}})
    wf = s.get("workflow", {})
    names = {c["name"]: c for c in info["columns"]}
    keep = wf.get("jira_column") if wf.get("jira_column") in names and wf.get("jira_project") == info["project"]["key"] else ""
    save_section("workflow", {"jira_project": info["project"]["key"], "jira_column": keep or "",
                              "jira_column_statuses": ",".join(names[keep]["status_ids"]) if keep else ""})


def status(store: Optional[TokenStore] = None) -> dict:
    s = load_settings()
    j, wf = s.get("jira", {}), s.get("workflow", {})
    conn = j.get("connection") or {}
    return {"connected": j.get("auth") == "mcp" and bool(conn), "signedIn": am.oauth(store).signed_in(),
            "connection": conn or None, "column": wf.get("jira_column", ""), "demo": bool(wf.get("demo", True)),
            "server": am.ATLASSIAN_MCP_URL}


def choose_column(name: str, use_on_board: bool) -> dict:
    s = load_settings()
    conn = s.get("jira", {}).get("connection") or {}
    col = next((c for c in conn.get("columns", []) if c["name"] == name), None)
    if not col:
        raise ConnectError(f"'{name}' is not a column on {(conn.get('board') or {}).get('name', 'the board')}")
    values: dict[str, Any] = {"jira_project": (conn.get("project") or {}).get("key", ""), "jira_column": col["name"],
                              "jira_column_statuses": ",".join(col["status_ids"])}
    if use_on_board:
        values["demo"] = False
    save_section("workflow", values)
    return status()


def refresh(store: Optional[TokenStore] = None) -> dict:
    conn = load_settings().get("jira", {}).get("connection") or {}
    if not conn.get("link"):
        raise ConnectError("Jira is not connected yet")
    return _discover_and_save(conn["link"], store)


def disconnect(store: Optional[TokenStore] = None) -> dict:
    am.oauth(store).store.sign_out(am.ATLASSIAN_MCP_URL)
    save_section("jira", {"auth": "", "cloud_id": "", "connection": {}, "enabled": False})
    save_section("workflow", {"demo": True})  # the board falls back to demo tickets instead of failing
    return status(store)
