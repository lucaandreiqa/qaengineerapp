"""A study run: collect from each connected source, analyse area by area, apply each area as it finishes, report.

Progress is published on the event bus as {"type": "onboarding", "event": "line" | "progress" | "done", ...}. One
study at a time; Stop keeps the areas already applied. Everything a run read and decided is kept in
<company>/onboarding/<run>/ (collected/*.json, summary.json, changes.json).
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from .. import config
from ..workflow.store import bus
from . import analyze, apply, collect


class OnboardingBusy(Exception):
    pass


class Onboarding:
    def __init__(self, sources: Callable[[], dict]) -> None:
        """sources() -> {"cfg": WorkflowConfig, "tracker": client|None, "testrail": settings|None, "confluence": reader|None}"""
        self.sources = sources
        self.task: Optional[asyncio.Task] = None
        self.lines: list[str] = []
        for d in self._runs():  # a run the app didn't finish (restart, crash) is stopped, its applied parts kept
            s = self._summary(d)
            if s.get("status") == "running":
                s["status"] = "stopped"
                self._save_summary(d, s)

    # ---------------------------------------------------------------------- files
    @property
    def company(self) -> Path:
        return config.company_dir()

    def _runs(self) -> list[Path]:
        root = self.company / "onboarding"
        return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: self._summary(p).get("started", 0)) if root.exists() else []

    @staticmethod
    def _summary(run_dir: Path) -> dict:
        try:
            return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _save_summary(run_dir: Path, s: dict) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "summary.json").write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")

    def _last_dir(self) -> Optional[Path]:
        runs = self._runs()
        return runs[-1] if runs else None

    # ---------------------------------------------------------------------- state for the screen
    def state(self) -> dict:
        d = self._last_dir()
        last = None
        if d:
            last = {**self._summary(d), "changes": [
                {k: c.get(k) for k in ("id", "kind", "target", "label", "area", "evidence", "replaced_edit", "undone")}
                for c in apply.load(d)]}
        return {"running": bool(self.task and not self.task.done()), "lines": self.lines[-200:], "last": last}

    # ---------------------------------------------------------------------- the run
    def _emit(self, event: str, **data) -> None:
        if event == "line":
            self.lines.append(data.get("text", ""))
        bus.publish({"type": "onboarding", "event": event, **data})

    async def study(self, choices: dict) -> str:
        if self.task and not self.task.done():
            raise OnboardingBusy("A study is already running.")
        self.task = asyncio.ensure_future(self._study(choices))
        return await self.task

    def stop(self) -> bool:
        if self.task and not self.task.done():
            self.task.cancel()
            return True
        return False

    async def _study(self, choices: dict) -> str:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        run_dir = self.company / "onboarding" / run_id
        projects = [p for p in choices.get("projects") or [] if p]
        summary = {"id": run_id, "started": time.time(), "status": "running", "choices": choices, "sources": {}, "failed": {}}
        self._save_summary(run_dir, summary)
        self.lines = []
        src = self.sources()
        cfg = src["cfg"]
        collected: dict = {}

        async def grab(name: str, label: str, fn, describe) -> None:
            self._emit("progress", source=name, status="reading", text=f"Reading {label}")
            try:
                data = await asyncio.to_thread(fn)
            except Exception as e:
                summary["sources"][name] = f"failed: {(str(e).splitlines() or ['error'])[0][:240]}"
                self._emit("line", text=f"{label}: {summary['sources'][name]}")
                return
            collected[name] = data
            (run_dir / "collected").mkdir(parents=True, exist_ok=True)
            (run_dir / "collected" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            summary["sources"][name] = describe(data)
            self._emit("line", text=summary["sources"][name])
            self._save_summary(run_dir, summary)

        try:
            if src.get("tracker") is not None and projects:
                await grab("tracker", "tickets", lambda: collect.collect_tracker(src["tracker"], projects, 200),
                           lambda d: f"Read {len(d['tickets'])} tickets from {', '.join(projects)}")
            else:
                summary["sources"]["tracker"] = "not connected"
            if src.get("testrail"):
                await grab("testrail", "TestRail", lambda: collect.collect_testrail(src["testrail"], 150),
                           lambda d: f"Read {len(d['cases'])} TestRail cases in {len(d['sections'])} sections")
            else:
                summary["sources"]["testrail"] = "not connected"
            if src.get("confluence") is not None:
                texts = [t.get("description", "") + " " + " ".join(t.get("comments") or [])
                         for t in (collected.get("tracker") or {}).get("tickets", [])]
                await grab("confluence", "Confluence", lambda: collect.collect_confluence(src["confluence"], texts, choices.get("spaces") or [], 30),
                           lambda d: f"Read {len(d['pages'])} Confluence pages")
            else:
                summary["sources"]["confluence"] = "not connected"
            if str(choices.get("repo") or "").strip():
                await grab("repo", "the automation repo", lambda: collect.collect_repo(choices["repo"], self.company / "repos"),
                           lambda d: f"Read the automation repo: {len(d['tree'])} files, {len(d['files'])} studied")
            else:
                summary["sources"]["repo"] = "not given"

            async def apply_area(area: str, result: dict) -> None:
                changes = apply.plan({area: result}, projects)
                done = apply.apply(changes, run_dir / "areas" / area, self.company)
                all_changes = apply.load(run_dir) + done
                apply.save_changes(run_dir, all_changes)
                self._emit("line", text=f"Applied {len(done)} change{'s' if len(done) != 1 else ''} from {area}")

            findings = await analyze.analyze(cfg, collected, lambda kind, text: self._emit("line", text=text), on_area=apply_area)
            summary["failed"] = findings.get("failed") or {}
            summary["status"] = "done"
        except asyncio.CancelledError:
            summary["status"] = "stopped"
            raise
        except Exception as e:
            summary["status"] = "error"
            summary["error"] = (str(e).splitlines() or ["error"])[0][:300]
        finally:
            summary["finished"] = time.time()
            self._save_summary(run_dir, summary)
            self._emit("done", status=summary["status"], id=run_id)
        return run_id

    # ---------------------------------------------------------------------- undo
    def undo(self, change_id: str) -> str:
        d = self._last_dir()
        if not d:
            raise KeyError(change_id)
        return apply.undo(d, change_id, self.company)

    def undo_all(self) -> dict:
        d = self._last_dir()
        return apply.undo_all(d, self.company) if d else {"undone": 0}
