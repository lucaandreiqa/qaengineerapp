"""A small MCP client for remote MCP servers (Streamable HTTP + OAuth 2.1), built on requests.

Used to reach Atlassian's MCP server, so a user signs in with Atlassian in the browser instead of
pasting an API token. It follows the MCP authorization spec:

  1. Find the authorization server: the 401's WWW-Authenticate resource_metadata, or the
     /.well-known/oauth-protected-resource document (RFC 9728).
  2. Read its metadata (RFC 8414 / OpenID discovery).
  3. Register this app as a public client (RFC 7591 dynamic client registration).
  4. Authorization code flow with PKCE (S256) and the resource indicator (RFC 8707).
  5. Refresh the access token when it expires, or when the server answers 401.

Tokens and the client registration are kept in one JSON file in the app folder.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlencode, urlparse

import requests

PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "YourQA"
TIMEOUT = 30


class McpError(Exception):
    """Something the user can act on; the message is shown as is."""


class McpAuthRequired(McpError):
    """No usable token: the user has to sign in (again)."""


# ------------------------------------------------------------------------------------- storage
class TokenStore:
    """{server_url: {"client": {...registration...}, "tokens": {...}, "as": {...metadata...}}} in one file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, server: str) -> dict:
        return self._read().get(server, {})

    def put(self, server: str, **values: Any) -> None:
        data = self._read()
        data[server] = {**data.get(server, {}), **values}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # tokens: owner only
        except OSError:
            pass
        os.replace(tmp, self.path)

    def sign_out(self, server: str) -> None:
        """Forget the tokens; keep the app registration so the next sign-in skips registering again."""
        data = self._read()
        if server in data:
            data[server].pop("tokens", None)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ------------------------------------------------------------------------------------- OAuth
def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _well_known(base: str, name: str) -> list[str]:
    """RFC 8414 / 9728 locations: path-inserted first, then the root."""
    p = urlparse(base)
    path = p.path.rstrip("/")
    urls = [f"{p.scheme}://{p.netloc}/.well-known/{name}{path}"] if path else []
    urls.append(f"{p.scheme}://{p.netloc}/.well-known/{name}")
    return urls


def _get_json(http: requests.Session, urls: list[str]) -> Optional[dict]:
    for u in urls:
        try:
            r = http.get(u, timeout=TIMEOUT, headers={"Accept": "application/json", "MCP-Protocol-Version": PROTOCOL_VERSION})
        except requests.RequestException:
            continue
        if r.ok:
            try:
                return r.json()
            except ValueError:
                continue
    return None


