"""Workflow rules: gates, stale approvals, exact transitions, verified pushes. Run with: pytest -q"""
from __future__ import annotations

import asyncio
import json
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
        assert any(m["role"] == "event" and "Test on pr-2" in m["text"] for m in t.chat)
        assert any(m["role"] == "progress" and "Testing on https://pr-2.preview.acme.dev/" in m["text"] for m in t.chat)
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


def test_a_run_is_recorded_with_live_check_progress_and_summaries(wf):
    from qa_app.workflow import history

    async def go():
        key = "OPTR-48498"  # demo ticket waiting at Gate 1
        t = wf.tickets.get(key)
        assert (t.stage, t.sub) == (0, "gate")
        seen = []
        orig = wf.patch

        def spy(k, **f):  # watch the live updates the board receives
            if k == key and "running_item" in f:
                seen.append(f["running_item"])
            return orig(k, **f)
        wf.patch = spy
        await wf.act(key, "approve_checklist", 0, "gate")
        await settle(wf)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if wf.tickets.get(key).sub == "gate":
                break
        wf.patch = orig
        t = wf.tickets.get(key)
        assert (t.stage, t.sub) == (2, "gate") and t.running_item == -1 and t.run_id
        n = len(t.items())
        assert [x for x in seen if x >= 0] == list(range(n))  # each check ran in turn, live
        store = wf.history()
        rec = store.get(t.run_id)
        assert rec["mode"] == "demo" and rec["run_no"] == 1 and rec["trigger"] == "first" and rec["status"] in ("passed", "failed")
        assert [i["result"] for i in rec["items"]] == [i.result for i in t.items()]
        assert rec["counts"] == history.counts([{"result": i.result} for i in t.items()])
        assert store.list(key=key)[0]["id"] == t.run_id and str(store.root).endswith("history/demo")
        progress = [m["text"] for m in t.chat if m["role"] == "progress"]
        assert any(p.startswith("Run 1 started") for p in progress) and any(p.startswith(f"Check {n} of {n}") for p in progress)
        assert any(p.startswith("Run finished") for p in progress)
        summary = [m for m in t.chat if m["role"] == "assistant"][-1]["text"]
        assert "checks passed" in summary or "need a look" in summary
    run(go())


