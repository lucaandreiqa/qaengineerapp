"""Runs your existing Runner (qa_app/runner.py) in a background thread for the web UI.

Live state (progress, findings, log) is kept in memory and pushed to the browser. When a run ends,
the Runner writes result.json, report.html and junit.xml exactly as before, and History reads those.
A small web.json next to result.json stores what the web UI adds (ticket key, published flag).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .. import integrations
from ..config import APP_DIR, BASELINES_DIR, RUNS_DIR, load_settings
from ..integrations import jira as jira_api
from ..models import Finding, PageResult, RunConfig, RunResult, Severity
from ..runner import Runner
from ..workflow.store import bus

CHECKS = ["functional", "visual", "accessibility", "seo", "performance"]


def file_url(path: Optional[str]) -> str:
    """URL for a file under the app folder (screenshots, diffs, baselines)."""
    if not path:
        return ""
    try:
        rel = Path(path).resolve().relative_to(APP_DIR.resolve())
    except ValueError:
        return ""
    return "/files/" + quote(rel.as_posix())


def result_from_json(path: Path) -> RunResult:
    d = json.loads(path.read_text(encoding="utf-8"))
    cfg = RunConfig(**d["config"])
    return RunResult(d["run_id"], cfg, datetime.fromisoformat(d["started"]),
                     datetime.fromisoformat(d["finished"]) if d.get("finished") else None,
                     [PageResult(**p) for p in d["pages"]],
                     [Finding(**{**f, "severity": Severity(f["severity"])}) for f in d["findings"]],
                     d.get("metrics", {}), str(path.parent), d.get("report_path", ""))


def _sidecar(run_dir: Path) -> dict:
    p = run_dir / "web.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_sidecar(run_dir: Path, **values) -> None:
    p = run_dir / "web.json"
    p.write_text(json.dumps({**_sidecar(run_dir), **values}, indent=2), encoding="utf-8")


def finding_view(i: int, f: Finding, jira_keys: dict) -> dict:
    """Shape a finding for the UI, including baseline / current / diff for visual changes."""
    d = {"id": f"F-{i + 1:03d}", "sev": f.severity.value, "check": f.check, "title": f.title, "url": f.url,
         "details": f.details, "kind": "none", "shot": "", "baseline": "", "diff": "", "viewport": "",
         "jira_key": jira_keys.get(f"F-{i + 1:03d}", "")}
    if not f.screenshot:
        return d
    shot = Path(f.screenshot)
    d["kind"], d["shot"] = "shot", file_url(str(shot))
    m = re.search(r"\((desktop|tablet|mobile)\)", f.title)
    if f.check == "visual" and shot.name.startswith("diff__"):
        name = shot.name[len("diff__"):]
        current = shot.parent / name
        baseline = next(BASELINES_DIR.glob(f"*/{name}"), None)
        if current.exists() and baseline:
            d.update(kind="diff", diff=file_url(str(shot)), shot=file_url(str(current)), baseline=file_url(str(baseline)))
    if m:
        d["viewport"] = m.group(1).title()
    return d


def _level(msg: str) -> str:
    low = msg.lower()
    if low.startswith("passed"):
        return "OK"
    if low.startswith("failed") or " failed" in low or "error" in low:
        return "ERROR"
    if "cancelled" in low or "skipped" in low:
        return "WARN"
    return "INFO"


class LiveRun:
    def __init__(self, run_id: str, options: dict) -> None:
        self.id = run_id
        self.options = options
        self.state = "running"
        self.started = time.time()
        self.finished = 0.0
        self.crawled = 0
        self.total = int(options.get("max_pages") or 10)
        self.current = ""
        self.findings: list[Finding] = []
        self.logs: list[dict] = []
        self.error = ""
        self.runner: Optional[Runner] = None
        self.result: Optional[RunResult] = None
        self._lock = threading.Lock()
        self._last = 0.0

    def push(self, force: bool = False) -> None:
        if force or time.time() - self._last > 0.3:
            self._last = time.time()
            bus.publish({"type": "run", "run": self.view()})

    def log(self, msg: str) -> None:
        with self._lock:
            m = re.match(r"\[(\d+)/(\d+)\] (\S+)", msg)
            if m:
                self.current = m.group(3)
            self.logs.append({"t": time.strftime("%H:%M:%S"), "lv": _level(msg), "msg": msg.strip()})
        self.push()

    def finding(self, f: Finding) -> None:
        with self._lock:
            self.findings.append(f)
        self.push(force=True)

    def progress(self, done: int, total: int) -> None:
        self.crawled, self.total = done, total
        self.push()

    def view(self) -> dict:
        r = self.result
        counts = {s.value: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity.value] += 1
        pages = [{"url": p.url, "status": p.status or 0, "load_ms": p.load_ms or 0} for p in (r.pages if r else [])]
        return {
            "id": self.id, "url": self.options.get("url", ""), "ticket": self.options.get("ticket", ""),
            "state": self.state, "started": self.started, "finished": self.finished, "counts": counts,
            "crawled": len(r.pages) if r else self.crawled, "total": len(r.pages) if r and self.state != "running" else self.total,
            "published": False, "duration": (self.finished or time.time()) - self.started,
            "options": self.options, "current": self.current, "error": self.error,
            "findings": [finding_view(i, f, {}) for i, f in enumerate(self.findings)],
            "pages": pages, "logs": list(self.logs), "lighthouse": {}, "vitals": {},
        }


def saved_view(run_dir: Path, full: bool = True) -> Optional[dict]:
    p = run_dir / "result.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    side = _sidecar(run_dir)
    sev = {s.value: 0 for s in Severity}
    for f in d["findings"]:
        sev[f["severity"]] += 1
    started = datetime.fromisoformat(d["started"]).timestamp()
    finished = datetime.fromisoformat(d["finished"]).timestamp() if d.get("finished") else started
    c = d["config"]
    view = {
        "id": d["run_id"], "url": c["url"], "ticket": side.get("ticket", ""),
        "state": side.get("state") or ("passed" if d.get("passed") else "failed"),
        "started": started, "finished": finished, "counts": sev, "crawled": len(d["pages"]), "total": len(d["pages"]),
        "published": bool(side.get("published")), "duration": finished - started, "error": "",
    }
    if not full:
        return view
    lh = d.get("metrics", {}).get("lighthouse", {})
    first = next(iter(lh.values()), {})
    findings = [Finding(**{**f, "severity": Severity(f["severity"])}) for f in d["findings"]]
    view.update(
        options={"url": c["url"], "ticket": side.get("ticket", ""), "checks": {k: k in c["checks"] for k in CHECKS},
                 "max_pages": c["max_pages"], "viewports": {k: k in c["viewports"] for k in ("desktop", "tablet", "mobile")},
                 "threshold": c["visual_threshold"], "lighthouse": c["use_lighthouse"], "accept_baselines": c["update_baselines"],
                 "headed": not c["headless"], "publish": bool(side.get("publish_after"))},
        current=d["pages"][-1]["url"] if d["pages"] else "",
        findings=[finding_view(i, f, side.get("jira", {})) for i, f in enumerate(findings)],
        pages=[{"url": p["url"], "status": p["status"] or 0, "load_ms": p["load_ms"] or 0} for p in d["pages"]],
        logs=side.get("logs", []),
        lighthouse={k: first[k] for k in ("performance", "accessibility", "best-practices", "seo") if k in first},
        vitals={"lcp": round(first["lcp_ms"] / 1000, 2), "cls": first.get("cls", 0)} if first.get("lcp_ms") else {},
    )
    return view


class RunManager:
    def __init__(self) -> None:
        self.live: dict[str, LiveRun] = {}

    def start(self, o: dict) -> dict:
        checks = [k for k in CHECKS if (o.get("checks") or {}).get(k)]
        if not checks:
            raise ValueError("Turn on at least one check")
        vps = [k for k in ("desktop", "tablet", "mobile") if (o.get("viewports") or {}).get(k)] or ["desktop"]
        cfg = RunConfig(url=o["url"].strip(), checks=checks, max_pages=max(1, int(o.get("max_pages") or 10)),
                        viewports=vps, visual_threshold=float(o.get("threshold") or 0.5),
                        use_lighthouse=bool(o.get("lighthouse", True)), headless=not o.get("headed"),
                        update_baselines=bool(o.get("accept_baselines")))
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        while run_id in self.live or (RUNS_DIR / run_id).exists():
            time.sleep(1)
            run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        live = LiveRun(run_id, {**o, "url": cfg.url})
        live.runner = Runner(cfg, log=live.log, on_finding=live.finding, on_progress=live.progress, run_id=run_id)
        self.live[run_id] = live
        threading.Thread(target=self._execute, args=(live, cfg, o), daemon=True).start()
        return live.view()

    def _execute(self, live: LiveRun, cfg: RunConfig, o: dict) -> None:
        try:
            result = live.runner.run()  # type: ignore[union-attr]
            live.result = result
            live.state = "stopped" if live.runner.cancelled.is_set() else ("passed" if result.passed else "failed")  # type: ignore[union-attr]
            run_dir = Path(result.output_dir)
            if o.get("publish") and live.state in ("passed", "failed"):
                live.log("Publishing to integrations…")
                outcomes = integrations.publish(result, load_settings(), log=live.log)
                _save_sidecar(run_dir, published=bool(outcomes) and not all(v.startswith("error") for v in outcomes.values()))
            _save_sidecar(run_dir, ticket=o.get("ticket", ""), state=live.state if live.state == "stopped" else None,
                          publish_after=bool(o.get("publish")), logs=live.logs[-500:])
        except Exception as e:  # shown as the error state on the Run screen
            live.state, live.error = "error", str(e)[:1000]
            live.log(f"Run failed: {str(e).splitlines()[0] if str(e) else e!r}")
        live.finished = time.time()
        view = live.view()
        if live.result:
            saved = saved_view(Path(live.result.output_dir))
            if saved:
                view = {**saved, "logs": live.logs, "state": live.state, "ticket": o.get("ticket", "")}
        bus.publish({"type": "run", "run": view})

    def stop(self, run_id: str) -> bool:
        live = self.live.get(run_id)
        if not live or not live.runner or live.state != "running":
            return False
        live.runner.cancel()
        return True

    def get(self, run_id: str) -> Optional[dict]:
        live = self.live.get(run_id)
        if live and live.state == "running":
            return live.view()
        view = saved_view(RUNS_DIR / run_id)
        if view is None and live:  # an error before the Runner wrote anything
            return live.view()
        return view

    def all(self) -> list[dict]:
        out = []
        if RUNS_DIR.exists():
            for d in RUNS_DIR.iterdir():
                v = saved_view(d, full=False) if d.is_dir() else None
                if v:
                    out.append(v)
        out += [l.view() | {"findings": [], "logs": []} for l in self.live.values() if l.state == "running"]
        return sorted(out, key=lambda r: r["started"], reverse=True)

    def publish(self, run_id: str) -> dict:
        run_dir = RUNS_DIR / run_id
        result = result_from_json(run_dir / "result.json")
        outcomes = integrations.publish(result, load_settings(), log=lambda m: None)
        ok = bool(outcomes) and not all(v.startswith("error") for v in outcomes.values())
        if ok:
            _save_sidecar(run_dir, published=True)
        return outcomes

    def create_jira(self, run_id: str, finding_id: str) -> str:
        run_dir = RUNS_DIR / run_id
        result = result_from_json(run_dir / "result.json")
        idx = int(finding_id.split("-")[1]) - 1
        if not 0 <= idx < len(result.findings):
            raise KeyError(finding_id)
        side = _sidecar(run_dir)
        keys = side.get("jira", {})
        if finding_id in keys:
            return keys[finding_id]
        cfg = load_settings().get("jira", {})
        missing = [k for k in ("base_url", "email", "api_token", "project_key") if not str(cfg.get(k, "")).strip()]
        if missing:
            raise ValueError("Set up Jira on the Integrations screen first (" + ", ".join(missing) + " missing)")
        key = jira_api.create_for_finding(cfg, result.findings[idx], result)
        _save_sidecar(run_dir, jira={**keys, finding_id: key})
        return key

