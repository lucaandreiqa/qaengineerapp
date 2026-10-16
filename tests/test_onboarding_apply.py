"""Onboarding apply and undo: everything applied at once, each change undoable, your own later edits protected."""
from __future__ import annotations

import json

import pytest

from qa_app import config
from qa_app.onboarding import apply as ap
from qa_app.workflow import move_rules, skills

FINDINGS = {
    "tickets": {"settings": {"jira_column": "QA", "fe_components": ["Web"], "be_components": ["Core", "API"], "env_hints": ["preview"]},
                "move_rules": {"failed": "Reopened"}, "skills": {"gather": "## SCRUM tickets\nAC are bullets.", "jira-comment": "## Comments"},
                "evidence": ["118 of 120 tickets put AC under 'Acceptance criteria:'"]},
    "testrail": {"skills": {"testrail": "## Cases"}, "section_map": {"Web": "Finance › Gift cards"}, "evidence": ["150 cases"]},
    "knowledge": {"markdown": "# Company\nOU = organization unit.", "evidence": ["Glossary"]},
    "repo": {"profile": {"framework": "Playwright", "language": "TypeScript"}, "skills": {"create-tests": "## Specs"}, "evidence": ["package.json"]},
    "failed": {},
}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(skills, "root", lambda: tmp_path / "skills")
    config.save_section("workflow", {"jira_column": "Testing", "fe_components": "Frontend", "be_components": "Backend", "env_hints": ""})
    return tmp_path


def _apply(home):
    changes = ap.plan(FINDINGS, ["SCRUM"])
    run_dir = home / "run1"
    return ap.apply(changes, run_dir, home / "company"), run_dir


def test_apply_writes_everything_and_records_before(home):
    applied, run_dir = _apply(home)
    w = config.load_settings()["workflow"]
    assert (w["jira_column"], w["fe_components"], w["be_components"], w["env_hints"]) == ("QA", "Web", "Core, API", "preview")
    assert config.load_settings()["testrail"]["section_map"] == {"Web": "Finance › Gift cards"}
    assert skills.project("SCRUM", "gather")["text"].startswith("## SCRUM tickets") and skills.project("SCRUM", "gather")["mode"] == "add"
    assert {"jira-comment", "testrail", "create-tests"} <= {s for s in skills.STEP_IDS if skills.project("SCRUM", s)}
    assert move_rules.rules(skills.general("jira-comment")[0]) == {"failed": "Reopened"}
    assert (home / "company" / "knowledge.md").read_text().startswith("# Company")
    assert json.loads((home / "company" / "profile.json").read_text())["framework"] == "Playwright"
    saved = json.loads((run_dir / "changes.json").read_text())
    col = next(c for c in saved if c["target"] == "workflow.jira_column")
    assert col["before"] == "Testing" and col["after"] == "QA" and col["evidence"]


def test_undo_restores_exactly(home):
    applied, run_dir = _apply(home)
    for c in applied:
        assert ap.undo(run_dir, c["id"], home / "company") == "undone"
    w = config.load_settings()["workflow"]
    assert (w["jira_column"], w["fe_components"]) == ("Testing", "Frontend")
    assert skills.project("SCRUM", "gather") is None and skills.general("jira-comment")[1] is False
    assert not (home / "company" / "knowledge.md").exists() and not (home / "company" / "profile.json").exists()


def test_undo_after_your_own_later_edit_leaves_it(home):
    applied, run_dir = _apply(home)
    config.save_section("workflow", {"jira_column": "Ready for QA"})       # you changed it after onboarding
    c = next(c for c in applied if c["target"] == "workflow.jira_column")
    assert ap.undo(run_dir, c["id"], home / "company") == "changed since"
    assert config.load_settings()["workflow"]["jira_column"] == "Ready for QA"


def test_undo_all_restores_the_run(home):
    applied, run_dir = _apply(home)
    res = ap.undo_all(run_dir, home / "company")
    assert res["undone"] == len(applied) and config.load_settings()["workflow"]["jira_column"] == "Testing"
    assert all(c.get("undone") for c in json.loads((run_dir / "changes.json").read_text()))


def test_replacing_your_own_project_skill_is_marked(home):
    skills.save_project("SCRUM", "gather", "My own SCRUM notes", mode="replace")
    applied, run_dir = _apply(home)
    c = next(c for c in applied if c["target"] == "SCRUM/gather")
    assert c["replaced_edit"] is True
    ap.undo(run_dir, c["id"], home / "company")
    assert skills.project("SCRUM", "gather") == {"text": "My own SCRUM notes", "mode": "replace", "shipped": False}
