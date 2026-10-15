"""Workflow rules: gates, stale approvals, exact transitions, verified pushes. Run with: pytest -q"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from qa_app.workflow import agent, seed
from qa_app.workflow.clients import MockJira, MockTestRail
from qa_app.workflow.engine import GateError, Workflow
from qa_app.workflow.settings import WorkflowConfig as Config
from qa_app.workflow.store import TicketStore


@pytest.fixture()
def wf(tmp_path):
    cfg = Config(demo=True, data_dir=tmp_path, workspace=tmp_path / "ws", mock_speed=1000.0,
                 test_account="qa@example.com", test_ou="testou", signature="Commented by Claude for Luca")
    tickets = TicketStore(tmp_path / "tickets.json")
    for t in seed.seed_tickets():
        tickets.tickets[t.key] = t
    issues, late = seed.jira_issues()
    return Workflow(tickets, TicketStore(tmp_path / "live.json"), MockJira(issues, late), MockTestRail(), cfg=cfg)


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def settle(wf: Workflow) -> None:
    for _ in range(50):
        await asyncio.sleep(0.01)
        if all(t.done() for t in wf.tasks.values()):
            return


def test_checklist_is_not_tested_before_a_run(wf):
    t = wf.tickets.get("OPTR-48498")
    assert (t.stage, t.sub) == (0, "gate")
    assert {i.result for i in t.items()} == {"nt"}
    assert not t.ran


def test_wrong_action_and_stale_state_are_rejected(wf):
    async def go():
        with pytest.raises(GateError, match="waiting for 'approve_checklist'"):
            await wf.act("OPTR-48498", "approve_results", 0, "gate")
        await wf.act("OPTR-48498", "approve_checklist", 0, "gate")
        await settle(wf)
        # The same approval sent again must not carry over to gate 2.
        with pytest.raises(GateError, match="moved on"):
            await wf.act("OPTR-48498", "approve_checklist", 0, "gate")
        t = wf.tickets.get("OPTR-48498")
        assert (t.stage, t.sub) == (2, "gate") and t.ran
        assert [i.result for i in t.items()] == ["pass", "pass", "fail", "pass", "pass"]
    run(go())


def test_comment_does_not_approve_the_move_and_transitions_match_exactly(wf):
    async def go():
        await wf.act("OPTR-48455", "post_comment", 3, "comment", {"comment": "QA result: ok"})
        t = wf.tickets.get("OPTR-48455")
        assert (t.stage, t.sub) == (3, "transition")
        assert wf.mock_jira.comments["OPTR-48455"][-1] == "QA result: ok"
        assert wf.mock_jira.issues["OPTR-48455"]["status"] == "Open"  # not moved yet
        with pytest.raises(GateError) as e:
            await wf.act("OPTR-48455", "transition", 3, "transition", {"target": "docs"})
        assert "Docs" in e.value.extra["transitions"]
        await wf.act("OPTR-48455", "transition", 3, "transition", {"target": "Docs"})
        await settle(wf)
        t = wf.tickets.get("OPTR-48455")
        assert (t.stage, t.sub, t.status) == (4, "gate", "Docs")
    run(go())


def test_draft_skips_duplicates_and_push_is_verified(wf):
    async def go():
        tr = wf.mock_testrail
        t = wf.tickets.get("OPTR-48437")
        assert t.sub == "gate"
        await wf.act("OPTR-48437", "approve_draft", 4, "gate")
        assert len(tr.cases[101]) == 1  # approving pushes nothing
        await wf.act("OPTR-48437", "push", 4, "approved")
        assert wf.tickets.get("OPTR-48437") is None
        titles = [c["title"] for c in tr.cases[101]]
        assert len(titles) == len(set(titles))
    run(go())


def test_retry_after_partial_push_only_adds_missing_cases(wf):
    async def go():
        tr = wf.mock_testrail
        real_add = tr.add_case
        calls = {"n": 0}

        def flaky(section_id, title, steps, expected):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("network dropped")
            return real_add(section_id, title, steps, expected)

        tr.add_case = flaky  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            await wf.act("OPTR-48430", "push", 4, "approved")
        assert wf.tickets.get("OPTR-48430").push_attempted
        tr.add_case = real_add  # type: ignore[method-assign]
        await wf.act("OPTR-48430", "push", 4, "approved")
        titles = [c["title"] for c in tr.cases[102]]
        assert len(titles) == 3 and len(set(titles)) == 3
    run(go())


def test_blocked_ticket_needs_a_real_url(wf):
    async def go():
        with pytest.raises(GateError):
            await wf.act("OPTR-48507", "use_env", 0, "blocked", {"url": "pr-1"})
        await wf.act("OPTR-48507", "use_env", 0, "blocked", {"url": "https://pr-1.preview.myapp.test/"})
        await settle(wf)
        assert wf.tickets.get("OPTR-48507").sub == "gate"
    run(go())


def test_environment_resolution(tmp_path):
    cfg = Config(demo=False, data_dir=tmp_path)
    env, reason = agent.resolve_environment({"merged": True}, cfg)
    assert env is None and "No test environment link" in reason  # no default set: never guess
    cfg = Config(demo=False, data_dir=tmp_path, default_env_url="https://staging.myapp.test/", default_env_name="staging")
    env, _ = agent.resolve_environment({"merged": True}, cfg)
    assert env and env.shared and env.url == "https://staging.myapp.test/" and env.kind == "staging · ticket is merged"
    env, _ = agent.resolve_environment({"merged": False, "comments": ["Deployed to https://pr-42.preview.myapp.test/"]}, cfg)
    assert env and env.url == "https://pr-42.preview.myapp.test/" and not env.shared
    env, reason = agent.resolve_environment({"merged": False, "type": "BE", "status": "Open", "comments": []}, cfg)
    assert env is None and "Paste the URL" in reason


def test_comment_template():
    t = seed.seed_tickets()[5]  # OPTR-48466 with results
    cfg = Config(demo=True, test_account="qa@example.com", test_ou="testou", signature="Commented by Claude for Luca")
    text = agent.comment_text(t, cfg, date(2026, 10, 14))
    assert text.startswith("QA result: 5/8 checks pass. Verified 14 Oct 2026 against feature-optr-48466")
    assert "prefixed OPTR-48466" in text
    assert "❌ Leading and trailing spaces are trimmed (Major)" in text
    assert text.endswith("Commented by Claude for Luca")


def test_playwright_report_mapping():
    report = {"suites": [{"specs": [
        {"title": "[1] passes", "tests": [{"results": [{"status": "passed"}], "annotations": []}]},
        {"title": "[2] fails", "tests": [{"results": [{"status": "failed", "error": {"message": "expected 1\nmore"}}], "annotations": []}]},
        {"title": "[3] partial", "tests": [{"results": [{"status": "passed"}], "annotations": [{"type": "qa-result", "description": "partial: slow"}]}]},
        {"title": "[4] skipped", "tests": [{"results": [{"status": "skipped"}], "annotations": []}]},
    ]}]}
    assert agent.parse_playwright_json(report, 5) == [("pass", ""), ("fail", "expected 1"), ("partial", "slow"), ("nt", ""), ("nt", "")]


def test_jira_comment_uses_wiki_bold(monkeypatch):
    from qa_app.integrations import jira

    sent = {}

    class FakeSession:
        def post(self, url, json, timeout):
            sent.update(json)

            class R:
                def raise_for_status(self):
                    pass
            return R()

    monkeypatch.setattr(jira, "_session", lambda cfg: FakeSession())
    jira.add_comment({"base_url": "https://x.atlassian.net"}, "OPTR-1", "QA result\n\n**Search**\n✅ Works")
    assert sent["body"] == "QA result\n\n*Search*\n✅ Works"


def test_report_renders(tmp_path):
    from datetime import datetime

    from qa_app.models import Finding, PageResult, RunConfig, RunResult, Severity
    from qa_app.report import write_html

    r = RunResult("20261014-120000", RunConfig(url="https://shop.example.com"), datetime(2026, 10, 14, 12),
                  datetime(2026, 10, 14, 12, 3), [PageResult("https://shop.example.com/", 200, 812, "Shop")],
                  [Finding("seo", "Missing meta description", Severity.MINOR, "https://shop.example.com/")],
                  {"lighthouse": {"https://shop.example.com/": {"performance": 52, "accessibility": 81,
                                                               "best-practices": 92, "seo": 88, "lcp_ms": 4100, "cls": 0.12}}})
    html = write_html(r, tmp_path).read_text(encoding="utf-8")
    assert "shop.example.com" in html and "Missing meta description" in html and "Failed" not in html
    assert ">52<" in html and "4.1 s" in html


def test_ticket_type_from_jira_components():
    from qa_app.workflow.models import classify_type
    fe, be = ["Frontend", "FE"], ["Backend", "BE", "Core"]
    assert classify_type(["Frontend"], fe, be) == "FE"
    assert classify_type(["core"], fe, be) == "BE"  # names match ignoring case
    assert classify_type(["Frontend", "Backend"], fe, be) == "FE+BE"
    assert classify_type(["Payments"], fe, be) == ""  # unmapped component: untyped, not guessed
    assert classify_type([], fe, be) == ""
    assert Config(fe_components=("Web app",), be_components=("Core",)).ticket_type(["Web app", "Core"]) == "FE+BE"


def test_saved_tickets_with_old_component_load_as_fe_or_be():
    from qa_app.workflow.models import Ticket
    assert Ticket.model_validate({"key": "A-1", "title": "x", "comp": "Core"}).type == "BE"
    assert Ticket.model_validate({"key": "A-2", "title": "x", "comp": "Frontend"}).type == "FE"
    assert "comp" not in Ticket(key="A-3", title="x").public()


def test_sync_types_new_tickets_and_finds_preview_in_comments(wf, tmp_path):
    async def go():
        assert await wf.sync() == ["OPTR-48520"]
        t = wf.tickets.get("OPTR-48520")
        assert t.type == "FE" and t.components == ["Frontend"]
    run(go())
    types = {t.key: t.type for t in seed.seed_tickets()}
    assert types["OPTR-48466"] == "FE+BE" and types["OPTR-48437"] == "BE" and types["OPTR-48498"] == "FE"
    cfg = Config(demo=True, data_dir=tmp_path)
    issue = {"merged": False, "status": "Open", "comments": ["Preview is up: https://x.pages.dev/"]}
    env, _ = agent.resolve_environment({**issue, "type": "FE+BE"}, cfg)
    assert env and env.url == "https://x.pages.dev/"

def test_redo_step_1_rereads_a_changed_ticket(tmp_path):
    cfg = Config(demo=True, data_dir=tmp_path, workspace=tmp_path / "ws", mock_speed=1000.0,
                 default_env_url="https://staging.shop-demo.test/", default_env_name="shared staging")
    tickets = TicketStore(tmp_path / "tickets.json")
    for t in seed.seed_tickets():
        tickets.tickets[t.key] = t
    issues, late = seed.jira_issues()
    jira = MockJira(issues, late)
    wf = Workflow(tickets, TicketStore(tmp_path / "live.json"), jira, MockTestRail(), cfg=cfg)

    async def go():
        # Gate 2 with results: the developer redeploys and says so on the ticket.
        t = wf.tickets.get("OPTR-48466")
        assert (t.stage, t.sub) == (2, "gate") and t.ran
        jira.add_comment("OPTR-48466", "Fixed the trimming, redeployed to https://feature-optr-48466-v2.shop-admin.pages.dev/")
        await wf.act("OPTR-48466", "redo_gather", 2, "gate")
        await settle(wf)
        t = wf.tickets.get("OPTR-48466")
        # two deploy links now: the user chooses, with the newest one suggested
        assert (t.stage, t.sub) == (0, "blocked") and not t.ran and t.env is None
        assert {i.result for i in t.items()} == {"nt"}  # earlier results discarded
        sug = [c for c in t.env_candidates if c["suggested"]]
        assert [c["url"] for c in sug] == ["https://feature-optr-48466-v2.shop-admin.pages.dev/"] and sug[0]["source"].startswith("comment by")
        assert "Suggested: feature-optr-48466-v2.shop-admin.pages.dev" in t.doing
        assert t.context["comments"] == 3
        await wf.act("OPTR-48466", "use_env", 0, "blocked", {"url": "feature-optr-48466-v2.shop-admin.pages.dev"})
        await settle(wf)
        t = wf.tickets.get("OPTR-48466")
        assert (t.stage, t.sub) == (0, "gate") and t.env.url == sug[0]["url"] and t.env.source.startswith("you · from comment by")
        assert len(t.env_candidates) >= 2  # every link still listed, to change later

        # Change the environment at Gate 1: re-reads the ticket and tests on the new address.
        await wf.act("OPTR-48466", "redo_gather", 0, "gate", {"env_url": "https://other.preview.test"})
        await settle(wf)
        t = wf.tickets.get("OPTR-48466")
        assert (t.stage, t.sub) == (0, "gate") and t.env.url == "https://other.preview.test" and t.env.source == "you"
        assert t.env_candidates  # still listed

        # An environment the user chose survives a redo.
        await wf.act("OPTR-48507", "use_env", 0, "blocked", {"url": "https://mine.test/"})
        await settle(wf)
        await wf.act("OPTR-48507", "redo_gather", 0, "gate")
        await settle(wf)
        assert wf.tickets.get("OPTR-48507").env.url == "https://mine.test/"

        # Not once Jira has been told, and not on a stale view.
        with pytest.raises(GateError, match="already being posted"):
            await wf.act("OPTR-48455", "redo_gather", 3, "comment")
        with pytest.raises(GateError, match="moved on"):
            await wf.act("OPTR-48466", "redo_gather", 2, "gate")
        with pytest.raises(GateError, match="busy"):
            await wf.act("OPTR-48490", "redo_gather", 1, "working")
    run(go())


def test_use_env_accepts_an_address_without_https(wf):
    async def go():
        with pytest.raises(GateError, match="e.g. staging"):
            await wf.act("OPTR-48507", "use_env", 0, "blocked", {"url": "not an address"})
        await wf.act("OPTR-48507", "use_env", 0, "blocked", {"url": "staging.myapp.com"})
        await settle(wf)
        assert wf.tickets.get("OPTR-48507").env.url == "https://staging.myapp.com"
    run(go())


def test_jira_colours_come_from_type_priority_and_status_category(wf):
    from qa_app.workflow.models import status_category
    from qa_app.workflow.ticket_context import brief
    assert status_category({"name": "In Review", "statusCategory": {"key": "indeterminate"}}) == "indeterminate"
    assert status_category({"name": "Whatever", "statusCategory": {"name": "To Do"}}) == "new"
    assert [status_category(n) for n in ("Done", "Backlog", "In QA", "")] == ["done", "new", "indeterminate", ""]
    row = brief({"key": "A-1", "fields": {"summary": "x", "status": {"name": "Done", "statusCategory": {"key": "done"}},
                                         "issuetype": {"name": "Bug"}, "priority": {"name": "High"}, "components": [{"name": "Frontend"}]}})
    assert (row["issue_type"], row["priority"], row["status_cat"], row["components"]) == ("Bug", "High", "done", ["Frontend"])

    async def go():  # a sync keeps the card's status, type and priority in step with Jira
        wf.mock_jira.issues["OPTR-48498"].update(status="Reopened", priority="Highest")
        await wf.sync()
        t = wf.tickets.get("OPTR-48498")
        assert (t.status, t.status_cat, t.priority, t.issue_type) == ("Reopened", "new", "Highest", "Bug")
        assert wf.tickets.get("OPTR-48520").issue_type == "Story"  # new tickets arrive with them
    run(go())


def test_type_comes_from_labels_too():
    from qa_app.workflow.models import classify_type
    fe, be = ["Frontend", "FE"], ["Backend", "BE"]
    assert classify_type([], fe, be, labels=["FE+BE"]) == "FE+BE"  # how the real SCRUM tickets are marked
    assert classify_type([], fe, be, labels=["fe + be"]) == "FE+BE"
    assert classify_type([], fe, be, labels=["Fullstack"]) == "FE+BE"
    assert classify_type([], fe, be, labels=["BE", "login"]) == "BE"
    assert classify_type(["Frontend"], fe, be, labels=["BE"]) == "FE+BE"  # component + label
    assert Config().ticket_type([], ["FE/BE"]) == "FE+BE"


def test_auto_sync_runs_on_its_interval_and_backs_off_after_a_failure(tmp_path):
    from qa_app.workflow.store import bus

    class Jira(MockJira):
        fail = False

        def search_column(self, project, column):
            if self.fail:
                raise RuntimeError("401 Unauthorized")
            return super().search_column(project, column)

    issues, late = seed.jira_issues()
    jira = Jira(issues[:1], [])
    cfg = Config(demo=False, data_dir=tmp_path, workspace=tmp_path / "ws", auto_sync_minutes=5, jira_project="SCRUM", jira_column="QA")
    w = Workflow(TicketStore(tmp_path / "demo.json"), TicketStore(tmp_path / "live.json"), jira, MockTestRail(), cfg=cfg)
    w.jira = lambda: jira
    w.spawn = lambda key, coro: coro.close()  # don't start step 1 here
    seen = []

    async def go():
        events = bus.subscribe()
        t0 = 1_000_000.0
        assert await w.auto_sync_once(now=t0) == [issues[0]["key"]]       # never synced: due now
        w.tickets.last_sync = t0
        assert await w.auto_sync_once(now=t0 + 60) is None                # 1 min later: not due
        jira.fail = True
        assert await w.auto_sync_once(now=t0 + 301) is None               # due, but Jira fails
        assert w.sync_error.startswith("401")
        assert await w.auto_sync_once(now=t0 + 400) is None               # waits a full interval after a failure
        jira.fail = False
        assert await w.auto_sync_once(now=t0 + 301 + 300) == []           # works again, nothing new
        assert w.sync_error == ""
        w._cfg = Config(demo=False, data_dir=tmp_path, auto_sync_minutes=0)
        assert await w.auto_sync_once(now=t0 + 10_000) is None            # off
        await asyncio.sleep(0.01)
        while not events.empty():
            seen.append(events.get_nowait())
        bus.unsubscribe(events)
    run(go())
    syncs = [e for e in seen if e["type"] == "sync"]
    assert [bool(e["error"]) for e in syncs] == [False, True, False]


def test_chat_with_claude_suggests_actions_that_run_only_when_clicked(wf, monkeypatch):
    replies = []

    async def fake_ask(cfg, system, prompt, max_tokens=4000, step=None):
        replies.append((system, prompt, step))
        return ("It stopped because the ticket has two preview links. The newer one is from Ben.\n\n"
                '```actions\n[{"kind": "change_env", "url": "https://pr-2.preview.acme.dev/", "label": "Test on pr-2"},'
                ' {"kind": "set_comment", "text": "nope", "label": "Rewrite comment"}, {"kind": "rm_rf", "label": "bad"}]\n```')

    monkeypatch.setattr(agent, "ask_claude", fake_ask)
    wf._cfg.anthropic_api_key, wf._cfg.claude_mode = "k", "api"

    async def go():
        key = "OPTR-48507"  # waiting for an environment
        t = wf.tickets.get(key)
        assert (t.stage, t.sub) == (0, "blocked")
        await wf.chat_send(key, "why did this stop?")
        assert wf.tickets.get(key).chat_busy
        await asyncio.gather(*wf.chat_tasks.values())
        t = wf.tickets.get(key)
        assert not t.chat_busy and [m["role"] for m in t.chat] == ["user", "assistant"]
        msg = t.chat[1]
        assert msg["text"].startswith("It stopped because") and "```" not in msg["text"]
        assert [a["kind"] for a in msg["actions"]] == ["change_env", "set_comment"]  # unknown kinds dropped
        system, prompt, step = replies[0]
        assert step == "chat" and key in prompt and "why did this stop?" in prompt and "set_checklist" in system
        assert "Actions allowed right now: redo_gather, change_env" in prompt

        # nothing ran yet; a suggestion that doesn't fit the ticket now is refused with a reason
        assert wf.tickets.get(key).env is None
        with pytest.raises(GateError, match="Only before the comment is posted"):
            await wf.chat_apply(key, 1, 1, 0, "blocked")
        with pytest.raises(GateError, match="moved on"):
            await wf.chat_apply(key, 1, 0, 0, "gate")
        # clicking it runs it, once
        await wf.chat_apply(key, 1, 0, 0, "blocked")
        await settle(wf)
        t = wf.tickets.get(key)
        assert t.env.url == "https://pr-2.preview.acme.dev/" and t.chat[1]["actions"][0]["state"] == "applied"
        assert t.chat[-1]["role"] == "event" and "Test on pr-2" in t.chat[-1]["text"]
        with pytest.raises(GateError, match="Already done"):
            await wf.chat_apply(key, 1, 0, t.stage, t.sub)
        with pytest.raises(GateError, match="still answering|Write a message"):
            await wf.chat_send(key, "   ")
        assert wf.chat_clear(key).chat == []
    run(go())


def test_chat_needs_claude_connected(wf):
    wf._cfg.claude_mode = "off"
    with pytest.raises(GateError, match="Connect Claude"):
        run(wf.chat_send("OPTR-48507", "hi"))