class OAuth:
    def __init__(self, server_url: str, store: TokenStore, http: Optional[requests.Session] = None) -> None:
        self.server = server_url
        self.store = store
        self.http = http or requests.Session()

    # ---- discovery
    def metadata(self) -> dict:
        """Authorization server metadata plus the protected resource document, cached in the store."""
        cached = self.store.get(self.server).get("as")
        if cached and cached.get("authorization_endpoint") and cached.get("token_endpoint"):
            return cached
        prm_url = None
        try:  # an unauthenticated request should answer 401 with resource_metadata
            r = self.http.post(self.server, json={"jsonrpc": "2.0", "id": 0, "method": "ping"}, timeout=TIMEOUT,
                               headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
            m = re.search(r'resource_metadata="([^"]+)"', r.headers.get("WWW-Authenticate", ""))
            prm_url = m.group(1) if m else None
        except requests.RequestException as e:
            raise McpError(f"Can't reach {_origin(self.server)}: {e.__class__.__name__}") from e
        prm = _get_json(self.http, ([prm_url] if prm_url else []) + _well_known(self.server, "oauth-protected-resource")) or {}
        issuer = (prm.get("authorization_servers") or [_origin(self.server)])[0]
        asm = _get_json(self.http, _well_known(issuer, "oauth-authorization-server") + _well_known(issuer, "openid-configuration"))
        if not asm or not asm.get("authorization_endpoint") or not asm.get("token_endpoint"):
            raise McpError(f"{_origin(self.server)} did not publish OAuth metadata, so sign-in can't start.")
        meta = {**asm, "resource": prm.get("resource") or self.server, "scopes_supported": prm.get("scopes_supported") or asm.get("scopes_supported") or []}
        self.store.put(self.server, **{"as": meta})
        return meta

    def client(self, redirect_uri: str) -> dict:
        """This app's registration with the authorization server (dynamic client registration)."""
        reg = self.store.get(self.server).get("client") or {}
        if reg.get("client_id") and redirect_uri in reg.get("redirect_uris", []):
            return reg
        meta = self.metadata()
        if not meta.get("registration_endpoint"):
            raise McpError("The sign-in server does not allow apps to register themselves (no registration endpoint).")
        body = {"client_name": CLIENT_NAME, "redirect_uris": [redirect_uri], "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"], "token_endpoint_auth_method": "none"}
        r = self.http.post(meta["registration_endpoint"], json=body, timeout=TIMEOUT)
        if not r.ok:
            raise McpError(f"Registering the app with Atlassian failed (HTTP {r.status_code}): {r.text[:200]}")
        reg = {**r.json(), "redirect_uris": [redirect_uri]}
        self.store.put(self.server, client=reg)
        return reg

    # ---- authorization code flow
    def start(self, redirect_uri: str) -> dict:
        """Returns {"url", "state", "verifier"}: send the user to url, keep state and verifier for finish()."""
        meta, reg = self.metadata(), self.client(redirect_uri)
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(24)
        q = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": redirect_uri,
             "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "resource": meta["resource"]}
        if meta.get("scopes_supported"):
            q["scope"] = " ".join(meta["scopes_supported"])
        sep = "&" if "?" in meta["authorization_endpoint"] else "?"
        return {"url": meta["authorization_endpoint"] + sep + urlencode(q), "state": state, "verifier": verifier}

    def finish(self, code: str, verifier: str, redirect_uri: str) -> dict:
        meta, reg = self.metadata(), self.client(redirect_uri)
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": reg["client_id"],
                "code_verifier": verifier, "resource": meta["resource"]}
        return self._token_request(meta, reg, data)

    def refresh(self) -> dict:
        entry = self.store.get(self.server)
        tokens, reg = entry.get("tokens") or {}, entry.get("client") or {}
        if not tokens.get("refresh_token") or not reg.get("client_id"):
            raise McpAuthRequired("Signed out of Atlassian. Sign in again.")
        meta = self.metadata()
        data = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": reg["client_id"],
                "resource": meta["resource"]}
        try:
            return self._token_request(meta, reg, data, keep_refresh=tokens["refresh_token"])
        except McpError as e:
            raise McpAuthRequired(f"Atlassian sign-in expired. Sign in again. ({e})") from e

    def _token_request(self, meta: dict, reg: dict, data: dict, keep_refresh: str = "") -> dict:
        auth = (reg["client_id"], reg["client_secret"]) if reg.get("client_secret") else None
        r = self.http.post(meta["token_endpoint"], data=data, auth=auth, timeout=TIMEOUT, headers={"Accept": "application/json"})
        if not r.ok:
            raise McpError(f"Atlassian sign-in failed (HTTP {r.status_code}): {r.text[:200]}")
        t = r.json()
        if not t.get("access_token"):
            raise McpError("Atlassian sign-in returned no access token.")
        tokens = {"access_token": t["access_token"], "refresh_token": t.get("refresh_token") or keep_refresh,
                  "expires_at": time.time() + float(t.get("expires_in") or 3600), "scope": t.get("scope", "")}
        self.store.put(self.server, tokens=tokens)
        return tokens

    def access_token(self) -> str:
        tokens = self.store.get(self.server).get("tokens") or {}
        if not tokens.get("access_token"):
            raise McpAuthRequired("Not signed in to Atlassian yet.")
        if tokens.get("expires_at", 0) - 60 < time.time():
            tokens = self.refresh()
        return tokens["access_token"]

    def signed_in(self) -> bool:
        return bool((self.store.get(self.server).get("tokens") or {}).get("access_token"))


