"""Onboarding analysis: tool-less Claude calls per area, JSON out, one bad answer fails only its area."""
from __future__ import annotations

import asyncio
import json

from qa_app.onboarding import analyze
from qa_app.workflow import agent
from qa_app.workflow.settings import WorkflowConfig as Config


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _tickets(n):
    return [{"key": f"SCRUM-{i}", "title": f"T{i}", "type": "Story", "status": "Testing", "priority": "High",
             "components": ["Frontend"], "labels": [], "description": "Acceptance criteria:\n- works", "comments": []} for i in range(n)]


COLLECTED = {
    "tracker": {"tickets": _tickets(120), "statuses": {"Testing": 120}, "components": {"Frontend": 120}, "labels": {},
                "types": {"Story": 120}, "transitions": {"Testing": ["Done", "Reopened"]}},
    "testrail": {"sections": ["Finance › Gift cards"], "cases": [{"id": 1, "title": "Balance shows", "section": "Finance › Gift cards",
                                                                    "steps": "1. Open", "expected": "Shown"}]},
    "confluence": {"pages": [{"title": "Glossary", "url": "u", "text": "OU means organization unit"}]},
    "repo": {"root": "/r", "tree": ["package.json", "tests/a.spec.ts"], "files": {"package.json": '{"devDependencies":{"@playwright/test":"1"}}'}, "skipped": []},
}
ANSWERS = {
    "batch": {"observations": ["Acceptance criteria are a bulleted list under 'Acceptance criteria:'"]},
    "combine": {"settings": {"jira_column": "Testing", "fe_components": ["Frontend"], "be_components": ["Backend"], "env_hints": ["preview"]},
                "move_rules": {"failed": "Reopened", "passed": "Done"}, "skills": {"gather": "## SCRUM tickets\nAC are bullets.", "jira-comment": "## Comments\nShort."},
                "evidence": ["120 of 120 tickets list AC under 'Acceptance criteria:'"]},
    "testrail": {"skills": {"testrail": "## Cases\nTitles are behaviours."}, "section_map": {"Frontend": "Finance › Gift cards"}, "evidence": ["1 case"]},
    "knowledge": {"markdown": "# Company\nOU = organization unit.", "evidence": ["Glossary page"]},
    "repo": {"profile": {"language": "TypeScript", "framework": "Playwright", "runner": "@playwright/test", "test_dir": "tests",
                         "file_pattern": "*.spec.ts", "page_objects": "", "helpers": [], "auth": "", "run_command": "npx playwright test",
                         "ci_command": "", "results": "junit"}, "skills": {"create-tests": "## Specs\nUse tests/."}, "evidence": ["package.json"]},
}


def fake_claude(calls, bad=()):
    async def ask(cfg, system, prompt, max_tokens=4000, step=None):
        area = next(a for a in ("batch", "combine", "testrail", "knowledge", "repo") if f"[onboarding:{a}]" in system)
        calls.append(area)
        return "not json at all" if area in bad else json.dumps(ANSWERS[area])
    return ask


def test_tickets_are_read_in_batches_then_combined(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "ask_claude", fake_claude(calls))
    out = run(analyze.analyze(Config(demo=False, anthropic_api_key="k"), COLLECTED, lambda *a: None))
    assert calls.count("batch") == 3 and calls.count("combine") == 1   # 120 tickets in batches of 50
    assert out["tickets"]["move_rules"]["failed"] == "Reopened" and out["failed"] == {}


def test_a_bad_answer_fails_only_that_area(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "ask_claude", fake_claude(calls, bad=("testrail",)))
    out = run(analyze.analyze(Config(demo=False, anthropic_api_key="k"), COLLECTED, lambda *a: None))
    assert out["testrail"] is None and "testrail" in out["failed"]
    assert out["tickets"] and out["knowledge"] and out["repo"]


def test_each_area_returns_its_contract_and_missing_sources_are_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "ask_claude", fake_claude(calls))
    events = []
    out = run(analyze.analyze(Config(demo=False, anthropic_api_key="k"), {**COLLECTED, "confluence": None},
                              lambda kind, text: events.append((kind, text))))
    assert out["repo"]["profile"]["framework"] == "Playwright" and "create-tests" in out["repo"]["skills"]
    assert out["testrail"]["section_map"] == {"Frontend": "Finance › Gift cards"}
    assert out["knowledge"]["markdown"].startswith("# Company")       # knowledge still made from the tickets alone
    assert any("Studying" in t for _, t in events)
