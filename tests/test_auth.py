"""Google sign-in and sessions."""
from __future__ import annotations

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest

from qa_app import auth, config


def _jwt(payload):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(payload)}.sig"


class FakeHttp:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.sent = payload, status, None

    def post(self, url, data=None, timeout=None, headers=None):
        self.sent = (url, data)
        p, status = self.payload, self.status

        class R:
            status_code = status
            ok = status < 400
            text = "bad"
            def json(self_):
                return {"id_token": _jwt(p), "access_token": "a"}
        return R()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setenv("QA_APP_GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("QA_APP_GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.delenv("QA_APP_AUTH", raising=False)
    return tmp_path


def _good(**over):
    return {"iss": "https://accounts.google.com", "aud": "cid.apps.googleusercontent.com", "exp": time.time() + 600,
            "email": "luca@example.com", "email_verified": True, "name": "Luca", "picture": "https://p/x.png", "sub": "123", **over}


def test_sign_in_starts_with_pkce_and_finishes_with_a_checked_id_token(home):
    pending = {}
    url = auth.start("http://127.0.0.1:8765/api/auth/google/callback", pending)
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://accounts.google.com/") and q["client_id"] == ["cid.apps.googleusercontent.com"]
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["openid email profile"]
    state = q["state"][0]
    http = FakeHttp(_good())
    user = auth.finish("the-code", state, pending, http=http)
    assert user == {"email": "luca@example.com", "name": "Luca", "picture": "https://p/x.png", "sub": "123"}
    assert http.sent[1]["code_verifier"] and http.sent[1]["client_secret"] == "csecret"
    assert state not in pending                                              # one use only
    with pytest.raises(auth.AuthError):
        auth.finish("the-code", state, pending, http=http)


@pytest.mark.parametrize("bad", [{"aud": "someone-else"}, {"iss": "https://evil.example"}, {"exp": 1},
                                 {"email_verified": False}, {"email": ""}])
def test_a_wrong_id_token_is_refused(home, bad):
    pending = {}
    state = parse_qs(urlparse(auth.start("http://127.0.0.1:1/cb", pending)).query)["state"][0]
    with pytest.raises(auth.AuthError):
        auth.finish("c", state, pending, http=FakeHttp(_good(**bad)))


def test_sessions_store_only_a_hash_and_sign_out_ends_them(home):
    token = auth.create_session({"email": "luca@example.com", "name": "Luca"})
    assert auth.session_user(token)["email"] == "luca@example.com"
    assert token not in (home / "sessions.json").read_text()
    assert auth.session_user("nope") is None and auth.session_user("") is None
    auth.end_session(token)
    assert auth.session_user(token) is None


def test_an_expired_session_is_gone(home, monkeypatch):
    token = auth.create_session({"email": "a@b.c"})
    monkeypatch.setattr(auth.time, "time", lambda: 10 ** 12)
    assert auth.session_user(token) is None


def test_without_a_client_sign_in_is_not_set_up_and_guests_can_continue(home, monkeypatch, tmp_path):
    monkeypatch.delenv("QA_APP_GOOGLE_CLIENT_ID")
    monkeypatch.setattr(auth, "CLIENT_FILE", tmp_path / "none.json")
    assert auth.client() is None and auth.status()["google"] is False
    with pytest.raises(auth.AuthError):
        auth.start("http://127.0.0.1:1/cb", {})
    token = auth.guest_session()
    assert auth.session_user(token)["guest"] is True
    monkeypatch.setenv("QA_APP_GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    with pytest.raises(auth.AuthError):          # once Google is set up, guests can't skip it
        auth.guest_session()


def test_public_paths_and_turning_sign_in_off(home, monkeypatch):
    assert auth.needs_session("/api/board") and auth.needs_session("/api/events")
    for p in ("/api/auth/status", "/api/auth/google/start", "/api/auth/google/callback", "/api/jira/oauth/callback",
              "/api/mcp/oauth/callback", "/", "/static/app.js"):
        assert not auth.needs_session(p), p
    monkeypatch.setenv("QA_APP_AUTH", "off")
    assert not auth.needs_session("/api/board")
