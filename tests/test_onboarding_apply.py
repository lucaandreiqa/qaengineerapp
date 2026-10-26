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


def saved_changes(run_dir):
    return json.loads((run_dir / "changes.json").read_text())


def _apply(home):
    changes = ap.plan(FINDINGS, ["SCRUM"])
    run_dir = home / "run1"
    return ap.apply(changes, run_dir, home / "company"), run_dir


def test_apply_writes_everything_and_records_before(home):
    applied, run_dir = _apply(home)
    w = config.load_settings()["workflow"]
    assert (w["jira_column"], w["fe_components"], w["be_components"], w["env_hints"]) == ("QA", "Web", "Core, API", "preview")
    assert config.load_settings()["testrail"]["section_map"] == {"Web": "Finance › Gift cards"}
    lessons = {c["target"]: c for c in saved_changes(run_dir) if c["kind"] == "skill"}
    assert lessons["SCRUM/gather"]["after"].startswith("## SCRUM tickets")    # skill lessons are recorded for Finish…
    assert {"SCRUM/jira-comment", "SCRUM/testrail", "SCRUM/create-tests"} <= set(lessons)
    assert not skills.changed("gather") and not skills.changed("testrail")    # …and written nowhere yet
    assert move_rules.rules(skills.personal("jira-comment")) == {"failed": "Reopened"}   # move rules go in the personal skill
    assert move_rules.rules(skills.general("jira-comment")) == {}             # the general one never changes
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
    assert not skills.changed("jira-comment") and move_rules.rules(skills.personal("jira-comment") or "") == {}
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


def test_a_move_rule_builds_on_your_own_personal_comment_skill_and_undo_brings_it_back(home):
    skills.save_personal("jira-comment", "My own comment rules")
    applied, run_dir = _apply(home)
    c = next(c for c in applied if c["target"] == "move_rule.failed")
    assert skills.personal("jira-comment").startswith("My own comment rules")
    assert move_rules.rules(skills.personal("jira-comment")) == {"failed": "Reopened"}
    ap.undo(run_dir, c["id"], home / "company")
    assert skills.personal("jira-comment") == "My own comment rules"
    lesson = next(c for c in applied if c["target"] == "SCRUM/gather")
    assert lesson["replaced_edit"] is False and ap.undo(run_dir, lesson["id"], home / "company") == "undone"


def test_each_change_is_kept_or_undone_before_finishing(home):
    changes = ap.plan(FINDINGS, ["SCRUM"])
    run_dir = home / "run"
    ap.apply(changes, run_dir, home / "company")
    assert ap.undecided(run_dir) == len(changes)
    first, second = ap.load(run_dir)[:2]
    assert ap.keep(run_dir, first["id"]) == "kept"
    ap.undo(run_dir, second["id"], home / "company")
    assert ap.undecided(run_dir) == len(changes) - 2
    assert ap.keep(run_dir, second["id"]) == "already undone"       # an undone change can't be kept
    ap.keep_all(run_dir)
    assert ap.undecided(run_dir) == 0
    kept = [c for c in ap.load(run_dir) if c.get("kept")]
    assert len(kept) == len(changes) - 1
