"""Applying what onboarding learned, with Undo.

plan() turns the analysis into a list of changes; apply() writes them all and records the value before each one in
`<run>/changes.json`; undo() restores one change, but only while it still holds onboarding's value (your own later
edit is left alone); undo_all() undoes the whole run.

Targets:
  workflow.<key> / testrail.section_map     settings (comma lists are stored as text, as the cards do)
  <PROJECT>/<step>                          a project version of a skill (mode add)
  move_rule.<result>                        a learned move rule in the general Jira comment skill
  company/knowledge.md, company/profile.json   company files
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from ..config import load_settings, save_section
from ..workflow import move_rules, skills

LIST_SETTINGS = {"fe_components", "be_components", "env_hints"}
SETTING_LABELS = {"jira_column": "Board column", "fe_components": "Frontend components", "be_components": "Backend components",
                  "env_hints": "Test environment hints"}
STEP_LABELS = dict(skills.STEPS)


def _ev(area: dict) -> list[str]:
    return [str(e) for e in (area or {}).get("evidence") or []][:5]


def plan(findings: dict, projects: list[str]) -> list[dict]:
    out: list[dict] = []

    def add(kind: str, target: str, label: str, after: Any, area: str) -> None:
        out.append({"id": uuid.uuid4().hex[:10], "kind": kind, "target": target, "label": label, "after": after,
                    "area": area, "evidence": _ev(findings.get(area) or {})})
    t = findings.get("tickets")
    if t:
        for key, value in (t.get("settings") or {}).items():
            if key in SETTING_LABELS and value not in (None, "", []):
                text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                add("setting", f"workflow.{key}", SETTING_LABELS[key], text, "tickets")
        for result, state in (t.get("move_rules") or {}).items():
            if result in move_rules.OUTCOMES and str(state).strip():
                add("move_rule", f"move_rule.{result}", f"Move rule: when {move_rules.OUTCOMES[result]}", str(state), "tickets")
    for area, steps in (("tickets", ("gather", "jira-comment")), ("testrail", ("testrail",)), ("repo", ("create-tests",))):
        a = findings.get(area)
        for step in steps:
            text = ((a or {}).get("skills") or {}).get(step)
            if text:
                for p in projects:
                    add("skill", f"{p}/{step}", f"{STEP_LABELS[step]} skill for {p}", str(text), area)
    tr = findings.get("testrail")
    if tr and tr.get("section_map"):
        add("setting", "testrail.section_map", "TestRail sections by area", dict(tr["section_map"]), "testrail")
    k = findings.get("knowledge")
    if k and k.get("markdown"):
        add("file", "company/knowledge.md", "Company knowledge base", k["markdown"], "knowledge")
    r = findings.get("repo")
    if r and r.get("profile"):
        add("file", "company/profile.json", "Framework profile", json.dumps(r["profile"], indent=2, ensure_ascii=False), "repo")
    return out


# ------------------------------------------------------------------------------------------- read / write one target
def _read(target: str, company: Path) -> Any:
    if target.startswith("workflow.") or target.startswith("testrail."):
        section, key = target.split(".", 1)
        return load_settings().get(section, {}).get(key)
    if target.startswith("move_rule."):
        text, custom = skills.general("jira-comment")
        return {"text": text, "custom": custom}
    if target.startswith("company/"):
        p = company / target.split("/", 1)[1]
        return p.read_text(encoding="utf-8") if p.exists() else None
    project, step = target.split("/", 1)
    p = skills.project(project, step)
    return None if not p or p.get("shipped") else {"text": p["text"], "mode": p["mode"]}


def _write(target: str, value: Any, company: Path) -> None:
    if target.startswith("workflow.") or target.startswith("testrail."):
        section, key = target.split(".", 1)
        save_section(section, {key: value})
    elif target.startswith("move_rule."):
        if value is None or not value.get("custom"):
            skills.reset_general("jira-comment")
            if value and value.get("text") != skills.general("jira-comment")[0]:
                skills.save_general("jira-comment", value["text"])
        else:
            skills.save_general("jira-comment", value["text"])
    elif target.startswith("company/"):
        p = company / target.split("/", 1)[1]
        if value is None:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value, encoding="utf-8")
    else:
        project, step = target.split("/", 1)
        if value is None:
            skills.delete_project(project, step)
        else:
            skills.save_project(project, step, value["text"], mode=value.get("mode", "add"))


def _after_value(change: dict, before: Any) -> Any:
    """What the target holds once the change is applied (move rules and skills have a richer shape than `after`)."""
    if change["kind"] == "move_rule":
        result = change["target"].split(".", 1)[1]
        return {"text": move_rules.with_rule((before or {}).get("text", ""), result, change["after"]).strip() + "\n", "custom": True}
    if change["kind"] == "skill":
        return {"text": change["after"], "mode": "add"}
    return change["after"]


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, dict) and isinstance(b, dict) and "text" in a and "text" in b:
        return str(a.get("text", "")).strip() == str(b.get("text", "")).strip() and a.get("mode", "add") == b.get("mode", "add")
    return a == b


# ------------------------------------------------------------------------------------------- apply / undo
def save_changes(run_dir: Path, changes: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "changes.json").write_text(json.dumps(changes, indent=1, ensure_ascii=False), encoding="utf-8")


def load(run_dir: Path) -> list[dict]:
    p = run_dir / "changes.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _replaces_edit(change: dict, before: Any) -> bool:
    """Did this change replace something you had set yourself? (So the summary can say so; Undo brings it back.)"""
    if change["kind"] == "skill":
        return before is not None  # you had your own project version
    if change["kind"] == "move_rule":
        old = move_rules.rules((before or {}).get("text", "")).get(change["target"].split(".", 1)[1])
        return old is not None and old != change["after"]
    return False


def apply(changes: list[dict], run_dir: Path, company: Path) -> list[dict]:
    done = []
    for c in changes:
        before = _read(c["target"], company)
        value = _after_value(c, before)
        _write(c["target"], value, company)
        done.append({**c, "before": before, "applied": value, "replaced_edit": _replaces_edit(c, before)})
    save_changes(run_dir, done)
    return done


def undo(run_dir: Path, change_id: str, company: Path) -> str:
    """'undone', 'changed since' (you edited it after onboarding, so it stays), or 'already undone'."""
    changes = load(run_dir)
    c = next((x for x in changes if x["id"] == change_id), None)
    if c is None:
        raise KeyError(change_id)
    if c.get("undone"):
        return "already undone"
    if not _same(_read(c["target"], company), c["applied"]):
        return "changed since"
    _write(c["target"], c["before"], company)
    c["undone"] = True
    save_changes(run_dir, changes)
    return "undone"


def undo_all(run_dir: Path, company: Path) -> dict:
    counts = {"undone": 0, "changed since": 0, "already undone": 0}
    for c in reversed(load(run_dir)):  # newest first, so changes to the same target unwind in order
        counts[undo(run_dir, c["id"], company)] += 1
    return counts


def keep(run_dir: Path, change_id: str) -> str:
    """'kept', 'already kept', or 'already undone'. Kept changes are the ones Finish onboarding polishes."""
    changes = load(run_dir)
    c = next((x for x in changes if x["id"] == change_id), None)
    if c is None:
        raise KeyError(change_id)
    if c.get("undone"):
        return "already undone"
    if c.get("kept"):
        return "already kept"
    c["kept"] = True
    save_changes(run_dir, changes)
    return "kept"


def keep_all(run_dir: Path) -> int:
    changes = load(run_dir)
    n = 0
    for c in changes:
        if not c.get("undone") and not c.get("kept"):
            c["kept"], n = True, n + 1
    save_changes(run_dir, changes)
    return n


def undecided(run_dir: Path) -> int:
    return sum(1 for c in load(run_dir) if not c.get("kept") and not c.get("undone"))
