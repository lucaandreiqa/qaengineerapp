"""HTML report for humans, JUnit XML for CI systems."""
from __future__ import annotations

import math
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import RunResult, Severity

SEV_COLORS = {"critical": "#c62828", "major": "#ef6c00", "minor": "#f9a825", "info": "#607d8b"}


def _rel(path: str | None, base: Path) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(path, base).replace("\\", "/")
    except ValueError:
        return Path(path).as_uri()


_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=select_autoescape(["html", "j2"]))
CHECK_LABELS = {"functional": "Functional", "visual": "Visual", "accessibility": "Accessibility", "seo": "SEO",
                "performance": "Performance", "best-practices": "Best practices"}
SEV_LABELS = {"critical": "Critical", "major": "Major", "minor": "Minor", "info": "Info", "none": "None"}
VIEWPORT_LABELS = {"desktop": "Desktop 1440×900", "tablet": "Tablet 768×1024", "mobile": "Mobile 390×844"}


def _band(score: float, good: float, poor: float, lower_is_better: bool = True) -> str:
    if lower_is_better:
        return "good" if score <= good else "mid" if score <= poor else "bad"
    return "good" if score >= good else "mid" if score >= poor else "bad"


def write_html(result: RunResult, run_dir: Path) -> Path:
    """Standalone report in the app's design (light/dark, filters, screenshots, Lighthouse gauges)."""
    findings = sorted(result.findings, key=lambda f: (f.severity.rank, f.check, f.url))
    rank = {s.value: 4 - s.rank for s in Severity}
    items = []
    for i, f in enumerate(findings, 1):
        shot = _rel(f.screenshot, run_dir)
        items.append({"id": f"F-{i:03d}", "sev": f.severity.value, "sevLabel": SEV_LABELS[f.severity.value],
                      "check": f.check, "checkLabel": CHECK_LABELS.get(f.check, f.check.title()), "title": f.title,
                      "url": f.url, "href": f.url, "details": f.details or "",
                      "kind": "diff" if f.check == "visual" and shot.split("/")[-1].startswith("diff__") else ("shot" if shot else "none"),
                      "shot": shot, "diff": shot})
    pages = []
    for p in result.pages:
        fs = [f for f in result.findings if f.url == p.url]
        worst = max((f.severity.value for f in fs), key=lambda v: rank[v], default="none")
        pages.append({"path": p.url, "href": p.url, "code": p.status or 0,
                      "load": f"{p.load_ms / 1000:.2f} s" if p.load_ms else "—",
                      "n": len(fs), "worst": worst, "worstLabel": SEV_LABELS[worst]})
    lh = result.metrics.get("lighthouse", {})
    lh_url, first = next(iter(lh.items()), ("", {}))
    circ = 2 * math.pi * 38
    gauges = []
    for key, label in (("performance", "Performance"), ("accessibility", "Accessibility"),
                       ("best-practices", "Best practices"), ("seo", "SEO")):
        if key in first:
            s = int(first[key])
            gauges.append({"label": label, "score": s, "cls": "g-" + _band(s, 90, 50, lower_is_better=False),
                           "dash": f"{s / 100 * circ:.1f} {circ:.1f}"})
    vitals = []
    word = {"good": "Good", "mid": "Needs improvement", "bad": "Poor"}
    if first.get("lcp_ms"):
        lcp = first["lcp_ms"] / 1000
        b = _band(lcp, 2.5, 4)
        vitals.append({"label": "Largest Contentful Paint", "value": f"{lcp:.1f} s", "band": b, "word": word[b], "goal": "good ≤ 2.5 s"})
    if "cls" in first:
        b = _band(first["cls"], 0.1, 0.25)
        vitals.append({"label": "Cumulative Layout Shift", "value": f"{first['cls']:.2f}", "band": b, "word": word[b], "goal": "good ≤ 0.1"})
    counts = {s.value: result.count(s) for s in Severity}
    duration = int((result.finished - result.started).total_seconds()) if result.finished else 0
    html = _env.get_template("report.html.j2").render(
        run_id=result.run_id, host=urlparse(result.config.url).netloc or result.config.url, base=result.config.url,
        failed=not result.passed, counts=counts, sev_keys=["critical", "major", "minor", "info"], SEVL=SEV_LABELS,
        CHECKS={k: v for k, v in CHECK_LABELS.items() if any(f.check == k for f in findings)},
        started=result.started.strftime("%b %d, %Y · %H:%M"), generated=datetime.now().strftime("%b %d, %Y %H:%M"),
        duration=f"{duration // 60}m {duration % 60:02d}s",
        viewports=", ".join(VIEWPORT_LABELS.get(v, v) for v in result.config.viewports),
        checks=", ".join(CHECK_LABELS.get(c, c) for c in result.config.checks),
        findings=items, pages=pages, pages_with=sum(1 for p in pages if p["n"]),
        gauges=gauges, vitals=vitals, lh_url=lh_url,
        lh_rows=[{"url": u, "s": sc, "report": _rel(sc.get("report"), run_dir)} for u, sc in lh.items()],
    )
    path = run_dir / "report.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_junit(result: RunResult, run_dir: Path) -> Path:
    """One testcase per (check, page); critical/major findings become failures."""
    suites = ET.Element("testsuites", name="QA Website Tests")
    by_check: dict[str, dict[str, list]] = {}
    for check in result.config.checks:
        by_check[check] = {p.url: [] for p in result.pages}
    for f in result.findings:
        by_check.setdefault(f.check, {}).setdefault(f.url, []).append(f)

    for check, pages in by_check.items():
        suite = ET.SubElement(suites, "testsuite", name=check)
        failures = 0
        for url, items in pages.items():
            case = ET.SubElement(suite, "testcase", classname=check, name=url)
            blocking = [f for f in items if f.severity in (Severity.CRITICAL, Severity.MAJOR)]
            if blocking:
                failures += 1
                fail = ET.SubElement(case, "failure", message=f"{len(blocking)} blocking issue(s)")
                fail.text = "\n".join(f"[{f.severity.value}] {f.title}: {f.details}" for f in blocking)
            others = [f for f in items if f not in blocking]
            if others:
                ET.SubElement(case, "system-out").text = "\n".join(
                    f"[{f.severity.value}] {f.title}: {f.details}" for f in others)
        suite.set("tests", str(len(pages)))
        suite.set("failures", str(failures))
    path = run_dir / "junit.xml"
    ET.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)
    return path
