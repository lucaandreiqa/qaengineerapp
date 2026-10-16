"""MCP servers the user connects on the Integrations page (remote, Streamable HTTP).

Each server is saved in settings as `mcp.servers`: {id, name, url, auth: oauth|token|none, header, token, tools,
read, write, confirmed}. Adding a server lists its tools and sorts them into read and write; nothing runs until the
user confirms the lists with Save.

- Read tools (`read`) are used by YourQA when a step asks for data, by Claude's fetching and by onboarding.
- Write tools (`write`) only run through `call_write`, which the server calls only after the user clicked Run on a
  call Claude proposed in the ticket chat.

Only remote servers: YourQA never starts a local server or runs a command a server names. Tool descriptions and
results are data written by others, never instructions.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

from .. import config
from .mcp_client import McpError, McpSession, OAuth, TokenStore

READ_WORDS = ("get", "list", "search", "read", "find", "query", "fetch", "describe", "lookup", "show", "view", "count")
RESULT_MAX = 20000
DESC_MAX = 300
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


# ------------------------------------------------------------------------------------------ settings
def servers() -> list[dict]:
    return list((config.load_settings().get("mcp") or {}).get("servers") or [])


def _save_all(items: list[dict]) -> None:
    config.save_section("mcp", {"servers": items})


def get(server_id: str) -> Optional[dict]:
    return next((s for s in servers() if s.get("id") == server_id), None)


def _put(srv: dict) -> dict:
    items = [s for s in servers() if s.get("id") != srv["id"]]
    items.append(srv)
    _save_all(items)
    return srv


def remove(server_id: str) -> None:
    srv = get(server_id)
    _save_all([s for s in servers() if s.get("id") != server_id])
    if srv:
        token_store().sign_out(srv["url"])


def public() -> list[dict]:
    """What the Integrations page shows: everything except the token."""
    return [{**{k: v for k, v in s.items() if k != "token"}, "has_token": bool(s.get("token")),
             "signed_in": s.get("auth") != "oauth" or oauth(s).signed_in()} for s in servers()]


# ------------------------------------------------------------------------------------------ checks
def check_url(url: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    if not p.hostname or p.scheme not in ("https", "http"):
        raise McpError("Use the server's full address, like https://example.com/mcp")
    if p.scheme == "http" and p.hostname not in LOCAL_HOSTS:
        raise McpError("The address must start with https:// (http is only allowed for localhost).")
    return url


def classify(tool: dict) -> str:
    """'read' or 'write'. The server's own hints win; otherwise a read-sounding name (get_…, search…) counts as read."""
    ann = tool.get("annotations") or {}
    if ann.get("destructiveHint") is True or ann.get("readOnlyHint") is False:
        return "write"
    if ann.get("readOnlyHint") is True:
        return "read"
    first = re.split(r"[_\-.\s]|(?<=[a-z])(?=[A-Z])", str(tool.get("name", "")))[0].lower()
    return "read" if first in READ_WORDS else "write"


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:30] or "server"
    taken = {s.get("id") for s in servers()}
    sid, n = base, 2
    while sid in taken:
        sid, n = f"{base}-{n}", n + 1
    return sid


# ------------------------------------------------------------------------------------------ connecting
def token_store() -> TokenStore:
    return TokenStore(config.APP_DIR / "mcp-servers.json")


def oauth(srv: dict) -> OAuth:
    return OAuth(srv["url"], token_store(), label=srv.get("name") or "the MCP server")


def _session(srv: dict) -> Any:
    label = srv.get("name") or "the MCP server"
    if srv.get("auth") == "oauth":
        o = oauth(srv)
        return McpSession(srv["url"], o.access_token, o.refresh, label=label)
    headers = {}
    if srv.get("auth") == "token" and srv.get("token"):
        header = srv.get("header") or "Authorization"
        value = srv["token"]
        if header.lower() == "authorization" and not re.match(r"^\w+\s", value):
            value = "Bearer " + value
        headers[header] = value
    return McpSession(srv["url"], None, None, label=label, headers=headers)


def _tool_entry(t: dict) -> dict:
    return {"name": str(t.get("name", "")), "description": str(t.get("description") or "")[:DESC_MAX],
            "schema": t.get("inputSchema") or {}, "kind": classify(t)}


def discover(srv: dict) -> list[dict]:
    return [_tool_entry(t) for t in _session(srv).tools() if t.get("name")]


def add(name: str, url: str, auth: str = "none", token: str = "", header: str = "") -> dict:
    """Save a new server. For a token or no sign-in its tools are listed straight away; an OAuth server lists them
    after the user signed in (refresh_tools)."""
    url = check_url(url)
    if auth not in ("oauth", "token", "none"):
        raise McpError("Choose how to sign in: in the browser, with a token, or none.")
    if auth == "token" and not token.strip():
        raise McpError("Paste the token for this server.")
    srv = {"id": _slug(name or urlparse(url).hostname or ""), "name": (name or urlparse(url).hostname or "MCP server").strip()[:60],
           "url": url, "auth": auth, "header": (header or "").strip()[:60], "token": token.strip(),
           "tools": [], "read": [], "write": [], "confirmed": False}
    if auth != "oauth":
        _fill_tools(srv)
    return _put(srv)


