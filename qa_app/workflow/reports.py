"""Reports from History: trends, and run / ticket / period reports as self-contained HTML, PDF and CSV.

Everything is built from the run records (history.py), so reports work for tickets that already left the board.
Reports are saved under <history root>/_reports/<id>/ (report.html, report.pdf once made, meta.json).
"""
from __future__ import annotations

import base64
import csv
import html
import io
import json
import mimetypes
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .history import RunStore, counts, norm

KINDS = {"run": "Run report", "ticket": "Ticket report", "period": "Period summary"}
RES_WORD = {"pass": "Passed", "fail": "Failed", "partial": "Partial", "blocked": "Blocked", "nt": "Not tested"}
STATUS_WORD = {"passed": "Passed", "failed": "Failed", "error": "Error", "stopped": "Stopped", "skipped": "Skipped", "running": "Running"}
BAD = ("fail", "partial", "blocked")
MAX_IMG = 900_000  # bytes per inlined screenshot


# ------------------------------------------------------------------ trends
def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def trends(store: RunStore, since: Optional[float] = None, project: str = "", type_: str = "") -> dict:
    runs = [r for r in store.list(project=project, type_=type_, since=since) if r.get("status") in ("passed", "failed", "error")]
    runs.sort(key=lambda r: r.get("started") or 0)
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        by_day[_day(r["started"])].append(r)
    series = [{"day": d, "runs": len(rs), "passed": sum(r["status"] == "passed" for r in rs),
               "pass_rate": round(100 * sum(r["status"] == "passed" for r in rs) / len(rs))} for d, rs in sorted(by_day.items())]
    per_ticket: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        per_ticket[r["key"]].append(r)
    first_pass = sum(1 for rs in per_ticket.values() if rs[0]["status"] == "passed")
    to_green = [next(i + 1 for i, r in enumerate(rs) if r["status"] == "passed") for rs in per_ticket.values()
                if any(r["status"] == "passed" for r in rs)]
    flaky = _flaky(store, per_ticket)

    def group(field: str) -> list[dict]:
        g: dict[str, list[dict]] = defaultdict(list)
        for r in runs:
            g[r.get(field) or "—"].append(r)
        return sorted(({"name": k, "runs": len(v), "pass_rate": round(100 * sum(x["status"] == "passed" for x in v) / len(v)),
                        "tickets": len({x["key"] for x in v})} for k, v in g.items()), key=lambda x: -x["runs"])

    tickets = []
    for k, rs in per_ticket.items():
        costs_ = [r.get("cost") for r in rs if r.get("cost") is not None]
        tickets.append({"key": k, "title": rs[-1].get("title", ""), "runs": len(rs), "status": rs[-1]["status"],
                        "time_s": round(sum(r.get("duration_s") or 0 for r in rs)), "cost": round(sum(costs_), 4) if costs_ else None})
    tickets.sort(key=lambda x: (-x["runs"], x["key"]))
    return {"series": series, "runs": len(runs), "tickets": len(per_ticket),
            "pass_rate": round(100 * sum(r["status"] == "passed" for r in runs) / len(runs)) if runs else None,
            "first_time_pass": round(100 * first_pass / len(per_ticket)) if per_ticket else None,
            "avg_runs_to_green": round(sum(to_green) / len(to_green), 1) if to_green else None,
            "flaky": flaky, "by_project": group("project"), "by_type": group("type"), "by_issue_type": group("issue_type"),
            "per_ticket": tickets}


def _flaky(store: RunStore, per_ticket: dict[str, list[dict]]) -> list[dict]:
    """Checks whose result went back and forth (pass → fail → pass, or the reverse) between runs of the same ticket
    with the same environment and spec."""
    out = []
    for key, rs in per_ticket.items():
        if len(rs) < 2:
            continue
        recs = []
        for r in rs:
            try:
                recs.append(store.get(r["id"]))
            except (KeyError, ValueError):
                continue
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for rec in recs:
            groups[((rec.get("env") or {}).get("url", ""), rec.get("spec_hash", ""))].append(rec)
        for g in groups.values():
            if len(g) < 2:
                continue
            seq: dict[str, list[tuple[str, str]]] = defaultdict(list)
            text: dict[str, str] = {}
            for rec in g:
                for i in rec["items"]:
                    seq[norm(i["text"])].append((i["result"], rec["id"]))
                    text[norm(i["text"])] = i["text"]
            for k, vals in seq.items():
                res = [v for v, _ in vals if v in ("pass", "fail")]
                flips = sum(1 for a, b in zip(res, res[1:]) if a != b)
                if flips >= 2:  # back and forth; a single fail → pass is a fix, not flakiness
                    out.append({"key": key, "text": text[k], "flips": flips, "runs": [rid for _, rid in vals]})
    return sorted(out, key=lambda x: -x["flips"])[:20]


