"""Jira connected with an API token (same board link as the Atlassian sign-in) and Azure Boards (board link + PAT).
Both run against fakes whose replies copy the real APIs' shapes."""
from __future__ import annotations

import json
from urllib.parse import unquote, urlparse

import pytest

from qa_app import config
from qa_app.config import load_settings
from qa_app.integrations import azure_boards as ab
from qa_app.integrations import jira as rest
from qa_app.web import azure_connect, jira_connect

JIRA_LINK = "https://qaengineerapp.atlassian.net/jira/software/projects/SCRUM/boards/1?filter=&groupBy=none"
AZ_LINK = "https://dev.azure.com/acme/Shop%20Web/_boards/board/t/Shop%20Web%20Team/Stories"


class Resp:
    def __init__(self, body=None, status=200, ctype="application/json"):
        self.body, self.status_code = body, status
        self.ok = 200 <= status < 300
        self.headers = {"Content-Type": ctype}
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        if isinstance(self.body, str):
            raise ValueError("not json")
        return self.body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


def board_client():
    """The tracker client the Testing board would use with the saved settings."""
    from types import SimpleNamespace

    from qa_app.workflow.engine import Workflow
    from qa_app.workflow.settings import WorkflowConfig
    return Workflow.jira(SimpleNamespace(cfg=WorkflowConfig.load(), mock_jira=None))


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    return tmp_path


# ------------------------------------------------------------------------------------- Jira with an API token
class FakeJira:
    def __init__(self, good_token="tok"):
        self.good, self.posted = good_token, []
        self.auth = None

    def get(self, url, params=None, timeout=None):
        if self.auth[1] != self.good:
            return Resp({"message": "Unauthorized"}, 401)
        path = urlparse(url).path
        table = {
            "/rest/api/2/myself": {"displayName": "Andrei Luca", "emailAddress": "luca@example.com", "accountId": "abc"},
            "/rest/agile/1.0/board/1": {"id": 1, "name": "SCRUM board", "location": {"projectKey": "SCRUM", "name": "QA Testing"}},
            "/rest/agile/1.0/board/1/configuration": {"id": 1, "name": "SCRUM board", "type": "simple", "columnConfig": {"columns": [
                {"name": "To Do", "statuses": [{"id": "10000"}]}, {"name": "In Review", "statuses": [{"id": "10002"}, {"id": "10004"}]},
                {"name": "Done", "statuses": [{"id": "10003"}]}]}},
            "/rest/api/2/project/SCRUM": {"key": "SCRUM", "name": "QA Testing", "style": "next-gen"},
            "/rest/api/2/status": [{"id": "10000", "name": "To Do", "statusCategory": {"key": "new"}},
                                   {"id": "10002", "name": "In Review", "statusCategory": {"key": "indeterminate"}},
                                   {"id": "10004", "name": "QA", "statusCategory": {"key": "indeterminate"}},
                                   {"id": "10003", "name": "Done", "statusCategory": {"key": "done"}}],
            "/rest/api/2/project/SCRUM/components": [{"name": "Frontend"}, {"name": "Backend"}],
        }
        return Resp(table[path]) if path in table else Resp({"errorMessages": ["nope"]}, 404)

    def post(self, url, json=None, timeout=None):
        self.posted.append((urlparse(url).path, json))
        if url.endswith("/search/approximate-count"):
            return Resp({"count": 2 if "10002" in json["jql"] else 0})
        if url.endswith("/search/jql"):
            return Resp({"issues": [{"key": "SCRUM-3", "fields": {"summary": "Task 3", "status": {"name": "QA"}, "labels": ["FE+BE"],
                                                                  "issuetype": {"name": "Story"}}}]})
        return Resp({}, 404)


def _fake_rest(monkeypatch, fake):
    def session(cfg):
        fake.auth = (cfg["email"], cfg["api_token"])
        return fake
    monkeypatch.setattr(rest, "_session", session)


