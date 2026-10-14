"""Ticket models for the workflow board."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Result = Literal["pass", "partial", "fail", "blocked", "nt"]

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
    shared: bool = False  # the shared environment (euw): confirm before changing sensitive settings


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
    comp: Literal["Core", "Frontend"] = "Frontend"
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
    # Demo mode only: what the simulated run reports. Never shown before a run.
    mock_results: list[list[str]] = Field(default_factory=list)
    mock_cleanup: list[CleanupItem] = Field(default_factory=list)
    mock_left: str = ""

    def public(self) -> dict:
        return self.model_dump(exclude={"mock_results", "mock_cleanup", "mock_left"})

    def items(self) -> list[CheckItem]:
        return [i for s in self.checklist for i in s.items]
