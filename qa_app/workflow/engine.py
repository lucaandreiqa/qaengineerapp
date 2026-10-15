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
import re
import time
from urllib.parse import urlparse
from datetime import datetime
from typing import Any, Callable, Optional

from ..config import load_settings
from . import agent, sso
from .clients import MockJira, MockTestRail, RealJira, RealTestRail, normalise
from . import chat as chat_mod
from . import costs, history, move_rules, skills, sources, terminal as term_mod, ticket_context
from .models import WORKING_SUBS, Env, Ticket, type_label
from .settings import WorkflowConfig
from .store import TicketStore, bus

log = logging.getLogger("qa.workflow")

RESULT_WORD = {"pass": "passed", "fail": "failed", "partial": "partial", "blocked": "blocked", "nt": "not tested"}

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
        self.chat_tasks: dict[str, asyncio.Task] = {}  # Claude's chat replies, apart from the steps
        self._next_trigger: dict[str, str] = {}  # why the next run of a ticket happens (History)
        self._stores: dict[str, "history.RunStore"] = {}
        self._terminal: dict[str, list[dict]] = {}  # each ticket's live Playwright output (its current or last run)
        self.toast: Callable[[str], None] = lambda msg: bus.publish({"type": "toast", "message": msg})
        self.sync_error = ""          # the last automatic sync's error, shown on the board until one works
        self._sync_failed_at = 0.0
        self._syncing = False
        agent.usage_listeners.append(self._on_usage)

    # ---------------------------------------------------------------- history and the ticket's live feed
    def history(self) -> "history.RunStore":
        root = self.cfg.history_dir
        if str(root) not in self._stores:
            self._stores[str(root)] = history.RunStore(root)
        return self._stores[str(root)]

    def say(self, key: str, text: str, step: str = "", role: str = "progress") -> None:
        """A line in the ticket's feed (the chat pane): where the ticket is and what is happening."""
        t = self.tickets.get(key)
        if t:
            self.patch(key, chat=(t.chat + [chat_mod.message(role, text, step=step)])[-chat_mod.MAX_MESSAGES:])

    def terminal(self, key: str) -> list[dict]:
        return list(self._terminal.get(key, []))

    def term(self, key: str, kind: str, text: str) -> None:
        """A line of the run's terminal: kept for the drawer and sent live to the board."""
        line = {"kind": kind, "text": text[:2000], "at": time.time()}
        lines = self._terminal.setdefault(key, [])
        lines.append(line)
        del lines[:-term_mod.MAX_LINES]
        bus.publish({"type": "term", "key": key, "line": line})

    def _on_usage(self, key: str, step: str, model: str, usage: dict, billing: str = "api") -> None:
        """Keep each Claude call's tokens and cost on its ticket (redos add to it)."""
        t = self.tickets.get(key) if key else None
        if t:
            self.patch(key, usage=(t.usage + [costs.entry(step, model, usage, billing=billing)])[-500:])

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
        if s.get("workflow", {}).get("tracker") == "azure":  # Azure Boards: same calls, work items instead of issues
            from ..integrations.azure_boards import AzureBoards
            return AzureBoards(s.get("azure", {}), s.get("workflow", {}))
        if s.get("jira", {}).get("auth") == "mcp":  # signed in with Atlassian (MCP)
            from ..integrations.atlassian_mcp import McpJira
            return McpJira(s.get("jira", {}), s.get("workflow", {}))
        return RealJira(s.get("jira", {}), s.get("workflow", {}))

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
        try:
            self.history().close_unfinished()
        except Exception:
            log.exception("Could not close unfinished runs")
        for t in self.tickets.all():
            if t.running_item != -1:
                self.patch(t.key, running_item=-1)
            if t.chat_busy:  # a chat reply that was cut off by the restart
                self.patch(t.key, chat_busy=False, chat=t.chat + [chat_mod.message("assistant", "The app restarted before I answered. Ask again.", error=True)])
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
    AUTO_SYNC_TICK = 30  # seconds between checks; the interval itself is the board setting (minutes)

    async def auto_sync(self) -> None:
        """Pull the board column every few minutes while a real board is connected. Runs for the app's lifetime."""
        while True:
            await asyncio.sleep(self.AUTO_SYNC_TICK)
            try:
                await self.auto_sync_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # never let the loop die
                pass

    async def auto_sync_once(self, now: Optional[float] = None) -> Optional[list[str]]:
        """Sync if the interval has passed. None when it wasn't due (or is off), else the new ticket keys.
        A failure waits a full interval before trying again, and is shown on the board."""
        cfg = self.cfg
        mins = cfg.auto_sync_minutes
        if cfg.is_mock or mins <= 0 or self._syncing:
            return None
        now = now or time.time()
        if now - max(self.tickets.last_sync or 0.0, self._sync_failed_at) < mins * 60:
            return None
        try:
            new = await self.sync()
        except Exception as e:
            self._sync_failed_at = now
            self.sync_error = (str(e).splitlines() or ["error"])[0][:300]
            bus.publish({"type": "sync", "lastSync": self.tickets.last_sync, "error": self.sync_error, "auto": True})
            return None
        if new:
            self.toast(f"Auto-sync: {len(new)} new ticket{'s' if len(new) != 1 else ''} · {', '.join(new[:4])}{'…' if len(new) > 4 else ''}")
        return new

    async def sync(self) -> list[str]:
        self._syncing = True
        try:
            new = await self._sync()
        finally:
            self._syncing = False
        self.sync_error = ""
        bus.publish({"type": "sync", "lastSync": self.tickets.last_sync, "error": "", "new": new})
        return new

    async def _sync(self) -> list[str]:
        issues = await self._call(self.jira().search_column, self.cfg.jira_project, self.cfg.jira_column)
        new: list[Ticket] = []
        for i in issues:
            if i["key"] in self.tickets.tickets:  # keep what the card shows in step with Jira
                cur = self.tickets.get(i["key"])
                upd = {k: i[k] for k in ("status", "status_cat", "issue_type", "priority") if i.get(k) and getattr(cur, k) != i[k]}
                if "components" in i or "labels" in i:  # the FE/BE type follows the ticket's components and labels
                    comps, labels = list(i.get("components", [])), list(i.get("labels", []))
                    ttype = self.cfg.ticket_type(comps, labels)
                    if (ttype, comps, labels) != (cur.type, cur.components, cur.labels):
                        upd.update(type=ttype, components=comps, labels=labels)
                if upd:
                    self.patch(i["key"], **upd)
                continue
            if i["key"] in self.tickets.done_keys:
                continue
            comps, labels = list(i.get("components", [])), list(i.get("labels", []))
            t = Ticket(key=i["key"], title=i["title"], type=self.cfg.ticket_type(comps, labels), components=comps, labels=labels,
                       status=i.get("status", ""),
                       status_cat=i.get("status_cat", ""), issue_type=i.get("issue_type", ""), priority=i.get("priority", ""),
                       description=i.get("description", ""), stage=0, sub="working", doing="Gathering context from Jira")
            if self.cfg.is_mock:
                from .seed import late_ticket
                late = late_ticket()
                if late.key == t.key:  # mock checklist and expected results for the demo ticket
                    t = late.model_copy(update={"env": None, "status": t.status, "status_cat": t.status_cat})
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
        if action == "stop":
            return await self._stop(t)
        if (t.stage, t.sub) != (stage, sub):
            raise GateError(f"{key} has moved on (now lane {t.stage + 1} · {t.sub}). Review it again before acting.")
        if action == "redo_gather":
            return await self._redo_gather(t, payload)
        expected = self.expected_action(t)
        if expected != action:
            raise GateError(f"{key} is waiting for '{expected or 'nothing'}', not '{action}'")
        return await getattr(self, f"_a_{action}")(t, payload)

    async def _stop(self, t: Ticket) -> Ticket:
        """Stop the ticket's running step (the Playwright process is ended with it). Retry starts it again."""
        task = self.tasks.get(t.key)
        if t.sub not in WORKING_SUBS or not task or task.done():
            raise GateError(f"Nothing is running for {t.key}")
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), 5)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        self.say(t.key, "Stopped by you. Press Retry to run it again.", "run" if t.stage == 2 else "")
        return self.patch(t.key, error="Stopped by you. Press Retry to start this step again.", running_item=-1, doing="")

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
            upd["target_from"] = ""  # your choice now, not the skill's
        return self.patch(key, **upd) if upd else t

    # ---------------------------------------------------------------- chat with Claude about a ticket
    STEP_SKILL = ["gather", "create-tests", "run-tests", "jira-comment", "testrail"]

    async def chat_send(self, key: str, text: str) -> Ticket:
        """Add the user's message and start Claude's reply (it arrives on the board's live events)."""
        t = self.tickets.get(key)
        if not t:
            raise GateError(f"{key} is not on the board", 404)
        text = (text or "").strip()[:4000]
        if not text:
            raise GateError("Write a message first", 422)
        if t.chat_busy:
            raise GateError("Claude is still answering the last message")
        if not self.cfg.claude_ready:
            raise GateError("Connect Claude on the Integrations screen to chat about tickets", 409)
        t = self.patch(key, chat=(t.chat + [chat_mod.message("user", text)])[-chat_mod.MAX_MESSAGES:], chat_busy=True)
        old = self.chat_tasks.get(key)
        if old and not old.done():
            old.cancel()
        self.chat_tasks[key] = asyncio.create_task(self._chat_reply(key))
        return t

    async def _chat_reply(self, key: str) -> None:
        agent.CURRENT_TICKET.set(key)
        t = self.tickets.get(key)
        if not t:
            return
        try:
            d = self.cfg.ticket_dir(key)
            read = lambda n: (d / n).read_text(encoding="utf-8") if (d / n).exists() else ""  # noqa: E731
            from . import skills
            system, prompt = chat_mod.build(t, self.can_redo_gather(t), read(f"{key}-context.md"), read(f"{key}-report.md"),
                                            skills.for_prompt(self.STEP_SKILL[t.stage], self.cfg.jira_project))
            raw = await agent.ask_claude(self.cfg, system, prompt, max_tokens=2500, step="chat")
            reply, actions = chat_mod.parse(raw)
            msg = chat_mod.message("assistant", reply or "(no answer)", actions)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            msg = chat_mod.message("assistant", f"Couldn't reach Claude: {(str(e).splitlines() or ['error'])[0][:300]}", error=True)
        t = self.tickets.get(key)
        if t:
            self.patch(key, chat=(t.chat + [msg])[-chat_mod.MAX_MESSAGES:], chat_busy=False)

    async def chat_apply(self, key: str, msg_i: int, act_i: int, stage: int, sub: str) -> Ticket:
        """Run one action Claude suggested, after checking it against where the ticket is now."""
        t = self.tickets.get(key)
        if not t:
            raise GateError(f"{key} is not on the board", 404)
        try:
            a = t.chat[msg_i]["actions"][act_i]
        except (IndexError, KeyError, TypeError):
            raise GateError("That suggestion is gone", 404)
        if a.get("state") in ("applied", "dismissed"):
            raise GateError("Already done")
        if a.get("kind") in ("learn_move", "skip_learn"):  # YourQA's own question: about the skill, not the ticket's state
            return self._answer_learn(t, msg_i, act_i, a)
        if (t.stage, t.sub) != (stage, sub):
            raise GateError(f"{key} has moved on (now lane {t.stage + 1} · {t.sub}). Ask Claude again.")
        why = chat_mod.check(a, t, self.can_redo_gather(t))
        if why:
            raise GateError(why)
        kind = a["kind"]
        if kind == "redo_gather":
            await self.act(key, "redo_gather", stage, sub)
        elif kind == "change_env":
            await self.act(key, "redo_gather", stage, sub, {"env_url": str(a["url"])})
        elif kind == "retry":
            await self.act(key, "retry", stage, sub)
        elif kind == "rerun_tests":
            self._next_trigger[key] = "rerun_chat"
            self.patch(key, stage=2, sub="working", doing=f"Running {key}.spec.ts again", error="")
            self.spawn(key, self._run(key))
        elif kind == "set_checklist":
            from .models import CheckItem, Section
            sections = [Section(name=str(s.get("name") or "Checks")[:80], items=[CheckItem(text=str(i)[:300]) for i in s.get("items", []) if str(i).strip()])
                        for s in a["sections"] if isinstance(s, dict)]
            self.patch(key, checklist=[s for s in sections if s.items], ran=False)
            agent.write_file(self.cfg, key, f"{key}-qa-checklist.md", agent.checklist_md(self.tickets.get(key)))  # type: ignore[arg-type]
        elif kind == "set_comment":
            self.save_draft(key, comment=str(a["text"]))
        elif kind == "set_target":
            self.save_draft(key, target=str(a["target"]))
        t = self.tickets.get(key)
        assert t
        chat = [dict(m) for m in t.chat]
        chat[msg_i]["actions"] = [dict(x, state="applied") if j == act_i else x for j, x in enumerate(chat[msg_i]["actions"])]
        chat.append(chat_mod.message("event", f"Done: {a['label']}"))
        self.toast(f"{key}: {a['label']}")
        return self.patch(key, chat=chat[-chat_mod.MAX_MESSAGES:])

    def _answer_learn(self, t: Ticket, msg_i: int, act_i: int, a: dict) -> Ticket:
        if a["kind"] == "learn_move":
            if a.get("outcome") not in move_rules.OUTCOMES or not str(a.get("state") or "").strip():
                raise GateError("That suggestion is incomplete")
            text, _ = skills.general("jira-comment")
            skills.save_general("jira-comment", move_rules.with_rule(text, a["outcome"], str(a["state"])))
            note = f"Skill updated: when {move_rules.OUTCOMES[a['outcome']]}, I'll pick \"{a['state']}\". You can edit it on the Skills screen."
        else:
            note = "OK, the skill stays as it is."
        chat = [dict(m) for m in t.chat]
        chat[msg_i]["actions"] = [dict(x, state="applied" if j == act_i else "dismissed") for j, x in enumerate(chat[msg_i]["actions"])]
        chat.append(chat_mod.message("event", note))
        if a["kind"] == "learn_move":
            self.toast("Skill updated: Jira comment & move")
        return self.patch(t.key, chat=chat[-chat_mod.MAX_MESSAGES:])

    def chat_clear(self, key: str) -> Ticket:
        t = self.tickets.get(key)
        if not t:
            raise GateError(f"{key} is not on the board", 404)
        return self.patch(key, chat=[], chat_busy=False)

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
        if p.get("env_url"):  # "Change environment": test on this address from now on
            keep_env = self._chosen_env(t, str(p["env_url"]))
            self._next_trigger[t.key] = "after_env_change"
        checklist: list = []
        if self.cfg.is_mock:  # demo: keep the sample items (their simulated results are tied to them)
            from .models import CheckItem, Section
            checklist = [Section(name=s.name, items=[CheckItem(text=i.text) for i in s.items]) for s in t.checklist]
        t = self.patch(t.key, stage=0, sub="working", p1=0, error="", doing="Reading the ticket again",
                       env=keep_env, env_candidates=[], checklist=checklist, ran=False, cleanup=[], left="",
                       comment=None, comment_at="", target="", target_from="", transitions=[], cases=[], dups=0)
        self.spawn(t.key, self._gather(t.key))
        self.toast(f"{t.key}: reading the ticket again" + (" (keeping the environment you chose)" if keep_env else ""))
        return t

    def _chosen_env(self, t: Ticket, raw: str) -> Env:
        """The address the user picked or typed, as the ticket's environment."""
        url = raw.strip()
        if url and not url.lower().startswith(("http://", "https://")):
            url = "https://" + url.lstrip("/")  # staging.myapp.com → https://staging.myapp.com
        host = urlparse(url).hostname or ""
        if not url or " " in url or not ("." in host or host == "localhost"):
            raise GateError("Enter the test environment address, e.g. staging.your-app.com", 422)
        same = lambda a, b: re.sub(r"^https?://", "", a).rstrip("/").lower() == re.sub(r"^https?://", "", b).rstrip("/").lower()  # noqa: E731
        picked = next((c for c in t.env_candidates if same(c.get("url", ""), url)), None)
        return Env(kind="API" if picked and picked.get("api") else "Test environment", url=picked["url"] if picked else url,
                   source="you" + (f" · from {picked['source']}" if picked else ""), api="Chosen by you")

    async def _a_use_env(self, t: Ticket, p: dict) -> Ticket:
        t = self.patch(t.key, env=self._chosen_env(t, str(p.get("url", ""))), sub="working", p1=2, error="")
        self.spawn(t.key, self._gather(t.key))
        self.toast(f"Environment set for {t.key} · building scenarios and checklist")
        return t

    async def _a_approve_checklist(self, t: Ticket, p: dict) -> Ticket:
        t = self.patch(t.key, stage=1, sub="working", doing=f"Building {t.key}.spec.ts", error="")
        self.spawn(t.key, self._build_and_run(t.key))
        self.say(t.key, "You approved the checklist (Gate 1).", "gather")
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
        agent.CURRENT_TICKET.set(t.key)
        try:
            comment = await agent.write_comment(self.cfg, t)
            if self.cfg.claude_ready and not self.cfg.is_mock:
                self._used(t.key, "jira-comment")
        except Exception:  # Claude unavailable: the template comment, still editable at gate 3
            log.exception("Comment drafting failed for %s", t.key)
            comment = agent.comment_text(t, self.cfg)
        t = self.patch(t.key, stage=3, sub="comment", comment=comment)
        self.say(t.key, "You approved the results (Gate 2). The Jira comment is drafted for your review.", "jira")
        self.toast(f"Gate 2 approved · comment drafted for {t.key}")
        return t

    async def _a_post_comment(self, t: Ticket, p: dict) -> Ticket:
        text = p.get("comment") if p.get("comment") is not None else (t.comment or agent.comment_text(t, self.cfg))
        if not str(text).strip():
            raise GateError("The comment is empty", 422)
        jira = self.jira()
        await self._call(jira.add_comment, t.key, text)
        transitions = [tr["name"] for tr in await self._call(jira.get_transitions, t.key)]
        target, target_from = (t.target, "") if t.target in transitions else ("", "")
        if not target:  # nothing planned: the state the skill learned for this kind of result
            target = move_rules.pick(skills.general("jira-comment")[0], move_rules.outcome(t.items()), transitions)
            target_from = "skill" if target else ""
        t = self.patch(t.key, sub="transition", comment=text, comment_at=now_hhmm(), transitions=transitions, target=target,
                       target_from=target_from)
        self.history().annotate(t.run_id, comment=text, comment_at=time.time())
        self.say(t.key, "Comment posted on the ticket. Moving it needs its own approval (Gate 3b).", "jira")
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
        self.say(t.key, f"Ticket moved to {target}. Drafting TestRail cases.", "jira")
        self.history().annotate(t.run_id, moved_to=target)
        self.toast(f"{t.key} moved to {target} · drafting TestRail cases")
        self._offer_to_learn(t, target)
        return self.tickets.get(t.key) or t

    def _offer_to_learn(self, t: Ticket, target: str) -> None:
        """After a move: if the skill wouldn't have picked this state, ask whether to learn it for next time."""
        result = move_rules.outcome(t.items())
        if move_rules.rules(skills.general("jira-comment")[0]).get(result) == target:
            return
        line = move_rules.rule_line(result, target)
        text = (f"You moved {t.key} to **{target}** after {move_rules.DESCRIBE[result]}. Should I update the "
                f"**Jira comment & move** skill so I pick this state myself next time, on every board?\n\nRule: `{line[2:]}`")
        acts = [{"kind": "learn_move", "label": "Update the skill", "outcome": result, "state": target},
                {"kind": "skip_learn", "label": "No thanks"}]
        cur = self.tickets.get(t.key)
        if cur:
            self.patch(t.key, chat=(cur.chat + [chat_mod.message("assistant", text, actions=acts, step="jira")])[-chat_mod.MAX_MESSAGES:])

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
        self.history().annotate(t.run_id, cases=[{"title": c.title} for c in t.cases], testrail_section=t.section)
        self.toast(f"{t.key} cases pushed to TestRail and verified · ticket done")
        return t

    # ---------------------------------------------------------------- connected apps (read-only lookups)
    def _source_clients(self) -> dict:
        """The connected apps a step may read: GitHub (own card), Confluence (through the Jira connection), TestRail."""
        st = load_settings()
        out: dict = {"github": None, "github_scope": [], "confluence": None, "testrail_search": None}
        gh = st.get("github", {})
        if gh.get("enabled") and gh.get("token"):
            from ..integrations import github
            out["github"], out["github_scope"] = github.GitHub(gh["token"]), github.scope(gh)
        try:
            from ..integrations import confluence
            out["confluence"] = confluence.for_jira(self.jira())
        except Exception:  # Jira not connected yet, or Azure Boards
            out["confluence"] = None
        tr = st.get("testrail", {})
        if tr.get("enabled") and tr.get("base_url") and tr.get("api_key") and tr.get("project_id"):
            from ..integrations import testrail
            out["testrail_search"] = lambda text: testrail.search_cases(tr, text)
        return out

    async def _lookups(self, key: str, issue: dict) -> "sources.Sources":
        """Read what the connected apps know about the ticket, show each lookup in the feed and keep it for later steps."""
        if self.cfg.is_mock:
            return sources.Sources()
        self.patch(key, doing="Looking in the connected apps: GitHub, Confluence, TestRail")
        ctx = issue.get("context")
        text = ticket_context.to_markdown(ctx) if ctx else (issue.get("description", "") + "\n" + "\n".join(issue.get("comments", [])))
        clients = await asyncio.to_thread(self._source_clients)
        found = await asyncio.to_thread(lambda: sources.lookup(key=key, title=issue.get("title", ""), ticket_text=text, **clients))
        for line in found.feed + found.problems:
            self.say(key, line, "gather")
        sources.save(self.cfg, key, found)
        return found

    # ---------------------------------------------------------------- background steps
    async def _gather(self, key: str) -> None:
        """Phase 1: context → classification and environment → scenarios → checklist → gate 1."""
        agent.CURRENT_TICKET.set(key)
        t = self.tickets.get(key)
        assert t
        jira = self.jira()
        issue = self._typed(await self._call(jira.get_issue, key))
        if t.p1 <= 0:
            self.patch(key, p1=0, doing="Reading the whole ticket: fields, comments, links and attachments",
                       description=issue.get("description", ""),
                       context=ticket_context.summary(issue["context"]) if issue.get("context") else {},
                       **({k: issue["context"][v] for k, v in (("issue_type", "issue_type"), ("priority", "priority"),
                                                               ("status", "status"), ("status_cat", "status_cat"))
                           if issue["context"].get(v)} if issue.get("context") else {}))
            agent.write_file(self.cfg, key, f"{key}-context.md", self._context_md(issue))
            ctx = issue.get("context") or {}
            parts = [f"{len(ctx.get('comments') or [])} comment{'s' if len(ctx.get('comments') or []) != 1 else ''}",
                     "a description" if ctx.get("description") else "no description"]
            if ctx.get("acceptance_criteria"):
                parts.append("acceptance criteria")
            if ctx.get("attachments"):
                parts.append(f"{len(ctx['attachments'])} attachment(s)")
            self.say(key, f"Read {key}: " + ", ".join(parts) + ".", "gather")
            await self.pause(2.5)
        if t.p1 <= 1 or self.tickets.get(key).env is None:  # type: ignore[union-attr]
            self.patch(key, p1=1, doing="Classifying and resolving the environment",
                       type=issue["type"], components=issue["components"], labels=issue["labels"])
            await self.pause(2.5)
            env = self.tickets.get(key).env  # type: ignore[union-attr]
            found_env, reason = agent.resolve_environment(issue, self.cfg)  # every link on the ticket, refreshed each read
            self.patch(key, env_candidates=issue.get("env_candidates", []))
            if env is None:
                env = found_env
                if env is None:
                    self.patch(key, sub="blocked", p1=1, doing=reason)
                    self.say(key, reason, "gather")
                    self.toast(f"{key} needs an environment")
                    return
                self.patch(key, env=env)
                self.say(key, f"Testing on {env.url} ({env.source or env.kind}).", "gather")
            else:
                self.say(key, f"Testing on {env.url} (" + ("chosen by you" if env.source.startswith("you") else env.source or env.kind) + ").", "gather")
        self.patch(key, p1=2, doing="Writing scenarios", pr_url=issue.get("pr_url", ""))
        t = self.tickets.get(key)
        assert t and t.env
        if self.cfg.is_mock and t.checklist:
            scenarios = "\n".join(f"- Scenario: {i.text}" for i in t.items())
            sections, serial = t.checklist, t.serial
            await self.pause(2.5)
        else:
            found = await self._lookups(key, issue)
            scenarios, sections, serial, analysis = await agent.plan_checklist(self.cfg, issue, t.env, sources_md=found.markdown("gather"))
            if self.cfg.claude_ready:
                self._used(key, "gather")
            extra = found.markdown("gather")
            if analysis.strip() or extra:  # what the apps said and the gather-context findings, after what the ticket says
                agent.write_file(self.cfg, key, f"{key}-context.md", self._context_md(issue).rstrip()
                                 + (f"\n\n## From connected apps\n\n{extra}" if extra else "")
                                 + (f"\n\n## QA analysis\n\n{analysis.strip()}" if analysis.strip() else "") + "\n")
        agent.write_file(self.cfg, key, f"{key}-scenarios.md", f"# {key} scenarios\n\n{scenarios}\n")
        self.patch(key, p1=3, doing="Writing the QA checklist", checklist=sections, serial=serial, ran=False)
        t = self.tickets.get(key)
        assert t
        agent.write_file(self.cfg, key, f"{key}-qa-checklist.md", agent.checklist_md(t))
        await self.pause(1.5)
        self.patch(key, sub="gate", doing="")
        n = len(t.items())
        self.say(key, f"Checklist ready: {n} check{'s' if n != 1 else ''} in {len(t.checklist)} section{'s' if len(t.checklist) != 1 else ''}. Waiting for your review (Gate 1).", "gather")
        self.say(key, self._plan_summary(t, scenarios), "gather", role="assistant")
        self.toast(f"{key} checklist ready for review")

    def _used(self, key: str, step: str) -> None:
        """Remember which skill version Claude followed for this step (shown in the drawer)."""
        t = self.tickets.get(key)
        if t:
            self.patch(key, skills={**t.skills, step: agent.skill_source(step, self.cfg)})

    def _typed(self, issue: dict) -> dict:
        """The issue plus its FE / BE / FE+BE type from the Jira components."""
        comps = list(issue.get("components", []))
        labels = list(issue.get("labels") or (issue.get("context") or {}).get("labels") or [])
        return {**issue, "components": comps, "labels": labels, "type": self.cfg.ticket_type(comps, labels)}

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
        labels = ", ".join(issue.get("labels", [])) or "none"
        return {"QA type": f"{type_label(issue.get('type', ''))} (from components: {comps}; labels: {labels})",
                "Merged": "yes" if issue.get("merged") else "no", "PR": issue.get("pr_url") or "none linked"}

    async def _build_and_run(self, key: str) -> None:
        agent.CURRENT_TICKET.set(key)
        t = self.tickets.get(key)
        assert t
        self.patch(key, stage=1, sub="working", doing=f"Building {key}.spec.ts" + (" and .serial.spec.ts" if t.serial else ""))
        self.say(key, f"Building the Playwright spec for {len(t.items())} checks.", "build")
        await agent.build_spec(self.cfg, t, sources_md=sources.load(self.cfg, key).markdown("create-tests"))
        if self.cfg.claude_ready and not self.cfg.is_mock:
            self._used(key, "create-tests")
        await self.pause(2.6)
        self.say(key, f"Spec ready: {key}.spec.ts" + (" and a serial spec for multi-user checks" if t.serial else "") + ".", "build")
        needs_sso = t.needs_sso if self.cfg.is_mock else not sso.has_session(self.cfg.auth_dir)
        if needs_sso:
            self.patch(key, stage=2, sub="sso", doing="")
            if not self.cfg.is_mock and t.env and t.env.url.startswith("http"):
                await sso.open_login(key, t.env.url)
            self.say(key, "Waiting for you to sign in (SSO) in the browser window that opened.", "run")
            self.toast(f"{key} needs an SSO sign-in")
            return
        await self._run(key)

    async def _run(self, key: str) -> None:
        """Phase 2: run (each check reported live), fill in the checklist, write bug notes and the report,
        revert settings, and record the run in History with its evidence."""
        agent.CURRENT_TICKET.set(key)
        t = self.tickets.get(key)
        assert t
        store = self.history()
        trigger = self._next_trigger.pop(key, None) or ("first" if not store.runs_for(key) else "redo")
        tdir = self.cfg.ticket_dir(key)
        spec_files = [tdir / f"{key}.spec.ts"] + ([tdir / f"{key}.serial.spec.ts"] if t.serial else [])
        run_id = store.start(t, trigger, "demo" if self.cfg.is_mock else "live", project=self.cfg.jira_project,
                             account=agent.who(self.cfg), spec_files=spec_files)
        started = time.time()
        items = t.items()
        for i in items:  # a fresh run: nothing is tested yet
            i.result, i.bug, i.severity = "nt", "", None
        self.patch(key, stage=2, sub="working", run_id=run_id, running_item=-1, checklist=t.checklist, ran=False,
                   doing=f"Running {key}.spec.ts on {agent.env_name(t, self.cfg)}")
        self.say(key, f"Run {store.get(run_id)['run_no']} started: {len(items)} checks on {agent.env_name(t, self.cfg)}.", "run")
        self._terminal[key] = []
        bus.publish({"type": "term", "key": key, "reset": True})

        async def on_output(kind: str, text: str) -> None:
            self.term(key, kind, text)
            if kind == "stall":
                self.say(key, term_mod.stall_message(text), "run", role="assistant")
            elif kind in ("sys", "out"):
                note = term_mod.friendly(text)
                if note:
                    self.say(key, note, "run")

        async def on_event(ev: dict) -> None:
            n = ev.get("n")
            if not n or not 1 <= int(n) <= len(items):
                return
            n = int(n)
            cur = self.tickets.get(key)
            if not cur:
                return
            text = cur.items()[n - 1].text
            if ev.get("type") == "begin":
                self.patch(key, running_item=n - 1, doing=f"Check {n} of {len(items)}: {text}")
            elif ev.get("type") == "end":
                res = ev.get("result", "nt")
                cl = [s.model_copy(deep=True) for s in cur.checklist]
                flat = [i for s in cl for i in s.items]
                flat[n - 1].result = res  # type: ignore[assignment]
                flat[n - 1].bug = (ev.get("error") or "").splitlines()[0][:300] if res == "fail" else flat[n - 1].bug
                self.patch(key, checklist=cl, running_item=-1)
                store.item_result(run_id, n, res, ev.get("error", ""), ev.get("attachments"))
                self.say(key, f"Check {n} of {len(items)}: {text} · {RESULT_WORD.get(res, res)}", "run")

        try:
            if self.cfg.is_mock:
                sim = [(r[0], r[1]) for r in t.mock_results] or [("nt", "") for _ in items]
                await on_output("sys", f"$ npx playwright test --config {store.dir(run_id) / 'playwright.config.js'}")
                await on_output("out", f"Running {len(sim)} test{'s' if len(sim) != 1 else ''} using 1 worker")
                for n, (res, bug) in enumerate(sim, start=1):
                    await on_output("out", f"  {'✓' if res == 'pass' else '✘' if res == 'fail' else '-'}  {n} [chromium] › {key}.spec.ts › [{n}] {items[n - 1].text[:80]}")
                    await on_event({"type": "begin", "n": n})
                    await self.pause(0.6)
                    await on_event({"type": "end", "n": n, "result": res, "error": bug if res == "fail" else ""})
                results, cleanup, left = sim, t.mock_cleanup, t.mock_left
                errors, atts, exit_code = {}, {}, 0 if all(r == "pass" for r, _ in sim) else 1
            else:
                out = await agent.run_spec(self.cfg, t, store.dir(run_id), on_event, on_output)
                results, cleanup, left = out["results"], out["cleanup"], t.left
                errors, atts, exit_code = out["errors"], out["attachments"], out["exit_code"]
        except asyncio.CancelledError:
            store.fail(run_id, "The run was stopped", status="stopped")
            self.patch(key, running_item=-1)
            raise
        except Exception as e:
            store.fail(run_id, str(e))
            self.patch(key, running_item=-1)
            self.say(key, f"The run couldn't finish: {(str(e).splitlines() or ['error'])[0][:200]}", "run")
            raise
        t = self.tickets.get(key)
        assert t
        t = t.model_copy(deep=True)
        agent.apply_results(t, results)
        t.cleanup, t.left, t.ran, t.running_item = cleanup, left, True, -1
        if not self.cfg.is_mock and self.cfg.claude_ready:
            self.patch(key, doing="Claude is reviewing the failures with the Run tests skill")
            try:
                errfile = self.cfg.ticket_dir(key) / f"{key}-errors.json"
                details = json.loads(errfile.read_text(encoding="utf-8")) if errfile.exists() else {}
                if await agent.review_results(self.cfg, t, details, sources_md=sources.load(self.cfg, key).markdown("run-tests")):
                    t.skills = {**t.skills, "run-tests": agent.skill_source("run-tests", self.cfg)}
            except Exception:  # the runner's own notes stay; the review is a refinement
                log.exception("Result review failed for %s", key)
        agent.write_file(self.cfg, key, f"{key}-qa-checklist.md", agent.checklist_md(t))
        agent.write_file(self.cfg, key, f"{key}-report.md", agent.report_md(t, self.cfg))
        t.sub, t.doing = "gate", ""
        self.tickets.put(t)
        usage = [u for u in t.usage if (u.get("at") or 0) >= started]
        rec = store.finish(run_id, t, cleanup=cleanup, exit_code=exit_code, errors=errors, attachments=atts, usage=usage)
        try:
            store.prune_evidence(key, self.cfg.evidence_keep_runs)
        except Exception:
            log.exception("Evidence pruning failed for %s", key)
        c = rec["counts"]
        self.say(key, f"Run finished: {c['pass']} passed, {c['fail']} failed" + (f", {c['partial']} partial" if c["partial"] else "")
                 + (f", {c['blocked']} blocked" if c["blocked"] else "") + ". Waiting for your review (Gate 2).", "run")
        self.say(key, self._run_summary(t), "run", role="assistant")
        self.toast(f"{key} results ready for review")

    @staticmethod
    def _plan_summary(t: Ticket, scenarios: str) -> str:
        lines = [f"Here's what I'll test on **{t.env.url if t.env else 'the environment'}**:"]
        for s in t.checklist:
            lines.append(f"- **{s.name}**: {len(s.items)} check{'s' if len(s.items) != 1 else ''}")
        if t.serial:
            lines.append("- Some checks need two sessions, so they run in a separate serial spec.")
        oq = re.search(r"open questions?:?\s*\n(.+)", scenarios or "", re.I | re.S)
        if oq:
            qs = [q.strip("-• ").strip() for q in oq.group(1).splitlines() if q.strip().startswith(("-", "•", "*"))][:3]
            if qs:
                lines.append("\nOpen questions from the ticket:")
                lines += [f"- {q}" for q in qs]
        lines.append("\nReview the checklist, then approve it to build and run the tests. Ask me if you want checks added or changed.")
        return "\n".join(lines)

    @staticmethod
    def _run_summary(t: Ticket) -> str:
        items = t.items()
        bad = [(n, i) for n, i in enumerate(items, start=1) if i.result in ("fail", "partial", "blocked")]
        if not bad:
            return f"All {len(items)} checks passed. Review the results, then approve to draft the Jira comment."
        out = [f"{len(items) - len(bad)} of {len(items)} checks passed. These need a look:"]
        for n, i in bad[:8]:
            out.append(f"- **Check {n}** ({RESULT_WORD.get(i.result, i.result)}): {i.text}" + (f": {i.bug}" if i.bug else ""))
        out.append("\nOpen a failed check to see its screenshot and error, or ask me whether it's a real bug or a test problem.")
        return "\n".join(out)

    def _section_for(self, t: Ticket) -> str:
        area = {"FE": "Frontend", "BE": "Backend", "FE+BE": "Frontend and backend"}.get(t.type, self.cfg.jira_project or "QA")
        return f"{area} › {t.checklist[0].name if t.checklist else t.title}"

    async def _draft(self, key: str) -> None:
        agent.CURRENT_TICKET.set(key)
        """Phase 4 draft: PASS items only, read-only section lookup and duplicate check."""
        t = self.tickets.get(key)
        assert t
        tr = self.testrail()
        section = t.section or self._section_for(t)
        section_id = await self._call(tr.find_section, section)
        existing = {normalise(c["title"]) for c in await self._call(tr.get_cases, section_id)}
        try:
            drafts = await agent.write_cases(self.cfg, t, sorted(existing))
            if self.cfg.claude_ready and not self.cfg.is_mock:
                self._used(key, "testrail")
        except Exception:
            log.exception("Case drafting failed for %s", key)
            drafts = agent.draft_cases(t)
        fresh = [c for c in drafts if normalise(c.title) not in existing]
        await self.pause(2.8)
        t = self.patch(key, section=section, cases=fresh, dups=len(drafts) - len(fresh))
        agent.write_file(self.cfg, key, f"{key}-testrail-cases.md", agent.cases_md(t))
        self.patch(key, sub="gate")
        self.say(key, f"TestRail draft ready: {len(fresh)} case{'s' if len(fresh) != 1 else ''} in {section}. Waiting for your review (Gate 4).", "testrail")
        self.toast(f"{key} TestRail draft ready for review")