def _fill_tools(srv: dict) -> dict:
    srv["tools"] = discover(srv)
    names = {t["name"] for t in srv["tools"]}
    if not srv.get("confirmed"):  # first listing: every read tool on, every write tool off
        srv["read"] = [t["name"] for t in srv["tools"] if t["kind"] == "read"]
        srv["write"] = []
    else:  # a tool the server dropped is dropped from the lists; new tools stay off until switched on
        srv["read"] = [n for n in srv["read"] if n in names]
        srv["write"] = [n for n in srv["write"] if n in names]
    return srv


def refresh_tools(server_id: str) -> dict:
    srv = get(server_id)
    if not srv:
        raise McpError("That MCP server isn't connected.")
    return _put(_fill_tools(srv))


def save(server_id: str, read: list[str], write: list[str]) -> dict:
    """The user confirmed which tools YourQA may use. Read tools must be read tools; write tools must be write tools."""
    srv = get(server_id)
    if not srv:
        raise McpError("That MCP server isn't connected.")
    kinds = {t["name"]: t["kind"] for t in srv.get("tools") or []}
    srv["read"] = [n for n in dict.fromkeys(read) if kinds.get(n) == "read"]
    srv["write"] = [n for n in dict.fromkeys(write) if kinds.get(n) == "write"]
    srv["confirmed"] = True
    return _put(srv)


# ------------------------------------------------------------------------------------------ using
def _allowed(server_id: str, tool: str, kind: str) -> dict:
    srv = get(server_id)
    if not srv:
        raise McpError(f"No MCP server called {server_id!r} is connected.")
    if not srv.get("confirmed"):
        raise McpError(f"{srv['name']}: confirm its tools on the Integrations page first.")
    if tool not in srv.get(kind) or []:
        raise McpError(f"{srv['name']}: {tool} isn't switched on as a {kind} tool.")
    return srv


def _text(result: Any) -> str:
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)
    return text if len(text) <= RESULT_MAX else text[:RESULT_MAX] + f"\n… (trimmed, {len(text)} characters in all)"


def call_read(server_id: str, tool: str, args: Optional[dict] = None) -> str:
    srv = _allowed(server_id, tool, "read")
    return _text(_session(srv).call(tool, args or {}))


def call_write(server_id: str, tool: str, args: Optional[dict] = None) -> str:
    """Only ever called from the route behind the user's Run click."""
    srv = _allowed(server_id, tool, "write")
    return _text(_session(srv).call(tool, args or {}))


def _catalog(kind: str) -> list[dict]:
    out = []
    for s in servers():
        if not s.get("confirmed"):
            continue
        tools = {t["name"]: t for t in s.get("tools") or []}
        out += [{"server": s["id"], "name": s["name"], "tool": n, "description": tools.get(n, {}).get("description", ""),
                 "schema": tools.get(n, {}).get("schema", {})} for n in s.get(kind) or [] if n in tools]
    return out


def catalog() -> list[dict]:
    return _catalog("read")


def write_catalog() -> list[dict]:
    return _catalog("write")


def _lines(items: list[dict]) -> str:
    def args(schema: dict) -> str:
        props = (schema or {}).get("properties") or {}
        return ", ".join(list(props)[:8])
    return "\n".join(f"- {c['server']} {c['tool']}({args(c['schema'])}): {c['description'][:200]}" for c in items)


def catalog_md() -> str:
    cat = catalog()
    return _lines(cat) if cat else ""


def write_catalog_md() -> str:
    cat = write_catalog()
    return _lines(cat) if cat else ""


NEED = re.compile(r"^\s*mcp:\s*([a-z0-9-]+)\s+([A-Za-z0-9_.\-]+)\s*(\{.*\})?\s*$", re.S)


def parse_need(text: str) -> Optional[tuple[str, str, dict]]:
    """'mcp: <server> <tool> {json args}' -> (server, tool, args); None when the request isn't an MCP call."""
    if not str(text).strip().lower().startswith("mcp:"):
        return None
    m = NEED.match(str(text))
    if not m:
        raise McpError(f"Can't read the MCP call {text[:120]!r}. Use: mcp: <server> <tool> {{json arguments}}")
    try:
        args = json.loads(m.group(3)) if m.group(3) else {}
    except ValueError as e:
        raise McpError(f"The arguments for {m.group(2)} aren't valid JSON: {e}") from e
    if not isinstance(args, dict):
        raise McpError(f"The arguments for {m.group(2)} must be a JSON object.")
    return m.group(1), m.group(2), args


def claude_code_config() -> tuple[dict, list[str]]:
    """For Claude's fetching: an --mcp-config with the confirmed servers (names prefixed yq_) and the exact read tools
    it may use. Servers whose sign-in fails are left out."""
    conf, allow = {}, []
    for s in servers():
        if not s.get("confirmed") or not s.get("read"):
            continue
        name = "yq_" + s["id"].replace("-", "_")
        headers = {}
        try:
            if s.get("auth") == "oauth":
                headers["Authorization"] = "Bearer " + oauth(s).access_token()
            elif s.get("auth") == "token" and s.get("token"):
                sess = _session(s)
                headers = dict(sess.extra_headers)
        except McpError:
            continue
        conf[name] = {"type": "http", "url": s["url"], **({"headers": headers} if headers else {})}
        allow += [f"mcp__{name}__{t}" for t in s["read"]]
    return conf, allow
