"""Ticket models for the workflow board."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Result = Literal["pass", "partial", "fail", "blocked", "nt"]

# What a ticket changes: frontend, backend or both. "" when none of its Jira components is mapped.
TicketType = Literal["FE", "BE", "FE+BE", ""]
DEFAULT_FE_COMPONENTS = "Frontend, FE, Front-end, UI"
DEFAULT_BE_COMPONENTS = "Backend, BE, Back-end, Core, API"
DEFAULT_BOTH_NAMES = "FE+BE, FE/BE, BE+FE, Fullstack, Full-stack, Full stack"


def component_list(value: object) -> list[str]:
    """'Frontend, FE' (settings text) or a list, as clean names."""
    items = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    return [str(i).strip() for i in items if str(i).strip()]


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", str(name)).lower()  # "FE + BE" == "fe+be"


def classify_type(components: list[str], fe_names: list[str], be_names: list[str],
                  labels: Optional[list[str]] = None, both_names: Optional[list[str]] = None) -> str:
    """FE, BE or FE+BE from the ticket's Jira components and labels (names match ignoring case and spaces).
    A ticket with an FE name and a BE name, or a combined name such as "FE+BE", is FE+BE."""
    names = {_norm(c) for c in list(components or []) + list(labels or []) if str(c).strip()}
    both = names & {_norm(n) for n in (both_names if both_names is not None else component_list(DEFAULT_BOTH_NAMES))}
    fe = bool(both) or bool(names & {_norm(n) for n in fe_names})
    be = bool(both) or bool(names & {_norm(n) for n in be_names})
    return "FE+BE" if fe and be else "FE" if fe else "BE" if be else ""


def status_category(status: object) -> str:
    """Jira's status category, which decides a status lozenge's colour: new (grey), indeterminate (blue), done (green)."""
    if isinstance(status, dict):
        cat = status.get("statusCategory") or {}
        key = str(cat.get("key") or cat.get("name") or "").lower() if isinstance(cat, dict) else ""
        if key in ("new", "to do"):
            return "new"
        if key in ("done", "complete"):
            return "done"
        if key in ("indeterminate", "in progress"):
            return "indeterminate"
        status = status.get("name", "")
    name = str(status or "").lower()
    if re.search(r"\b(done|closed|resolved|released|merged|complete|cancel)", name):
        return "done"
    if re.search(r"\b(to ?do|open|backlog|new|selected|ready for dev|created|reopened)\b", name):
        return "new"
    return "indeterminate" if name else ""


def has_fe(ticket_type: str) -> bool:
    return "FE" in ticket_type.split("+")


def type_label(ticket_type: str) -> str:
    return ticket_type or "Untyped"

# (stage, sub) pairs the state machine allows. Stage is the board lane (0-4).
STATES: set[tuple[int, str]] = {
    (0, "working"), (0, "blocked"), (0, "gate"),
    (1, "working"),
    (2, "sso"), (2, "working"), (2, "gate"),
    (3, "comment"), (3, "transition"),
    (4, "drafting"), (4, "gate"), (4, "approved"),
}
WORKING_SUBS = {"working", "drafting"}


class Env(BaseModel):
    kind: str
    url: str
    api: str = ""
    shared: bool = False  # the team's default environment: confirm before changing sensitive settings
    source: str = ""  # where it was found: "comment by Ana · 2026-10-14", "Environment field", "you", "settings"


class CheckItem(BaseModel):
    text: str
    result: Result = "nt"
    bug: str = ""
    severity: Optional[Literal["Critical", "Major", "Minor"]] = None


class Section(BaseModel):
    name: str
    items: list[CheckItem] = Field(default_factory=list)


class CleanupItem(BaseModel):
    name: str
    value: str
    reread: bool = True


class DraftCase(BaseModel):
    title: str
    steps: str = ""
    expected: str = ""


class Ticket(BaseModel):
    key: str
    title: str
    type: TicketType = ""
    components: list[str] = Field(default_factory=list)  # the Jira components the type came from
    labels: list[str] = Field(default_factory=list)  # the Jira labels (the type can come from these too)
    context: dict = Field(default_factory=dict)  # what the ticket says (ticket_context.summary), for the drawer
    env_candidates: list[dict] = Field(default_factory=list)  # links on the ticket that could be the test environment
    issue_type: str = ""  # Jira issue type (Story, Bug, Task…), coloured like Jira
    priority: str = ""
    status_cat: str = ""  # new | indeterminate | done (Jira's status category)
    skills: dict[str, str] = Field(default_factory=dict)
    usage: list[dict] = Field(default_factory=list)  # every Claude call for this ticket (costs.entry): tokens and USD  # step → which skill Claude used ("general", "general + KEY", "KEY")
    status: str = "Open"
    description: str = ""
    stage: int = 0
    sub: str = "working"
    env: Optional[Env] = None
    p1: int = 0  # phase 1 progress step (0..3)
    doing: str = ""
    checklist: list[Section] = Field(default_factory=list)
    ran: bool = False  # True only once results came from an actual run
    cleanup: list[CleanupItem] = Field(default_factory=list)
    left: str = ""  # test data that could not be deleted
    serial: bool = False
    needs_sso: bool = False
    comment: Optional[str] = None
    comment_at: str = ""
    target: str = ""
    transitions: list[str] = Field(default_factory=list)
    section: str = ""
    dups: int = 0
    cases: list[DraftCase] = Field(default_factory=list)
    push_attempted: bool = False
    pushed_case_ids: list[int] = Field(default_factory=list)
    error: str = ""
    pr_url: str = ""
    updated: float = 0.0
    run_id: str = ""        # the latest run's record in History
    running_item: int = -1  # index of the check running right now (-1 when idle)
    chat: list[dict] = Field(default_factory=list)  # the ticket's chat with Claude (chat.message), suggested actions included
    chat_busy: bool = False                          # Claude is writing a reply
    # Demo mode only: what the simulated run reports. Never shown before a run.
    mock_results: list[list[str]] = Field(default_factory=list)
    mock_cleanup: list[CleanupItem] = Field(default_factory=list)
    mock_left: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_comp(cls, data: object) -> object:
        """Tickets saved before FE/BE had comp = Core | Frontend."""
        if isinstance(data, dict) and "comp" in data:
            data = dict(data)
            comp = data.pop("comp")
            data.setdefault("type", "BE" if comp == "Core" else "FE" if comp == "Frontend" else "")
        return data

    def public(self) -> dict:
        return self.model_dump(exclude={"mock_results", "mock_cleanup", "mock_left"})

    def items(self) -> list[CheckItem]:
        return [i for s in self.checklist for i in s.items]
