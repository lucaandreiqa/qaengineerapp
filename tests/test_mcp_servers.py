import pytest

from qa_app import config
from qa_app.integrations import mcp_servers as ms
from qa_app.integrations.mcp_client import McpError

TOOLS = [
    {"name": "get_merge_request", "description": "Read one merge request", "inputSchema": {"type": "object"}},
    {"name": "search_issues", "description": "Search", "annotations": {"readOnlyHint": True}},
    {"name": "get_secret_but_writes", "description": "Says get, but the server marks it as a write",
     "annotations": {"readOnlyHint": False}},
    {"name": "create_note", "description": "Adds a note to a merge request"},
    {"name": "delete_branch", "description": "Deletes", "annotations": {"destructiveHint": True}},
]


class FakeSession:
    calls: list = []

    def __init__(self, srv):
        self.srv = srv

    def tools(self):
        return TOOLS

    def call(self, name, args):
        FakeSession.calls.append((self.srv["id"], name, args))
        return {"text": "x" * 30000} if name == "search_issues" else {"iid": args.get("iid"), "title": "Fix rounding"}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(ms, "_session", lambda srv: FakeSession(srv))
    FakeSession.calls = []
    return tmp_path


def test_tools_are_sorted_into_read_and_write(home):
    kinds = {t["name"]: ms.classify(t) for t in TOOLS}
    assert kinds == {"get_merge_request": "read", "search_issues": "read", "get_secret_but_writes": "write",
                     "create_note": "write", "delete_branch": "write"}


def test_only_https_or_localhost_addresses(home):
    assert ms.check_url("https://gitlab.example.com/api/mcp") == "https://gitlab.example.com/api/mcp"
    assert ms.check_url("http://localhost:8000/mcp") == "http://localhost:8000/mcp"
    assert ms.check_url("  https://mcp.notion.com/mcp  ") == "https://mcp.notion.com/mcp"
    for bad in ("http://gitlab.example.com/mcp", "ftp://x/mcp", "gitlab.example.com", "", "https://"):
        with pytest.raises(McpError):
            ms.check_url(bad)


def test_adding_a_server_lists_its_tools_but_nothing_runs_until_saved(home):
    srv = ms.add("GitLab", "https://gitlab.example.com/api/mcp", auth="token", token="glpat-mine")
    assert srv["id"] == "gitlab" and srv["confirmed"] is False
    assert srv["read"] == ["get_merge_request", "search_issues"] and srv["write"] == []
    with pytest.raises(McpError):
        ms.call_read("gitlab", "get_merge_request", {"iid": 5})
    assert ms.catalog() == []


def test_saved_read_tools_run_trimmed_and_others_are_refused(home):
    ms.add("GitLab", "https://gitlab.example.com/api/mcp", auth="token", token="t")
    # a write tool can't be put in the read list, and unknown names are dropped
    srv = ms.save("gitlab", read=["get_merge_request", "search_issues", "create_note", "nope"], write=[])
    assert srv["read"] == ["get_merge_request", "search_issues"] and srv["confirmed"]
    assert '"Fix rounding"' in ms.call_read("gitlab", "get_merge_request", {"iid": 5})
    assert len(ms.call_read("gitlab", "search_issues", {})) <= ms.RESULT_MAX + 100
    for tool in ("create_note", "delete_branch", "made_up"):
        with pytest.raises(McpError):
            ms.call_read("gitlab", tool, {})
    with pytest.raises(McpError):
        ms.call_read("other", "get_merge_request", {})
    assert [c[1] for c in FakeSession.calls] == ["get_merge_request", "search_issues"]


def test_write_tools_run_only_when_switched_on(home):
    ms.add("GitLab", "https://gitlab.example.com/api/mcp", auth="token", token="t")
    ms.save("gitlab", read=["get_merge_request"], write=["create_note", "get_merge_request"])
    assert ms.get("gitlab")["write"] == ["create_note"]
    ms.call_write("gitlab", "create_note", {"body": "QA passed"})
    with pytest.raises(McpError):
        ms.call_write("gitlab", "delete_branch", {})
    assert ms.write_catalog()[0]["tool"] == "create_note"


def test_catalog_and_public_view_never_show_the_token(home):
    ms.add("GitLab", "https://gitlab.example.com/api/mcp", auth="token", token="glpat-secret")
    ms.save("gitlab", read=["get_merge_request"], write=[])
    cat = ms.catalog()
    assert cat == [{"server": "gitlab", "name": "GitLab", "tool": "get_merge_request", "description": "Read one merge request",
                    "schema": {"type": "object"}}]
    assert "gitlab get_merge_request" in ms.catalog_md()
    pub = ms.public()
    assert "glpat-secret" not in str(pub) and pub[0]["has_token"] is True


def test_a_need_names_a_call(home):
    assert ms.parse_need('mcp: gitlab get_merge_request {"iid": 5}') == ("gitlab", "get_merge_request", {"iid": 5})
    assert ms.parse_need("mcp: gitlab search_issues") == ("gitlab", "search_issues", {})
    assert ms.parse_need("The PR diff for SCRUM-5") is None
    with pytest.raises(McpError):
        ms.parse_need("mcp: gitlab get_merge_request {not json")


def test_two_servers_with_the_same_name_get_different_ids_and_remove_works(home):
    a = ms.add("GitLab", "https://a.example.com/mcp", auth="none")
    b = ms.add("GitLab", "https://b.example.com/mcp", auth="none")
    assert a["id"] == "gitlab" and b["id"] == "gitlab-2"
    ms.remove("gitlab")
    assert [s["id"] for s in ms.servers()] == ["gitlab-2"]
