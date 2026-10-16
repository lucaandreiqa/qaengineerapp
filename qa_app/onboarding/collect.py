"""Bounded, read-only samples from each source a company connects. Nothing here writes anywhere."""
from __future__ import annotations

from typing import Any

DESC_MAX, COMMENT_MAX, COMMENTS = 2000, 400, 5


def brief_ticket(raw: dict) -> dict:
    """A tracker issue (Jira-shaped: {key, fields}) in the small shape onboarding studies."""
    from ..workflow.ticket_context import text
    f = raw.get("fields") or {}

    def name(v: Any) -> str:
        return (v or {}).get("name", "") if isinstance(v, dict) else str(v or "")
    comments = ((f.get("comment") or {}).get("comments") or []) if isinstance(f.get("comment"), dict) else (f.get("comment") or [])
    bodies = [text(c.get("body") if isinstance(c, dict) else c).strip() for c in comments]
    return {"key": raw.get("key", ""), "title": f.get("summary", ""), "type": name(f.get("issuetype")),
            "status": name(f.get("status")), "priority": name(f.get("priority")),
            "components": [name(c) for c in f.get("components") or [] if name(c)], "labels": list(f.get("labels") or []),
            "description": text(f.get("description")).strip()[:DESC_MAX],
            "comments": [b[:COMMENT_MAX] for b in bodies if b][-COMMENTS:]}
