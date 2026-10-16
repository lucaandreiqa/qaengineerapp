"""Sign-in with Google, and sessions.

YourQA ships with its own Google OAuth client (a Desktop app client): `qa_app/google_client.json`
({"client_id": …, "client_secret": …}, not in git) or QA_APP_GOOGLE_CLIENT_ID / QA_APP_GOOGLE_CLIENT_SECRET. Any Google
account may sign in: sign-in says who is using YourQA. The flow is the authorization code flow with PKCE on a loopback
redirect; the ID token comes straight from Google's token endpoint over TLS and is checked for audience, issuer,
expiry and a verified email.

Sessions: a random token in an HttpOnly cookie; only its SHA-256 is kept, in <app>/sessions.json. QA_APP_AUTH=off
turns sign-in off.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from . import config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
CLIENT_FILE = Path(__file__).with_name("google_client.json")
COOKIE = "yourqa_session"
SESSION_DAYS = 30
PENDING_MAX_AGE = 600
PUBLIC_API = ("/api/auth/", "/api/jira/oauth/callback", "/api/mcp/oauth/callback")


class AuthError(Exception):
    """Shown to the person as is."""


# ------------------------------------------------------------------------------------------ settings
def enabled() -> bool:
    return os.environ.get("QA_APP_AUTH", "").lower() not in ("off", "0", "false", "no")


def client() -> Optional[dict]:
    cid, secret = os.environ.get("QA_APP_GOOGLE_CLIENT_ID", ""), os.environ.get("QA_APP_GOOGLE_CLIENT_SECRET", "")
    if not cid:
        try:
            data = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
            data = data.get("installed") or data.get("web") or data  # a file downloaded from Google Cloud works too
            cid, secret = str(data.get("client_id") or ""), str(data.get("client_secret") or "")
        except (OSError, ValueError, AttributeError):
            return None
    return {"client_id": cid, "client_secret": secret} if cid else None


def status() -> dict:
    return {"required": enabled(), "google": client() is not None}


def needs_session(path: str) -> bool:
    return enabled() and path.startswith("/api/") and not path.startswith(PUBLIC_API)


# ------------------------------------------------------------------------------------------ Google
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def start(redirect_uri: str, pending: dict) -> str:
    c = client()
    if not c:
        raise AuthError("Google sign-in isn't set up in this copy of YourQA.")
    now = time.time()
    for k in [k for k, v in pending.items() if now - v["at"] > PENDING_MAX_AGE]:
        pending.pop(k, None)
    verifier = _b64(secrets.token_bytes(48))
    state = secrets.token_urlsafe(24)
    pending[state] = {"verifier": verifier, "redirect_uri": redirect_uri, "at": now}
    q = {"client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": "openid email profile",
         "state": state, "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
         "prompt": "select_account"}
    return AUTH_URL + "?" + urlencode(q)


def _payload(id_token: str) -> dict:
    try:
        part = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError) as e:
        raise AuthError("Google sent an ID token YourQA couldn't read.") from e


def finish(code: str, state: str, pending: dict, http: Any = None) -> dict:
    p = pending.pop(state or "", None)
    if not p or time.time() - p["at"] > PENDING_MAX_AGE:
        raise AuthError("This sign-in link has expired. Sign in again.")
    c = client()
    if not c:
        raise AuthError("Google sign-in isn't set up in this copy of YourQA.")
    if http is None:
        import requests
        http = requests
    r = http.post(TOKEN_URL, data={"code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "redirect_uri": p["redirect_uri"], "grant_type": "authorization_code",
                                   "code_verifier": p["verifier"]}, timeout=30, headers={"Accept": "application/json"})
    if not r.ok:
        raise AuthError(f"Google sign-in failed (HTTP {r.status_code}).")
    claims = _payload(str(r.json().get("id_token") or ""))
    if claims.get("aud") != c["client_id"] or claims.get("iss") not in ISSUERS:
        raise AuthError("That sign-in wasn't meant for YourQA.")
    if float(claims.get("exp") or 0) < time.time():
        raise AuthError("That sign-in has expired. Sign in again.")
    if not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise AuthError("Your Google account needs a verified email address.")
    return {"email": claims["email"], "name": claims.get("name") or claims["email"], "picture": claims.get("picture") or "",
            "sub": str(claims.get("sub") or "")}


# ------------------------------------------------------------------------------------------ sessions
def _file() -> Path:
    return config.APP_DIR / "sessions.json"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _read() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, f)


def create_session(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    data = {k: v for k, v in _read().items() if v.get("expires", 0) > now}
    data[_hash(token)] = {"user": user, "expires": now + SESSION_DAYS * 86400}
    _write(data)
    return token


def guest_session() -> str:
    """Only while this copy has no Google client: sign-in identifies people, it isn't a lock."""
    if client():
        raise AuthError("Sign in with Google.")
    return create_session({"email": "", "name": "Guest", "picture": "", "guest": True})


def session_user(token: str) -> Optional[dict]:
    if not token:
        return None
    s = _read().get(_hash(token))
    if not s or s.get("expires", 0) < time.time():
        return None
    return s.get("user")


def end_session(token: str) -> None:
    data = _read()
    if data.pop(_hash(token or ""), None) is not None:
        _write(data)
