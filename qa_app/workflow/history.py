"""Every ticket test run, kept on disk: what ran, where, what passed and failed, and the evidence.

One folder per run under <root> (live and demo runs have separate roots), plus index.json with one summary line per
run so History and Reports can list and chart runs without opening every folder.

  <root>/<KEY>-<YYYYMMDD-HHMMSS>/run.json        the full record
                                 /artifacts/      screenshots, videos, traces (Playwright outputDir)
                                 /report/         Playwright HTML report
                                 /spec/           copies of the spec files that ran
                                 events.jsonl, results.json, playwright.config.ts, yourqa-reporter.js
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .models import Ticket

RESULTS = ("pass", "partial", "fail", "blocked", "nt")
TRIGGERS = {"first": "First run", "rerun_gate2": "Rerun at Gate 2", "rerun_chat": "Rerun from the chat",
            "after_env_change": "After an environment change", "redo": "After redoing step 1"}
EVIDENCE_DIRS = ("artifacts", "report")


def _write(path: Path, data: Any) -> None:
    """Atomic JSON write: never leaves a half-written file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def counts(items: list[dict]) -> dict[str, int]:
    c = {k: 0 for k in RESULTS}
    for i in items:
        c[i.get("result", "nt") if i.get("result", "nt") in c else "nt"] += 1
    return c


def status_of(c: dict[str, int], error: str = "") -> str:
    """passed only when every check passed; any other outcome of a run that ended is failed."""
    if error:
        return "error"
    return "passed" if sum(c.values()) and c["pass"] == sum(c.values()) else "failed"