def test_jira_api_token_uses_the_same_link_and_column_picker(settings, monkeypatch):
    fake = FakeJira()
    _fake_rest(monkeypatch, fake)
    info = jira_connect.connect_token(JIRA_LINK, "luca@example.com", "tok")
    assert info["project"] == {"key": "SCRUM", "name": "QA Testing", "style": "team-managed"}
    assert [(c["name"], c["statuses"], c["category"], c["count"]) for c in info["columns"]] == [
        ("To Do", ["To Do"], "new", 0), ("In Review", ["In Review", "QA"], "indeterminate", 2), ("Done", ["Done"], "done", 0)]
    assert info["components"] == ["Frontend", "Backend"] and info["user"]["name"] == "Andrei Luca"

    st = jira_connect.status()
    assert st["connected"] and st["signedIn"] and st["auth"] == "token" and st["email"] == "luca@example.com"
    j = load_settings()["jira"]
    assert (j["auth"], j["base_url"], j["project_key"], j["api_token"]) == ("token", "https://qaengineerapp.atlassian.net", "SCRUM", "tok")

    st = jira_connect.choose_column("In Review", use_on_board=True)
    wf = load_settings()["workflow"]
    assert (wf["tracker"], wf["demo"], wf["jira_column_statuses"]) == ("jira", False, "10002,10004") and st["active"]

    client = board_client()
    rows = client.search_column("SCRUM", "In Review")
    assert rows[0]["key"] == "SCRUM-3" and rows[0]["labels"] == ["FE+BE"]
    assert 'status in (10002, 10004)' in fake.posted[-1][1]["jql"]  # every status in the column, not just its name

    jira_connect.refresh()  # refresh works with the token too
    jira_connect.disconnect()
    assert not jira_connect.status()["connected"] and load_settings()["jira"]["api_token"] == ""


def test_jira_bad_token_and_missing_fields_explain_themselves(settings, monkeypatch):
    _fake_rest(monkeypatch, FakeJira())
    with pytest.raises(jira_connect.ConnectError, match="didn't accept that email and API token"):
        jira_connect.connect_token(JIRA_LINK, "luca@example.com", "wrong")
    with pytest.raises(jira_connect.ConnectError, match="email"):
        jira_connect.connect_token(JIRA_LINK, "", "tok")
    with pytest.raises(jira_connect.ConnectError):
        jira_connect.connect_token("https://www.atlassian.com/software/jira", "a@b.c", "tok")


def test_bugs_from_site_checks_are_off_until_turned_on(settings, monkeypatch):
    from qa_app import integrations

    _fake_rest(monkeypatch, FakeJira())
    jira_connect.connect_token(JIRA_LINK, "luca@example.com", "tok")
    called = []
    monkeypatch.setattr(rest, "publish", lambda *a, **k: called.append(1) or "ok")
    integrations.publish(object(), load_settings(), log=lambda m: None, only=["jira"])
    assert called == []  # connected for the board, but no bugs filed
    st = jira_connect.save_bugs(True, "Task", "minor")
    assert st["bugs"] == {"on_runs": True, "issue_type": "Task", "min_severity": "minor"}
    with pytest.raises(jira_connect.ConnectError):
        jira_connect.save_bugs(True, "Bug", "everything")
    assert rest.ready(load_settings()["jira"]) == ""
    assert "Connect Jira" in rest.ready({"auth": "mcp"})


# ------------------------------------------------------------------------------------- Azure Boards
COLUMN_FIELD = "WEF_6CB6_Kanban.Column"
ITEM = {"id": 42, "fields": {
    "System.Title": "Checkout shows gift card balance", "System.State": "Active", "System.WorkItemType": "User Story",
    "System.Tags": "FE; checkout", "System.AreaPath": "Shop Web\\Frontend", "Microsoft.VSTS.Common.Priority": 2,
    "System.Description": "<div>Show the balance.<br>Preview: <a href=\"https://pr-42.shop-web.dev/\">https://pr-42.shop-web.dev/</a></div>",
    "Microsoft.VSTS.Common.AcceptanceCriteria": "<ul><li>Balance shows</li><li>Errors are clear</li></ul>",
    "System.CreatedBy": {"displayName": "Andrei Luca"}, "System.AssignedTo": {"displayName": "Dev One"},
    "System.CreatedDate": "2026-10-14T10:00:00Z", "System.IterationPath": "Shop Web\\Sprint 4", COLUMN_FIELD: "Testing",
    "Custom.TestNotes": "Use the EU store"},
    "relations": [{"rel": "System.LinkTypes.Hierarchy-Reverse", "url": "https://dev.azure.com/acme/_apis/wit/workItems/40", "attributes": {"name": "Parent"}},
                  {"rel": "Hyperlink", "url": "https://www.figma.com/file/abc", "attributes": {"comment": "Design"}},
                  {"rel": "AttachedFile", "url": "https://x/att/1", "attributes": {"name": "balance.png"}},
                  {"rel": "System.LinkTypes.Related", "url": "https://dev.azure.com/acme/_apis/wit/workItems/41", "attributes": {"name": "Related"}}]}


