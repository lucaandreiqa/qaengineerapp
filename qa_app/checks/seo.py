"""On-page SEO and basic performance timing (no external tools needed)."""
from __future__ import annotations

from ..models import Finding, Severity
from . import PageContext

COLLECT_JS = """() => {
  const meta = n => document.querySelector(`meta[name="${n}"]`)?.getAttribute('content') || '';
  const nav = performance.getEntriesByType('navigation')[0];
  return {
    title: document.title || '',
    description: meta('description'),
    robots: meta('robots'),
    viewport: meta('viewport'),
    lang: document.documentElement.getAttribute('lang') || '',
    canonical: document.querySelector('link[rel="canonical"]')?.href || '',
    h1: document.querySelectorAll('h1').length,
    imgsNoAlt: [...document.images].filter(i => !i.hasAttribute('alt')).length,
    loadMs: nav ? Math.round(nav.loadEventEnd - nav.startTime) : null,
    domMs: nav ? Math.round(nav.domContentLoadedEventEnd - nav.startTime) : null,
    transferKb: Math.round(performance.getEntriesByType('resource')
                  .reduce((s, r) => s + (r.transferSize || 0), nav?.transferSize || 0) / 1024),
  };
}"""


def run(ctx: PageContext) -> dict:
    d = ctx.page.evaluate(COLLECT_JS)
    add = lambda title, sev, detail="": ctx.add(Finding("seo", title, sev, ctx.url, detail))

    if not d["title"]:
        add("Missing <title>", Severity.MAJOR)
    elif not 10 <= len(d["title"]) <= 65:
        add("Title length outside 10–65 chars", Severity.MINOR, f"{len(d['title'])} chars: {d['title']!r}")
    if not d["description"]:
        add("Missing meta description", Severity.MINOR)
    elif not 50 <= len(d["description"]) <= 170:
        add("Meta description length outside 50–170 chars", Severity.INFO, f"{len(d['description'])} chars")
    if d["h1"] == 0:
        add("No <h1> heading", Severity.MINOR)
    elif d["h1"] > 1:
        add("Multiple <h1> headings", Severity.INFO, f"{d['h1']} found")
    if not d["lang"]:
        add("Missing lang attribute on <html>", Severity.MINOR)
    if not d["viewport"]:
        add("Missing responsive viewport meta tag", Severity.MAJOR)
    if not d["canonical"]:
        add("Missing canonical link", Severity.INFO)
    if "noindex" in d["robots"].lower():
        add("Page is set to noindex", Severity.MAJOR, f"robots: {d['robots']}")
    if d["imgsNoAlt"]:
        add("Images without alt attribute", Severity.MINOR, f"{d['imgsNoAlt']} image(s)")

    if d["loadMs"] is not None:
        if d["loadMs"] > 8000:
            ctx.add(Finding("performance", "Very slow page load", Severity.MAJOR, ctx.url, f"Load event at {d['loadMs']} ms"))
        elif d["loadMs"] > 3000:
            ctx.add(Finding("performance", "Slow page load", Severity.MINOR, ctx.url, f"Load event at {d['loadMs']} ms"))
    if d["transferKb"] > 5000:
        ctx.add(Finding("performance", "Heavy page weight", Severity.MINOR, ctx.url, f"{d['transferKb']} KB transferred"))
    return {"load_ms": d["loadMs"], "dom_ms": d["domMs"], "transfer_kb": d["transferKb"]}
