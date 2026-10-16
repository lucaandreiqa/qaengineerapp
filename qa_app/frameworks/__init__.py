"""Framework adapters: who writes and runs a ticket's tests, in the company's style.

First version: Playwright TypeScript only. When the company's profile names another framework, YourQA still writes
Playwright in its own workspace and says so once (pick() returns a note). Tests are written in YourQA's workspace and
never import the company's code; when a ticket is done they're kept on a local branch (keep.commit_ticket).
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import STYLE_MAX, Adapter
from .playwright_ts import PlaywrightTS

ADAPTERS: list[Adapter] = [PlaywrightTS()]


def profile(company: Path) -> dict:
    try:
        data = json.loads((company / "profile.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def pick(prof: dict) -> tuple[Adapter, str]:
    """(adapter, note). The note is '' when an adapter matches the company's framework, or when nothing is known."""
    for a in ADAPTERS:
        if a.matches(prof):
            return a, ""
    named = str(prof.get("framework") or prof.get("runner") or "").strip()
    if not named:
        return ADAPTERS[0], ""
    return ADAPTERS[0], (f"Your automation uses {named}. YourQA writes and runs Playwright tests in its own workspace, "
                         f"following your structure, naming and test data.")


__all__ = ["ADAPTERS", "Adapter", "STYLE_MAX", "pick", "profile"]