class FakeAzure:
    def __init__(self, pat="pat"):
        self.good, self.calls, self.comments, self.patches = pat, [], [], []
        self.auth, self.headers = None, {}

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        path = unquote(urlparse(url).path)
        self.calls.append((method, path, params, json))
        if self.auth[1] != self.good:
            return Resp("<html>Sign in</html>", 203, "text/html")
        base = "/acme/"
        p = path[len(base):] if path.startswith(base) else path
        if method == "GET" and p == "_apis/projects/Shop Web":
            return Resp({"id": "p1", "name": "Shop Web", "defaultTeam": {"name": "Shop Web Team"}})
        if p == "_apis/connectionData":
            return Resp({"authenticatedUser": {"providerDisplayName": "Andrei Luca", "id": "u1"}})
        if p == "Shop Web/Shop Web Team/_apis/work/boards":
            return Resp({"value": [{"id": "b1", "name": "Stories"}, {"id": "b2", "name": "Features"}]})
        if p == "Shop Web/Shop Web Team/_apis/work/boards/b1":
            return Resp({"id": "b1", "name": "Stories", "fields": {"columnField": {"referenceName": COLUMN_FIELD},
                                                                  "doneField": {"referenceName": "WEF_6CB6_Kanban.Column.Done"}},
                         "columns": [{"name": "New", "columnType": "incoming", "stateMappings": {"User Story": "New", "Bug": "New"}},
                                     {"name": "Testing", "columnType": "inProgress", "stateMappings": {"User Story": "Active", "Bug": "Active"}},
                                     {"name": "Closed", "columnType": "outgoing", "stateMappings": {"User Story": "Closed", "Bug": "Closed"}}]})
        if method == "POST" and p.endswith("_apis/wit/wiql"):
            q = json["query"]
            return Resp({"workItems": [{"id": 42}] if "'Testing'" in q else []})
        if p == "Shop Web/_apis/wit/workitemsbatch":
            return Resp({"value": [{"id": 42, "fields": {k: v for k, v in ITEM["fields"].items() if k in json["fields"]}}]})
        if method == "GET" and p == "Shop Web/_apis/wit/workitems/42":
            return Resp(ITEM if (params or {}).get("$expand") == "all" else {"id": 42, "fields": ITEM["fields"]})
        if p == "Shop Web/_apis/wit/workItems/42/comments":
            if method == "POST":
                self.comments.append(json["text"])
                return Resp({"id": 9})
            return Resp({"comments": [{"text": "<p>Deployed to <b>https://pr-42.shop-web.dev/</b></p>", "createdBy": {"displayName": "Dev One"},
                                       "createdDate": "2026-10-14T12:00:00Z"}]})
        if method == "PATCH" and p == "Shop Web/_apis/wit/workitems/42":
            self.patches.append((headers, json))
            col = next(o["value"] for o in json if o["path"] == f"/fields/{COLUMN_FIELD}")
            return Resp({"id": 42, "fields": {COLUMN_FIELD: col}})
        return Resp({"message": f"no route {method} {p}"}, 404)


def test_parse_azure_links():
    p = ab.parse_azure_link(AZ_LINK)
    assert (p["org"], p["org_url"], p["project"], p["team"], p["board"]) == ("acme", "https://dev.azure.com/acme", "Shop Web", "Shop Web Team", "Stories")
    p = ab.parse_azure_link("acme.visualstudio.com/DefaultCollection/Shop/_workitems/edit/123")
    assert (p["org_url"], p["project"], p["item_id"], p["team"]) == ("https://acme.visualstudio.com", "Shop", "123", "")
    assert ab.parse_azure_link("https://dev.azure.com/acme/Shop/_boards/board")["team"] == ""
    for bad in ("", "https://dev.azure.com/acme", "https://github.com/a/b", "https://dev.azure.com/acme/_settings"):
        with pytest.raises(ValueError):
            ab.parse_azure_link(bad)
    assert ab.skill_key("Shop Web") == "SHOP_WEB" and ab.skill_key("2026 app") == "P_2026_APP"