# ------------------------------------------------------------------------------------- MCP session
def _sse_messages(text: str) -> list[dict]:
    out, data = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                out.append(json.loads("\n".join(data)))
            except ValueError:
                pass
            data = []
    return out


class McpSession:
    """JSON-RPC over Streamable HTTP. One session per object; initialize() runs on first use."""

    def __init__(self, server_url: str, token: Callable[[], str], refresh: Optional[Callable[[], Any]] = None,
                 http: Optional[requests.Session] = None) -> None:
        self.server = server_url
        self.token = token
        self.refresh = refresh
        self.http = http or requests.Session()
        self.session_id = ""
        self._id = 0
        self._ready = False
        self._tools: Optional[list[dict]] = None

    def _post(self, payload: dict, retry: bool = True) -> Optional[dict]:
        headers = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            r = self.http.post(self.server, json=payload, headers=headers, timeout=90)
        except requests.RequestException as e:
            raise McpError(f"Can't reach {_origin(self.server)}: {e.__class__.__name__}") from e
        if r.status_code == 401 and retry and self.refresh:
            self.refresh()
            return self._post(payload, retry=False)
        if r.status_code == 401:
            raise McpAuthRequired("Atlassian rejected the sign-in. Sign in again.")
        if r.status_code == 404 and self.session_id and retry:  # session expired on the server: start a new one
            self.session_id, self._ready = "", False
            self.initialize()
            return self._post(payload, retry=False)
        if r.status_code == 403:
            raise McpError(f"Atlassian refused the request (HTTP 403). An admin may need to allow this app: {r.text[:200]}")
        if not r.ok:
            raise McpError(f"MCP server error (HTTP {r.status_code}): {r.text[:200]}")
        self.session_id = r.headers.get("Mcp-Session-Id", self.session_id)
        if "id" not in payload or r.status_code == 202 or not r.content:
            return None
        if "text/event-stream" in r.headers.get("Content-Type", ""):
            msgs = [m for m in _sse_messages(r.text) if m.get("id") == payload["id"]]
            if not msgs:
                raise McpError("The MCP server sent no reply.")
            msg = msgs[-1]
        else:
            msg = r.json()
        if msg.get("error"):
            raise McpError(f"MCP error: {msg['error'].get('message', msg['error'])}")
        return msg.get("result") or {}

    def request(self, method: str, params: Optional[dict] = None) -> dict:
        if not self._ready and method != "initialize":
            self.initialize()
        self._id += 1
        return self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}) or {}

    def initialize(self) -> dict:
        self._id += 1
        res = self._post({"jsonrpc": "2.0", "id": self._id, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "yourqa", "title": CLIENT_NAME, "version": "1.0"}}}) or {}
        self._ready = True
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    def tools(self) -> list[dict]:
        if self._tools is None:
            tools, cursor = [], None
            while True:
                res = self.request("tools/list", {"cursor": cursor} if cursor else {})
                tools += res.get("tools", [])
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            self._tools = tools
        return self._tools

    def tool_names(self) -> set[str]:
        return {t.get("name", "") for t in self.tools()}

    def call(self, name: str, arguments: dict) -> Any:
        """Call a tool and return its JSON result (structuredContent, or the text parsed as JSON)."""
        res = self.request("tools/call", {"name": name, "arguments": arguments})
        texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        if res.get("isError"):
            raise McpError(f"{name}: {' '.join(texts)[:300] or 'failed'}")
        if res.get("structuredContent") is not None:
            return res["structuredContent"]
        joined = "\n".join(texts).strip()
        try:
            return json.loads(joined)
        except ValueError:
            return {"text": joined}
