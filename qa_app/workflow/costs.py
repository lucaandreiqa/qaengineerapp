"""What Claude cost per ticket: exact token counts from each API reply, priced from Anthropic's price list.

Prices in USD per million tokens, from https://platform.claude.com/docs/en/about-claude/pricing (October 2026):
(model id prefix, input, output, cache write 5 min, cache write 1 h, cache read). The longest matching prefix wins.
A model that isn't listed is still counted in tokens; its cost shows as unknown rather than guessed.
"""
from __future__ import annotations

import time
from typing import Optional

PRICES: list[tuple[str, float, float, float, float, float]] = [
    ("claude-fable-5-1", 10, 50, 12.5, 20, 0.25),
    ("claude-mythos-5-1", 10, 50, 12.5, 20, 0.25),
    ("claude-fable-5", 10, 50, 12.5, 20, 1),
    ("claude-mythos-5", 10, 50, 12.5, 20, 1),
    ("claude-opus-5-5", 4, 20, 5, 8, 0.2),
    ("claude-opus-5", 5, 25, 6.25, 10, 0.5),
    ("claude-opus-4-8", 5, 25, 6.25, 10, 0.5),
    ("claude-opus-4-7", 5, 25, 6.25, 10, 0.5),
    ("claude-opus-4-6", 5, 25, 6.25, 10, 0.5),
    ("claude-opus-4-5", 5, 25, 6.25, 10, 0.5),
    ("claude-opus-4-1", 15, 75, 18.75, 30, 1.5),
    ("claude-opus-4", 15, 75, 18.75, 30, 1.5),
    ("claude-sonnet-5-5", 2, 10, 2.5, 4, 0.1),
    ("claude-sonnet-5", 2, 10, 2.5, 4, 0.2),
    ("claude-sonnet-4", 3, 15, 3.75, 6, 0.3),
    ("claude-haiku-5-5", 0.1, 0.5, 0.125, 0.2, 0.01),
    ("claude-haiku-4-5", 1, 5, 1.25, 2, 0.1),
    ("claude-3-5-haiku", 0.8, 4, 1, 1.6, 0.08),
]
# Haiku 5.5 costs more when one request's prompt (input + cache reads + writes) is over 100,000 tokens.
HAIKU_55_LONG = (0.5, 2.5, 0.625, 1, 0.05)
STEP_NAMES = {"gather": "Gather requirements", "create-tests": "Create tests", "run-tests": "Run tests",
              "jira-comment": "Jira comment", "testrail": "TestRail cases",
              "chat": "Chat with Claude", "fetch": "Fetching data"}


def _prices(model: str) -> Optional[tuple[float, float, float, float, float]]:
    m = (model or "").lower()
    for prefix, *p in sorted(PRICES, key=lambda r: -len(r[0])):
        if m.startswith(prefix):
            return tuple(p)  # type: ignore[return-value]
    return None


def tokens(usage: dict) -> dict:
    """The API reply's usage block as plain counts."""
    cc = usage.get("cache_creation") or {}
    w5 = int(cc.get("ephemeral_5m_input_tokens") or 0)
    w1 = int(cc.get("ephemeral_1h_input_tokens") or 0)
    if not cc:  # older replies only give the total, written at the 5-minute rate
        w5 = int(usage.get("cache_creation_input_tokens") or 0)
    return {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0),
            "cache_write_5m": w5, "cache_write_1h": w1, "cache_read": int(usage.get("cache_read_input_tokens") or 0)}


def cost(model: str, usage: dict) -> Optional[float]:
    """USD for one API call, or None for a model with no known price."""
    p = _prices(model)
    if p is None:
        return None
    t = tokens(usage)
    if (model or "").lower().startswith("claude-haiku-5-5") and \
            t["input"] + t["cache_read"] + t["cache_write_5m"] + t["cache_write_1h"] > 100_000:
        p = HAIKU_55_LONG
    i, o, w5, w1, r = p
    return (t["input"] * i + t["output"] * o + t["cache_write_5m"] * w5 + t["cache_write_1h"] * w1 + t["cache_read"] * r) / 1e6


def entry(step: str, model: str, usage: dict, at: Optional[float] = None, billing: str = "api") -> dict:
    """One Claude call, as kept on the ticket. billing "plan": made through Claude Code on the user's Claude plan,
    so cost is what it would have cost at API prices, not money spent."""
    t = tokens(usage)
    return {"step": step or "other", "model": model, "billing": billing, "input": t["input"] + t["cache_write_5m"] + t["cache_write_1h"] + t["cache_read"],
            "output": t["output"], "cache_read": t["cache_read"], "cost": cost(model, usage), "at": at or time.time()}


def summary(entries: list[dict]) -> dict:
    """Totals for a ticket (or several): cost, tokens and calls, overall and per step."""
    out = {"calls": 0, "input": 0, "output": 0, "cost": 0.0, "unpriced": 0, "plan_calls": 0, "by_step": {}}
    for e in entries or []:
        s = out["by_step"].setdefault(e.get("step", "other"), {"name": STEP_NAMES.get(e.get("step", ""), e.get("step", "other")),
                                                               "calls": 0, "input": 0, "output": 0, "cost": 0.0})
        for d in (out, s):
            d["calls"] += 1
            d["input"] += int(e.get("input") or 0)
            d["output"] += int(e.get("output") or 0)
            if e.get("cost") is not None:
                d["cost"] += float(e["cost"])
        if e.get("cost") is None:
            out["unpriced"] += 1
        if e.get("billing") == "plan":
            out["plan_calls"] += 1
    out["by_step"] = dict(sorted(out["by_step"].items(), key=lambda kv: list(STEP_NAMES).index(kv[0]) if kv[0] in STEP_NAMES else 99))
    return out