def test_azure_connect_pick_column_then_board_reads_comments_and_moves(settings, monkeypatch):
    fake = FakeAzure()
    info = azure_connect.connect(AZ_LINK, "pat", http=fake)
    assert info["project"]["name"] == "Shop Web" and info["board"]["name"] == "Shop Web Team · Stories"
    assert [(c["name"], c["category"], c["count"]) for c in info["columns"]] == [("New", "new", 0), ("Testing", "indeterminate", 1), ("Closed", "done", 0)]
    assert info["user"]["name"] == "Andrei Luca"
    assert azure_connect.status()["connected"] and not azure_connect.status()["active"]

    st = azure_connect.choose_column("Testing", use_on_board=True)
    wf = load_settings()["workflow"]
    assert st["active"] and (wf["tracker"], wf["jira_column"], wf["jira_project"], wf["demo"]) == ("azure", "Testing", "SHOP_WEB", False)
    assert not jira_connect.status()["active"]
    assert type(board_client()).__name__ == "AzureBoards"

    board = ab.AzureBoards(load_settings()["azure"], wf, http=fake)
    rows = board.search_column("SHOP_WEB", "Testing")
    assert rows == [{"key": "42", "title": "Checkout shows gift card balance", "status": "Active", "status_cat": "indeterminate",
                     "issue_type": "User Story", "priority": "High", "components": ["Frontend"], "labels": ["FE", "checkout"]}]

    issue = board.get_issue("42")
    ctx = issue["context"]
    assert ctx["acceptance_criteria"] == "- Balance shows\n- Errors are clear"
    assert "Preview: https://pr-42.shop-web.dev/" in ctx["description"]
    assert ctx["comments"] == [{"author": "Dev One", "created": "2026-10-14 12:00", "body": "Deployed to https://pr-42.shop-web.dev/"}]
    assert ctx["parent"]["key"] == "40" and ctx["links"][0]["key"] == "41" and ctx["attachments"][0]["name"] == "balance.png"
    assert ctx["web_links"] == [{"title": "Design", "url": "https://www.figma.com/file/abc"}]
    assert ctx["fields"]["Test Notes"] == "Use the EU store" and ctx["fields"]["Board column"] == "Testing"
    assert ctx["reporter"] == "Andrei Luca" and ctx["sprint"] == "" and ctx["fields"]["Iteration"] == "Shop Web\\Sprint 4"

    board.add_comment("42", "**QA passed** on https://pr-42.shop-web.dev/\nAll good")
    assert fake.comments == ['<b>QA passed</b> on <a href="https://pr-42.shop-web.dev/">https://pr-42.shop-web.dev/</a><br>All good']

    assert [t["name"] for t in board.get_transitions("42")] == ["New", "Closed"]
    assert board.transition("42", "Closed") == "Closed"
    headers, ops = fake.patches[-1]
    assert headers["Content-Type"] == "application/json-patch+json"
    assert {o["path"]: o["value"] for o in ops} == {f"/fields/{COLUMN_FIELD}": "Closed", "/fields/WEF_6CB6_Kanban.Column.Done": False,
                                                   "/fields/System.State": "Closed"}

    azure_connect.disconnect()
    wf = load_settings()["workflow"]
    assert (wf["tracker"], wf["demo"]) == ("jira", True) and load_settings()["azure"]["pat"] == ""


def test_azure_bad_token_wrong_board_and_wrong_project_explain_themselves(settings):
    with pytest.raises(azure_connect.ConnectError, match="didn't accept the personal access token"):
        azure_connect.connect(AZ_LINK, "bad", http=FakeAzure())
    with pytest.raises(azure_connect.ConnectError, match="no board 'Epics'"):
        azure_connect.connect(AZ_LINK.replace("Stories", "Epics"), "pat", http=FakeAzure())
    with pytest.raises(azure_connect.ConnectError, match="Project 'Other'"):
        azure_connect.connect("https://dev.azure.com/acme/Other/_boards/board", "pat", http=FakeAzure())
    with pytest.raises(azure_connect.ConnectError, match="personal access token"):
        azure_connect.connect(AZ_LINK, "", http=FakeAzure())
