"""Workflow rules: gates, stale approvals, exact transitions, verified pushes. Run with: pytest -q"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from qa_app.integrations.jira import find_pr_environment
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
        await wf.act("OPTR-48507", "use_env", 0, "blocked", {"url": "https://pr-1.ci-cd.on-eva.io/"})
        await settle(wf)
        assert wf.tickets.get("OPTR-48507").sub == "gate"
    run(go())


def test_environment_resolution(tmp_path):
    cfg = Config(demo=True, data_dir=tmp_path)
    env, _ = agent.resolve_environment({"merged": True}, cfg)
    assert env and env.shared
    env, _ = agent.resolve_environment({"merged": False, "comments": ["up at https://pr-42.ci-cd.on-eva.io/"]}, cfg)
    assert env and env.url == "https://pr-42.ci-cd.on-eva.io/"
    env, reason = agent.resolve_environment({"merged": False, "type": "BE", "components": ["Core"], "status": "Open", "comments": []}, cfg)
    assert env is None and "Stopped" in reason
    assert find_pr_environment(["nothing"]) == ""


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
    assert Config(fe_components=("Admin Suite",), be_components=("Core",)).ticket_type(["Admin Suite", "Core"]) == "FE+BE"


def test_saved_tickets_with_old_component_load_as_fe_or_be():
    from qa_app.workflow.models import Ticket
    assert Ticket.model_validate({"key": "A-1", "title": "x", "comp": "Core"}).type == "BE"
    assert Ticket.model_validate({"key": "A-2", "title": "x", "comp": "Frontend"}).type == "FE"
    assert "comp" not in Ticket(key="A-3", title="x").public()


def test_sync_types_new_tickets_and_preview_needs_fe(wf, tmp_path):
    async def go():
        assert await wf.sync() == ["OPTR-48520"]
        t = wf.tickets.get("OPTR-48520")
        assert t.type == "FE" and t.components == ["Frontend"]
    run(go())
    types = {t.key: t.type for t in seed.seed_tickets()}
    assert types["OPTR-48466"] == "FE+BE" and types["OPTR-48437"] == "BE" and types["OPTR-48498"] == "FE"
    cfg = Config(demo=True, data_dir=tmp_path)
    issue = {"merged": False, "status": "Open", "comments": [], "preview_url": "https://x.pages.dev/"}
    assert agent.resolve_environment({**issue, "type": "FE+BE"}, cfg)[0].kind == "Cloudflare Pages preview"
    env, reason = agent.resolve_environment({**issue, "type": "BE"}, cfg)
    assert env is None and reason.startswith("BE ticket")