# ------------------------------------------------------------------ building reports
CSS = """
*{box-sizing:border-box}body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;color:#17181b;margin:0;background:#fff}
main{max-width:900px;margin:0 auto;padding:32px 28px 48px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:16px;margin:28px 0 10px}h3{font-size:14px;margin:18px 0 8px}
.sub{color:#5c616b;margin:0 0 18px}.brand{color:#4c58d6;font-weight:700;font-size:12px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:10px}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px 18px;padding:14px 16px;border:1px solid #e1e2e7;border-radius:10px;margin:0 0 16px}
.facts dt{font-size:11.5px;color:#80858f}.facts dd{margin:0;font-weight:500;overflow-wrap:anywhere}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 10px}.chip{padding:3px 10px;border-radius:12px;font-size:12.5px;background:#eeeff2}
.c-pass{background:#e5f5ec;color:#17734a}.c-fail{background:#fdecec;color:#c62a2f}.c-partial{background:#fff6d9;color:#855400}.c-blocked{background:#eeeff2;color:#585d66}
.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:#e1e2e7;margin:0 0 18px}.bar i{display:block}
.b-pass{background:#30a46c}.b-fail{background:#e5484d}.b-partial{background:#ffb224}.b-blocked{background:#8b8d98}.b-nt{background:#d2d4da}
table{width:100%;border-collapse:collapse;margin:0 0 8px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #e1e2e7;vertical-align:top;font-size:13px}
th{font-size:11.5px;color:#80858f;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.res{display:inline-block;min-width:74px;text-align:center;padding:1px 8px;border-radius:5px;font-size:11.5px;font-weight:700}
.fail-box{border:1px solid #f3c7c8;border-radius:10px;padding:12px 14px;margin:0 0 12px;page-break-inside:avoid}
.fail-box pre{white-space:pre-wrap;background:#f6f6f7;border-radius:6px;padding:8px 10px;font-size:12px;margin:8px 0}
.fail-box img{max-width:100%;border:1px solid #e1e2e7;border-radius:6px;margin-top:6px}
.muted{color:#80858f}.foot{margin-top:36px;color:#80858f;font-size:12px;border-top:1px solid #e1e2e7;padding-top:10px}
.comment{white-space:pre-wrap;background:#f6f6f7;border-radius:8px;padding:12px 14px;font-size:13px}
@media print{main{padding:0}a{color:inherit}}
"""


def e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _when(ts: Optional[float]) -> str:
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M") if ts else "—"


def _dur(s: Optional[float]) -> str:
    if s is None:
        return "—"
    s = int(round(s))
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


def _bar(c: dict) -> str:
    tot = sum(c.values()) or 1
    return "<div class='bar'>" + "".join(f"<i class='b-{k}' style='width:{100 * c[k] / tot:.1f}%'></i>" for k in ("pass", "fail", "partial", "blocked", "nt") if c.get(k)) + "</div>"


def _chips(c: dict) -> str:
    return "<div class='chips'>" + "".join(f"<span class='chip c-{k}'>{c[k]} {RES_WORD[k].lower()}</span>" for k in ("pass", "fail", "partial", "blocked", "nt") if c.get(k)) + "</div>"


def _img(store: RunStore, run_id: str, path: str) -> str:
    try:
        f = store.file(run_id, path)
    except KeyError:
        return ""
    if f.stat().st_size > MAX_IMG:
        return ""
    mime = mimetypes.guess_type(f.name)[0] or "image/png"
    return f"<img alt='Screenshot' src='data:{mime};base64,{base64.b64encode(f.read_bytes()).decode()}'>"


