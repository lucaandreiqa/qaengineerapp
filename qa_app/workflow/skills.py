"""Skills: how Claude does each board step, general for everyone and refined per project.

Each of the five board columns has one skill, a Markdown text Claude gets every time it does that step.

  general   qa_app/skills/<step>.md ships with the app. Editing it in the app saves your own copy in
            ~/.qa_app/skills/general/<step>.md; "Reset" goes back to the shipped one.
  project   ~/.qa_app/skills/projects/<JIRA KEY>/<step>.md, per Jira project. Its front matter says how it combines:
            mode: add      (default) the general skill, then the project's additions
            mode: replace  the project skill alone

Output formats (JSON shapes, file layout) stay in the code, so editing a skill can change how Claude does the
step but can't break what the app reads back.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..config import APP_DIR

SHIPPED = Path(__file__).resolve().parent.parent / "skills"
STEPS = [("gather", "Gather requirements"), ("create-tests", "Create tests"), ("run-tests", "Run tests"),
         ("jira-comment", "Comment & move Jira ticket"), ("testrail", "Update TestRail tests")]
STEP_IDS = [s for s, _ in STEPS]
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
MAX_CHARS = 60000  # the team's skills are long (test-specs alone is ~28k characters)


def root() -> Path:
    return APP_DIR / "skills"


def _check(step: str, project: Optional[str] = None) -> None:
    if step not in STEP_IDS:
        raise ValueError(f"Unknown step '{step}'")
    if project is not None and not KEY_RE.match(project):
        raise ValueError(f"'{project}' is not a Jira project key")


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


def shipped(step: str) -> str:
    _check(step)
    return split(_read(SHIPPED / f"{step}.md") or "")[1]


def general(step: str) -> tuple[str, bool]:
    """(text, customised?)"""
    _check(step)
    own = _read(root() / "general" / f"{step}.md")
    return (split(own)[1], True) if own is not None else (shipped(step), False)


def project(key: str, step: str) -> Optional[dict]:
    """{"text", "mode"} or None."""
    _check(step, key)
    raw = _read(root() / "projects" / key / f"{step}.md")
    if raw is None:
        return None
    meta, body = split(raw)
    return {"text": body, "mode": "replace" if meta.get("mode") == "replace" else "add"}


def effective(step: str, key: Optional[str] = None) -> tuple[str, str]:
    """(the text Claude gets, where it came from: 'general' | 'general + KEY' | 'KEY')."""
    text, _ = general(step)
    p = project(key, step) if key and KEY_RE.match(key) else None
    if not p or not p["text"]:
        return text, "general"
    if p["mode"] == "replace":
        return p["text"], key  # type: ignore[return-value]
    return f"{text}\n\n## For project {key}\n\n{p['text']}", f"general + {key}"


def for_prompt(step: str, key: Optional[str] = None) -> str:
    """The skill as a block for a system prompt."""
    text, source = effective(step, key)
    return f"\n\n<skill step=\"{step}\" source=\"{source}\">\nHow to do this step (follow it):\n\n{text}\n</skill>"


def _write(p: Path, text: str) -> None:
    if len(text) > MAX_CHARS:
        raise ValueError(f"A skill can be at most {MAX_CHARS} characters")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def save_general(step: str, text: str) -> None:
    _check(step)
    name = dict(STEPS)[step]
    _write(root() / "general" / f"{step}.md", f"---\nname: {name}\n---\n{text.strip()}\n")


def reset_general(step: str) -> None:
    _check(step)
    (root() / "general" / f"{step}.md").unlink(missing_ok=True)


def save_project(key: str, step: str, text: str, mode: str = "add") -> None:
    _check(step, key)
    mode = "replace" if mode == "replace" else "add"
    _write(root() / "projects" / key / f"{step}.md", f"---\nname: {dict(STEPS)[step]} ({key})\nmode: {mode}\n---\n{text.strip()}\n")


def delete_project(key: str, step: str) -> None:
    _check(step, key)
    (root() / "projects" / key / f"{step}.md").unlink(missing_ok=True)


def projects() -> list[str]:
    d = root() / "projects"
    return sorted(p.name for p in d.iterdir() if p.is_dir() and KEY_RE.match(p.name) and any(p.glob("*.md"))) if d.exists() else []


def overview(key: Optional[str] = None) -> dict:
    """Everything the Skills screen shows."""
    steps = []
    for sid, name in STEPS:
        text, custom = general(sid)
        p = project(key, sid) if key else None
        eff, source = effective(sid, key)
        steps.append({"id": sid, "name": name, "general": {"text": text, "customised": custom, "shipped": shipped(sid)},
                      "project": p, "effective": eff, "source": source})
    return {"steps": steps, "project": key or "", "projects": projects()}
