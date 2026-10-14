"""Connect Jira from a link through an MCP server with OAuth 2.1. Runs against a local fake of
Atlassian's MCP server whose replies copy the real ones (board 1 of a team-managed SCRUM project)."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from qa_app import config
from qa_app.integrations import atlassian_mcp as am
from qa_app.integrations.mcp_client import McpAuthRequired, TokenStore
from qa_app.web import jira_connect

CLOUD = "f044e72a-d38f-4ae4-897b-7dd74feaa08a"
BOARD_CONFIG = {"id": 1, "name": "SCRUM board", "type": "simple", "location": {"type": "project", "key": "SCRUM", "name": "QA Testing"},
                "columnConfig": {"columns": [
                    {"name": "To Do", "statuses": [{"id": "10000", "name": "To Do"}]},
                    {"name": "In Progress", "statuses": [{"id": "10001", "name": "In Progress"}]},
                    {"name": "In Review", "statuses": [{"id": "10002", "name": "In Review"}]},
                    {"name": "Done", "statuses": [{"id": "10003", "name": "Done"}]}]}}
ISSUES = {"SCRUM-2": {"summary": "Task 2", "status": "In Progress", "components": [{"name": "Frontend"}, {"name": "Backend"}]},
          "SCRUM-3": {"summary": "Task 3", "status": "In Review", "components": []}}


class Fake:
    """State of the fake server, inspected by the tests."""
    def __init__(self) -> None:
        self.codes: dict[str, dict] = {}
        self.tokens: set[str] = set()
        self.refreshes = 0
        self.calls: list[tuple[str, dict]] = []
        self.comments: dict[str, list[str]] = {"SCRUM-2": ["Preview: https://feature-x.pages.dev/ ready"]}
        self.status = {k: v["status"] for k, v in ISSUES.items()}
        self.registered: list[dict] = []
        self.direct_tools = {"getAccessibleAtlassianResources", "atlassianUserInfo", "getJiraIssue", "searchJiraIssuesUsingJql",
                             "addOrEditJiraIssueComment", "transitionJiraIssue", "executeRead", "executeWrite"}


def make_server(fake: Fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, body, headers=None, sse=False):
            data = json.dumps(body)
            raw = (f"event: message\ndata: {data}\n\n" if sse else data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/.well-known/oauth-protected-resource/v1/mcp":
                return self._json(200, {"resource": base + "/v1/mcp", "authorization_servers": [base + "/auth"]})
            if self.path == "/.well-known/oauth-authorization-server/auth":
                return self._json(200, {"issuer": base + "/auth", "authorization_endpoint": base + "/auth/authorize",
                                        "token_endpoint": base + "/auth/token", "registration_endpoint": base + "/auth/register"})
            self._json(404, {})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode()
            if self.path == "/auth/register":
                body = json.loads(raw)
                fake.registered.append(body)
                return self._json(201, {"client_id": "client-1", "redirect_uris": body["redirect_uris"]})
            if self.path == "/auth/token":
                f = {k: v[0] for k, v in parse_qs(raw).items()}
                if f["grant_type"] == "authorization_code":
                    c = fake.codes.pop(f["code"], None)
                    ok = c and base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode() == c["challenge"]
                    if not ok or f["redirect_uri"] != c["redirect_uri"]:
                        return self._json(400, {"error": "invalid_grant"})
                    fake.tokens.add("tok-1")
                    return self._json(200, {"access_token": "tok-1", "refresh_token": "ref-1", "expires_in": 3600})
                if f["grant_type"] == "refresh_token" and f["refresh_token"] == "ref-1":
                    fake.refreshes += 1
                    t = f"tok-r{fake.refreshes}"
                    fake.tokens.add(t)
                    return self._json(200, {"access_token": t, "expires_in": 3600})
                return self._json(400, {"error": "invalid_grant"})
            if self.path == "/v1/mcp":
                base = f"http://127.0.0.1:{self.server.server_port}"
                auth = self.headers.get("Authorization", "")
                if auth.removeprefix("Bearer ") not in fake.tokens:
                    return self._json(401, {"error": "unauthorized"},
                                      {"WWW-Authenticate": f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/v1/mcp"'})
                msg = json.loads(raw)
                if "id" not in msg:
                    self.send_response(202)
                    self.end_headers()
                    return
                if msg["method"] == "initialize":
                    return self._json(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-06-18"}},
                                      {"Mcp-Session-Id": "s-1"})
                if msg["method"] == "tools/list":
                    return self._json(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [{"name": n} for n in fake.direct_tools]}})
                name, args = msg["params"]["name"], msg["params"]["arguments"]
                if name in ("executeRead", "executeWrite"):
                    name, args = args["name"], {**args["inputs"], "cloudId": args["cloudId"]}
                elif name not in fake.direct_tools:
                    return self._json(200, {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32602, "message": f"Unknown tool {name}"}})
                fake.calls.append((name, args))
                try:
                    data = tool(fake, name, args)
                except KeyError as e:
                    return self._json(200, {"jsonrpc": "2.0", "id": msg["id"],
                                            "result": {"isError": True, "content": [{"type": "text", "text": f"not found {e}"}]}}, sse=True)
                return self._json(200, {"jsonrpc": "2.0", "id": msg["id"],
                                        "result": {"content": [{"type": "text", "text": json.dumps({"data": data})}]}}, sse=True)
            self._json(404, {})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def tool(fake: Fake, name: str, a: dict):
    if name != "getAccessibleAtlassianResources" and name != "atlassianUserInfo":
        assert a["cloudId"] == CLOUD
    if name == "getAccessibleAtlassianResources":
        return {"resources": [{"id": CLOUD, "url": "https://qaengineerapp.atlassian.net", "products": [{"id": "jira"}]}]}
    if name == "atlassianUserInfo":
        return {"accountId": "712020:abc"}
    if name == "getJiraCurrentUser":
        return {"accountId": "712020:abc", "displayName": "Andrei Luca", "emailAddress": "luca@example.com"}
    if name == "getJiraBoardConfig":
        if a["boardId"] != 1:
            raise KeyError("board")
        return BOARD_CONFIG
    if name == "listJiraProjects":
        return {"values": [{"id": "10000", "key": "SCRUM", "name": "QA Testing", "style": "next-gen"}]}
    if name == "listJiraProjectComponents":
        return {"values": [{"name": "Frontend"}, {"name": "Backend"}]}
    if name == "listJiraBoards":
        return {"values": [{"id": 1, "name": "SCRUM board"}]}
    if name == "getJiraBoardIssueData":
        ids = a["jql"].split("(")[1].rstrip(")").split(",")
        by_id = {c["statuses"][0]["id"]: c["statuses"][0]["name"] for c in BOARD_CONFIG["columnConfig"]["columns"]}
        keys = [k for k, s in fake.status.items() if s in {by_id[i] for i in ids}]
        if a.get("searchResultMode") == "count":
            return {"total": len(keys)}
        return {"isLast": True, "issues": [{"key": k, "fields": {"summary": ISSUES[k]["summary"], "status": {"name": fake.status[k]},
                                                                  "components": ISSUES[k]["components"]}} for k in keys]}
    if name == "getJiraIssue":
        k = a["issueIdOrKey"]
        return {"key": k, "fields": {"summary": ISSUES[k]["summary"], "description": "- Export works\n- Filter works",
                                     "status": {"name": fake.status[k]}, "components": ISSUES[k]["components"]}}
    if name == "listJiraIssueComments":
        return {"comments": [{"body": b} for b in fake.comments.get(a["issueIdOrKey"], [])]}
    if name == "addOrEditJiraIssueComment":
        fake.comments.setdefault(a["issueIdOrKey"], []).append(a["commentBody"])
        return {"commentId": "1"}
    if name == "listJiraIssueTransitions":
        return {"transitions": [{"id": "11", "name": "To Do"}, {"id": "31", "name": "In Review"}, {"id": "41", "name": "Done"}]}
    if name == "transitionJiraIssue":
        to = {"11": "To Do", "31": "In Review", "41": "Done"}[a["transitionId"]]
        fake.status[a["issueIdOrKey"]] = to
        return {"status": {"name": to}}
    raise KeyError(name)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    fake = Fake()
    srv = make_server(fake)
    url = f"http://127.0.0.1:{srv.server_port}/v1/mcp"
    monkeypatch.setattr(am, "ATLASSIAN_MCP_URL", url)
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    store = TokenStore(tmp_path / "atlassian-mcp.json")
    monkeypatch.setattr(am, "store_path", lambda: tmp_path / "atlassian-mcp.json")
    yield fake, store, url
    srv.shutdown()


def approve(fake: Fake, authorize_url: str) -> tuple[str, str]:
    """What Atlassian does when the user clicks Accept: remember the PKCE challenge, hand back a code."""
    q = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
    assert q["code_challenge_method"] == "S256" and q["response_type"] == "code" and q["resource"].endswith("/v1/mcp")
    fake.codes["code-1"] = {"challenge": q["code_challenge"], "redirect_uri": q["redirect_uri"]}
    return "code-1", q["state"]


REDIRECT = "http://localhost:8765/api/jira/oauth/callback"
LINK = "https://qaengineerapp.atlassian.net/jira/software/projects/SCRUM/boards/1?filter=&groupBy=none"


def test_parse_jira_links():
    p = am.parse_jira_link(LINK)
    assert (p["site"], p["base_url"], p["project_key"], p["board_id"], p["issue_key"]) == \
        ("qaengineerapp.atlassian.net", "https://qaengineerapp.atlassian.net", "SCRUM", "1", "")
    assert am.parse_jira_link("acme.atlassian.net/jira/software/c/projects/ops/boards/12")["project_key"] == "OPS"
    p = am.parse_jira_link("https://acme.atlassian.net/browse/SCRUM-12")
    assert (p["project_key"], p["issue_key"], p["board_id"]) == ("SCRUM", "SCRUM-12", "")
    assert am.parse_jira_link("https://acme.atlassian.net/jira/software/projects/A/boards/3?selectedIssue=A-7")["issue_key"] == "A-7"
    assert am.parse_jira_link("https://acme.atlassian.net/secure/RapidBoard.jspa?rapidView=5&projectKey=ops")["board_id"] == "5"
    assert am.parse_jira_link("  qaengineerapp.atlassian.net ")["project_key"] == ""
    for bad in ("", "hello", "https://www.atlassian.com/software/jira"):
        with pytest.raises(ValueError):
            am.parse_jira_link(bad)


def test_connect_with_link_and_atlassian_sign_in(env):
    fake, store, _ = env
    pending: dict = {}
    r = jira_connect.start(LINK, REDIRECT, pending, store)
    assert "authorize_url" in r and len(pending) == 1
    assert fake.registered[0]["redirect_uris"] == [REDIRECT] and fake.registered[0]["token_endpoint_auth_method"] == "none"
    code, state = approve(fake, r["authorize_url"])
    info = jira_connect.finish(code, state, pending, store)
    assert info["cloud_id"] == CLOUD and info["user"]["name"] == "Andrei Luca"
    assert info["project"] == {"key": "SCRUM", "name": "QA Testing", "style": "team-managed"}
    assert info["board"]["name"] == "SCRUM board"
    assert [(c["name"], c["status_ids"], c["count"]) for c in info["columns"]] == \
        [("To Do", ["10000"], 0), ("In Progress", ["10001"], 1), ("In Review", ["10002"], 1), ("Done", ["10003"], 0)]
    assert info["components"] == ["Frontend", "Backend"]
    s = config.load_settings()
    assert s["jira"]["auth"] == "mcp" and s["jira"]["cloud_id"] == CLOUD and s["workflow"]["jira_project"] == "SCRUM"
    st = jira_connect.status(store)
    assert st["connected"] and st["signedIn"] and st["column"] == ""
    with pytest.raises(jira_connect.ConnectError, match="expired or was already used"):  # a state is single-use
        jira_connect.finish(code, state, pending, store)


def test_pick_column_then_board_reads_and_writes_jira(env):
    fake, store, _ = env
    pending: dict = {}
    code, state = approve(fake, jira_connect.start(LINK, REDIRECT, pending, store)["authorize_url"])
    jira_connect.finish(code, state, pending, store)
    with pytest.raises(jira_connect.ConnectError):
        jira_connect.choose_column("QA", True)
    st = jira_connect.choose_column("In Review", True)
    assert st["column"] == "In Review" and st["demo"] is False
    s = config.load_settings()
    assert s["workflow"]["jira_column_statuses"] == "10002"

    from qa_app.workflow.clients import MockJira, MockTestRail
    from qa_app.workflow.engine import Workflow
    from qa_app.workflow.settings import WorkflowConfig
    from qa_app.workflow.store import TicketStore
    wf = Workflow(TicketStore(store.path.parent / "d.json"), TicketStore(store.path.parent / "l.json"), MockJira([]), MockTestRail(),
                  cfg=WorkflowConfig(demo=False, data_dir=store.path.parent))
    jira = wf.jira()  # signed in with Atlassian, so the board uses the MCP client
    assert isinstance(jira, am.McpJira) and jira.board_id == "1" and jira.status_ids == ["10002"]
    assert jira.search_column("SCRUM", "In Review") == [{"key": "SCRUM-3", "title": "Task 3", "status": "In Review", "components": []}]
    issue = jira.get_issue("SCRUM-2")
    assert issue["components"] == ["Frontend", "Backend"] and issue["preview_url"] == "https://feature-x.pages.dev/"
    jira.add_comment("SCRUM-2", "QA result: **2/2 pass**")
    assert fake.comments["SCRUM-2"][-1] == "QA result: **2/2 pass**"  # markdown as is
    tr = {t["name"]: t["id"] for t in jira.get_transitions("SCRUM-2")}
    assert jira.transition("SCRUM-2", tr["Done"]) == "Done" and fake.status["SCRUM-2"] == "Done"
    assert ("transitionJiraIssue", {"cloudId": CLOUD, "issueIdOrKey": "SCRUM-2", "transitionId": "41"}) in fake.calls


def test_already_signed_in_connects_without_browser_and_expired_token_refreshes(env):
    fake, store, url = env
    pending: dict = {}
    code, state = approve(fake, jira_connect.start(LINK, REDIRECT, pending, store)["authorize_url"])
    jira_connect.finish(code, state, pending, store)
    fake.tokens.discard("tok-1")  # server-side expiry: the next call gets 401 and must refresh once
    r = jira_connect.start("https://qaengineerapp.atlassian.net/browse/SCRUM-3", REDIRECT, pending, store)
    assert r["connected"]["board"]["id"] == "1" and fake.refreshes == 1  # board found from the project
    jira_connect.disconnect(store)
    assert not store.get(url).get("tokens") and store.get(url).get("client")  # registration kept
    assert config.load_settings()["workflow"]["demo"] is True
    with pytest.raises(McpAuthRequired):
        am.oauth(store).access_token()


def test_wrong_site_and_bad_board_give_clear_messages(env):
    fake, store, _ = env
    pending: dict = {}
    code, state = approve(fake, jira_connect.start("https://other.atlassian.net/jira/software/projects/X/boards/1", REDIRECT, pending, store)["authorize_url"])
    with pytest.raises(jira_connect.ConnectError, match="can't open other.atlassian.net. Sites it can open: qaengineerapp.atlassian.net"):
        jira_connect.finish(code, state, pending, store)
    with pytest.raises(jira_connect.ConnectError, match="Can't open board 9"):
        jira_connect.start("https://qaengineerapp.atlassian.net/jira/software/projects/SCRUM/boards/9", REDIRECT, pending, store)
    with pytest.raises(jira_connect.ConnectError, match="doesn't look like a Jira link"):
        jira_connect.start("not a link", REDIRECT, pending, store)
