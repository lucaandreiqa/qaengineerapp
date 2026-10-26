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


def added_lines(before: str, after: str) -> list[str]:
    """The lines a skill gained, for the summary (blank lines left out)."""
    old = {l.strip() for l in before.splitlines()}
    return [l for l in after.splitlines() if l.strip() and l.strip() not in old][:80]


class Onboarding:
    def __init__(self, sources: Callable[[], dict]) -> None:
        """sources() -> {"cfg": WorkflowConfig, "tracker": client|None, "testrail": settings|None, "confluence": reader|None}"""
        self.sources = sources
        self.task: Optional[asyncio.Task] = None
        self.lines: list[str] = []
        self.progress = {"percent": 0, "text": "", "started": None, "done": 0, "total": 0, "phase": ""}
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
        if last:  # a source or Claude call that failed, in plain words with where to fix it
            from ..integrations import failures
            svc = {"tracker": failures.tracker(), "testrail": "testrail", "confluence": "confluence"}
            last["source_info"] = {k: failures.explain(str(v)[len("failed:"):].strip(), svc.get(k), "read it")
                                   for k, v in (last.get("sources") or {}).items() if str(v).startswith("failed")}
            last["failed_info"] = {k: failures.explain(str(v), "claude", "study it") for k, v in (last.get("failed") or {}).items()}
        if last and last.get("status") == "finished":  # how each step's skill changed, to accept or revert
            fin = self._finish_record(d)
            last["finish"] = {"merged": [{k: v for k, v in m.items() if k not in ("before", "after")} for m in fin.get("merged", [])],
                              "projects": fin.get("projects", [])}
        if last and last.get("status") in ("done", "finished") and self.progress["percent"] < 100 and not self._busy():
            self.progress = {**self.progress, "percent": 100}
        return {"running": self._busy() and self.progress["phase"] == "study", "finishing": self._busy() and self.progress["phase"] == "finish",
                "lines": self.lines[-200:], "last": last, "progress": {k: self.progress[k] for k in ("percent", "text", "started", "phase")},
                "undecided": apply.undecided(d) if d else 0, "finished": bool(config.load_settings().get("app", {}).get("onboarding_done"))}

    def _busy(self) -> bool:
        return bool(self.task and not self.task.done())

    # ---------------------------------------------------------------------- progress
    def _progress_start(self, phase: str, total: int, text: str) -> None:
        self.progress = {"percent": 0, "text": text, "started": time.time(), "done": 0, "total": max(1, total), "phase": phase}
        self._emit("progress", percent=0, text=text)

    def _tick(self, text: str = "", units: int = 1) -> None:
        p = self.progress
        p["done"] += units
        if p["done"] >= p["total"]:  # the estimate was low: grow it so the bar never reaches 100 early
            p["total"] = p["done"] + 1
        pct = max(p["percent"], min(99, int(p["done"] * 100 / p["total"])))
        p["percent"], p["text"] = pct, text or p["text"]
        self._emit("progress", percent=pct, text=p["text"])

    def _retotal(self, remaining: int) -> None:
        self.progress["total"] = max(self.progress["done"] + max(1, remaining), 1)

    def _progress_end(self, text: str) -> None:
        self.progress.update(percent=100, text=text)
        self._emit("progress", percent=100, text=text)

    # ---------------------------------------------------------------------- the run
    def _emit(self, event: str, **data) -> None:
        if event == "line":
            self.lines.append(data.get("text", ""))
        bus.publish({"type": "onboarding", "event": event, **data})

    async def study(self, choices: dict) -> str:
        if self._busy():
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
        config.save_section("app", {"onboarding_done": False})  # a new study brings the Onboarding screen back
        mcp_ids = [x for x in choices.get("mcp") or [] if x]
        has = {"tracker": src.get("tracker") is not None and bool(projects), "testrail": bool(src.get("testrail")),
               "confluence": src.get("confluence") is not None, "repo": bool(str(choices.get("repo") or "").strip())}
        # The estimate: one unit per project and source read, then every Claude call (about 4 ticket batches per project).
        estimate = (len(projects) if has["tracker"] else 0) + sum(has[k] for k in ("testrail", "confluence", "repo")) \
            + (3 if mcp_ids else 0) + (len(projects) * 5 if has["tracker"] else 0) + sum(has[k] for k in ("testrail", "repo")) + 1
        self._progress_start("study", estimate, "Starting")
        loop = asyncio.get_running_loop()

        async def grab(name: str, label: str, fn, describe, units: int = 1) -> None:
            self._emit("progress", source=name, status="reading", text=f"Reading {label}", percent=self.progress["percent"])
            try:
                data = await asyncio.to_thread(fn)
            except Exception as e:
                summary["sources"][name] = f"failed: {(str(e).splitlines() or ['error'])[0][:240]}"
                self._emit("line", text=f"{label}: {summary['sources'][name]}")
                self._tick(units=units)
                return
            collected[name] = data
            (run_dir / "collected").mkdir(parents=True, exist_ok=True)
            (run_dir / "collected" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            summary["sources"][name] = describe(data)
            self._emit("line", text=summary["sources"][name])
            self._save_summary(run_dir, summary)
            if name != "tracker":  # the tracker ticks once per project as it reads
                self._tick(summary["sources"][name], units=units)

        try:
            if src.get("tracker") is not None and projects:
                def read_project(project: str, count: int) -> None:
                    loop.call_soon_threadsafe(self._tick, f"Read {count} tickets from {project}")
                await grab("tracker", "tickets", lambda: collect.collect_tracker(src["tracker"], projects, 200, on_project=read_project),
                           lambda d: f"Read {len(d['tickets'])} tickets from {', '.join(projects)}")
                await asyncio.sleep(0)  # let the per-project ticks land
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
            servers = [x for x in choices.get("mcp") or [] if x]
            if servers:
                await self._study_mcp(cfg, servers, collected, summary, run_dir)

            async def apply_area(area: str, result: dict) -> None:
                changes = apply.plan({area: result}, projects)
                done = apply.apply(changes, run_dir / "areas" / area, self.company)
                all_changes = apply.load(run_dir) + done
                apply.save_changes(run_dir, all_changes)
                self._emit("line", text=f"Applied {len(done)} change{'s' if len(done) != 1 else ''} from {area}")

            self._retotal(analyze.count_calls(collected))
            last_line = {"text": "Studying"}

            def on_event(kind: str, text: str) -> None:
                if kind == "line":
                    last_line["text"] = text
                self._emit("line", text=text)
            findings = await analyze.analyze(cfg, collected, on_event, on_area=apply_area,
                                             on_step=lambda: self._tick(last_line["text"]))
            summary["failed"] = findings.get("failed") or {}
            summary["status"] = "done"
            self._progress_end("Done. Keep or undo each change, then finish onboarding.")
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

    async def _study_mcp(self, cfg, servers: list[str], collected: dict, summary: dict, run_dir: Path) -> None:
        """Claude picks read calls on the chosen MCP servers; YourQA runs them (confirmed read tools only)."""
        from ..integrations import mcp_servers
        catalog = [c for c in mcp_servers.catalog() if c["server"] in servers]
        if not catalog:
            summary["sources"]["mcp"] = "failed: no confirmed read tools on the chosen servers"
            self._emit("line", text="MCP servers: " + summary["sources"]["mcp"])
            return
        self._emit("progress", source="mcp", status="reading", text="Reading the MCP servers", percent=self.progress["percent"])
        tickets = (collected.get("tracker") or {}).get("tickets") or []
        context = "\n".join(f"- {t.get('title')}" for t in tickets[:40])
        try:
            calls = await analyze.plan_mcp(cfg, catalog, context, lambda kind, text: self._emit("line", text=text))
        except Exception as e:
            summary["sources"]["mcp"] = f"failed: {(str(e).splitlines() or ['error'])[0][:240]}"
            self._tick(units=3)
            return
        self._tick("Chose what to read from the MCP servers")
        results = []
        for server, tool, args in calls:
            try:
                text = await asyncio.to_thread(mcp_servers.call_read, server, tool, args)
                results.append({"server": server, "tool": tool, "args": args, "text": text})
                self._emit("line", text=f"Read {tool} on {server}")
            except Exception as e:
                self._emit("line", text=f"{server} {tool}: {(str(e).splitlines() or ['error'])[0][:200]}")
        self._tick(f"Read {len(results)} results from the MCP servers", units=2)
        collected["mcp"] = {"results": results}
        (run_dir / "collected").mkdir(parents=True, exist_ok=True)
        (run_dir / "collected" / "mcp.json").write_text(json.dumps(collected["mcp"], ensure_ascii=False, indent=1), encoding="utf-8")
        summary["sources"]["mcp"] = f"Read {len(results)} result{'s' if len(results) != 1 else ''} from {', '.join(servers)}"
        self._emit("line", text=summary["sources"]["mcp"])
        self._save_summary(run_dir, summary)

    # ---------------------------------------------------------------------- keep / undo
    def _open_dir(self, change_id: str = "") -> Path:
        d = self._last_dir()
        if not d or self._summary(d).get("status") == "finished":  # finished: the changes are final
            raise KeyError(change_id)
        return d

    def undo(self, change_id: str) -> str:
        return apply.undo(self._open_dir(change_id), change_id, self.company)

    def undo_all(self) -> dict:
        try:
            return apply.undo_all(self._open_dir(), self.company)
        except KeyError:
            return {"undone": 0}

    def keep(self, change_id: str) -> str:
        return apply.keep(self._open_dir(change_id), change_id)

    def keep_all(self) -> int:
        return apply.keep_all(self._open_dir())

    # ---------------------------------------------------------------------- after finishing: accept or revert each skill update
    @staticmethod
    def _finish_record(d: Path) -> dict:
        try:
            return json.loads((d / "finish.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _merge(self, node: str) -> tuple[Path, dict, dict]:
        d = self._last_dir()
        fin = self._finish_record(d) if d else {}
        m = next((x for x in fin.get("merged", []) if x.get("node") == node), None)
        if not m:
            raise KeyError(node)
        return d, fin, m

    def _save_finish(self, d: Path, fin: dict) -> None:
        (d / "finish.json").write_text(json.dumps(fin, indent=1, ensure_ascii=False), encoding="utf-8")

    def accept_merge(self, node: str) -> str:
        d, fin, m = self._merge(node)
        if m.get("state") == "reverted":
            return "already reverted"
        m["state"] = "accepted"
        self._save_finish(d, fin)
        return "accepted"

    def revert_merge(self, node: str) -> str:
        """The personal skill back to how it was before Finish (the general one, if it had no personal version); only
        while it still holds what Finish wrote ('changed since' otherwise, and it stays)."""
        from ..workflow import skills
        d, fin, m = self._merge(node)
        if m.get("state") == "reverted":
            return "already reverted"
        if (skills.personal(node) or "").strip() != m["after"].strip():
            return "changed since"
        if m.get("before_file"):
            skills.save_personal(node, m["before"])
        else:
            skills.reset_personal(node)
        m["state"] = "reverted"
        self._save_finish(d, fin)
        return "reverted"

    # ---------------------------------------------------------------------- finish
    async def finish(self) -> None:
        """Every change kept or undone: the personal skills are built from the general ones and the kept lessons, the
        studied projects switch to them, the run becomes final, and the Onboarding screen is hidden (a new study brings
        it back)."""
        if self._busy():
            raise OnboardingBusy("Onboarding is busy. Wait for it to finish.")
        d = self._last_dir()
        if not d or self._summary(d).get("status") not in ("done", "stopped"):
            raise OnboardingBusy("Finish a study first.")
        left = apply.undecided(d)
        if left:
            raise OnboardingBusy(f"Keep or undo every change first ({left} left).")
        self.task = asyncio.ensure_future(self._finish(d))
        await self.task

    async def _finish(self, d: Path) -> None:
        """Personal skills: a copy of the general tree (an existing personal tree is kept and built on), with every
        skill under a step that has kept lessons improved by one Claude pass per step. The general tree never changes."""
        from ..workflow import skills
        cfg = self.sources()["cfg"]
        kept = [c for c in apply.load(d) if c["kind"] == "skill" and c.get("kept") and not c.get("undone")]
        steps: dict[str, list[dict]] = {}
        for c in kept:
            steps.setdefault(c["target"].split("/", 1)[1], []).append(c)
        self._progress_start("finish", len(steps) + 1, "Building your personal skills")
        had_files = {n for n in skills.NODE_IDS if (skills.personal_dir() / f"{n}.md").exists()}
        skills.create_personal()
        self._tick("Copied the general skills into your personal skills")
        knowledge = (self.company / "knowledge.md").read_text(encoding="utf-8") if (self.company / "knowledge.md").exists() else ""
        profile = (self.company / "profile.json").read_text(encoding="utf-8") if (self.company / "profile.json").exists() else ""
        summary = self._summary(d)
        merged, failed = [], {}
        for step, cs in steps.items():
            label = f"{apply.STEP_LABELS.get(step, step)} skills"
            texts: dict[str, list[str]] = {}
            for c in cs:  # the same text for several projects is used once
                texts.setdefault(c["after"].strip(), []).append(c["target"].split("/", 1)[0])
            learned = "\n\n".join(t if len(texts) == 1 else f"In {', '.join(ps)}:\n{t}" for t, ps in texts.items())
            nodes = {n: {"name": skills.NODES[n]["name"], "text": skills.personal(n) or skills.general(n)} for n in skills.branch(step)}
            try:
                improved = await analyze.improve(cfg, step, nodes, learned, knowledge, profile if step == "create-tests" else "")
            except Exception as e:  # what was kept goes into the step's own skill as it is
                failed[step] = (str(e).splitlines() or ["error"])[0][:200]
                improved = {step: nodes[step]["text"].rstrip() + "\n\n## Your team's way\n\n" + learned}
            projects_from = sorted({c["target"].split("/", 1)[0] for c in cs})
            for node, after in improved.items():
                before = nodes[node]["text"]
                if after.strip() == before.strip():
                    continue
                skills.save_personal(node, after)
                merged.append({"node": node, "step": step, "name": skills.NODES[node]["name"],
                               "step_name": apply.STEP_LABELS.get(step, step), "from": projects_from,
                               "added": added_lines(before, after), "before": before, "before_file": node in had_files,
                               "after": after, "state": "pending", "fallback": step in failed})
            self._emit("line", text=f"Improved the {label} with what was learnt")
            self._tick(f"Improved the {label} with what was learnt")
        projects = sorted({p for p in (summary.get("choices") or {}).get("projects") or [] if skills.KEY_RE.match(str(p))}
                          | {c["target"].split("/", 1)[0] for c in kept if skills.KEY_RE.match(c["target"].split("/", 1)[0])})
        for p in projects:
            skills.set_choice(p, "personal")
        (d / "finish.json").write_text(json.dumps({"at": time.time(), "merged": merged, "failed": failed, "projects": projects},
                                                  indent=1, ensure_ascii=False), encoding="utf-8")
        summary.update(status="finished", finished_at=time.time(), merge_failed=failed, personal_for=projects)
        self._save_summary(d, summary)
        config.save_section("app", {"onboarding_done": True})
        self._progress_end("Onboarding finished")
        self._emit("done", status="finished", id=summary.get("id"))
