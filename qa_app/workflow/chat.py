"""Chat with Claude about one ticket: ask why it stopped, what to test, or to change something.

Claude sees everything YourQA knows about the ticket (what Jira says, the environment and every link found,
the checklist and results, the draft comment, where it is on the board) and answers in plain text.
It can also suggest a few actions. Each one is shown as a button and only runs when the user clicks it,
after it is checked against where the ticket is *now*. Claude can never approve a gate or post to Jira.
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

from .models import Ticket, type_label

MAX_MESSAGES = 300  # chat, progress lines and summaries
HISTORY = 20  # earlier messages Claude sees

LANES = ["Gather requirements", "Create tests", "Run tests", "Comment & move ticket", "Update TestRail tests"]
WAITING = {(0, "working"): "Claude is reading the ticket and writing the checklist",
           (0, "blocked"): "stopped: needs the test environment",
           (0, "gate"): "Gate 1: waiting for the user to review the checklist",
           (1, "working"): "building the Playwright spec",
           (2, "sso"): "waiting for the user to sign in (SSO)",
           (2, "working"): "running the tests",
           (2, "gate"): "Gate 2: waiting for the user to review the results",
           (3, "comment"): "Gate 3a: the Jira comment is drafted, waiting for the user to post it",
           (3, "transition"): "Gate 3b: comment posted, waiting for the user to move the ticket",
           (4, "drafting"): "drafting TestRail cases",
           (4, "gate"): "Gate 4: waiting for the user to review the TestRail draft",
           (4, "approved"): "TestRail draft approved, waiting for the push go-ahead"}

# What Claude may suggest, and when each is allowed (checked again when the user clicks).
ACTIONS = {
    "redo_gather": "Read the ticket again and redo step 1 (environment, scenarios, checklist). {}",
    "change_env": "Test on another address: redoes step 1 for it. {\"url\": \"https://…\"}",
    "retry": "Retry the step that stopped with an error. {}",
    "rerun_tests": "Run the tests again (only at Gate 2). {}",
    "set_checklist": "Replace the checklist (only at Gate 1). {\"sections\": [{\"name\": \"…\", \"items\": [\"…\"]}]}",
    "set_comment": "Replace the draft Jira comment (only at Gate 3a, before it is posted). {\"text\": \"…\"}",
    "set_target": "Choose the status to move the ticket to (only at Gate 3). {\"target\": \"one of the available statuses\"}",
}

SYSTEM = """You are Claude, inside YourQA, helping a QA engineer with one ticket on their testing board.
The board takes each ticket through 5 steps with 4 review gates the user approves: 1 gather requirements (environment,
scenarios, QA checklist) → Gate 1 → 2 build and run Playwright tests → Gate 2 → 3 post the Jira comment (Gate 3a) and
move the ticket (Gate 3b) → 4 draft TestRail cases → Gate 4 → push.

Answer the user's question about this ticket: explain what happened and why, suggest what to test, rewrite things,
or help them get unstuck. Be concise and concrete; use the ticket's own facts. Never invent test results.

You can't approve gates, post to Jira, push to TestRail or run anything yourself. When an action would help, suggest it
(at most 3) in a fenced block at the very end of your reply, exactly like this:

```actions
[{"kind": "change_env", "url": "https://staging.example.com/", "label": "Test on staging.example.com"}]
```

