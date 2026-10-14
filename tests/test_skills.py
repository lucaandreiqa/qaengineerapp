"""Skills: a general one per board step, refined per Jira project, and passed to Claude in that step."""
from __future__ import annotations

import asyncio
import json

import pytest

from qa_app.workflow import agent, skills
from qa_app.workflow.models import CheckItem, CleanupItem, Env, Section, Ticket
from qa_app.workflow.settings import WorkflowConfig as Config


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "root", lambda: tmp_path / "skills")
    return tmp_path / "skills"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_every_board_step_has_a_general_skill(store):
    assert [s for s, _ in skills.STEPS] == ["gather", "create-tests", "run-tests", "jira-comment", "testrail"]
    for step in skills.STEP_IDS:
        text, custom = skills.general(step)
        assert len(text) > 400 and not custom and not text.startswith("---")  # front matter stripped


def test_project_skill_adds_or_replaces_and_general_can_be_edited_and_reset(store):
    base = skills.general("gather")[0]
    assert skills.effective("gather", "SCRUM") == (base, "general")
    skills.save_project("SCRUM", "gather", "Our API is GraphQL. Always include a mobile viewport item.")
    text, source = skills.effective("gather", "SCRUM")
    assert source == "general + SCRUM" and text.startswith(base) and text.endswith("Always include a mobile viewport item.")
    assert skills.effective("gather", "OTHER")[1] == "general"  # other projects are untouched
    skills.save_project("SCRUM", "gather", "Only this.", mode="replace")
    assert skills.effective("gather", "SCRUM") == ("Only this.", "SCRUM")
    assert skills.projects() == ["SCRUM"]
    skills.delete_project("SCRUM", "gather")
    assert skills.effective("gather", "SCRUM")[1] == "general" and skills.projects() == []

    skills.save_general("testrail", "Write cases in Gherkin.")
    assert skills.general("testrail") == ("Write cases in Gherkin.", True)
    skills.reset_general("testrail")
    assert skills.general("testrail")[1] is False and "TestRail" in skills.general("testrail")[0]
    for bad in (lambda: skills.save_project("../x", "gather", "t"), lambda: skills.save_general("deploy", "t"),
                lambda: skills.save_general("gather", "x" * 20001)):
        with pytest.raises(ValueError):
            bad()


def test_each_step_sends_its_skill_to_claude(store, monkeypatch, tmp_path):
    skills.save_project("SCRUM", "gather", "SCRUM: test on Safari too.")
    skills.save_project("SCRUM", "jira-comment", "SCRUM: write the comment in Romanian.", mode="replace")
    calls: list[tuple[str, str]] = []
    replies = {
        "gather": json.dumps({"scenarios": "- s", "serial": False, "sections": [{"name": "A", "items": ["x works"]}]}),
        "create-tests": "test('[1] x works', async () => {});",
        "run-tests": json.dumps({"items": [{"n": 2, "note": "Saving fails with 500. Severity: Major", "severity": "Major"}]}),
        "jira-comment": "QA result: 1/2 checks pass.",
        "testrail": json.dumps({"cases": [{"title": "x works", "steps": "1. Open x", "expected": "x works"}]}),
    }

    async def fake(cfg, system, prompt, max_tokens=4000):
        step = system.split('<skill step="')[1].split('"')[0]
        calls.append((step, system))
        return replies[step]

    monkeypatch.setattr(agent, "ask_claude", fake)
    cfg = Config(demo=False, anthropic_api_key="k", jira_project="SCRUM", data_dir=tmp_path, workspace=tmp_path / "ws")
    env = Env(kind="Test environment", url="https://pr-1.preview.acme.dev/")
    issue = {"key": "SCRUM-2", "title": "X", "description": "", "comments": [], "type": "FE"}
    run(agent.plan_checklist(cfg, issue, env))
    t = Ticket(key="SCRUM-2", title="X", env=env, type="FE", ran=True,
               checklist=[Section(name="A", items=[CheckItem(text="x works", result="pass"), CheckItem(text="y saves", result="fail", bug="500")])],
               cleanup=[CleanupItem(name="Flag", value="off")])
    run(agent.build_spec(cfg, t))
    assert run(agent.review_results(cfg, t, {"1": "Error: expected 200, got 500"}))
    assert t.items()[1].bug == "Saving fails with 500. Severity: Major" and t.items()[1].result == "fail"  # never changes the result
    assert run(agent.write_comment(cfg, t)) == "QA result: 1/2 checks pass."
    assert [c.title for c in run(agent.write_cases(cfg, t, []))] == ["x works"]

    by_step = dict(calls)
    assert list(by_step) == ["gather", "create-tests", "run-tests", "jira-comment", "testrail"]
    assert 'source="general + SCRUM"' in by_step["gather"] and "Acceptance criteria are the contract" in by_step["gather"] \
        and "SCRUM: test on Safari too." in by_step["gather"]
    assert 'source="SCRUM"' in by_step["jira-comment"] and "Romanian" in by_step["jira-comment"] \
        and "First line: `QA result:" not in by_step["jira-comment"]  # replaced, not added
    assert 'source="general"' in by_step["testrail"] and "Only items that passed" in by_step["testrail"]
    assert agent.skill_source("jira-comment", cfg) == "SCRUM"


def test_without_claude_the_templates_still_work(store, tmp_path):
    cfg = Config(demo=False, data_dir=tmp_path)
    t = Ticket(key="A-1", title="X", env=Env(kind="Test environment", url="https://x.test/"), ran=True,
               checklist=[Section(name="A", items=[CheckItem(text="x works", result="pass")])])
    assert run(agent.write_comment(cfg, t)).startswith("QA result: 1/1 checks pass.")
    assert [c.title for c in run(agent.write_cases(cfg, t, []))] == ["x works"]
    assert run(agent.review_results(cfg, t, {})) is False
