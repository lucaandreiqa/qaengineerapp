"""HTML report for humans, JUnit XML for CI systems."""
from __future__ import annotations

import html
import os
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import RunResult, Severity

SEV_COLORS = {"critical": "#c62828", "major": "#ef6c00", "minor": "#f9a825", "info": "#607d8b"}


def _rel(path: str | None, base: Path) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(path, base).replace("\\", "/")
    except ValueError:
        return Path(path).as_uri()


def write_html(result: RunResult, run_dir: Path) -> Path:
    e = html.escape
    findings = sorted(result.findings, key=lambda f: (f.severity.rank, f.check, f.url))
    rows = []
    for f in findings:
        img = ""
        if f.screenshot:
            src = _rel(f.screenshot, run_dir)
            img = f'<a href="{e(src)}" target="_blank"><img src="{e(src)}" loading="lazy"></a>'
        rows.append(
            f'<tr data-sev="{f.severity.value}" data-check="{e(f.check)}">'
            f'<td><span class="sev" style="background:{SEV_COLORS[f.severity.value]}">{f.severity.value}</span></td>'
            f'<td>{e(f.check)}</td><td><b>{e(f.title)}</b><pre>{e(f.details)}</pre>{img}</td>'
            f'<td><a href="{e(f.url)}" target="_blank">{e(f.url)}</a></td></tr>')

    pages = "".join(f"<tr><td><a href='{e(p.url)}' target='_blank'>{e(p.url)}</a></td><td>{p.status or '—'}</td>"
                    f"<td>{p.load_ms or '—'}</td><td>{e(p.title)}</td></tr>" for p in result.pages)
    lh_rows = "".join(
        f"<tr><td>{e(u)}</td>" + "".join(f"<td>{s.get(c, '—')}</td>" for c in
                                         ("performance", "accessibility", "best-practices", "seo", "lcp_ms", "cls"))
        + f"<td><a href='{e(_rel(s.get('report'), run_dir))}' target='_blank'>open</a></td></tr>"
        for u, s in result.metrics.get("lighthouse", {}).items())
    lh_table = (f"<h2>Lighthouse</h2><table><tr><th>URL</th><th>Perf</th><th>A11y</th><th>Best pr.</th>"
                f"<th>SEO</th><th>LCP ms</th><th>CLS</th><th>Report</th></tr>{lh_rows}</table>") if lh_rows else ""
    counts = " ".join(f'<span class="pill" style="background:{SEV_COLORS[s.value]}">{result.count(s)} {s.value}</span>'
                      for s in Severity)
    status = ("PASSED", "#2e7d32") if result.passed else ("FAILED", "#c62828")
    duration = (result.finished - result.started).total_seconds() if result.finished else 0

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>QA Report {e(result.run_id)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:0;padding:24px;background:#f6f7f9;color:#1d2330}}
h1{{margin:0 0 4px}} .muted{{color:#667}} table{{width:100%;border-collapse:collapse;background:#fff;margin:12px 0 28px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #e3e6eb;vertical-align:top;font-size:14px}}
th{{background:#eef0f4}} pre{{white-space:pre-wrap;margin:4px 0;font-size:12px;color:#445}}
img{{max-width:320px;max-height:200px;border:1px solid #ccd;margin-top:4px}}
.sev,.pill{{color:#fff;border-radius:10px;padding:2px 8px;font-size:12px;text-transform:uppercase}}
.status{{display:inline-block;color:#fff;background:{status[1]};padding:4px 12px;border-radius:6px;font-weight:600}}
.filters button{{margin-right:6px;padding:4px 10px;border:1px solid #ccd;background:#fff;border-radius:6px;cursor:pointer}}
.filters button.on{{background:#1d2330;color:#fff}} td a{{word-break:break-all}}
</style></head><body>
<h1>QA Report</h1>
<div class="muted">{e(result.config.url)} · run {e(result.run_id)} · {duration:.0f}s · {len(result.pages)} pages ·
checks: {e(', '.join(result.config.checks))}</div>
<p><span class="status">{status[0]}</span> {counts}</p>
<h2>Findings ({len(findings)})</h2>
<div class="filters" id="f"><button class="on" data-v="">All</button>{''.join(
    f'<button data-v="{c}">{c}</button>' for c in sorted({f.check for f in findings}))}</div>
<table id="t"><tr><th>Severity</th><th>Check</th><th>Finding</th><th>Page</th></tr>{''.join(rows) or
    '<tr><td colspan=4>No findings 🎉</td></tr>'}</table>
{lh_table}
<h2>Pages crawled</h2><table><tr><th>URL</th><th>Status</th><th>Load ms</th><th>Title</th></tr>{pages}</table>
<script>
document.querySelectorAll('#f button').forEach(b=>b.onclick=()=>{{
  document.querySelectorAll('#f button').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('#t tr[data-check]').forEach(r=>r.style.display=!b.dataset.v||r.dataset.check===b.dataset.v?'':'none');
}});
</script></body></html>"""
    path = run_dir / "report.html"
    path.write_text(doc, encoding="utf-8")
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