def _checks_table(rec: dict) -> str:
    rows, sec = [], None
    for i in rec["items"]:
        if i["section"] != sec:
            sec = i["section"]
            rows.append(f"<tr><th colspan='3'>{e(sec)}</th></tr>")
        rows.append(f"<tr><td class='muted'>{i['n']}</td><td>{e(i['text'])}{('<div class=muted>' + e(i['bug']) + '</div>') if i.get('bug') and i['result'] in BAD else ''}</td>"
                    f"<td><span class='res c-{i['result']}'>{RES_WORD.get(i['result'], i['result'])}</span></td></tr>")
    return "<table><tbody>" + "".join(rows) + "</tbody></table>"


def _failures(store: RunStore, rec: dict) -> str:
    bad = [i for i in rec["items"] if i["result"] in BAD]
    if not bad:
        return ""
    out = ["<h2>What failed</h2>"]
    for i in bad:
        shots = "".join(_img(store, rec["id"], a["path"]) for a in i.get("attachments") or [] if a.get("kind") == "screenshot")
        out.append(f"<div class='fail-box'><b>Check {i['n']}: {e(i['text'])}</b> · <span class='res c-{i['result']}'>{RES_WORD[i['result']]}</span>"
                   f"{('<p>' + e(i['bug']) + '</p>') if i.get('bug') else ''}{('<pre>' + e(i['error']) + '</pre>') if i.get('error') else ''}{shots}</div>")
    return "".join(out)


def _page(title: str, sub: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}</title><style>{CSS}</style></head><body><main><div class='brand'>YourQA</div><h1>{e(title)}</h1>"
            f"<p class='sub'>{sub}</p>{body}<p class='foot'>Generated by YourQA on {_when(time.time())}. Results come from automated "
            "Playwright runs reviewed by a QA engineer at each gate.</p></main></body></html>")


def run_report(store: RunStore, run_id: str) -> tuple[str, str, str]:
    rec = store.get(run_id)
    c = counts(rec["items"])
    env = rec.get("env") or {}
    facts = [("Ticket", rec["key"]), ("Run", f"{rec['run_no']} · {STATUS_WORD.get(rec['status'], rec['status'])}"),
             ("Environment", env.get("url", "—")), ("Account", rec.get("account") or "—"), ("Started", _when(rec["started"])),
             ("Duration", _dur(rec.get("duration_s"))), ("Claude cost", f"${rec['cost']:.2f}" if rec.get("cost") is not None else "—")]
    body = ("<dl class='facts'>" + "".join(f"<div><dt>{k}</dt><dd>{e(v)}</dd></div>" for k, v in facts) + "</dl>"
            + (f"<p class='fail-box'>{e(rec['error'])}</p>" if rec.get("error") else "")
            + _chips(c) + _bar(c) + "<h2>Checks</h2>" + _checks_table(rec) + _failures(store, rec))
    title = f"{rec['key']} · run {rec['run_no']}"
    return title, _page(title, e(rec.get("title", "")), body), _summary_text(rec["key"], rec.get("title", ""), [rec])


def ticket_report(store: RunStore, key: str, ticket: Optional[dict] = None) -> tuple[str, str, str]:
    runs = store.runs_for(key)
    if not runs:
        raise KeyError(key)
    recs = [store.get(r["id"]) for r in runs]
    last = recs[-1]
    rows = "".join(f"<tr><td>Run {r['run_no']}</td><td>{_when(r['started'])}</td><td><span class='res c-{'pass' if r['status'] == 'passed' else 'fail'}'>{STATUS_WORD.get(r['status'], r['status'])}</span></td>"
                   f"<td>{counts(r['items'])['pass']}/{len(r['items'])} passed</td><td class='muted'>{e((r.get('env') or {}).get('url', ''))}</td></tr>" for r in recs)
    green = next((r["run_no"] for r in recs if r["status"] == "passed"), None)
    c = counts(last["items"])
    body = (f"<dl class='facts'><div><dt>Runs</dt><dd>{len(recs)}</dd></div><div><dt>Latest</dt><dd>{STATUS_WORD.get(last['status'], last['status'])}</dd></div>"
            f"<div><dt>Green at</dt><dd>{'run ' + str(green) if green else 'not yet'}</dd></div>"
            f"<div><dt>Time testing</dt><dd>{_dur(sum(r.get('duration_s') or 0 for r in recs))}</dd></div></dl>"
            "<h2>Runs</h2><table><thead><tr><th>Run</th><th>When</th><th>Status</th><th>Checks</th><th>Environment</th></tr></thead><tbody>" + rows + "</tbody></table>"
            f"<h2>Final checklist (run {last['run_no']})</h2>" + _chips(c) + _bar(c) + _checks_table(last) + _failures(store, last))
    after = {}
    for r in recs:  # the latest run that has them
        after.update({k: v for k, v in (r.get("after") or {}).items() if v})
    t = {**after, **{k: v for k, v in (ticket or {}).items() if v}}
    if t.get("moved_to"):
        body += f"<p>Moved to <b>{e(t['moved_to'])}</b> after QA.</p>"
    if t.get("comment"):
        body += "<h2>Jira comment</h2><div class='comment'>" + e(t["comment"]) + "</div>"
    if t.get("cases"):
        body += "<h2>TestRail cases</h2><ul>" + "".join(f"<li>{e(x.get('title', ''))}</li>" for x in t["cases"]) + "</ul>"
    title = f"{key} · ticket report"
    return title, _page(title, e(last.get("title", "")), body), _summary_text(key, last.get("title", ""), recs)


