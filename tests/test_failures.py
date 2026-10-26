"""Integration failures in plain words, with where to fix them."""
from __future__ import annotations

from qa_app.integrations import failures as F


def test_a_refused_sign_in_names_the_service_and_points_to_its_settings():
    f = F.explain("401 Client Error: Unauthorized for url: https://acme.atlassian.net/rest/api/3/search", doing="sync the board")
    assert f["service"] == "jira" and f["name"] == "Jira" and f["kind"] == "auth"
    assert f["title"] == "Jira didn't accept the sign-in"
    assert "sync the board" in f["message"] and "Test connection" in f["fix"]
    assert f["target"] == "jira" and f["action"] == "Fix Jira"
    assert f["detail"].startswith("401 Client Error")


def test_the_step_or_caller_can_say_which_service_when_the_error_doesnt():
    f = F.explain("HTTP 403 Forbidden", service="testrail")
    assert f["service"] == "testrail" and f["kind"] == "permission" and "access" in f["fix"]
    assert F.explain("Connection timed out", service="slack")["kind"] == "network"


def test_claude_failures():
    assert F.explain("Error code: 401 - invalid x-api-key")["kind"] == "auth"
    billing = F.explain("Your credit balance is too low to access the Anthropic API.")
    assert billing["service"] == "claude" and billing["kind"] == "billing" and "Claude Code" in billing["fix"]
    cli = F.explain("[Errno 2] No such file or directory: 'claude'", service="claude")
    assert cli["kind"] == "missing" and "Install Claude Code" in cli["fix"]
    busy = F.explain("Error code: 529 - Overloaded", service="claude")
    assert busy["kind"] == "server" and busy["retry"] is True


def test_kinds():
    cases = {
        "HTTPSConnectionPool(host='x.testrail.io'): Max retries exceeded (Caused by NameResolutionError)": "network",
        "429 Too Many Requests": "rate",
        "502 Bad Gateway": "server",
        "404 Not Found: project ACME does not exist": "notfound",
        "TestRail is not configured": "missing",
    }
    for text, kind in cases.items():
        assert F.explain(text, service="testrail")["kind"] == kind, text


def test_services_are_recognised_from_the_error():
    assert F.explain("https://dev.azure.com/acme: TF400813 not authorized")["service"] == "azure"
    assert F.explain("invalid_payload from hooks.slack.com")["service"] == "slack"
    assert F.explain("gh: Bad credentials (HTTP 401)")["service"] == "github"
    assert F.explain("MCP server gitlab: 401", service="mcp:gitlab")["target"] == "mcp:gitlab"


def test_not_every_error_is_an_integration_failure():
    assert F.explain("Stopped by you. Press Retry to start this step again.") is None
    assert F.explain("No checks to build tests from.") is None
    assert F.explain("") is None
    # an unknown error from a known service still gets the service and a way to its settings
    f = F.explain("something odd happened", service="testrail")
    assert f["kind"] == "other" and f["action"] == "Fix TestRail" and "something odd" in f["detail"]


def test_a_card_test_gets_a_short_hint_but_no_button():
    assert F.hint("401 Unauthorized", "testrail") == "Enter a new API key, then press Test connection."
    assert "webhook URL" in F.hint("invalid_token", "slack") or "webhook URL" in F.explain("401", "slack")["fix"]
    assert F.hint("fine", "testrail") == ""


def test_a_sync_error_is_the_trackers_unless_it_names_another_service(tmp_path, monkeypatch):
    from qa_app import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    assert F.sync_info("Connection timed out")["service"] == "jira"
    config.save_section("workflow", {"tracker": "azure"})
    f = F.sync_info("401 Unauthorized")
    assert f["service"] == "azure" and "sync the board" in f["message"]
    assert F.sync_info("") is None


def test_each_board_step_knows_its_service():
    assert F.for_stage(1) == "claude" and F.for_stage(3, "azure") == "azure" and F.for_stage(4) == "testrail"
    assert F.for_stage(0) is None and F.for_stage(2) is None