def _items(t: Ticket) -> list[dict]:
    out, n = [], 0
    for s in t.checklist:
        for i in s.items:
            n += 1
            out.append({"n": n, "section": s.name, "text": i.text, "result": i.result, "bug": i.bug,
                        "severity": i.severity, "error": "", "attachments": []})
    return out


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ paths
    def dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id or ""):
            raise KeyError(run_id)
        return self.root / run_id

    @property
    def index_path(self) -> Path:
        return self.root / "index.json"

    # ------------------------------------------------------------------ index
    def _index(self) -> list[dict]:
        p = self.index_path
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except ValueError:
                pass
        return self.rebuild_index()

    def rebuild_index(self) -> list[dict]:
        rows = []
        if self.root.exists():
            for d in self.root.iterdir():
                f = d / "run.json"
                if d.is_dir() and f.exists():
                    try:
                        rows.append(self._summary(json.loads(f.read_text(encoding="utf-8"))))
                    except ValueError:
                        continue
        rows.sort(key=lambda r: r.get("started", 0), reverse=True)
        if self.root.exists():
            _write(self.index_path, rows)
        return rows

    @staticmethod
    def _summary(rec: dict) -> dict:
        keys = ("id", "key", "title", "project", "type", "issue_type", "run_no", "trigger", "mode", "started",
                "finished", "duration_s", "status", "evidence_kept", "spec_hash")
        out = {k: rec.get(k) for k in keys}
        out["env_url"] = (rec.get("env") or {}).get("url", "")
        out["counts"] = rec.get("counts") or counts(rec.get("items", []))
        out["cost"] = rec.get("cost")
        return out

    def _put(self, rec: dict) -> None:
        with self._lock:
            _write(self.dir(rec["id"]) / "run.json", rec)
            rows = [r for r in self._index() if r.get("id") != rec["id"]]
            rows.append(self._summary(rec))
            rows.sort(key=lambda r: r.get("started", 0), reverse=True)
            _write(self.index_path, rows)

    # ------------------------------------------------------------------ recording
    def start(self, t: Ticket, trigger: str, mode: str, project: str = "", account: str = "",
              spec_files: Optional[list[Path]] = None, now: Optional[float] = None) -> str:
        now = now or time.time()
        base = f"{t.key}-{datetime.fromtimestamp(now).strftime('%Y%m%d-%H%M%S')}"
        run_id, n = base, 1
        while self.dir(run_id).exists():
            n += 1
            run_id = f"{base}-{n}"
        d = self.dir(run_id)
        (d / "spec").mkdir(parents=True, exist_ok=True)
        h = hashlib.sha1()
        for f in spec_files or []:
            if Path(f).exists():
                shutil.copy2(f, d / "spec" / Path(f).name)
                h.update(Path(f).read_bytes())
        rec = {"id": run_id, "key": t.key, "title": t.title, "project": project, "type": t.type, "issue_type": t.issue_type,
               "run_no": len(self.runs_for(t.key)) + 1, "trigger": trigger if trigger in TRIGGERS else "first", "mode": mode,
               "env": t.env.model_dump() if t.env else {}, "account": account, "started": now, "finished": None,
               "duration_s": None, "status": "running", "error": "", "exit_code": None, "items": _items(t),
               "cleanup": [], "skills": dict(t.skills), "usage": [], "cost": None, "evidence_kept": True,
               "spec_hash": h.hexdigest()[:12] if spec_files else ""}
        for i in rec["items"]:  # nothing has run yet
            i.update(result="nt", bug="", severity=None)
        rec["counts"] = counts(rec["items"])
        self._put(rec)
        return run_id

    def item_result(self, run_id: str, n: int, result: str, error: str = "", attachments: Optional[list[dict]] = None) -> None:
        """One check finished (live, while Playwright runs)."""
        with self._lock:
            rec = self.get(run_id)
            for i in rec["items"]:
                if i["n"] == n:
                    i["result"] = result if result in RESULTS else "nt"
                    i["error"] = error[:2000]
                    if attachments is not None:
                        i["attachments"] = attachments
            rec["counts"] = counts(rec["items"])
            self._put(rec)

    def finish(self, run_id: str, t: Ticket, *, cleanup: Optional[list] = None, exit_code: Optional[int] = None,
               errors: Optional[dict] = None, attachments: Optional[dict] = None, usage: Optional[list] = None,
               now: Optional[float] = None) -> dict:
        """The run ended: results come from the ticket's checklist (what the board shows)."""
        with self._lock:
            rec = self.get(run_id)
            now = now or time.time()
            prev = {i["n"]: i for i in rec["items"]}
            items = _items(t)
            for i in items:
                old = prev.get(i["n"], {})
                i["error"] = (errors or {}).get(i["n"]) or old.get("error", "")
                i["attachments"] = (attachments or {}).get(i["n"]) or old.get("attachments", [])
            rec.update(items=items, counts=counts(items), finished=now, duration_s=round(now - rec["started"], 1),
                       exit_code=exit_code, cleanup=[c.model_dump() if hasattr(c, "model_dump") else c for c in cleanup or []],
                       skills=dict(t.skills), usage=usage or [])
            rec["cost"] = round(sum(float(u.get("cost") or 0) for u in rec["usage"]), 4) if rec["usage"] else None
            rec["status"] = status_of(rec["counts"])
            self._put(rec)
            return rec

    def fail(self, run_id: str, message: str, now: Optional[float] = None, status: str = "error") -> dict:
        with self._lock:
            rec = self.get(run_id)
            now = now or time.time()
            rec.update(status=status, error=(message or "")[:2000], finished=now, duration_s=round(now - rec["started"], 1))
            self._put(rec)
            return rec

    def close_unfinished(self, message: str = "The app stopped before this run finished") -> list[str]:
        """After a restart: runs still marked running are closed as stopped."""
        done = []
        for r in self._index():
            if r.get("status") == "running":
                try:
                    self.fail(r["id"], message, status="stopped")
                    done.append(r["id"])
                except (KeyError, FileNotFoundError, ValueError):
                    continue
        return done

    # ------------------------------------------------------------------ reading
    def get(self, run_id: str) -> dict:
        f = self.dir(run_id) / "run.json"
        if not f.exists():
            raise KeyError(run_id)
        return json.loads(f.read_text(encoding="utf-8"))

    def list(self, q: str = "", key: str = "", project: str = "", type_: str = "", status: str = "", env: str = "",
             since: Optional[float] = None, until: Optional[float] = None) -> list[dict]:
        ql = q.strip().lower()
        out = []
        for r in self._index():
            if ql and ql not in f"{r.get('key', '')} {r.get('title', '')}".lower():
                continue
            if key and r.get("key") != key:
                continue
            if project and r.get("project") != project:
                continue
            if type_ and (r.get("type") or "") != type_:
                continue
            if status and r.get("status") != status:
                continue
            if env and env not in (r.get("env_url") or ""):
                continue
            if since and (r.get("started") or 0) < since:
                continue
            if until and (r.get("started") or 0) > until:
                continue
            out.append(r)
        return out

    def runs_for(self, key: str) -> list[dict]:
        """Runs of one ticket, oldest first."""
        return sorted((r for r in self._index() if r.get("key") == key), key=lambda r: r.get("started", 0))

    def previous(self, run_id: str) -> Optional[str]:
        rec = self.get(run_id)
        older = [r for r in self.runs_for(rec["key"]) if r.get("started", 0) < rec["started"]]
        return older[-1]["id"] if older else None

    # ------------------------------------------------------------------ compare
    def compare(self, a_id: str, b_id: str) -> dict:
        """b against a (a = the earlier run). Checks matched by their text."""
        a, b = self.get(a_id), self.get(b_id)
        if a["key"] != b["key"]:
            raise ValueError("Only runs of the same ticket can be compared")
        if a["started"] > b["started"]:
            a, b = b, a
        before = {norm(i["text"]): i for i in a["items"]}
        after = {norm(i["text"]): i for i in b["items"]}
        bad = {"fail", "partial", "blocked"}
        rows, tally = [], {"fixed": 0, "newly_failing": 0, "still_failing": 0, "unchanged": 0, "added": 0, "removed": 0}
        for k, i in after.items():
            o = before.get(k)
            if not o:
                tag = "added"
            elif o["result"] in bad and i["result"] == "pass":
                tag = "fixed"
            elif o["result"] != "fail" and i["result"] == "fail" or (o["result"] == "pass" and i["result"] in bad):
                tag = "newly_failing"
            elif o["result"] in bad and i["result"] in bad:
                tag = "still_failing"
            else:
                tag = "unchanged"
            tally[tag] += 1
            rows.append({"text": i["text"], "section": i["section"], "before": o["result"] if o else None,
                         "after": i["result"], "tag": tag, "n_after": i["n"], "n_before": o["n"] if o else None})
        for k, o in before.items():
            if k not in after:
                tally["removed"] += 1
                rows.append({"text": o["text"], "section": o["section"], "before": o["result"], "after": None,
                             "tag": "removed", "n_after": None, "n_before": o["n"]})
        return {"a": self._summary(a), "b": self._summary(b), "rows": rows, "tally": tally,
                "env_changed": (a.get("env") or {}).get("url") != (b.get("env") or {}).get("url"),
                "spec_changed": bool(a.get("spec_hash") and b.get("spec_hash") and a["spec_hash"] != b["spec_hash"])}

    # ------------------------------------------------------------------ evidence
    def evidence_bytes(self) -> int:
        total = 0
        if self.root.exists():
            for d in self.root.iterdir():
                for sub in EVIDENCE_DIRS:
                    for f in (d / sub).rglob("*") if (d / sub).exists() else []:
                        if f.is_file():
                            total += f.stat().st_size
        return total

    def prune_evidence(self, key: str, keep: int) -> list[str]:
        """Keep evidence for the newest `keep` runs of a ticket; older runs keep their results."""
        pruned = []
        runs = [r for r in self.runs_for(key) if r.get("evidence_kept", True)]
        for r in runs[:-keep] if keep > 0 else runs:
            d = self.dir(r["id"])
            for sub in EVIDENCE_DIRS:
                shutil.rmtree(d / sub, ignore_errors=True)
            rec = self.get(r["id"])
            rec["evidence_kept"] = False
            for i in rec["items"]:
                i["attachments"] = []
            self._put(rec)
            pruned.append(r["id"])
        return pruned

    def file(self, run_id: str, rel: str) -> Path:
        """A file inside a run folder (evidence, report). Raises KeyError outside it."""
        base = self.dir(run_id).resolve()
        p = (base / rel).resolve()
        if base not in p.parents or not p.is_file():
            raise KeyError(rel)
        return p