def period_report(store: RunStore, since: Optional[float], until: Optional[float], label: str) -> tuple[str, str, str]:
    runs = [r for r in store.list(since=since, until=until) if r.get("status") != "running"]
    runs.sort(key=lambda r: r.get("started") or 0)
    latest: dict[str, dict] = {}
    for r in runs:
        latest[r["key"]] = r
    finished = [r for r in runs if r["status"] in ("passed", "failed")]
    sev: Counter = Counter()
    areas: Counter = Counter()
    for r in latest.values():
        try:
            rec = store.get(r["id"])
        except (KeyError, ValueError):
            continue
        for i in rec["items"]:
            if i["result"] in BAD:
                sev[i.get("severity") or ("Blocked" if i["result"] == "blocked" else "Minor")] += 1
                areas[i["section"]] += 1
    tr = trends(store, since)
    pass_rate = round(100 * sum(r["status"] == "passed" for r in finished) / len(finished)) if finished else None
    cost = sum(r.get("cost") or 0 for r in runs)
    facts = [("Tickets tested", len(latest)), ("Runs", len(runs)), ("Pass rate", f"{pass_rate}%" if pass_rate is not None else "—"),
             ("Bugs found", sum(sev.values())), ("Time testing", _dur(sum(r.get("duration_s") or 0 for r in runs))),
             ("Claude cost", f"${cost:.2f}")]
    body = "<dl class='facts'>" + "".join(f"<div><dt>{k}</dt><dd>{e(v)}</dd></div>" for k, v in facts) + "</dl>"
    if sev:
        body += "<h2>Bugs found, by severity</h2><div class='chips'>" + "".join(f"<span class='chip c-fail'>{n} {e(k)}</span>" for k, n in sev.most_common()) + "</div>"
    if areas:
        body += "<h2>Areas that failed most</h2><table><tbody>" + "".join(f"<tr><td>{e(a)}</td><td>{n} failed check{'s' if n != 1 else ''}</td></tr>" for a, n in areas.most_common(8)) + "</tbody></table>"
    if tr["flaky"]:
        body += "<h2>Flaky checks</h2><table><tbody>" + "".join(f"<tr><td>{e(f['key'])}</td><td>{e(f['text'])}</td><td>{f['flips']} flip{'s' if f['flips'] != 1 else ''}</td></tr>" for f in tr["flaky"][:10]) + "</tbody></table>"
    body += ("<h2>Tickets</h2><table><thead><tr><th>Ticket</th><th>Title</th><th>Runs</th><th>Final status</th></tr></thead><tbody>"
             + "".join(f"<tr><td>{e(k)}</td><td>{e(r.get('title', ''))}</td><td>{sum(1 for x in runs if x['key'] == k)}</td>"
                       f"<td><span class='res c-{'pass' if r['status'] == 'passed' else 'fail'}'>{STATUS_WORD.get(r['status'], r['status'])}</span></td></tr>"
                       for k, r in sorted(latest.items())) + "</tbody></table>")
    if not runs:
        body += "<p class='muted'>No runs in this period.</p>"
    title = f"QA summary · {label}"
    text = (f"*{title}*\n{len(latest)} tickets tested, {len(runs)} runs, pass rate {pass_rate if pass_rate is not None else '—'}%, "
            f"{sum(sev.values())} bugs found.\n" + "\n".join(f"• {k}: {STATUS_WORD.get(r['status'], r['status'])}" for k, r in sorted(latest.items())[:15]))
    return title, _page(title, e(label), body), text