def test_a_run_that_cannot_start_is_recorded_as_an_error(wf, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("npx is not installed")
    monkeypatch.setattr(agent, "run_spec", boom)
    key = "OPTR-48498"
    t = wf.tickets.get(key)
    wf._cfg.demo = False  # a real run, with the board's demo tickets moved to the live store
    wf.live_store.tickets[key] = t

    async def go():
        with pytest.raises(RuntimeError):
            await wf._run(key)
    run(go())
    rec = wf.history().list(key=key)[0]
    assert rec["status"] == "error" and "history/live" in str(wf.history().root)
    assert wf.history().get(rec["id"])["error"] == "npx is not installed"


def _live(wf, key):
    t = wf.tickets.get(key)
    wf._cfg.demo = False
    wf.live_store.tickets[key] = t
    return t


def test_a_live_run_shows_its_terminal_and_explains_it_in_the_feed(wf, monkeypatch):
    from qa_app.workflow import store as store_mod
    published = []
    monkeypatch.setattr(store_mod.bus, "publish", lambda ev: published.append(ev))

    async def fake(cfg, t, run_dir, on_event, on_output=None):
        await on_output("sys", "$ npm install")
        await on_output("out", "added 3 packages in 2s")
        await on_output("out", "Running 3 tests using 1 worker")
        await on_output("stall", "No output for 45s. Last line: Ok to proceed? (y)")
        raise RuntimeError("Playwright did not produce a report: exit code 1")
    monkeypatch.setattr(agent, "run_spec", fake)
    key = "OPTR-48498"
    _live(wf, key)

    async def go():
        with pytest.raises(RuntimeError):
            await wf._run(key)
    run(go())
    lines = wf.terminal(key)
    assert [l["text"] for l in lines] == ["$ npm install", "added 3 packages in 2s", "Running 3 tests using 1 worker",
                                         "No output for 45s. Last line: Ok to proceed? (y)"]
    assert [e["line"]["text"] for e in published if e.get("type") == "term" and e.get("key") == key and "line" in e][:1] == ["$ npm install"]
    t = wf.tickets.get(key)
    progress = [m["text"] for m in t.chat if m["role"] == "progress"]
    assert any("Installing Playwright" in p for p in progress)
    assert any("Playwright started: 3 tests" in p for p in progress)
    stall = [m["text"] for m in t.chat if m["role"] == "assistant" and "silent" in m["text"]]
    assert stall and "Ok to proceed? (y)" in stall[0] and "Stop" in stall[0]  # what it saw + how to unblock


def test_a_running_test_can_be_stopped(wf, monkeypatch):
    started = asyncio.Event()

    async def forever(cfg, t, run_dir, on_event, on_output=None):
        started.set()
        await asyncio.sleep(3600)
    monkeypatch.setattr(agent, "run_spec", forever)
    key = "OPTR-48498"
    t = _live(wf, key)
    wf.live_store.tickets[key] = t.model_copy(update={"stage": 2, "sub": "working"})

    async def go():
        wf.spawn(key, wf._run(key))
        await asyncio.wait_for(started.wait(), 2)
        cur = wf.tickets.get(key)
        await wf.act(key, "stop", cur.stage, cur.sub)
        await asyncio.sleep(0.05)
    run(go())
    t = wf.tickets.get(key)
    rec = wf.history().list(key=key)[0]
    assert rec["status"] == "stopped" and t.error.startswith("Stopped by you") and t.running_item == -1
    assert any("stopped" in m["text"].lower() for m in t.chat)


def test_stop_needs_something_running(wf):
    key = "OPTR-48498"
    t = wf.tickets.get(key)
    with pytest.raises(GateError):
        run(wf.act(key, "stop", t.stage, t.sub))


def _skills_in(tmp_path, monkeypatch):
    from qa_app.workflow import skills
    from qa_app import config as appconfig
    monkeypatch.setattr(skills, "root", lambda: tmp_path / "skills")
    monkeypatch.setattr(appconfig, "SETTINGS_FILE", tmp_path / "settings.json")
    return skills


def test_after_a_move_claude_offers_to_learn_the_state_and_picks_it_next_time(wf, tmp_path, monkeypatch):
    from qa_app.workflow import move_rules
    skills = _skills_in(tmp_path, monkeypatch)
    key = "OPTR-48455"
    wf.tickets.tickets[key] = wf.tickets.get(key).model_copy(update={"target": ""})  # no state planned at 3a
    result = move_rules.outcome(wf.tickets.get(key).items())

    async def go():
        await wf.act(key, "post_comment", 3, "comment", {"comment": "QA result: ok"})
        assert wf.tickets.get(key).target == ""  # nothing learned yet: you choose
        await wf.act(key, "transition", 3, "transition", {"target": "Docs"})
        await settle(wf)
        t = wf.tickets.get(key)
        mi, ask = [(i, m) for i, m in enumerate(t.chat) if m.get("actions") and m["actions"][0]["kind"] == "learn_move"][-1]
        assert "Docs" in ask["text"] and [a["kind"] for a in ask["actions"]] == ["learn_move", "skip_learn"]
        assert ask["actions"][0]["state"] == "Docs" and ask["actions"][0]["outcome"] == result
        # clicked later, after the ticket moved on to TestRail: still works
        await wf.chat_apply(key, mi, 0, t.stage, t.sub)
        t = wf.tickets.get(key)
        assert [a.get("state") for a in t.chat[mi]["actions"]] == ["applied", "dismissed"]
        assert move_rules.rules(skills.personal("jira-comment")) == {result: "Docs"}   # in your personal skill
        assert skills.choice(wf.cfg.jira_project) == "personal"

    run(go())
    # the next ticket with the same kind of result gets the state picked by the skill
    nxt = wf.tickets.get(key).model_copy(update={"key": "OPTR-90001", "stage": 3, "sub": "comment", "target": "", "chat": []})
    wf.tickets.tickets["OPTR-90001"] = nxt
    wf.mock_jira.issues["OPTR-90001"] = dict(wf.mock_jira.issues[key], status="Open")

    async def again():
        await wf.act("OPTR-90001", "post_comment", 3, "comment", {"comment": "QA result: ok"})
        t = wf.tickets.get("OPTR-90001")
        assert t.target == "Docs" and t.target_from == "skill"
        await wf.act("OPTR-90001", "transition", 3, "transition", {"target": "Docs"})
        await settle(wf)
        t = wf.tickets.get("OPTR-90001")
        assert not [m for m in t.chat if m.get("actions") and m["actions"][0]["kind"] == "learn_move"]  # already knows
    run(again())


def test_no_thanks_leaves_the_skill_alone(wf, tmp_path, monkeypatch):
    skills = _skills_in(tmp_path, monkeypatch)
    key = "OPTR-48455"

    async def go():
        await wf.act(key, "post_comment", 3, "comment", {"comment": "QA result: ok"})
        await wf.act(key, "transition", 3, "transition", {"target": "Docs"})
        await settle(wf)
        t = wf.tickets.get(key)
        mi = [i for i, m in enumerate(t.chat) if m.get("actions") and m["actions"][0]["kind"] == "learn_move"][-1]
        await wf.chat_apply(key, mi, 1, t.stage, t.sub)
        t = wf.tickets.get(key)
        assert [a.get("state") for a in t.chat[mi]["actions"]] == ["dismissed", "applied"]
    run(go())
    assert not skills.has_personal()  # nothing learnt, no personal skills made


def test_gather_has_no_fixed_item_cap_says_claude_has_no_tools_and_keeps_its_analysis(wf, monkeypatch, tmp_path):
    from qa_app.workflow import agent as ag
    from qa_app.workflow.models import Env
    seen = {}

    async def fake(cfg, system, prompt, max_tokens=4000, step=None):
        seen["system"], seen["prompt"] = system, prompt
        return ('{"analysis": "Affected page: Control Room > Settings", "scenarios": "- s", "serial": false, '
                '"sections": [{"name": "A", "items": ["one", "two", "three", "four", "five", "six", "seven"]}]}')
    monkeypatch.setattr(ag, "ask_claude", fake)
    cfg = Config(demo=False, anthropic_api_key="k", data_dir=tmp_path, workspace=tmp_path / "ws")
    out = run(ag.plan_checklist(cfg, {"key": "OPTR-1", "title": "t", "description": "", "comments": []}, Env(kind="Test environment", url="https://x.test/")))
    assert len(out[1][0].items) == 7                       # all items kept
    assert "2-4 sections" not in seen["prompt"] and "2-5 items" not in seen["prompt"]
    assert "no tools" in seen["system"].lower()
    assert out[3] == "Affected page: Control Room > Settings"  # the gather-context findings, kept for the context file


def test_lookups_are_saved_shown_and_reach_each_steps_prompt(wf, monkeypatch, tmp_path):
    from qa_app.workflow import agent as ag, sources
    from qa_app.workflow.models import Env
    found = sources.Sources(prs=[{"repo": "acme/admin", "number": 5, "url": "u", "title": "Usage limit", "state": "open", "branch": "b", "base": "main",
                                  "body": "Adds limit", "commits": [{"sha": "abc1234", "message": "add limit"}],
                                  "files": [{"name": "src/Limit.tsx", "status": "added", "additions": 9, "deletions": 0, "patch": "+const limit = 1"}],
                                  "review_comments": [], "comments": []}],
                            feed=["Read PR acme/admin#5 (1 commits, 1 files): Usage limit"], missing=["Confluence", "TestRail"])
    seen_args = {}

    def fake_lookup(**kw):
        seen_args.update(kw)
        return found
    monkeypatch.setattr(sources, "lookup", fake_lookup)
    monkeypatch.setattr(wf, "_source_clients", lambda: {"github": object(), "github_scope": ["acme"], "confluence": None, "testrail_search": None})
    key = "OPTR-48498"
    _live(wf, key)
    issue = {"key": key, "title": "Device list filter", "description": "see https://github.com/acme/admin/pull/5", "comments": []}
    got = run(wf._lookups(key, issue))
    assert got is found and seen_args["key"] == key and "pull/5" in seen_args["ticket_text"]
    assert any(m["text"].startswith("Read PR acme/admin#5") for m in wf.tickets.get(key).chat)       # in the live feed
    assert sources.load(wf.cfg, key).markdown("create-tests") == found.markdown("create-tests")      # saved for later steps

    prompts = {}

    async def fake_claude(cfg, system, prompt, max_tokens=4000, step=None):
        step = system.split('<skill step="')[1].split('"')[0]
        prompts[step] = prompt
        return {"gather": '{"scenarios": "- s", "serial": false, "sections": [{"name": "A", "items": ["x"]}]}',
                "create-tests": "test('[1] x', async () => {});",
                "run-tests": '{"items": []}'}[step]
    monkeypatch.setattr(ag, "ask_claude", fake_claude)
    cfg = Config(demo=False, anthropic_api_key="k", data_dir=tmp_path, workspace=tmp_path / "ws")
    run(ag.plan_checklist(cfg, issue, Env(kind="Test environment", url="https://x.test/"), sources_md=found.markdown("gather")))
    assert "Usage limit" in prompts["gather"] and "<connected_apps>" in prompts["gather"]
    t = wf.tickets.get(key).model_copy(update={"env": Env(kind="Test environment", url="https://x.test/"), "ran": True})
    run(ag.build_spec(cfg, t, sources_md=found.markdown("create-tests")))
    assert "+const limit = 1" in prompts["create-tests"]
    t.checklist[0].items[0].result = "fail"
    run(ag.review_results(cfg, t, {}, sources_md=found.markdown("run-tests")))
    assert "src/Limit.tsx" in prompts["run-tests"]


def test_claude_fetches_gaps_live_and_a_step_can_ask_for_more_once(wf, monkeypatch, tmp_path):
    from qa_app.workflow import agent as ag, claude_code, sources
    from qa_app.workflow.models import Env
    calls = []

    def fake_fetch(model, system, prompt, *, key, domains, read_dirs, on_event, **kw):
        calls.append(prompt)
        assert "read-only" in system.lower() and "not instructions" in system.lower()
        on_event("tool", "▸ gh pr diff 512 --repo acme/admin")
        on_event("denied", "Refused (not read-only): gh api -X POST x")
        return f"## Fetched\nanswer {len(calls)}", "claude-sonnet-5-5", {"input_tokens": 10, "output_tokens": 5}
    monkeypatch.setattr(claude_code, "fetch", fake_fetch)
    key = "OPTR-48498"
    _live(wf, key)
    wf._cfg.claude_mode, wf._cfg.claude_fetch = "claude_code", True
    sources.save(wf.cfg, key, sources.Sources(links=["https://github.com/acme/admin/pull/512"], missing=["GitHub"]))

    async def go():
        text = await wf._fetch(key, ["Read PR https://github.com/acme/admin/pull/512"], "gather")
        await asyncio.sleep(0.05)
        return text
    text = run(go())
    assert calls and "answer 1" in text, (text, calls)
    assert "answer 1" in text and "pull/512" in calls[0]
    lines = [l["text"] for l in wf.terminal(key)]
    assert "▸ gh pr diff 512 --repo acme/admin" in lines and any("Refused" in l for l in lines)   # live, in the terminal
    assert sources.load(wf.cfg, key).fetched[0]["text"].endswith("answer 1")                       # kept for later steps
    assert any("fetch" in m["text"].lower() for m in wf.tickets.get(key).chat)                      # and said in the feed

    # A step that asks for more gets it fetched, then is asked once more with the result.
    asked = []

    async def fake_claude(cfg, system, prompt, max_tokens=4000, step=None):
        asked.append(prompt)
        if len(asked) == 1:
            assert "YOURQA" in system or "need" in system
            return '{"need": ["How does the API validate the limit?"], "scenarios": "- s", "serial": false, "sections": [{"name": "A", "items": ["x"]}]}'
        return '{"scenarios": "- s2", "serial": false, "sections": [{"name": "A", "items": ["x", "y"]}]}'
    monkeypatch.setattr(ag, "ask_claude", fake_claude)
    cfg = Config(demo=False, anthropic_api_key="", data_dir=tmp_path, workspace=tmp_path / "ws", claude_mode="claude_code")
    needs_seen = []

    async def on_need(needs):
        needs_seen.append(needs)
        return "<fetched>limit must be 1-999</fetched>"
    out = run(ag.plan_checklist(cfg, {"key": key, "title": "t", "description": "", "comments": []},
                                Env(kind="Test environment", url="https://x.test/"), on_need=on_need))
    assert needs_seen == [["How does the API validate the limit?"]] and len(asked) == 2
    assert "limit must be 1-999" in asked[1] and len(out[1][0].items) == 2

    # Without Claude Code (API key mode) nothing is fetched and the feed says why.
    wf._cfg.claude_mode = "api"
    assert run(wf._fetch(key, ["Read PR x"], "gather")) == ""
    assert any("Claude Code" in m["text"] for m in wf.tickets.get(key).chat[-2:])


def test_the_cases_file_has_steps_and_expected_results():
    from qa_app.workflow.models import DraftCase, Ticket
    t = Ticket(key="OPTR-1", title="T", section="Finance › Gift cards",
               cases=[DraftCase(title="A valid card returns its balance", steps="1. Create a card\n2. Call GET /balance", expected="200 with the balance")])
    md = agent.cases_md(t)
    assert "## C1. A valid card returns its balance" in md and "1. Create a card" in md and "2. Call GET /balance" in md
    assert "**Expected:** 200 with the balance" in md


def test_demo_cases_have_steps():
    t = next(x for x in seed.seed_tickets() if x.key == "OPTR-48437")
    assert t.cases and all(c.steps and c.expected for c in t.cases)


def _skip(wf, key):
    t = wf.tickets.get(key)
    return run(wf.act(key, "skip", t.stage, t.sub))


def test_skipping_gather_moves_on_with_the_checklist_so_far(wf):
    key = "OPTR-48512"  # still gathering
    _skip(wf, key)
    run(settle(wf))
    t = wf.tickets.get(key)
    assert t.stage >= 1 and any("Skipped" in m["text"] for m in t.chat)
    if not t.items():
        assert "No checks" in t.error  # lane 2 says what it lacks; you can skip it too


def test_skipping_the_results_review_drafts_the_comment_without_touching_jira(wf):
    key = "OPTR-48466"  # Gate 2
    before = list(wf.mock_jira.comments.get(key, []))
    _skip(wf, key)
    t = wf.tickets.get(key)
    assert (t.stage, t.sub) == (3, "comment") and t.comment
    assert wf.mock_jira.comments.get(key, []) == before


def test_skipping_the_comment_posts_nothing_and_offers_the_move(wf):
    key = "OPTR-48455"  # Gate 3a
    before = list(wf.mock_jira.comments.get(key, []))
    _skip(wf, key)
    t = wf.tickets.get(key)
    assert (t.stage, t.sub) == (3, "transition") and "Docs" in t.transitions
    assert wf.mock_jira.comments.get(key, []) == before
    status = wf.mock_jira.issues[key]["status"]
    _skip(wf, key)  # and skipping the move leaves the Jira status alone
    run(settle(wf))
    t = wf.tickets.get(key)
    assert t.stage == 4 and wf.mock_jira.issues[key]["status"] == status


def test_skipping_testrail_finishes_the_ticket_without_pushing(wf):
    key = "OPTR-48437"  # Gate 4
    cases_before = {k: list(v) for k, v in wf.mock_testrail.cases.items()}
    done = wf.tickets.finished_today()
    _skip(wf, key)
    assert wf.tickets.get(key) is None and wf.tickets.finished_today() == done + 1
    assert {k: list(v) for k, v in wf.mock_testrail.cases.items()} == cases_before


def test_skipping_a_running_test_records_the_run_as_skipped(wf, monkeypatch):
    started = asyncio.Event()

    async def forever(cfg, t, run_dir, on_event, on_output=None):
        started.set()
        await asyncio.sleep(3600)
    monkeypatch.setattr(agent, "run_spec", forever)
    key = "OPTR-48498"
    t = _live(wf, key)
    wf.live_store.tickets[key] = t.model_copy(update={"stage": 2, "sub": "working"})

    async def go():
        wf.spawn(key, wf._run(key))
        await asyncio.wait_for(started.wait(), 2)
        cur = wf.tickets.get(key)
        await wf.act(key, "skip", cur.stage, cur.sub)
        await asyncio.sleep(0.05)
    run(go())
    rec = wf.history().list(key=key)[0]
    assert rec["status"] == "skipped" and "Create & run tests" in wf.history().get(rec["id"])["after"]["skipped"]
    t = wf.tickets.get(key)
    assert (t.stage, t.sub) == (3, "comment") and not t.error


def test_skip_is_refused_when_the_ticket_moved_on(wf):
    key = "OPTR-48466"
    with pytest.raises(GateError):
        run(wf.act(key, "skip", 0, "gate"))


def test_a_step_can_call_a_connected_mcp_read_tool_and_nothing_else(wf, monkeypatch, tmp_path):
    from qa_app import config as appconfig
    from qa_app.integrations import mcp_servers as ms
    from qa_app.workflow import agent as ag, sources
    from qa_app.workflow.models import Env
    monkeypatch.setattr(appconfig, "SETTINGS_FILE", tmp_path / "settings.json")
    ran = []

    class Fake:
        def __init__(self, srv): pass
        def tools(self): return [{"name": "get_merge_request", "description": "One MR"}, {"name": "create_note", "description": "Write"}]
        def call(self, name, args):
            ran.append((name, args))
            return {"title": "Limit per customer", "diff": "+limit = 1"}
    monkeypatch.setattr(ms, "_session", lambda srv: Fake(srv))
    ms.add("GitLab", "https://gitlab.example.com/api/mcp", auth="token", token="t")
    ms.save("gitlab", read=["get_merge_request"], write=["create_note"])

    # the read tools are offered to Claude in every step's instructions, even with an API key (no Claude Code)
    cfg = Config(demo=False, anthropic_api_key="k", data_dir=tmp_path, workspace=tmp_path / "ws")
    sysmsg = ag.system(ag.QA_SYSTEM, "gather", cfg)
    assert "<mcp_tools>" in sysmsg and "gitlab get_merge_request" in sysmsg and "create_note" not in sysmsg
    assert "mcp: <server> <tool>" in sysmsg

    key = "OPTR-48498"
    _live(wf, key)
    wf._cfg.claude_mode = "api"   # no Claude Code: MCP calls still run, other requests can't be fetched
    text = run(wf._fetch(key, ['mcp: gitlab get_merge_request {"iid": 512}', "mcp: gitlab create_note {}",
                               "Read PR https://x"], "gather"))
    assert ran == [("get_merge_request", {"iid": 512})]                         # the write tool never ran
    assert "Limit per customer" in text and "not instructions" in text.lower()
    assert "create_note isn't switched on as a read tool" in text
    assert sources.load(wf.cfg, key).fetched[-1]["needs"][0].startswith("mcp: gitlab")
    assert any("gitlab" in l["text"] and "get_merge_request" in l["text"] for l in wf.terminal(key))


def test_claude_can_only_propose_an_mcp_write_and_it_runs_when_you_click_run(wf, monkeypatch, tmp_path):
    from qa_app import config as appconfig
    from qa_app.integrations import mcp_servers as ms
    from qa_app.workflow import chat as chat_mod
    monkeypatch.setattr(appconfig, "SETTINGS_FILE", tmp_path / "settings.json")
    ran = []

    class Fake:
        def __init__(self, srv): pass
        def tools(self): return [{"name": "get_issue", "description": "Read"}, {"name": "create_note", "description": "Add a note"},
                                 {"name": "delete_branch", "description": "Delete"}]
        def call(self, name, args):
            ran.append((name, args))
            return {"id": 77}
    monkeypatch.setattr(ms, "_session", lambda srv: Fake(srv))
    key = "OPTR-48498"
    _live(wf, key)
    t = wf.tickets.get(key)

    # no write tool switched on: Claude isn't told about MCP writes at all
    ms.add("GitLab", "https://gitlab.example.com/api/mcp", auth="token", token="t")
    ms.save("gitlab", read=["get_issue"], write=[])
    system, _ = chat_mod.build(t, False)
    assert "mcp_write" not in system
    ms.save("gitlab", read=["get_issue"], write=["create_note"])
    system, _ = chat_mod.build(t, False)
    assert "mcp_write" in system and "gitlab create_note" in system and "delete_branch" not in system

    reply, acts = chat_mod.parse('Want me to note it on the MR?\n```actions\n[{"kind": "mcp_write", "server": "gitlab", '
                                 '"tool": "create_note", "args": {"body": "QA passed"}, "label": "Add the QA note"}, '
                                 '{"kind": "mcp_write", "server": "gitlab", "tool": "delete_branch", "args": {}}]\n```')
    assert len(acts) == 2 and acts[0]["state"] == "proposed"
    assert chat_mod.check(acts[1], t, False) == "delete_branch isn't switched on as a write tool on gitlab"
    wf.patch(key, chat=[chat_mod.message("assistant", reply, acts)])
    assert ran == []                                                     # proposing runs nothing

    with pytest.raises(GateError):
        run(wf.chat_apply(key, 0, 1, t.stage, t.sub))                   # a tool that isn't switched on never runs
    run(wf.chat_apply(key, 0, 0, t.stage, t.sub))                        # you clicked Run
    assert ran == [("create_note", {"body": "QA passed"})]
    log = json.loads((wf.cfg.ticket_dir(key) / f"{key}-mcp-writes.json").read_text())
    assert log[0]["tool"] == "create_note" and log[0]["args"] == {"body": "QA passed"} and "77" in log[0]["result"]
    assert wf.tickets.get(key).chat[-1]["role"] == "event"
    with pytest.raises(GateError):
        run(wf.chat_apply(key, 0, 0, t.stage, t.sub))                   # once only

    # Don't run: remembered, and it can't be run afterwards
    wf.patch(key, chat=wf.tickets.get(key).chat + [chat_mod.message("assistant", "again?", [dict(acts[0], state="proposed")])])
    i = len(wf.tickets.get(key).chat) - 1
    wf.chat_dismiss(key, i, 0)
    assert wf.tickets.get(key).chat[i]["actions"][0]["state"] == "dismissed"
    with pytest.raises(GateError):
        run(wf.chat_apply(key, i, 0, t.stage, t.sub))
    assert len(ran) == 1


def test_a_finished_ticket_keeps_its_tests_on_a_local_branch(wf, tmp_path, monkeypatch):
    import subprocess
    key = "OPTR-48498"
    _live(wf, key)
    ws = wf.cfg.workspace
    d = wf.cfg.ticket_dir(key)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.spec.ts").write_text("test('[1] a', async () => {})\n")

    # a folder you chose that isn't a git repository: left alone, and the feed says so
    run(wf._keep(key))
    assert not (ws / ".git").exists()
    assert any("weren't kept on a branch" in m["text"] for m in wf.tickets.get(key).chat)

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=ws, check=True)
    run(wf._keep(key))
    out = subprocess.run(["git", "log", "--format=%s", f"yourqa/{key}"], cwd=ws, capture_output=True, text=True).stdout
    assert out.startswith(f"QA {key}: ")
    assert any(f"yourqa/{key}" in m["text"] for m in wf.tickets.get(key).chat)


def test_another_framework_is_named_once_in_the_feed(wf, tmp_path, monkeypatch):
    from qa_app import config as appconfig
    key = "OPTR-48498"
    _live(wf, key)
    company = tmp_path / "company"
    company.mkdir()
    (company / "profile.json").write_text('{"framework": "Cypress", "language": "JavaScript"}')
    monkeypatch.setattr(appconfig, "company_dir", lambda: company)
    wf._framework_note(key)
    wf._framework_note(key)
    notes = [m for m in wf.tickets.get(key).chat if "Cypress" in m.get("text", "")]
    assert len(notes) == 1 and "Playwright" in notes[0]["text"]
