"""Learned rules for where a ticket moves after QA, kept in the "Jira comment & move" skill.

A run's checks are grouped into one of three results; each result can have one rule, written as a plain line
under "## Moving the ticket" so it reads (and can be edited) like the rest of the skill:

    - When any check fails: move to "To Do".
"""
from __future__ import annotations

import re
from typing import Iterable

SECTION = "## Moving the ticket"
OUTCOMES = {  # result -> how the rule says it
    "passed": "all checks pass",
    "failed": "any check fails",
    "incomplete": "no check fails but some are blocked, partial or not tested",
}
DESCRIBE = {"passed": "a run where every check passed", "failed": "a run with failed checks",
            "incomplete": "a run with blocked or partial checks"}
_LINE = re.compile(r'^\s*[-*]\s*When (?P<when>.+?):\s*move to [“"](?P<state>[^”"]+)[”"]\.?\s*$', re.I | re.M)


def outcome(items: Iterable) -> str:
    res = [getattr(i, "result", "nt") for i in items]
    if any(r == "fail" for r in res):
        return "failed"
    if res and all(r == "pass" for r in res):
        return "passed"
    return "incomplete"


def rule_line(result: str, state: str) -> str:
    return f'- When {OUTCOMES[result]}: move to "{state}".'


def rules(skill_text: str) -> dict[str, str]:
    by_phrase = {v.lower(): k for k, v in OUTCOMES.items()}
    out: dict[str, str] = {}
    for m in _LINE.finditer(skill_text or ""):
        key = by_phrase.get(m.group("when").strip().lower())
        if key:
            out[key] = m.group("state").strip()
    return out


def with_rule(skill_text: str, result: str, state: str) -> str:
    """The skill with this result's rule set (replaced if there was one); everything else is kept as it was."""
    text = (skill_text or "").rstrip()
    line = rule_line(result, state)
    phrase = re.escape(OUTCOMES[result])
    existing = re.compile(rf'^\s*[-*]\s*When {phrase}:\s*move to [“"][^”"]+[”"]\.?\s*$', re.I | re.M)
    if existing.search(text):
        return existing.sub(line, text, count=1) + "\n"
    if SECTION in text:
        head, _, tail = text.partition(SECTION)
        nxt = re.search(r"^## ", tail, re.M)  # the section ends at the next heading
        body, rest = (tail[:nxt.start()], tail[nxt.start():]) if nxt else (tail, "")
        return head + SECTION + body.rstrip() + "\n" + line + "\n" + ("\n" + rest if rest else "")
    intro = "Where the ticket moves after QA, learned from your moves. YourQA picks the state from these rules."
    return (text + "\n\n" if text else "") + f"{SECTION}\n\n{intro}\n\n{line}\n"


def pick(skill_text: str, result: str, transitions: list[str]) -> str:
    """The state the skill picks for this result, only if Jira offers exactly that state for the ticket."""
    state = rules(skill_text).get(result, "")
    return state if state in transitions else ""
