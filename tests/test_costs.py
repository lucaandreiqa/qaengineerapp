"""What Claude cost per ticket: exact tokens from each reply, priced from Anthropic's list prices."""
from __future__ import annotations

import asyncio

import pytest

from qa_app.workflow import agent, costs, seed
from qa_app.workflow.clients import MockJira, MockTestRail
from qa_app.workflow.engine import Workflow
from qa_app.workflow.settings import WorkflowConfig as Config
from qa_app.workflow.store import TicketStore


def test_prices_follow_the_price_list():
    one_m = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert costs.cost("claude-sonnet-5-5", one_m) == pytest.approx(2 + 10)
    assert costs.cost("claude-opus-5-5", one_m) == pytest.approx(4 + 20)
    assert costs.cost("claude-fable-5-1", one_m) == pytest.approx(10 + 50)
    assert costs.cost("claude-opus-4-1-20250805", one_m) == pytest.approx(15 + 75)  # older Opus
    assert costs.cost("claude-sonnet-4-5-20250929", one_m) == pytest.approx(3 + 15)
    cached = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000,
              "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 1_000_000}}
    assert costs.cost("claude-sonnet-5-5", cached) == pytest.approx(0.1 + 2.5 + 4)
    short = {"input_tokens": 50_000, "output_tokens": 1_000}
    long = {"input_tokens": 150_000, "output_tokens": 1_000}
    assert costs.cost("claude-haiku-5-5", short) == pytest.approx((50_000 * 0.1 + 1_000 * 0.5) / 1e6)
    assert costs.cost("claude-haiku-5-5", long) == pytest.approx((150_000 * 0.5 + 1_000 * 2.5) / 1e6)  # over 100k
    assert costs.cost("some-other-model", one_m) is None  # counted in tokens, never guessed


def test_summary_adds_up_by_step():
    es = [costs.entry("gather", "claude-sonnet-5-5", {"input_tokens": 10_000, "output_tokens": 2_000}),
          costs.entry("gather", "claude-sonnet-5-5", {"input_tokens": 10_000, "output_tokens": 2_000}),  # a redo
          costs.entry("testrail", "mystery-model", {"input_tokens": 1_000, "output_tokens": 500})]
    s = costs.summary(es)
    assert (s["calls"], s["input"], s["output"], s["unpriced"]) == (3, 21_000, 4_500, 1)
    assert s["cost"] == pytest.approx(2 * (10_000 * 2 + 2_000 * 10) / 1e6)
    assert list(s["by_step"]) == ["gather", "testrail"] and s["by_step"]["gather"]["calls"] == 2


def test_each_claude_call_lands_on_its_ticket(tmp_path, monkeypatch):
    cfg = Config(demo=True, data_dir=tmp_path, workspace=tmp_path / "ws", mock_speed=1000.0, anthropic_api_key="k",
                 default_env_url="https://staging.shop-demo.test/")
    tickets = TicketStore(tmp_path / "t.json")
    for t in seed.seed_tickets():
        t.usage = []
        tickets.tickets[t.key] = t
    issues, late = seed.jira_issues()
    wf = Workflow(tickets, TicketStore(tmp_path / "l.json"), MockJira(issues, late), MockTestRail(), cfg=cfg)

    def fake_sync(cfg, system, prompt, max_tokens):  # what the API returns: text, model, usage
        return ('{"scenarios": "- s", "serial": false, "sections": [{"name": "A", "items": ["x"]}]}',
                "claude-sonnet-5-5", {"input_tokens": 12_000, "output_tokens": 1_500})
    monkeypatch.setattr(agent, "_ask_claude_sync", fake_sync)

    async def go():
        t = wf.tickets.get("OPTR-48498")
        t.checklist = []  # make step 1 ask Claude instead of using the sample checklist
        wf.tickets.put(t)
        await wf.act("OPTR-48498", "redo_gather", 0, "gate")
        for _ in range(100):
            await asyncio.sleep(0.01)
            if all(x.done() for x in wf.tasks.values()):
                break
        t = wf.tickets.get("OPTR-48498")
        assert [(e["step"], e["input"], e["output"]) for e in t.usage] == [("gather", 12_000, 1_500)]
        assert t.usage[0]["cost"] == pytest.approx((12_000 * 2 + 1_500 * 10) / 1e6)
        assert all(not x.usage for x in wf.tickets.all() if x.key != "OPTR-48498")  # nothing leaks to other tickets
    asyncio.new_event_loop().run_until_complete(go())
    agent.usage_listeners.remove(wf._on_usage)
