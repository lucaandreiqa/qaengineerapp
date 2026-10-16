"""Onboarding study runs: collect, analyse, apply area by area, report; one at a time; used by every step."""
from __future__ import annotations

import asyncio
import json

import pytest

from qa_app import config
from qa_app.onboarding import run as ob
from qa_app.workflow import agent, skills, store
from qa_app.workflow.clients import MockJira
from qa_app.workflow.settings import WorkflowConfig as Config
from tests.test_onboarding_analyze import ANSWERS, fake_claude


def go(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "company_dir", lambda: tmp_path / "company")
    monkeypatch.setattr(skills, "root", lambda: tmp_path / "skills")
    events = []
    monkeypatch.setattr(store.bus, "publish", lambda ev: events.append(ev))
    calls = []
    monkeypatch.setattr(agent, "ask_claude", fake_claude(calls))
    return tmp_path, events, calls


def _issues(n):
    return [{"key": f"SCRUM-{i}", "title": f"T{i}", "status": "Testing", "issue_type": "Story", "updated": f"2026-10-{i % 28 + 1:02d}",
             "components": ["Frontend"], "description": "Acceptance criteria:\n- works"} for i in range(n)]


def _sources(tmp, with_repo=True, tracker=True):
    repo = tmp / "repo"
    if with_repo:
        (repo / "tests").mkdir(parents=True, exist_ok=True)
        (repo / "package.json").write_text('{"devDependencies": {"@playwright/test": "1"}}')
        (repo / "tests" / "a.spec.ts").write_text("test('a', async () => {})")
    return lambda: {"cfg": Config(demo=False, anthropic_api_key="k"), "tracker": MockJira(_issues(60)) if tracker else None,
                    "testrail": None, "confluence": None}, str(repo)


def test_a_study_collects_analyses_applies_and_reports(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp)
    o = ob.Onboarding(factory)
    run_id = go(o.study({"projects": ["SCRUM"], "spaces": [], "repo": repo}))
    st = o.state()
    last = st["last"]
    assert last["id"] == run_id and last["status"] == "done" and not st["running"]
    assert last["sources"]["tracker"].startswith("Read 60 tickets") and last["sources"]["testrail"] == "not connected"
    assert last["sources"]["repo"].startswith("Read")
    targets = {c["target"] for c in last["changes"]}
    assert {"workflow.jira_column", "SCRUM/gather", "company/knowledge.md", "company/profile.json", "SCRUM/create-tests"} <= targets
    assert (tmp / "company" / "onboarding" / run_id / "collected" / "tracker.json").exists()   # what was studied is kept
    assert any(e.get("type") == "onboarding" and e.get("event") == "done" for e in events)
    o.undo_all()
    assert config.load_settings()["workflow"]["jira_column"] == "Testing" and skills.project("SCRUM", "gather") is None


def test_a_missing_source_is_skipped_and_listed(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp, with_repo=False)
    o = ob.Onboarding(factory)
    go(o.study({"projects": ["SCRUM"], "spaces": [], "repo": str(tmp / "nope")}))
    last = o.state()["last"]
    assert last["status"] == "done" and last["sources"]["repo"].startswith("failed") and "not found" in last["sources"]["repo"].lower()
    assert any(c["target"] == "SCRUM/gather" for c in last["changes"])   # the tracker part still applied


def test_only_one_study_at_a_time_and_an_interrupted_run_is_marked_stopped(home):
    tmp, events, calls = home
    factory, repo = _sources(tmp)
    o = ob.Onboarding(factory)

    async def both():
        first = asyncio.ensure_future(o.study({"projects": ["SCRUM"], "spaces": [], "repo": repo}))
        await asyncio.sleep(0)
        with pytest.raises(ob.OnboardingBusy):
            await o.study({"projects": ["SCRUM"], "spaces": [], "repo": repo})
        await first
    go(both())
    run_dir = tmp / "company" / "onboarding" / "r-crashed"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(json.dumps({"id": "r-crashed", "started": 9e12, "status": "running", "sources": {}, "changes": []}))
    assert ob.Onboarding(factory).state()["last"]["status"] == "stopped"


def test_knowledge_reaches_every_step_prompt_and_the_profile_reaches_test_writing(home):
    tmp, events, calls = home
    (tmp / "company").mkdir()
    (tmp / "company" / "knowledge.md").write_text("# Company\nOU = organization unit.")
    (tmp / "company" / "profile.json").write_text(json.dumps({"framework": "Playwright", "language": "TypeScript"}))
    cfg = Config(demo=False, anthropic_api_key="k")
    sys_text = agent.system("base", "gather", cfg)
    assert "<company_knowledge>" in sys_text and "OU = organization unit" in sys_text
    assert "Playwright" in agent.framework_note()
