"""Skills: a read-only general tree for any project, an editable personal tree, and a choice per project."""
from __future__ import annotations

import asyncio
import json

import pytest

from qa_app import config
from qa_app.workflow import agent, skills
from qa_app.workflow.models import CheckItem, CleanupItem, Env, Section, Ticket
from qa_app.workflow.settings import WorkflowConfig as Config


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "root", lambda: tmp_path / "skills")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    return tmp_path / "skills"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_the_general_tree_has_the_five_steps_with_their_skills_under_them(store):
    assert [s for s, _ in skills.STEPS] == ["gather", "create-tests", "run-tests", "jira-comment", "testrail"]
    tree = {n["id"]: [c["id"] for c in n["children"]] for n in skills.tree()}
    assert tree["gather"] == ["context", "scenarios", "checklist"]
    assert "page-objects" in tree["create-tests"] and "triage" in tree["run-tests"] and "writing" in tree["jira-comment"]
    for node in skills.NODE_IDS:
        text = skills.general(node)
        assert len(text) > 300 and not text.startswith("---"), node        # front matter stripped
    assert skills.NODES["scenarios"]["parent"] == "gather" and skills.NODES["gather"]["parent"] is None


def test_general_skills_are_product_neutral():
    for node in skills.NODE_IDS:
        text = skills.general(node)
        for eva in ("Admin Suite", "EVA", "euw", "andrei.luca", "on-eva.io", "callEvaApi", "OPTR-", "Luca"):
            assert eva not in text, (node, eva)
    assert "state and action matrix" in skills.general("scenarios").lower()
    assert "Find by identity" in skills.general("page-objects") and "<connected_apps>" in skills.general("gather")


def test_a_step_gets_its_whole_branch(store):
    text, source = skills.effective("create-tests")
    assert source == "general"
    for child in ("spec-conventions", "page-objects", "test-data", "ui-timing"):
        assert skills.general(child)[:60] in text
    assert text.index(skills.general("create-tests")[:60]) < text.index(skills.general("ui-timing")[:60])


def test_general_cannot_be_edited_personal_can_and_each_skill_resets_to_general(store):
    with pytest.raises(ValueError):
        skills.save_personal("deploy", "x")
    assert not skills.has_personal()
    skills.save_personal("scenarios", "Our scenarios: always add a mobile viewport scenario.")
    assert skills.has_personal()                                             # the whole tree was copied first
    assert skills.personal("scenarios").startswith("Our scenarios") and skills.personal("context") == skills.general("context")
    assert skills.changed("scenarios") and not skills.changed("context")
    skills.reset_personal("scenarios")
    assert skills.personal("scenarios") == skills.general("scenarios") and not skills.changed("scenarios")
    with pytest.raises(ValueError):
        skills.save_personal("gather", "x" * (skills.MAX_CHARS + 1))


def test_each_project_chooses_personal_or_general_and_personal_is_the_default_once_it_exists(store):
    assert skills.choice("SCRUM") == "general"                              # no personal skills yet
    skills.create_personal()
    skills.save_personal("gather", "PERSONAL GATHER")
    assert skills.choice("SCRUM") == "personal"                             # recommended, so the default
    assert skills.effective("gather", "SCRUM") == (skills.text("gather", "personal"), "personal")
    assert skills.effective("gather", "SCRUM")[0].startswith("PERSONAL GATHER")
    skills.set_choice("OPTR", "general")
    assert skills.effective("gather", "OPTR")[1] == "general" and "PERSONAL" not in skills.effective("gather", "OPTR")[0]
    assert skills.choice("SCRUM") == "personal"
    with pytest.raises(ValueError):
        skills.set_choice("../x", "personal")
    with pytest.raises(ValueError):
        skills.set_choice("SCRUM", "mine")
    ov = skills.overview("OPTR")
    assert ov["choice"] == "general" and ov["has_personal"] and ov["recommended"] == "personal"
    assert ov["nodes"]["gather"]["changed"] and not ov["nodes"]["context"]["changed"]
    assert "OPTR" in ov["projects"]


def test_old_edits_and_project_versions_move_into_personal_once(store):
    (store / "general").mkdir(parents=True)
    (store / "general" / "testrail.md").write_text("---\nname: x\n---\nWrite cases in Gherkin.\n")
    (store / "projects" / "SCRUM").mkdir(parents=True)
    (store / "projects" / "SCRUM" / "gather.md").write_text("---\nmode: add\n---\nSCRUM: test on Safari too.\n")
    skills.migrate()
    assert skills.has_personal()
    assert "Write cases in Gherkin." in skills.personal("testrail") and skills.personal("testrail").startswith(skills.general("testrail")[:40])
    assert "For project SCRUM" in skills.personal("gather") and "Safari" in skills.personal("gather")
    assert not (store / "general").exists() and not (store / "projects").exists()   # moved aside, not lost
    assert (store / "_before-personal" / "general" / "testrail.md").exists()
    skills.migrate()                                                          # once only
    assert skills.personal("gather").count("Safari") == 1


def test_each_step_sends_its_chosen_branch_to_claude(store, monkeypatch, tmp_path):
    skills.save_personal("checklist", "PERSONAL CHECKLIST RULE: test on Safari too.")
    skills.set_choice("OPTR", "general")
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
    assert 'source="personal"' in by_step["gather"] and "PERSONAL CHECKLIST RULE" in by_step["gather"]
    assert "state and action matrix" in by_step["gather"].lower()             # the children come along
    assert "Find by identity" in by_step["create-tests"]
    assert agent.skill_source("gather", cfg) == "personal"
    cfg.jira_project = "OPTR"
    assert agent.skill_source("gather", cfg) == "general"


def test_without_claude_the_templates_still_work(store, tmp_path):
    cfg = Config(demo=False, data_dir=tmp_path)
    t = Ticket(key="A-1", title="X", env=Env(kind="Test environment", url="https://x.test/"), ran=True,
               checklist=[Section(name="A", items=[CheckItem(text="x works", result="pass")])])
    assert run(agent.write_comment(cfg, t)).startswith("QA result: 1/1 checks pass.")
    assert [c.title for c in run(agent.write_cases(cfg, t, []))] == ["x works"]
    assert run(agent.review_results(cfg, t, {})) is False


def test_the_skills_screen_routes_edit_only_personal(store):
    try:
        from fastapi import HTTPException
        from qa_app.web import server
    except ImportError:  # the app's web packages aren't installed here
        return
    assert server.skills_overview("SCRUM")["has_personal"] is False
    server.skill_create_personal()
    server.skill_save_personal("scenarios", server.SkillIn(text="Our scenarios."))
    assert skills.personal("scenarios") == "Our scenarios."
    server.skill_reset_personal("scenarios")
    assert not skills.changed("scenarios")
    server.skill_choice("scrum", server.SkillChoiceIn(tree="general"))
    assert skills.choice("SCRUM") == "general"
    with pytest.raises(HTTPException):
        server.skill_save_personal("nope", server.SkillIn(text="x"))
    assert not any(r.path.startswith("/api/skills/general") or r.path.startswith("/api/skills/project") for r in server.app.routes)