Each action needs "kind", a short "label" for its button, and its fields. Only these kinds, and only when allowed now:
"""


def allowed(t: Ticket, can_redo: bool) -> dict[str, bool]:
    st = (t.stage, t.sub)
    return {"redo_gather": can_redo, "change_env": can_redo, "retry": bool(t.error),
            "rerun_tests": st == (2, "gate") and not t.error, "set_checklist": st == (0, "gate") and not t.error,
            "set_comment": st == (3, "comment"), "set_target": t.stage == 3 and bool(t.transitions or st == (3, "comment"))}


def check(action: dict, t: Ticket, can_redo: bool) -> str:
    """'' if the action can run on the ticket as it is now, else why not (shown on its button)."""
    kind = action.get("kind", "")
    if kind not in ACTIONS:
        return "Not something YourQA can do"
    if not allowed(t, can_redo).get(kind):
        return {"redo_gather": "Step 1 can't be redone now", "change_env": "The environment can't be changed now",
                "retry": "Nothing to retry", "rerun_tests": "Only at Gate 2", "set_checklist": "Only at Gate 1",
                "set_comment": "Only before the comment is posted", "set_target": "Only at Gate 3"}[kind]
    if kind == "change_env" and not str(action.get("url", "")).strip():
        return "No address given"
    if kind == "set_comment" and not str(action.get("text", "")).strip():
        return "The comment is empty"
    if kind == "set_target":
        target = str(action.get("target", "")).strip()
        if not target:
            return "No status given"
        if t.transitions and target not in t.transitions:
            return f"'{target}' isn't a status Jira offered"
    if kind == "set_checklist":
        secs = action.get("sections")
        if not isinstance(secs, list) or not any(isinstance(s, dict) and s.get("items") for s in secs):
            return "No checklist items given"
    return ""


def _ticket_state(t: Ticket, can_redo: bool) -> str:
    lines = [f"# {t.key}: {t.title}",
             f"- Type: {type_label(t.type)} · Jira: {t.issue_type or '-'} · priority {t.priority or '-'} · status {t.status}",
             f"- Board: lane {t.stage + 1} ({LANES[t.stage]}) · {WAITING.get((t.stage, t.sub), t.sub)}"]
    if t.doing:
        lines.append(f"- Now: {t.doing}")
    if t.error:
        lines.append(f"- Stopped with an error: {t.error}")
    if t.env:
        lines.append(f"- Test environment: {t.env.url} ({t.env.kind}, from {t.env.source or 'unknown'}) · {t.env.api}")
    else:
        lines.append("- Test environment: not chosen yet")
    if t.env_candidates:
        lines.append("- Links found on the ticket:")
        for c in t.env_candidates[:20]:
            tags = [x for x, on in (("suggested", c.get("suggested")), ("API", c.get("api")), ("production?", c.get("prod")),
                                     ("usually not an environment", c.get("other"))) if on]
            lines.append(f"  - {c.get('url')} · {c.get('source')}" + (f" · {', '.join(tags)}" if tags else ""))
    if t.checklist:
        lines.append(f"- Checklist ({'results from a run' if t.ran else 'not run yet'}):")
        for s in t.checklist:
            lines.append(f"  ## {s.name}")
            for i in s.items:
                lines.append(f"  - [{i.result}] {i.text}" + (f" — bug: {i.bug}" if i.bug else ""))
    if t.cleanup:
        lines.append("- Settings changed and reverted: " + ", ".join(f"{c.name}={c.value}" for c in t.cleanup))
    if t.comment:
        lines.append(f"- Jira comment ({'posted' if t.stage >= 3 and t.sub != 'comment' else 'draft'}):\n{t.comment}")
    if t.transitions:
        lines.append(f"- Statuses Jira offers for the move: {', '.join(t.transitions)}" + (f" · chosen: {t.target}" if t.target else ""))
    if t.cases:
        lines.append(f"- TestRail draft: {len(t.cases)} cases in {t.section}")
    ok = [k for k, v in allowed(t, can_redo).items() if v]
    lines.append(f"- Actions allowed right now: {', '.join(ok) if ok else 'none (the ticket is busy)'}")
    return "\n".join(lines)


def build(t: Ticket, can_redo: bool, context_md: str = "", report_md: str = "", skill: str = "") -> tuple[str, str]:
    """(system prompt, user prompt) for Claude's next reply."""
    system = SYSTEM + "\n".join(f"- {k}: {v}" for k, v in ACTIONS.items()) + (f"\n\n{skill}" if skill else "")
    parts = ["<ticket_state>\n" + _ticket_state(t, can_redo) + "\n</ticket_state>"]
    if context_md:
        parts.append("<ticket_from_jira>\n" + context_md[:40000] + "\n</ticket_from_jira>")
    if report_md:
        parts.append("<test_report>\n" + report_md[:15000] + "\n</test_report>")
    convo = [m for m in t.chat if m.get("role") in ("user", "assistant")][-HISTORY:]
    parts.append("<conversation>\n" + "\n\n".join(f"{'User' if m['role'] == 'user' else 'Claude'}: {m.get('text', '')}"
                                                  for m in convo) + "\n</conversation>")
    parts.append("Reply to the user's last message.")
    return system, "\n\n".join(parts)


ACTIONS_BLOCK = re.compile(r"```actions\s*(\[.*?\])\s*```", re.S)


def parse(text: str) -> tuple[str, list[dict]]:
    """(reply text, suggested actions) from Claude's answer."""
    actions: list[dict] = []
    m = ACTIONS_BLOCK.search(text or "")
    if m:
        try:
            raw = json.loads(m.group(1))
            actions = [a for a in raw if isinstance(a, dict) and a.get("kind") in ACTIONS][:3]
        except ValueError:
            actions = []
        text = (text[:m.start()] + text[m.end():]).strip()
    for a in actions:
        a["label"] = str(a.get("label") or a["kind"].replace("_", " ").capitalize())[:80]
        a["state"] = "proposed"
    return (text or "").strip(), actions


def message(role: str, text: str, actions: Optional[list[dict]] = None, **extra) -> dict:
    return {"role": role, "text": text, "at": time.time(), "actions": actions or [], **extra}
