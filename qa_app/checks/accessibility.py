"""Accessibility audit with axe-core (WCAG 2.x A/AA rules)."""
from __future__ import annotations

import requests

from ..config import VENDOR_DIR
from ..models import Finding, Severity
from . import PageContext

AXE_VERSION = "4.10.2"
AXE_URL = f"https://cdnjs.cloudflare.com/ajax/libs/axe-core/{AXE_VERSION}/axe.min.js"

IMPACT = {"critical": Severity.CRITICAL, "serious": Severity.MAJOR,
          "moderate": Severity.MINOR, "minor": Severity.INFO}


def axe_script() -> str:
    path = VENDOR_DIR / f"axe-{AXE_VERSION}.min.js"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(AXE_URL, timeout=30)
        resp.raise_for_status()
        path.write_text(resp.text, encoding="utf-8")
    return str(path)


def run(ctx: PageContext) -> None:
    ctx.page.add_script_tag(path=axe_script())
    result = ctx.page.evaluate("""() => axe.run(document, {
        runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']},
        resultTypes: ['violations']
    })""")
    for v in result["violations"]:
        targets = [", ".join(n["target"]) if isinstance(n["target"], list) else str(n["target"])
                   for n in v["nodes"][:5]]
        details = (f"{v['help']} ({len(v['nodes'])} element(s)).\n"
                   f"Rule: {v['id']} — {v['helpUrl']}\n"
                   f"Examples: " + "; ".join(str(t) for t in targets))
        ctx.add(Finding("accessibility", v["help"], IMPACT.get(v.get("impact") or "minor", Severity.MINOR),
                        ctx.url, details))