def _summary_text(key: str, title: str, recs: list[dict]) -> str:
    last = recs[-1]
    c = counts(last["items"])
    bad = [i for i in last["items"] if i["result"] in BAD]
    lines = [f"*{key}: {title}*", f"Run {last['run_no']} {STATUS_WORD.get(last['status'], last['status']).lower()}: "
             f"{c['pass']}/{len(last['items'])} checks passed on {(last.get('env') or {}).get('url', 'the environment')}."]
    lines += [f"• ✗ {i['text']}" + (f": {i['bug']}" if i.get("bug") else "") for i in bad[:8]]
    return "\n".join(lines)


# ------------------------------------------------------------------ saving, export
class ReportStore:
    def __init__(self, store: RunStore) -> None:
        self.store = store
        self.root = store.root / "_reports"

    def create(self, kind: str, ref: str = "", since: Optional[float] = None, until: Optional[float] = None,
               label: str = "", ticket: Optional[dict] = None) -> dict:
        if kind == "run":
            title, page, text = run_report(self.store, ref)
            key = self.store.get(ref)["key"]
        elif kind == "ticket":
            title, page, text = ticket_report(self.store, ref, ticket)
            key = ref
        elif kind == "period":
            title, page, text = period_report(self.store, since, until, label or "all time")
            key = ""
        else:
            raise ValueError(f"Unknown report kind '{kind}'")
        rid = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3] + "-" + kind
        d = self.root / rid
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.html").write_text(page, encoding="utf-8")
        meta = {"id": rid, "kind": kind, "kind_name": KINDS[kind], "title": title, "ref": ref, "key": key,
                "created": time.time(), "summary": text, "label": label}
        (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        return meta

    def list(self) -> list[dict]:
        out = []
        if self.root.exists():
            for d in self.root.iterdir():
                f = d / "meta.json"
                if f.exists():
                    try:
                        out.append(json.loads(f.read_text(encoding="utf-8")))
                    except ValueError:
                        continue
        return sorted(out, key=lambda m: -m.get("created", 0))

    def get(self, rid: str) -> dict:
        if not re.fullmatch(r"[\w-]+", rid or ""):
            raise KeyError(rid)
        f = self.root / rid / "meta.json"
        if not f.exists():
            raise KeyError(rid)
        return json.loads(f.read_text(encoding="utf-8"))

    def html_path(self, rid: str) -> Path:
        self.get(rid)
        return self.root / rid / "report.html"

    def pdf_path(self, rid: str) -> Path:
        """The report as PDF, rendered once with Playwright's Chromium (already installed for the tests)."""
        src = self.html_path(rid)
        out = src.with_suffix(".pdf")
        if not out.exists():
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.set_content(src.read_text(encoding="utf-8"), wait_until="load")
                page.pdf(path=str(out), format="A4", print_background=True,
                         margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
                browser.close()
        return out


def runs_csv(store: RunStore, runs: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", "ticket", "title", "project", "type", "run", "trigger", "status", "started", "duration_s",
                "environment", "passed", "failed", "partial", "blocked", "not_tested", "cost_usd"])
    for r in runs:
        c = r.get("counts") or {}
        w.writerow([r["id"], r["key"], r.get("title", ""), r.get("project", ""), r.get("type", ""), r.get("run_no"), r.get("trigger"),
                    r.get("status"), _when(r.get("started")), r.get("duration_s"), r.get("env_url", ""), c.get("pass", 0), c.get("fail", 0),
                    c.get("partial", 0), c.get("blocked", 0), c.get("nt", 0), r.get("cost") if r.get("cost") is not None else ""])
    return buf.getvalue()


def checks_csv(store: RunStore, runs: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["run_id", "ticket", "run", "check", "section", "text", "result", "severity", "note", "error"])
    for r in runs:
        try:
            rec = store.get(r["id"])
        except (KeyError, ValueError):
            continue
        for i in rec["items"]:
            w.writerow([rec["id"], rec["key"], rec["run_no"], i["n"], i["section"], i["text"], i["result"], i.get("severity") or "",
                        i.get("bug", ""), (i.get("error") or "").splitlines()[0] if i.get("error") else ""])
    return buf.getvalue()


# ------------------------------------------------------------------ sending (only on the user's click, after a preview)
class SendError(Exception):
    pass


def preview(meta: dict, to: str, settings: dict) -> dict:
    """What will be sent where, before anything is sent."""
    if to in ("slack", "teams"):
        cfg = settings.get(to, {})
        if not (cfg.get("enabled") and cfg.get("webhook_url")):
            raise SendError(f"{'Slack' if to == 'slack' else 'Microsoft Teams'} isn't set up. Add its webhook on the Integrations screen.")
        return {"to": to, "where": "the channel of the configured webhook", "what": "summary text", "text": meta["summary"]}
    if to == "tracker":
        if not meta.get("key"):
            raise SendError("Only run and ticket reports belong to a ticket")
        wf = settings.get("workflow", {})
        if wf.get("tracker") == "azure":
            return {"to": "azure", "where": f"work item {meta['key']}", "what": "the PDF report as an attachment", "text": ""}
        j = settings.get("jira", {})
        if j.get("auth") == "token" and j.get("api_token"):
            return {"to": "jira", "where": f"{meta['key']} on {j.get('base_url', 'Jira')}", "what": "the PDF report as an attachment", "text": ""}
        if j.get("auth") == "mcp" and j.get("cloud_id"):
            return {"to": "jira", "where": f"{meta['key']} on {j.get('base_url', 'Jira')}",
                    "what": "the report summary as a comment (attaching files needs Jira connected with an API token)",
                    "text": meta["summary"]}
        raise SendError("Connect Jira or Azure Boards on the Integrations screen first")
    raise SendError(f"Unknown destination '{to}'")


def send(rstore: ReportStore, rid: str, to: str, settings: dict, http=None) -> str:
    import requests

    http = http or requests
    meta = rstore.get(rid)
    pv = preview(meta, to, settings)
    if to == "slack":
        r = http.post(settings["slack"]["webhook_url"], json={"text": meta["summary"]}, timeout=15)
        r.raise_for_status()
        return "Posted to Slack"
    if to == "teams":
        from ..integrations.teams import _card
        body = [{"type": "TextBlock", "wrap": True, "text": line} for line in meta["summary"].replace("*", "**").splitlines() if line.strip()]
        r = http.post(settings["teams"]["webhook_url"], json=_card(body), timeout=15)
        r.raise_for_status()
        return "Posted to Microsoft Teams"
    key = meta["key"]
    if pv["to"] == "azure":
        a = settings.get("azure", {})
        from ..integrations.azure_boards import Azure, _p
        az = Azure(a["org_url"], a["pat"], http if http is not requests else None)
        pdf = rstore.pdf_path(rid)
        up = az.req("POST", f"{_p(a['project'])}/_apis/wit/attachments", params={"fileName": f"{key}-report.pdf"},
                    json=None, headers={"Content-Type": "application/octet-stream"}, data=pdf.read_bytes())
        az.req("PATCH", f"{_p(a['project'])}/_apis/wit/workitems/{key}", headers={"Content-Type": "application/json-patch+json"},
               json=[{"op": "add", "path": "/relations/-", "value": {"rel": "AttachedFile", "url": up.get("url", ""),
                                                                     "attributes": {"comment": meta["title"]}}}])
        return f"Attached to work item {key}"
    j = settings.get("jira", {})
    if j.get("auth") == "token":
        pdf = rstore.pdf_path(rid)
        with pdf.open("rb") as fh:
            r = http.post(f"{j['base_url'].rstrip('/')}/rest/api/2/issue/{key}/attachments", auth=(j["email"], j["api_token"]),
                          headers={"X-Atlassian-Token": "no-check"}, files={"file": (f"{key}-report.pdf", fh, "application/pdf")}, timeout=60)
        r.raise_for_status()
        return f"Attached to {key}"
    from ..integrations.atlassian_mcp import AtlassianMcp
    AtlassianMcp.signed_in(j["cloud_id"]).op("addOrEditJiraIssueComment", issueIdOrKey=key,
                                              commentBody=meta["summary"].replace("*", "**") + f"\n\n_{meta['title']}, from YourQA_")
    return f"Posted the summary on {key}"
