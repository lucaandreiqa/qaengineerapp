"""Skills: how Claude does each board step, as a tree.

  general   qa_app/skills/general/ ships with the app and works for any project or product. Read-only.
            tree.json lists the five board steps, each with the skills under it (Gather requirements ->
            Ticket context, Scenarios, QA checklist; Create tests -> Spec conventions, …).
  personal  ~/.qa_app/skills/personal/<skill>.md, an editable copy of the general tree. Onboarding's Finish makes
            it from the general tree plus what it learnt about the team; it can also be copied by hand. A skill
            missing from it is the general one. Each skill resets to its general version.

Each project chooses which tree its steps use (`skills.choice` in settings). Personal is recommended, so it is the
default once it exists. A step gets its own skill followed by every skill under it.

Output formats (JSON shapes, file layout) stay in the code, so editing a skill can change how Claude does the
step but can't break what the app reads back.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional

from .. import config
from ..config import APP_DIR

GENERAL = Path(__file__).resolve().parent.parent / "skills" / "general"
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
MAX_CHARS = 60000
TREES = ("personal", "general")


def _load_tree() -> list[dict]:
    return json.loads((GENERAL / "tree.json").read_text(encoding="utf-8"))


_TREE = _load_tree()
STEPS = [(n["id"], n["name"]) for n in _TREE]
STEP_IDS = [s for s, _ in STEPS]
NODES: dict[str, dict] = {}
for _n in _TREE:
    NODES[_n["id"]] = {"id": _n["id"], "name": _n["name"], "parent": None}
    for _c in _n.get("children", []):
        NODES[_c["id"]] = {"id": _c["id"], "name": _c["name"], "parent": _n["id"]}
NODE_IDS = list(NODES)


def tree() -> list[dict]:
    return json.loads(json.dumps(_TREE))


def branch(step: str) -> list[str]:
    """The step and every skill under it, in order."""
    _check_step(step)
    return [step] + [c["id"] for n in _TREE if n["id"] == step for c in n.get("children", [])]


def step_of(node: str) -> str:
    _check(node)
    return NODES[node]["parent"] or node


def root() -> Path:
    return APP_DIR / "skills"


def personal_dir() -> Path:
    return root() / "personal"


def _check(node: str) -> None:
    if node not in NODES:
        raise ValueError(f"Unknown skill '{node}'")


def _check_step(step: str) -> None:
    if step not in STEP_IDS:
        raise ValueError(f"Unknown step '{step}'")


def split(text: str) -> tuple[dict, str]:
    """Front matter (simple key: value lines) and body."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text.strip()
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():].strip()


