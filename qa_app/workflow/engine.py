"""The gated QA workflow: five lanes, four review gates, background work between them.

Rules enforced here (not just in the UI):
- Every action names the state the user saw; if the ticket moved on, the action is rejected.
  So no approval can carry over to the next gate.
- Posting the comment never approves the transition; each is its own action.
- Checklist results only change through a run. Before that every item is NOT TESTED.
- Cleanup is recorded as part of the run, before gate 2.
- Jira transitions are matched by exact name only; otherwise the available ones are returned.
- A TestRail push is verified with get_cases, and a retry verifies first and only adds what is missing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Optional

from ..config import load_settings
from . import agent, sso
from .clients import MockJira, MockTestRail, RealJira, RealTestRail, normalise
from . import ticket_context
from .models import WORKING_SUBS, Env, Ticket, type_label
from .settings import WorkflowConfig
from .store import TicketStore, bus

log = logging.getLogger("qa.workflow")

# The single action each waiting state accepts.
ACTIONS: dict[tuple[int, str], str] = {
    (0, "blocked"): "use_env",
    (0, "gate"): "approve_checklist",
    (2, "sso"): "signed_in",
    (2, "gate"): "approve_results",
    (3, "comment"): "post_comment",
    (3, "transition"): "transition",
    (4, "gate"): "approve_draft",
    (4, "approved"): "push",
}


class GateError(Exception):
    def __init__(self, message: str, status: int = 409, extra: Optional[dict] = None) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra or {}


def now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")


class Workflow:
    """Demo and live mode keep separate ticket stores, so demo tickets never mix with real ones."""

    def __init__(self, demo_store: TicketStore, live_store: TicketStore, mock_jira: MockJira,
                 mock_testrail: Optional[MockTestRail] = None, cfg: Optional[WorkflowConfig] = None) -> None:
        self._cfg = cfg  # fixed config for tests; otherwise read from settings each time
        self.demo_store = demo_store
        self.live_store = live_store
        self.mock_jira = mock_jira
        self.mock_testrail = mock_testrail or MockTestRail()
        self.tasks: dict[str, asyncio.Task] = {}
        self.toast: Callable[[str], None] = lambda msg: bus.publish({"type": "toast", "message": msg})

    @property
    def cfg(self) -> WorkflowConfig:
        return self._cfg or WorkflowConfig.load()

    @property
    def tickets(self) -> TicketStore:
        return self.demo_store if self.cfg.is_mock else self.live_store

    # ---------------------------------------------------------------- clients
    def jira(self):
        if self.cfg.is_mock:
            return self.mock_jira
        s = load_settings()
        if s.get("jira", {}).get("auth") == "mcp":  # signed in with Atlassian (MCP)
            from ..integrations.atlassian_mcp import McpJira
            return McpJira(s.get("jira", {}), s.get("workflow", {}))
        return RealJira(s.get("jira", {}))

    def testrail(self):
        if self.cfg.is_mock:
            return self.mock_testrail
        return RealTestRail(load_settings().get("testrail", {}))

    async def _call(self, fn: Callable, *args: Any) -> Any:
        """Run a (blocking) client call off the event loop."""
        return await asyncio.to_thread(fn, *args)

    async def pause(self, seconds: float) -> None:
        if self.cfg.is_mock:
            await asyncio.sleep(seconds / max(self.cfg.mock_speed, 0.01))

    # ---------------------------------------------------------------- lifecycle
    def resume(self) -> None:
        """Restart background work for tickets that were mid-step when the app stopped."""
        for t in self.tickets.all():
            if t.sub in WORKING_SUBS and not t.error:
                self._spawn_for(t)

    def _spawn_for(self, t: Ticket) -> None:
        if t.stage == 0:
            self.spawn(t.key, self._gather(t.key))
        elif t.stage == 1:
            self.spawn(t.key, self._build_and_run(t.key))
        elif t.stage == 2:
            self.spawn(t.key, self._run(t.key))
        elif t.stage == 4:
            self.spawn(t.key, self._draft(t.key))

    def spawn(self, key: str, coro) -> None:
        old = self.tasks.get(key)
        if old and not old.done():
            old.cancel()

        async def guarded() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep the ticket where it is and show the error in the drawer
                log.exception("Background step failed for %s", key)
                if self.tickets.get(key):
                    self.tickets.patch(key, error=str(e)[:500])
                    self.toast(f"{key} stopped: {str(e)[:120]}")

        self.tasks[key] = asyncio.create_task(guarded())

    def patch(self, key: str, **fields: Any) -> Ticket:
        return self.tickets.patch(key, **fields)

    # ---------------------------------------------------------------- sync
    async def sync(self) -> list[str]:
        issues = await self._call(self.jira().search_column, self.cfg.jira_project, self.cfg.jira_column)
        new: list[Ticket] = []
        for i in issues:
            if i["key"] in self.tickets.tickets or i["key"] in self.tickets.done_keys:
                continue
            comps = list(i.get("components", []))
            t = Ticket(key=i["key"], title=i["title"], type=self.cfg.ticket_type(comps), components=comps, status=i.get("status", ""),
                       description=i.get("description", ""), stage=0, sub="working", doing="Gathering context from Jira")
            if self.cfg.is_mock:
                from .seed import late_ticket
                late = late_ticket()
                if late.key == t.key:  # mock checklist and expected results for the demo ticket
                    t = late.model_copy(update={"env": None, "status": t.status})
            new.append(t)
        if new:  # newest at the top of lane 1
            self.tickets.tickets = {**{t.key: t for t in new}, **self.tickets.tickets}
        self.tickets.last_sync = time.time()
        for t in new:
            self.tickets.put(t)
            self.spawn(t.key, self._gather(t.key))
        self.tickets.save()
        return [t.key for t in new]

    # ---------------------------------------------------------------- actions
    def expected_action(self, t: Ticket) -> Optional[str]:
        return ACTIONS.get((t.stage, t.sub))

    async def act(self, key: str, action: str, stage: int, sub: str, payload: Optional[dict] = None) -> Ticket:
        payload = payload or {}
        t = self.tickets.get(key)
        if not t:
            raise GateError(f"{key} is not on the board", 404)
        if action == "retry":
            if not t.error:
                raise GateError("Nothing to retry")
            self.patch(key, error="")
            self._spawn_for(self.tickets.get(key))  # type: ignore[arg-type]
            return self.tickets.get(key)  # type: ignore[return-value]
        if (t.stage, t.sub) != (stage, sub):
            raise GateError(f"{key} has moved on (now lane {t.stage + 1} · {t.sub}). Review it again before acting.")
        if action == "redo_gather":
            return await self._redo_gather(t, payload)
        expected = self.expected_action(t)
        if expected != action:
            raise GateError(f"{key} is waiting for '{expected or 'nothing'}', not '{action}'")
        return await getattr(self, f"_a_{action}")(t, payload)

    def save_draft(self, key: str, comment: Optional[str] = None, target: Optional[str] = None, env_draft: Optional[str] = None) -> Ticket:
        """Edits that are not approvals: the comment text and the chosen target state."""
        t = self.tickets.get(key)
        if not t:
            raise GateError(f"{key} is not on the board", 404)
        upd: dict[str, Any] = {}
        if comment is not None:
            if (t.stage, t.sub) != (3, "comment"):
                raise GateError("The comment can only be edited before it is posted")
            upd["comment"] = comment
        if target is not None:
            if (t.stage, t.sub) not in {(3, "comment"), (3, "transition")}:
                raise GateError("The target state can only be chosen at gate 3")
            if target and t.transitions and target not in t.transitions:
                raise GateError(f"'{target}' is not a transition Jira returned", extra={"transitions": t.transitions})
            upd["target"] = target
        return self.patch(key, **upd) if upd else t

    # States where step 1 can be done again: before anything about this pass reached Jira.
    REDO_GATHER_FROM = {(0, "gate"), (0, "blocked"), (2, "gate")}

    def can_redo_gather(self, t: Ticket) -> bool:
        return (t.stage, t.sub) in self.REDO_GATHER_FROM or (t.stage == 0 and bool(t.error))

    async def _redo_gather(self, t: Ticket, p: dict) -> Ticket:
        """Read the ticket again and rebuild environment, scenarios and checklist (it may have changed in Jira).
        Results of an earlier run are discarded; an environment the user picked is kept unless they ask otherwise."""
        if not self.can_redo_gather(t):
            if t.stage >= 3:
                raise GateError(f"The QA comment for {t.key} is already being posted to Jira, so step 1 can't be redone now.")
            raise GateError(f"{t.key} is busy in lane {t.stage + 1}. Wait until it stops at a review, then redo step 1.")
        keep_env = t.env if (t.env and t.env.source.startswith("you") and not p.get("refind_env")) else None
        checklist: list = []
        if self.cfg.is_mock:  # demo: keep the sample items (their simulated results are tied to them)
            from .models import CheckItem, Section
            checklist = [Section(name=s.name, items=[CheckItem(text=i.text) for i in s.items]) for s in t.checklist]
        t = self.patch(t.key, stage=0, sub="working", p1=0, error="", doing="Reading the ticket again",
                       env=keep_env, env_candidates=[], checklist=checklist, ran=False, cleanup=[], left="",
                       comment=None, comment_at="", target="", transitions=[], cases=[], dups=0)
        self.spawn(t.key, self._gather(t.key))
        self.toast(f"{t.key}: reading the ticket again" + (" (keeping the environment you chose)" if keep_env else ""))
        return t

    async def _a_use_env(self, t: Ticket, p: dict) -> Ticket:
        url = str(p.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            raise GateError("Enter the test environment URL, starting with https://", 422)
        picked = next((c for c in t.env_candidates if c.get("url") == url), None)
        t = self.patch(t.key, env=Env(kind="Test environment", url=url, source="you" + (f" · from {picked['source']}" if picked else ""),
                                      api="Chosen by you"), sub="working", p1=2, error="")
        self.spawn(t.key, self._gather(t.key))
        self.toast(f"Environment set for {t.key} · building scenarios and checklist")
        return t

    async def _a_approve_checklist(self, t: Ticket, p: dict) -> Ticket:
        t = self.patch(t.key, stage=1, sub="working", doing=f"Building {t.key}.spec.ts", error="")
        self.spawn(t.key, self._build_and_run(t.key))
        self.toast(f"Gate 1 approved · building and running {t.key}")
        return t

    async def _a_signed_in(self, t: Ticket, p: dict) -> Ticket:
        if not self.cfg.is_mock:
            ok = await sso.save_login(t.key, self.cfg.auth_dir)
            if not ok:
                raise GateError("No signed-in browser session was found. Sign in in the window that opened, then try again.")
        t = self.patch(t.key, stage=2, sub="working", error="")
        self.spawn(t.key, self._run(t.key))
        self.toast(f"SSO session ready · running {t.key}")
        return t

    async def _a_approve_results(self, t: Ticket, p: dict) -> Ticket:
        if not t.ran:
            raise GateError("These results did not come from a run")
        try:
            comment = await agent.write_comment(self.cfg, t)
            if self.cfg.anthropic_api_key and not self.cfg.is_mock:
                self._used(t.key, "jira-comment")
        except Exception:  # Claude unavailable: the template comment, still editable at gate 3
            log.exception("Comment drafting failed for %s", t.key)
            comment = agent.comment_text(t, self.cfg)
        t = self.patch(t.key, stage=3, sub="comment", comment=comment)
        self.toast(f"Gate 2 approved · comment drafted for {t.key}")
        return t

    async def _a_post_comment(self, t: Ticket, p: dict) -> Ticket:
        text = p.get("comment") if p.get("comment") is not None else (t.comment or agent.comment_text(t, self.cfg))
        if not str(text).strip():
            raise GateError("The comment is empty", 422)
        jira = self.jira()
        await self._call(jira.add_comment, t.key, text)
        transitions = [tr["name"] for tr in await self._call(jira.get_transitions, t.key)]
        target = t.target if t.target in transitions else ""
        t = self.patch(t.key, sub="transition", comment=text, comment_at=now_hhmm(), transitions=transitions, target=target)
        self.toast(f"Comment posted on {t.key} · the move needs its own approval")
        return t

    async def _a_transition(self, t: Ticket, p: dict) -> Ticket:
        target = str(p.get("target") or t.target or "")
        if not target:
            raise GateError("Choose a target state first", 422)
        jira = self.jira()
        available = await self._call(jira.get_transitions, t.key)
        tr = agent.exact_transition(available, target)
        names = [a["name"] for a in available]
        if not tr:
            self.patch(t.key, transitions=names, target="")
            raise GateError(f"'{target}' is not available for {t.key}. Available: {', '.join(names) or 'none'}",
                            extra={"transitions": names})
        status = await self._call(jira.transition, t.key, tr["id"])
        section = t.section or self._section_for(t)
        t = self.patch(t.key, stage=4, sub="drafting", status=status or target, section=section, error="")
        self.spawn(t.key, self._draft(t.key))
        self.toast(f"{t.key} moved to {target} · drafting TestRail cases")
        return t

    async def _a_approve_draft(self, t: Ticket, p: dict) -> Ticket:
        t = self.patch(t.key, sub="approved")
        self.toast(f"Draft approved for {t.key} · nothing pushed yet")
        return t

    async def _a_push(self, t: Ticket, p: dict) -> Ticket:
        tr = self.testrail()
        wanted = [c for c in t.cases]
        section_id = await self._call(tr.find_section, t.section)
        if section_id is not None:
            # Never add a case that is already there: covers cases created since the draft
            # and a previous push that partly landed. Verify before adding anything again.
            existing = {normalise(c["title"]) for c in await self._call(tr.get_cases, section_id)}
            wanted = [c for c in wanted if normalise(c.title) not in existing]
        if section_id is None:
            section_id = await self._call(tr.ensure_section, t.section)
        self.patch(t.key, push_attempted=True)
        ids: list[int] = list(t.pushed_case_ids)
        for c in wanted:
            ids.append(await self._call(tr.add_case, section_id, c.title, c.steps, c.expected))
            self.patch(t.key, pushed_case_ids=ids)
        present = {normalise(c["title"]) for c in await self._call(tr.get_cases, section_id)}
        missing = [c.title for c in t.cases if normalise(c.title) not in present]
        if missing:
            self.patch(t.key, error=f"Verification with get_cases found {len(t.cases) - len(missing)} of {len(t.cases)} cases. "
                                    f"Pushing again will only add the missing ones.")
            raise GateError(f"Push not verified: {len(missing)} cases missing in TestRail")
        self.tickets.finish(t.key)
        self.toast(f"{t.key} cases pushed to TestRail and verified · ticket done")
        return t

    # ---------------------------------------------------------------- background steps
    async def _gather(self, key: str) -> None:
        """Phase 1: context → classification and environment → scenarios → checklist → gate 1."""
        t = self.tickets.get(key)
        assert t
        jira = self.jira()
        issue = self._typed(await self._call(jira.get_issue, key))
        if t.p1 <= 0:
            self.patch(key, p1=0, doing="Reading the whole ticket: fields, comments, links and attachments",
                       description=issue.get("description", ""),
                       context=ticket_context.summary(issue["context"]) if issue.get("context") else {})
            agent.write_file(self.cfg, key, f"{key}-context.md", self._context_md(issue))
            await self.pause(2.5)
        if t.p1 <= 1 or self.tickets.get(key).env is None:  # type: ignore[union-attr]
            self.patch(key, p1=1, doing="Classifying and resolving the environment",
                       type=issue["type"], components=issue["components"])
            await self.pause(2.5)
            env = self.tickets.get(key).env  # type: ignore[union-attr]
            if env is None:
                env, reason = agent.resolve_environment(issue, self.cfg)
                self.patch(key, env_candidates=issue.get("env_candidates", []))
                if env is None:
                    self.patch(key, sub="blocked", p1=1, doing=reason)
                    self.toast(f"{key} needs an environment")
                    return
                self.patch(key, env=env)
        self.patch(key, p1=2, doing="Writing scenarios", pr_url=issue.get("pr_url", ""))
        t = self.tickets.get(key)
        assert t and t.env
        if self.cfg.is_mock and t.checklist:
            scenarios = "\n".join(f"- Scenario: {i.text}" for i in t.items())
            sections, serial = t.checklist, t.serial
            await self.pause(2.5)
        else:
            scenarios, sections, serial = await agent.plan_checklist(self.cfg, issue, t.env)
            if self.cfg.anthropic_api_key:
                self._used(key, "gather")
        agent.write_file(self.cfg, key, f"{key}-scenarios.md", f"# {key} scenarios\n\n{scenarios}\n")
        self.patch(key, p1=3, doing="Writing the QA checklist", checklist=sections, serial=serial, ran=False)
        t = self.tickets.get(key)
        assert t
        agent.write_file(self.cfg, key, f"{key}-qa-checklist.md", agent.checklist_md(t))
        await self.pause(1.5)
        self.patch(key, sub="gate", doing="")
        self.toast(f"{key} checklist ready for review")

    def _used(self, key: str, step: str) -> None:
        """Remember which skill version Claude followed for this step (shown in the drawer)."""
        t = self.tickets.get(key)
        if t:
            self.patch(key, skills={**t.skills, step: agent.skill_source(step, self.cfg)})

    def _typed(self, issue: dict) -> dict:
        """The issue plus its FE / BE / FE+BE type from the Jira components."""
        comps = list(issue.get("components", []))
        return {**issue, "components": comps, "type": self.cfg.ticket_type(comps)}

    def _context_md(self, issue: dict) -> str:
        if issue.get("context"):
            return ticket_context.to_markdown(issue["context"], extra=self._qa_facts(issue))
        comments = "\n\n".join(f"> {c}" for c in issue.get("comments", [])) or "_No comments._"
        return (f"# {issue['key']}: {issue['title']}\n\n- Status: {issue.get('status')}\n- Type: {type_label(issue.get('type', ''))}"
                f" (components: {', '.join(issue.get('components', [])) or 'none'})\n"
                f"- Merged: {issue.get('merged')}\n- PR: {issue.get('pr_url') or 'none linked'}\n\n## Description\n\n"
                f"{issue.get('description') or '_None._'}\n\n## Comments\n\n{comments}\n")

    @staticmethod
    def _qa_facts(issue: dict) -> dict:
        comps = ", ".join(issue.get("components", [])) or "none"
        return {"QA type": f"{type_label(issue.get('type', ''))} (from components: {comps})",
                "Merged": "yes" if issue.get("merged") else "no", "PR": issue.get("pr_url") or "none linked"}

    async def _build_and_run(self, key: str) -> None:
        t = self.tickets.get(key)
        assert t
        self.patch(key, stage=1, sub="working", doing=f"Building {key}.spec.ts" + (" and .serial.spec.ts" if t.serial else ""))
        await agent.build_spec(self.cfg, t)
        if self.cfg.anthropic_api_key and not self.cfg.is_mock:
            self._used(key, "create-tests")
        await self.pause(2.6)
        needs_sso = t.needs_sso if self.cfg.is_mock else not sso.has_session(self.cfg.auth_dir)
        if needs_sso:
            self.patch(key, stage=2, sub="sso", doing="")
            if not self.cfg.is_mock and t.env and t.env.url.startswith("http"):
                await sso.open_login(key, t.env.url)
            self.toast(f"{key} needs an SSO sign-in")
            return
        await self._run(key)

    async def _run(self, key: str) -> None:
        """Phase 2: run, fill in the checklist, write bug notes and the report, revert settings."""
        t = self.tickets.get(key)
        assert t
        self.patch(key, stage=2, sub="working", doing=f"Running {key}.spec.ts on {agent.env_name(t, self.cfg)}")
        if self.cfg.is_mock:
            await self.pause(3.0)
            results = [(r[0], r[1]) for r in t.mock_results] or [("nt", "") for _ in t.items()]
            cleanup, left = t.mock_cleanup, t.mock_left
        else:
            results, cleanup = await agent.run_spec(self.cfg, t, lambda m: log.info("%s: %s", key, m))
            left = t.left
        t = self.tickets.get(key)
        assert t
        t = t.model_copy(deep=True)
        agent.apply_results(t, results)
        t.cleanup, t.left, t.ran = cleanup, left, True
        if not self.cfg.is_mock and self.cfg.anthropic_api_key:
            self.patch(key, doing="Claude is reviewing the failures with the Run tests skill")
            try:
                errors = self.cfg.ticket_dir(key) / f"{key}-errors.json"
                details = json.loads(errors.read_text(encoding="utf-8")) if errors.exists() else {}
                if await agent.review_results(self.cfg, t, details):
                    t.skills = {**t.skills, "run-tests": agent.skill_source("run-tests", self.cfg)}
            except Exception:  # the runner's own notes stay; the review is a refinement
                log.exception("Result review failed for %s", key)
        agent.write_file(self.cfg, key, f"{key}-qa-checklist.md", agent.checklist_md(t))
        agent.write_file(self.cfg, key, f"{key}-report.md", agent.report_md(t, self.cfg))
        t.sub, t.doing = "gate", ""
        self.tickets.put(t)
        self.toast(f"{key} results ready for review")

    def _section_for(self, t: Ticket) -> str:
        area = {"FE": "Frontend", "BE": "Backend", "FE+BE": "Frontend and backend"}.get(t.type, self.cfg.jira_project or "QA")
        return f"{area} › {t.checklist[0].name if t.checklist else t.title}"

    async def _draft(self, key: str) -> None:
        """Phase 4 draft: PASS items only, read-only section lookup and duplicate check."""
        t = self.tickets.get(key)
        assert t
        tr = self.testrail()
        section = t.section or self._section_for(t)
        section_id = await self._call(tr.find_section, section)
        existing = {normalise(c["title"]) for c in await self._call(tr.get_cases, section_id)}
        try:
            drafts = await agent.write_cases(self.cfg, t, sorted(existing))
            if self.cfg.anthropic_api_key and not self.cfg.is_mock:
                self._used(key, "testrail")
        except Exception:
            log.exception("Case drafting failed for %s", key)
            drafts = agent.draft_cases(t)
        fresh = [c for c in drafts if normalise(c.title) not in existing]
        await self.pause(2.8)
        t = self.patch(key, section=section, cases=fresh, dups=len(drafts) - len(fresh))
        agent.write_file(self.cfg, key, f"{key}-testrail-cases.md", agent.cases_md(t))
        self.patch(key, sub="gate")
        self.toast(f"{key} TestRail draft ready for review")