def _read(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# ------------------------------------------------------------------------------------------------ the two trees
def general(node: str) -> str:
    _check(node)
    return split(_read(GENERAL / f"{node}.md") or "")[1]


def has_personal() -> bool:
    d = personal_dir()
    return d.exists() and any(d.glob("*.md"))


def personal(node: str) -> Optional[str]:
    """The personal version, or None when there are no personal skills. A skill missing from the personal tree is
    the general one."""
    _check(node)
    if not has_personal():
        return None
    own = _read(personal_dir() / f"{node}.md")
    return split(own)[1] if own is not None else general(node)


def changed(node: str) -> bool:
    p = personal(node)
    return p is not None and p.strip() != general(node).strip()


def _write(node: str, text: str) -> None:
    if len(text) > MAX_CHARS:
        raise ValueError(f"A skill can be at most {MAX_CHARS} characters")
    personal_dir().mkdir(parents=True, exist_ok=True)
    meta = f"name: {NODES[node]['name']}" + (f"\nparent: {NODES[node]['parent']}" if NODES[node]["parent"] else "")
    (personal_dir() / f"{node}.md").write_text(f"---\n{meta}\n---\n{text.strip()}\n", encoding="utf-8")


def create_personal() -> None:
    """Copy every general skill that the personal tree doesn't have yet."""
    for node in NODE_IDS:
        if not (personal_dir() / f"{node}.md").exists():
            _write(node, general(node))


def save_personal(node: str, text: str) -> None:
    _check(node)
    if len(text) > MAX_CHARS:
        raise ValueError(f"A skill can be at most {MAX_CHARS} characters")
    if not has_personal():
        create_personal()
    _write(node, text)


def reset_personal(node: str) -> None:
    """Back to the general version of this one skill."""
    _check(node)
    if has_personal():
        _write(node, general(node))


def remove_personal_skill(node: str) -> None:
    """Forget the personal file for one skill (it then follows the general one)."""
    _check(node)
    (personal_dir() / f"{node}.md").unlink(missing_ok=True)


def drop_personal_if_unchanged() -> bool:
    """Remove the personal tree when it holds nothing but general copies (for undoing whatever created it)."""
    if not has_personal() or any(changed(n) for n in NODE_IDS):
        return False
    shutil.rmtree(personal_dir(), ignore_errors=True)
    return True


# ------------------------------------------------------------------------------------------------ choice per project
def _choices() -> dict:
    return dict((config.load_settings().get("skills") or {}).get("choice") or {})


def choice(project: Optional[str]) -> str:
    """'personal' or 'general' for this project. Personal is recommended: the default once it exists."""
    want = _choices().get(project or "", "")
    if want == "general":
        return "general"
    return "personal" if has_personal() else "general"


def set_choice(project: str, which: str) -> None:
    if not KEY_RE.match(project or ""):
        raise ValueError(f"'{project}' is not a Jira project key")
    if which not in TREES:
        raise ValueError("Choose personal or general")
    ch = _choices()
    ch[project] = which
    config.save_section("skills", {"choice": ch})


def text(step: str, which: str) -> str:
    """A step's skill and every skill under it, from one tree."""
    parts = []
    for node in branch(step):
        body = (personal(node) if which == "personal" else None) or general(node)
        parts.append(body)
    return "\n\n---\n\n".join(parts)


def effective(step: str, project: Optional[str] = None) -> tuple[str, str]:
    """(the text Claude gets, which tree it came from: 'personal' | 'general')."""
    _check_step(step)
    which = choice(project if project and KEY_RE.match(project) else None)
    return text(step, which), which


def for_prompt(step: str, project: Optional[str] = None) -> str:
    """The step's branch as a block for a system prompt."""
    body, source = effective(step, project)
    return f"\n\n<skill step=\"{step}\" source=\"{source}\">\nHow to do this step (follow it, with every skill under it):\n\n{body}\n</skill>"


def projects() -> list[str]:
    found = set(_choices())
    try:
        found.add(str(config.load_settings().get("workflow", {}).get("jira_project") or ""))
    except Exception:
        pass
    return sorted(p for p in found if KEY_RE.match(p))


def overview(project: Optional[str] = None) -> dict:
    """Everything the Skills screen shows."""
    has = has_personal()
    nodes = {}
    for node in NODE_IDS:
        g = general(node)
        p = personal(node)
        nodes[node] = {"id": node, "name": NODES[node]["name"], "parent": NODES[node]["parent"], "general": g,
                       "personal": p, "changed": p is not None and p.strip() != g.strip()}
    return {"tree": tree(), "nodes": nodes, "has_personal": has, "recommended": "personal",
            "project": project or "", "projects": projects(), "choice": choice(project),
            "choices": {k: choice(k) for k in projects()}}


# ------------------------------------------------------------------------------------------------ the old layout
def migrate() -> None:
    """One time: edits to the old general skills and your own project versions move into the personal tree, so
    nothing you wrote is lost. The old files are kept in skills/_before-personal/."""
    old_general, old_projects = root() / "general", root() / "projects"
    if not old_general.exists() and not old_projects.exists():
        return
    edits: dict[str, list[str]] = {}
    for p in sorted(old_general.glob("*.md")) if old_general.exists() else []:
        if p.stem in STEP_IDS:
            body = split(_read(p) or "")[1]
            if body:
                edits.setdefault(p.stem, []).append(f"## Kept from your earlier version of this skill\n\n{body}")
    for d in sorted(old_projects.iterdir()) if old_projects.exists() else []:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if p.stem in STEP_IDS:
                body = split(_read(p) or "")[1]
                if body:
                    edits.setdefault(p.stem, []).append(f"## For project {d.name}\n\n{body}")
    if edits:
        create_personal()
        for step, extra in edits.items():
            _write(step, (personal(step) or general(step)).rstrip() + "\n\n" + "\n\n".join(extra))
    backup = root() / "_before-personal"
    backup.mkdir(parents=True, exist_ok=True)
    for d in (old_general, old_projects):
        if d.exists():
            target = backup / d.name
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(d), str(target))
