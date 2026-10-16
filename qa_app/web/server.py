"""Web UI server: Board (ticket workflow), Run, History, Integrations.

Start it with  python -m qa_app  (opens the browser). The classic PySide window is  python -m qa_app --classic.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import subprocess
import re
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import integrations
from ..config import APP_DIR, DEFAULT_SETTINGS, SECRET_KEYS, WORKFLOW_DIR, ensure_dirs, load_settings, save_section
from ..workflow import agent, seed
from ..workflow.clients import MockJira, MockTestRail
from ..workflow.engine import GateError, Workflow
from ..workflow import costs
from ..workflow.models import Ticket
from ..workflow.settings import WorkflowConfig
from ..workflow.store import TicketStore, bus
from . import azure_connect, jira_connect

log = logging.getLogger("qa_app.web")
STATIC = Path(__file__).parent / "static"

# Integrations screen (Jira and Azure Boards have their own connect flows under /api/jira and /api/azure;
# AWS S3 report upload is off the screen for now, its settings stay). Keys match DEFAULT_SETTINGS in config.py, so the CLI, the classic window
# and this UI all read and write the same settings.json.
SEV_OPTS = [{"v": v, "label": v.title()} for v in ("critical", "major", "minor", "info")]
CATALOGUE: list[dict[str, Any]] = [
    {"key": "workflow", "name": "Testing board", "mono": "QA", "tint": "#5865E0", "desc": "Which Jira or Azure Boards column the board takes tickets from",
     "fields": [{"k": "demo", "label": "Demo data (sample tickets, simulated Jira and TestRail)", "check": True, "full": True},
                {"k": "jira_project", "label": "Project key"}, {"k": "jira_column", "label": "Board column"},
                {"k": "auto_sync_minutes", "label": "Sync the board automatically", "options": [
                    {"v": "0", "label": "Off (Sync now only)"}, {"v": "2", "label": "Every 2 minutes"}, {"v": "5", "label": "Every 5 minutes"},
                    {"v": "10", "label": "Every 10 minutes"}, {"v": "15", "label": "Every 15 minutes"}, {"v": "30", "label": "Every 30 minutes"}]},
                {"k": "evidence_every_check", "label": "Evidence: screenshot every check (not only failures)", "check": True, "full": True},
                {"k": "evidence_keep_runs", "label": "Keep evidence for the last N runs of each ticket", "ph": "5"},
                {"k": "test_account", "label": "Test account (SSO)"},
                {"k": "test_ou", "label": "Test scope (optional)", "ph": "e.g. a test store, tenant or workspace"},
                {"k": "comment_signature", "label": "Comment signature"},
                {"k": "env_hints", "label": "Environment hints (words or domains in your test URLs)", "full": True,
                 "ph": "e.g. preview.myapp.com, staging, qa"},
                {"k": "default_env_url", "label": "Default environment URL (merged tickets only)", "ph": "https://staging.myapp.com"},
                {"k": "default_env_name", "label": "Default environment name", "ph": "staging"},
                {"k": "fe_components", "label": "FE: Jira components or labels (comma-separated)", "ph": "Frontend, FE"},
                {"k": "be_components", "label": "BE: Jira components or labels (comma-separated)", "ph": "Backend, BE, Core"},
                {"k": "both_names", "label": "FE+BE: components or labels that mean both", "full": True, "ph": "FE+BE, Fullstack"},
                {"k": "workspace", "label": "Playwright workspace folder (tests/tickets/<KEY>/ is written here)", "full": True,
                 "ph": str(APP_DIR / "workspace")}],
     "required": ["jira_project", "jira_column"]},
    {"key": "claude", "name": "Claude", "mono": "C", "tint": "#C2643F",
     "desc": "Does every board step: checklist, spec, bug notes, Jira comment, TestRail cases",
     "fields": [{"k": "mode", "label": "Connection", "full": True, "options": [
                    {"v": "api", "label": "API key (billed per use to your Anthropic API account)"},
                    {"v": "claude_code", "label": "Claude Code on this computer (your Claude plan, for your own use)"}]},
{"k": "api_key", "label": "Anthropic API key", "secret": True, "full": True},
                {"k": "model", "label": "Model", "full": True},
                {"k": "fetch_missing", "label": "Let Claude fetch missing data (read-only: gh, git, your Claude Code MCP servers, links on the ticket). Claude Code mode only", "check": True, "full": True}],
     "required": ["api_key"]},
    {"key": "slack", "name": "Slack", "mono": "S", "tint": "#7B3F8C", "desc": "Post a run summary to a channel",
     "fields": [{"k": "webhook_url", "label": "Webhook URL", "secret": True, "full": True, "ph": "https://hooks.slack.com/services/…"},
                {"k": "only_on_failure", "label": "Only on failure", "check": True, "full": True}],
     "required": ["webhook_url"]},
    {"key": "teams", "name": "Microsoft Teams", "mono": "T", "tint": "#4F57C2", "desc": "Post a run summary to a channel",
     "fields": [{"k": "webhook_url", "label": "Webhook URL", "secret": True, "full": True, "ph": "https://…webhook.office.com/…"},
                {"k": "only_on_failure", "label": "Only on failure", "check": True, "full": True}],
     "required": ["webhook_url"]},
    {"key": "github", "name": "GitHub", "mono": "GH", "tint": "#3B3F46",
     "desc": "Claude reads the PRs behind a ticket (read-only) when gathering context and writing tests",
     "fields": [{"k": "token", "label": "Token (fine-grained, read-only)", "secret": True, "full": True, "ph": "github_pat_…"},
                {"k": "repos", "label": "Repos or orgs to search for the ticket key", "full": True, "ph": "acme, acme/admin-suite"}],
     "required": ["token"]},
    {"key": "testrail", "name": "TestRail", "mono": "TR", "tint": "#1F7F70", "desc": "Run results, and board cases on your go-ahead",
     "fields": [{"k": "base_url", "label": "TestRail link: paste any page of your project", "full": True,
                 "ph": "https://your-org.testrail.io/index.php?/projects/overview/3"},
                {"k": "username", "label": "Username"}, {"k": "api_key", "label": "API key", "secret": True},
                {"k": "project_id", "label": "Project ID (filled in from the link)"}, {"k": "suite_id", "label": "Suite ID (optional, from the link)"}],
     "required": ["base_url", "username", "api_key"]},
    {"key": "xray", "name": "Xray", "mono": "X", "tint": "#2E7D3E", "desc": "Import executions into Xray",
     "fields": [{"k": "client_id", "label": "Client ID"}, {"k": "client_secret", "label": "Client secret", "secret": True},
                {"k": "project_key", "label": "Project key", "full": True}],
     "required": ["client_id", "client_secret", "project_key"]},
    {"key": "zephyr", "name": "Zephyr Scale", "mono": "Z", "tint": "#B5501C", "desc": "Sync test cycles to Zephyr Scale",
     "fields": [{"k": "api_token", "label": "API token", "secret": True, "full": True, "ph": "Paste an API token"},
                {"k": "project_key", "label": "Project key"}],
     "required": ["api_token", "project_key"]},
]
STATUS_FILE = WORKFLOW_DIR / "integration-status.json"


def _status() -> dict:
    return json.loads(STATUS_FILE.read_text(encoding="utf-8")) if STATUS_FILE.exists() else {}


def _set_status(key: str, value: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps({**_status(), key: value}, indent=2), encoding="utf-8")


def _onboarding_sources() -> dict:
    """What onboarding can read right now: the board's tracker, Confluence through it, TestRail when set up."""
    wf = S().workflow
    st = load_settings()
    try:
        tracker = wf.jira()
    except Exception:
        tracker = None
    reader = None
    if tracker is not None:
        try:
            from ..integrations import confluence
            reader = confluence.for_jira(tracker)
        except Exception:
            reader = None
    tr = st.get("testrail", {})
    testrail = tr if tr.get("enabled") and tr.get("base_url") and tr.get("api_key") else None
    return {"cfg": wf.cfg, "tracker": tracker, "testrail": testrail, "confluence": reader}


class Services:
    def __init__(self) -> None:
        ensure_dirs()
        WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
        issues, late = seed.jira_issues()
        self.workflow = Workflow(TicketStore(WORKFLOW_DIR / "tickets-demo.json"), TicketStore(WORKFLOW_DIR / "tickets.json"),
                                 MockJira(issues, late), MockTestRail())
        self.jira_pending: dict[str, dict] = {}  # Atlassian sign-ins in progress, by OAuth state
        from ..onboarding.run import Onboarding
        self.onboarding = Onboarding(_onboarding_sources)

    def seed_demo(self) -> None:
        store = self.workflow.demo_store
        if store.tickets or store.done_keys:
            # Demo boards saved before FE/BE types only had Core/Frontend: take the types from the demo data.
            fresh = {t.key: t for t in seed.seed_tickets() + [seed.late_ticket()]}
            stale = [t for t in store.tickets.values() if t.key in fresh and (not t.components or not t.context or not t.issue_type
                                                                              or (not t.usage and fresh[t.key].usage))]
            for t in stale:
                f = fresh[t.key]
                t.type, t.components, t.context = f.type, f.components, f.context
                t.issue_type, t.priority, t.status_cat = f.issue_type, f.priority, f.status_cat
                t.usage = t.usage or f.usage
            if stale:
                store.save()
            return
        seeded = seed.seed_tickets()
        for t in seeded:
            store.tickets[t.key] = t
        cfg = WorkflowConfig.load()
        cfg.demo, cfg.workspace = True, WORKFLOW_DIR / "demo-workspace"  # demo files never land in a real repo
        seed.write_seed_files(cfg, seeded)
        store.finished = {date.today().isoformat(): 3}
        store.last_sync = time.time() - 120
        store.save()

    def ticket_view(self, t: Ticket) -> dict:
        cfg = self.workflow.cfg
        d = t.public()
        d["files"] = agent.ticket_files(cfg, t)
        d["expected"] = self.workflow.expected_action(t)
        d["canRedo"] = self.workflow.can_redo_gather(t)
        d["cost"] = costs.summary(t.usage)
        d.pop("usage", None)
        st = load_settings()
        if not cfg.is_mock and st.get("workflow", {}).get("tracker") == "azure":
            a = st.get("azure", {})
            from urllib.parse import quote
            d["jiraUrl"] = f"{str(a.get('org_url', '')).rstrip('/')}/{quote(a.get('project', ''), safe='')}/_workitems/edit/{t.key}"
            d["tracker"] = "Azure Boards"
        else:
            base = st.get("jira", {}).get("base_url") or "https://example.atlassian.net"
            d["jiraUrl"] = f"{base.rstrip('/')}/browse/{t.key}"
            d["tracker"] = "Jira"
        d["envShort"] = agent.env_name(t, cfg) if t.env else ""
        # The latest run's evidence per check, and every run of this ticket (History)
        store = self.workflow.history()
        d["evidence"] = {}
        if t.run_id:
            try:
                rec = store.get(t.run_id)
                d["evidence"] = {str(i["n"]): {"error": i.get("error", ""), "attachments": i.get("attachments", [])}
                                 for i in rec["items"] if i.get("error") or i.get("attachments")}
            except (KeyError, ValueError, OSError):
                pass
        d["runs"] = [{k: r.get(k) for k in ("id", "run_no", "status", "started", "counts", "trigger")} for r in store.runs_for(t.key)][-10:]
        return d


svc: Optional[Services] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global svc
    svc = Services()
    svc.seed_demo()
    svc.workflow.resume()
    auto = asyncio.create_task(svc.workflow.auto_sync())
    yield
    auto.cancel()
    for task in svc.workflow.tasks.values():
        task.cancel()


app = FastAPI(title="YourQA", lifespan=lifespan)


def S() -> Services:
    assert svc is not None
    return svc


@app.exception_handler(GateError)
async def gate_error(_: Request, e: GateError):
    return JSONResponse({"detail": str(e), **e.extra}, status_code=e.status)


# ------------------------------------------------------------------ board
@app.get("/api/state")
def state() -> dict:
    s, cfg = S(), S().workflow.cfg
    store = s.workflow.tickets
    return {
        # Demo tickets always come from the sample OPTR · Testing column, whatever Jira is connected.
        "config": {"mode": "mock" if cfg.is_mock else "live", "project": "OPTR" if cfg.is_mock else cfg.jira_project,
                   "column": "Testing" if cfg.is_mock else cfg.jira_column,
                   "tracker": "Azure Boards" if not cfg.is_mock and load_settings().get("workflow", {}).get("tracker") == "azure" else "Jira",
                   "account": cfg.test_account, "ou": cfg.test_ou, "claude": cfg.claude_ready, "claudeMode": cfg.claude_mode},
        "tickets": [s.ticket_view(t) for t in store.all()],
        "claude": costs.summary([e for t in store.all() for e in t.usage]),
        "model": cfg.anthropic_model,
        "finishedToday": store.finished_today(),
        "lastSync": store.last_sync,
        "autoSync": 0 if cfg.is_mock else cfg.auto_sync_minutes, "syncError": s.workflow.sync_error,
    }


@app.post("/api/sync")
async def sync() -> dict:
    try:
        new = await S().workflow.sync()
    except Exception as e:
        raise HTTPException(502, f"Jira sync failed: {str(e)[:300]}")
    return {"new": new, "lastSync": S().workflow.tickets.last_sync}


class ActionIn(BaseModel):
    action: str
    stage: int
    sub: str
    payload: dict[str, Any] = {}


@app.post("/api/tickets/{key}/action")
async def ticket_action(key: str, body: ActionIn) -> dict:
    try:
        await S().workflow.act(key, body.action, body.stage, body.sub, body.payload)
    except GateError:
        raise
    except Exception as e:  # Jira / TestRail errors
        raise HTTPException(502, str(e)[:400])
    live = S().workflow.tickets.get(key)
    return {"ticket": S().ticket_view(live) if live else None, "done": live is None}


# ------------------------------------------------------------------ History: run records and their evidence
@app.get("/api/history/{run_id}/file/{rel:path}")
def history_file(run_id: str, rel: str):
    try:
        return FileResponse(S().workflow.history().file(run_id, rel))
    except KeyError:
        raise HTTPException(404, "That evidence file isn't there any more")


class TraceIn(BaseModel):
    path: str


@app.post("/api/history/{run_id}/trace")
async def history_trace(run_id: str, body: TraceIn) -> dict:
    """Open a trace in Playwright's Trace Viewer on this computer."""
    import shutil as _sh
    try:
        f = S().workflow.history().file(run_id, body.path)
    except KeyError:
        raise HTTPException(404, "That trace isn't there any more")
    npx = _sh.which("npx")
    if not npx:
        raise HTTPException(409, "Node.js (npx) is needed to open the Trace Viewer. Download the trace instead.")
    await asyncio.create_subprocess_exec(npx, "playwright", "show-trace", str(f), cwd=str(S().workflow.cfg.workspace),
                                         stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    return {"ok": True}


# ------------------------------------------------------------------ Reports: trends, reports, export, send
def _period(range_: str = "30d", from_: str = "", to: str = "") -> tuple[Optional[float], Optional[float], str]:
    from datetime import datetime as _dt
    if from_ or to:
        try:
            since = _dt.strptime(from_, "%Y-%m-%d").timestamp() if from_ else None
            until = _dt.strptime(to, "%Y-%m-%d").timestamp() + 86399 if to else None
        except ValueError:
            raise HTTPException(422, "Dates must look like 2026-10-15")
        return since, until, f"{from_ or 'start'} to {to or 'today'}"
    labels = {"today": "today", "7d": "the last 7 days", "30d": "the last 30 days", "all": "all time"}
    return _since(range_), None, labels.get(range_, range_)


@app.get("/api/reports/trends")
def reports_trends(range: str = "30d", project: str = "", type: str = "") -> dict:
    from ..workflow import reports as rep
    since, _, label = _period(range)
    return {**rep.trends(S().workflow.history(), since, project, type), "label": label}


@app.get("/api/reports")
def reports_list() -> dict:
    from ..workflow import reports as rep
    return {"reports": rep.ReportStore(S().workflow.history()).list()}


class ReportIn(BaseModel):
    kind: str
    ref: str = ""
    range: str = "30d"
    from_: str = ""
    to: str = ""


@app.post("/api/reports")
async def reports_create(body: ReportIn) -> dict:
    from ..workflow import reports as rep
    store = S().workflow.history()
    since, until, label = _period(body.range, body.from_, body.to) if body.kind == "period" else (None, None, "")
    t = S().workflow.tickets.get(body.ref) if body.kind == "ticket" else None
    ticket = {"comment": t.comment, "cases": [c.model_dump() for c in t.cases]} if t else None
    try:
        return await asyncio.to_thread(rep.ReportStore(store).create, body.kind, body.ref, since, until, label, ticket)
    except KeyError:
        raise HTTPException(404, "There are no runs for that yet")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/reports/{rid}.html")
def reports_html(rid: str):
    from ..workflow import reports as rep
    try:
        return FileResponse(rep.ReportStore(S().workflow.history()).html_path(rid), media_type="text/html")
    except KeyError:
        raise HTTPException(404, "That report isn't there any more")


@app.get("/api/reports/{rid}.pdf")
async def reports_pdf(rid: str):
    from ..workflow import reports as rep
    rs = rep.ReportStore(S().workflow.history())
    try:
        meta = rs.get(rid)
        f = await asyncio.to_thread(rs.pdf_path, rid)
    except KeyError:
        raise HTTPException(404, "That report isn't there any more")
    except Exception as e:  # Chromium missing, etc.
        raise HTTPException(500, f"Couldn't make the PDF: {str(e).splitlines()[0][:200]}")
    name = re.sub(r"[^\w.-]+", "-", meta["title"]).strip("-") + ".pdf"
    return FileResponse(f, media_type="application/pdf", filename=name)


@app.get("/api/reports/csv/{what}")
def reports_csv(what: str, range: str = "30d", from_: str = "", to: str = "", key: str = ""):
    from fastapi.responses import Response
    from ..workflow import reports as rep
    store = S().workflow.history()
    since, until, _ = _period(range, from_, to)
    runs = store.list(key=key, since=since, until=until)
    if what == "runs":
        data = rep.runs_csv(store, runs)
    elif what == "checks":
        data = rep.checks_csv(store, runs)
    else:
        raise HTTPException(404)
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="yourqa-{what}.csv"'})


class SendIn(BaseModel):
    to: str


@app.post("/api/reports/{rid}/preview")
def reports_preview(rid: str, body: SendIn) -> dict:
    from ..workflow import reports as rep
    try:
        return rep.preview(rep.ReportStore(S().workflow.history()).get(rid), body.to, load_settings())
    except KeyError:
        raise HTTPException(404, "That report isn't there any more")
    except rep.SendError as e:
        raise HTTPException(409, str(e))


@app.post("/api/reports/{rid}/send")
async def reports_send(rid: str, body: SendIn) -> dict:
    from ..workflow import reports as rep
    try:
        return {"result": await asyncio.to_thread(rep.send, rep.ReportStore(S().workflow.history()), rid, body.to, load_settings())}
    except KeyError:
        raise HTTPException(404, "That report isn't there any more")
    except rep.SendError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"Sending failed: {str(e).splitlines()[0][:300]}")


@app.get("/api/tickets/{key}/terminal")
def ticket_terminal(key: str) -> dict:
    """The ticket's run output: live while it runs; after an app restart, the last run's saved terminal.log."""
    wf = S().workflow
    lines = wf.terminal(key)
    t = wf.tickets.get(key)
    if not lines and t and t.run_id:
        log_file = wf.history().dir(t.run_id) / "terminal.log"
        if log_file.exists():
            lines = [{"kind": "out", "text": l, "at": 0} for l in log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-1500:]]
    return {"lines": lines, "running": bool(t and t.stage == 2 and t.sub == "working" and not t.error)}


# ------------------------------------------------------------------ onboarding
class StudyIn(BaseModel):
    projects: list[str] = []
    spaces: list[str] = []
    repo: str = ""


@app.get("/api/onboarding")
def onboarding_state() -> dict:
    svc = S()
    cfg = svc.workflow.cfg
    st = load_settings()
    tracker_kind = "demo" if cfg.is_mock else st.get("workflow", {}).get("tracker", "jira")
    src = _onboarding_sources()
    ws = str(st.get("workflow", {}).get("workspace") or "").strip()
    return {**svc.onboarding.state(),
            "connections": {
                "tracker": {"name": {"demo": "Demo tickets", "azure": "Azure Boards"}.get(tracker_kind, "Jira"),
                            "connected": src["tracker"] is not None, "demo": cfg.is_mock},
                "testrail": {"name": "TestRail", "connected": bool(src["testrail"])},
                "confluence": {"name": "Confluence", "connected": src["confluence"] is not None,
                               "note": "through your Jira connection"}},
            "defaults": {"projects": [p for p in [cfg.jira_project] if p], "spaces": [], "repo": ws}}


@app.post("/api/onboarding/study")
async def onboarding_study(body: StudyIn) -> dict:
    ob = S().onboarding
    if ob.state()["running"]:
        raise HTTPException(409, "A study is already running")
    if not body.projects and not body.repo.strip():
        raise HTTPException(422, "Choose at least one project or an automation repo to study")

    async def go() -> None:
        try:
            await ob.study(body.model_dump())
        except Exception:
            log.exception("Onboarding study failed")
    asyncio.create_task(go())
    await asyncio.sleep(0)
    return ob.state()


@app.post("/api/onboarding/stop")
def onboarding_stop() -> dict:
    return {"stopped": S().onboarding.stop()}


@app.post("/api/onboarding/undo/{change_id}")
def onboarding_undo(change_id: str) -> dict:
    try:
        return {"result": S().onboarding.undo(change_id), **S().onboarding.state()}
    except KeyError:
        raise HTTPException(404, "That change is gone")


@app.post("/api/onboarding/undo-all")
def onboarding_undo_all() -> dict:
    return {"result": S().onboarding.undo_all(), **S().onboarding.state()}


class ChatIn(BaseModel):
    message: str


@app.post("/api/tickets/{key}/chat")
async def ticket_chat(key: str, body: ChatIn) -> dict:
    t = await S().workflow.chat_send(key, body.message)
    return {"ticket": S().ticket_view(t)}


class ChatApplyIn(BaseModel):
    msg: int
    action: int
    stage: int
    sub: str


@app.post("/api/tickets/{key}/chat/apply")
async def ticket_chat_apply(key: str, body: ChatApplyIn) -> dict:
    try:
        t = await S().workflow.chat_apply(key, body.msg, body.action, body.stage, body.sub)
    except GateError:
        raise
    except Exception as e:
        raise HTTPException(502, str(e)[:400])
    return {"ticket": S().ticket_view(t)}


@app.delete("/api/tickets/{key}/chat")
def ticket_chat_clear(key: str) -> dict:
    return {"ticket": S().ticket_view(S().workflow.chat_clear(key))}


class DraftIn(BaseModel):
    comment: Optional[str] = None
    target: Optional[str] = None


@app.patch("/api/tickets/{key}/draft")
def ticket_draft(key: str, body: DraftIn) -> dict:
    t = S().workflow.save_draft(key, comment=body.comment, target=body.target)
    return {"ticket": S().ticket_view(t)}


@app.get("/api/tickets/{key}/files/{name}")
def ticket_file(key: str, name: str):
    root = S().workflow.cfg.ticket_dir(key).resolve()
    p = (root / name).resolve()
    if root not in p.parents or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="text/plain; charset=utf-8")


# ------------------------------------------------------------------ events
# Set by __main__ to the running uvicorn server, so live streams end as soon as Ctrl+C is pressed.
# Without this the server waits for the browser's /api/events connection to close, which it never does.
_server: Any = None


def stopping() -> bool:
    return bool(_server is not None and getattr(_server, "should_exit", False))


@app.get("/api/events")
async def events(request: Request):
    q = bus.subscribe()

    async def stream():
        try:
            yield "retry: 2000\n\n"
            idle = 0.0
            while not stopping():
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1)
                except asyncio.TimeoutError:
                    idle += 1
                    if idle >= 15:  # keep-alive for proxies and the browser
                        idle = 0
                        yield ": ping\n\n"
                    continue
                idle = 0
                if ev.get("type") == "ticket":
                    t = S().workflow.tickets.get(ev["ticket"]["key"])
                    if t is None:
                        continue
                    ev = {"type": "ticket", "ticket": S().ticket_view(t)}
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ History: every ticket run
def _since(range_: str) -> Optional[float]:
    days = {"today": 0, "7d": 7, "30d": 30}.get(range_)
    if days is None:
        return None
    now = time.time()
    if days == 0:
        lt = time.localtime(now)
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return now - days * 86400


@app.get("/api/history")
def history_list(q: str = "", key: str = "", project: str = "", type: str = "", status: str = "", env: str = "",
                 range: str = "all") -> dict:
    store = S().workflow.history()
    runs = store.list(q=q, key=key, project=project, type_=type, status=status, env=env, since=_since(range))
    every = store.list()
    return {"runs": runs, "mode": "demo" if S().workflow.cfg.is_mock else "live",
            "totals": store.totals(runs),
            "projects": sorted({r.get("project") for r in every if r.get("project")}),
            "envs": sorted({r.get("env_url") for r in every if r.get("env_url")}),
            "evidence_mb": round(store.evidence_bytes() / 1e6, 1)}


@app.get("/api/history/{run_id}")
def history_get(run_id: str) -> dict:
    store = S().workflow.history()
    try:
        rec = store.view(run_id)
    except KeyError:
        raise HTTPException(404, "That run isn't in History")
    st = load_settings()
    if st.get("workflow", {}).get("tracker") == "azure":
        a = st.get("azure", {})
        from urllib.parse import quote
        tracker_url = f"{str(a.get('org_url', '')).rstrip('/')}/{quote(a.get('project', ''), safe='')}/_workitems/edit/{rec['key']}"
    else:
        tracker_url = f"{(st.get('jira', {}).get('base_url') or 'https://example.atlassian.net').rstrip('/')}/browse/{rec['key']}"
    return {**rec, "on_board": S().workflow.tickets.get(rec["key"]) is not None, "tracker_url": tracker_url}


@app.get("/api/history/{run_id}/compare/{other}")
def history_compare(run_id: str, other: str) -> dict:
    try:
        return S().workflow.history().compare(other, run_id)
    except KeyError:
        raise HTTPException(404, "That run isn't in History")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/history/{run_id}/open-folder")
def open_folder(run_id: str) -> dict:
    try:
        d = S().workflow.history().dir(run_id)
    except KeyError:
        raise HTTPException(404)
    if not d.exists():
        raise HTTPException(404)
    try:
        if platform.system() == "Windows":
            os.startfile(str(d))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if platform.system() == "Darwin" else "xdg-open", str(d)])
    except OSError as e:
        raise HTTPException(500, f"Could not open {d}: {e}")
    return {"path": str(d)}


# ------------------------------------------------------------------ integrations
@app.get("/api/integrations")
def list_integrations() -> dict:
    settings, status = load_settings(), _status()
    cards = []
    for c in CATALOGUE:
        values = {f["k"]: settings.get(c["key"], {}).get(f["k"], DEFAULT_SETTINGS[c["key"]].get(f["k"], ""))
                  for f in c["fields"]}
        logo = next((f"/static/logos/{c['key']}.{ext}" for ext in ("svg", "png") if (STATIC / "logos" / f"{c['key']}.{ext}").exists()), None)
        cards.append({**c, "values": values, "enabled": bool(settings.get(c["key"], {}).get("enabled")),
                      "result": status.get(c["key"]), "logo": logo})
    logos = {f.stem: f"/static/logos/{f.name}" for f in sorted((STATIC / "logos").glob("*")) if f.suffix in (".svg", ".png")}
    return {"cards": cards, "logos": logos, "mode": "mock" if WorkflowConfig.load().is_mock else "live"}


class IntegrationIn(BaseModel):
    values: dict[str, Any]
    enabled: bool


@app.put("/api/integrations/{key}")
def save_integration(key: str, body: IntegrationIn) -> dict:
    if key not in DEFAULT_SETTINGS:
        raise HTTPException(404)
    allowed = set(DEFAULT_SETTINGS[key])
    values = {k: v for k, v in body.values.items() if k in allowed}
    if key == "testrail" and values.get("base_url"):  # a pasted page link: keep the site, take the project / suite from it
        from ..integrations import testrail
        link = testrail.parse_link(str(values["base_url"]))
        values["base_url"] = link["base_url"]
        for f in ("project_id", "suite_id"):
            if not str(values.get(f) or "").strip() and link.get(f):
                values[f] = link[f]
        if not str(values.get("project_id") or "").strip() and values.get("api_key"):
            try:  # a suite / case / run link names its project only through TestRail itself
                values = {**values, **{k: v for k, v in testrail.resolve(values).items() if k in ("project_id", "suite_id")}}
            except Exception:
                pass  # the board works it out on first use instead
    save_section(key, {**values, "enabled": body.enabled})
    return {"ok": True}


@app.post("/api/integrations/{key}/test")
async def test_integration(key: str, values: dict[str, Any] = Body(...)) -> dict:
    card = next((c for c in CATALOGUE if c["key"] == key), None)
    if not card:
        raise HTTPException(404)
    required = [] if key == "claude" and values.get("mode") == "claude_code" else card["required"]
    missing = [f["label"] for f in card["fields"] if f["k"] in required and not str(values.get(f["k"], "")).strip()]
    if missing:
        res = {"ok": False, "text": ", ".join(missing) + (" is required" if len(missing) == 1 else " are required")}
    elif key == "workflow":
        ws = str(values.get("workspace") or "").strip()
        res = {"ok": True, "text": "Demo data is on" if values.get("demo") else
               f"Live · {values['jira_project']} / {values['jira_column']}" + (f" · workspace {ws}" if ws else "")}
    elif key == "claude" and values.get("mode") == "claude_code":
        res = await asyncio.to_thread(_test_claude_code)
    elif key == "claude":
        res = await asyncio.to_thread(_test_claude, values)
    elif key == "testrail":
        from ..integrations import testrail
        try:
            text, filled = await asyncio.to_thread(testrail.check, values)
            res = {"ok": True, "text": text, "values": filled}
        except Exception as e:
            res = {"ok": False, "text": (str(e).splitlines() or ["error"])[0][:300]}
    elif key == "github":
        from ..integrations import github
        try:
            res = {"ok": True, "text": await asyncio.to_thread(github.test_connection, values)}
        except Exception as e:
            res = {"ok": False, "text": (str(e).splitlines() or ["error"])[0][:300]}
    else:
        try:
            res = {"ok": True, "text": await asyncio.to_thread(integrations.test_connection, key, values)}
        except Exception as e:  # show the service's own error on the card
            res = {"ok": False, "text": (str(e).splitlines() or ["error"])[0][:300]}
    _set_status(key, res)
    return res


def _test_claude_code() -> dict:
    from ..workflow import claude_code
    try:
        st = claude_code.auth_status()
    except claude_code.ClaudeCodeError as e:
        return {"ok": False, "text": str(e)}
    return {"ok": st["ok"], "text": st["text"]}


def _test_claude(values: dict) -> dict:
    import requests

    r = requests.get("https://api.anthropic.com/v1/models", timeout=15,
                     headers={"x-api-key": values["api_key"], "anthropic-version": "2023-06-01"})
    return {"ok": r.ok, "text": "API key works" if r.ok else f"HTTP {r.status_code} · {r.text[:150]}"}


# ------------------------------------------------------------------ Jira: paste a link, sign in with Atlassian (MCP)
def _jira_error(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


class JiraLinkIn(BaseModel):
    link: str


class JiraColumnIn(BaseModel):
    column: str
    use_on_board: bool = True


@app.get("/api/jira")
def jira_status() -> dict:
    return jira_connect.status()


@app.post("/api/jira/connect")
async def jira_connect_start(body: JiraLinkIn, request: Request) -> dict:
    # Atlassian sends the browser back here. "localhost" is the loopback name MCP clients register with.
    redirect = f"http://localhost:{request.url.port or 8765}/api/jira/oauth/callback"
    try:
        return await asyncio.to_thread(jira_connect.start, body.link, redirect, S().jira_pending)
    except (jira_connect.ConnectError, jira_connect.McpError) as e:
        raise _jira_error(e)


@app.get("/api/jira/oauth/callback")
async def jira_oauth_callback(request: Request):
    q = request.query_params
    back = f"http://127.0.0.1:{request.url.port or 8765}/#/integrations"
    if q.get("error"):
        return _callback_page(False, q.get("error_description") or q.get("error") or "Sign-in was cancelled", back)
    try:
        info = await asyncio.to_thread(jira_connect.finish, q.get("code", ""), q.get("state", ""), S().jira_pending)
    except (jira_connect.ConnectError, jira_connect.McpError) as e:
        return _callback_page(False, str(e), back)
    bus.publish({"type": "toast", "message": f"Jira connected: {info['project']['name']} · {info['board']['name']}"})
    return RedirectResponse(back + "?jira=connected", status_code=303)


def _callback_page(ok: bool, text: str, back: str) -> HTMLResponse:
    import html
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>Jira sign-in</title>
<body style="font:15px system-ui;max-width:520px;margin:12vh auto;padding:0 16px;color:#17181B">
<h1 style="font-size:20px">{'Jira connected' if ok else 'Jira sign-in did not finish'}</h1>
<p>{html.escape(text)}</p><p><a href="{html.escape(back)}">Back to YourQA</a></p></body>""", status_code=200 if ok else 400)


class JiraTokenIn(BaseModel):
    link: str
    email: str
    api_token: str


@app.post("/api/jira/connect-token")
async def jira_connect_token(body: JiraTokenIn) -> dict:
    try:
        info = await asyncio.to_thread(jira_connect.connect_token, body.link, body.email, body.api_token)
    except jira_connect.ConnectError as e:
        raise _jira_error(e)
    return {"connected": info}


class JiraBugsIn(BaseModel):
    on_runs: bool = False
    issue_type: str = "Bug"
    min_severity: str = "major"


@app.post("/api/jira/bugs")
def jira_bugs(body: JiraBugsIn) -> dict:
    try:
        return jira_connect.save_bugs(body.on_runs, body.issue_type, body.min_severity)
    except jira_connect.ConnectError as e:
        raise _jira_error(e)


@app.post("/api/jira/column")
def jira_column(body: JiraColumnIn) -> dict:
    try:
        return jira_connect.choose_column(body.column, body.use_on_board)
    except jira_connect.ConnectError as e:
        raise _jira_error(e)


@app.post("/api/jira/refresh")
async def jira_refresh() -> dict:
    try:
        await asyncio.to_thread(jira_connect.refresh)
    except jira_connect.McpAuthRequired as e:
        raise HTTPException(401, str(e))
    except (jira_connect.ConnectError, jira_connect.McpError) as e:
        raise _jira_error(e)
    return jira_connect.status()


@app.post("/api/jira/disconnect")
def jira_disconnect() -> dict:
    return jira_connect.disconnect()


# ------------------------------------------------------------------ Azure Boards: paste a board link + personal access token
class AzureConnectIn(BaseModel):
    link: str
    pat: str = ""


@app.get("/api/azure")
def azure_status() -> dict:
    return azure_connect.status()


@app.post("/api/azure/connect")
async def azure_connect_start(body: AzureConnectIn) -> dict:
    try:
        return {"connected": await asyncio.to_thread(azure_connect.connect, body.link, body.pat)}
    except azure_connect.ConnectError as e:
        raise HTTPException(400, str(e))


@app.post("/api/azure/column")
def azure_column(body: JiraColumnIn) -> dict:
    try:
        return azure_connect.choose_column(body.column, body.use_on_board)
    except azure_connect.ConnectError as e:
        raise HTTPException(400, str(e))


@app.post("/api/azure/refresh")
async def azure_refresh() -> dict:
    try:
        return await asyncio.to_thread(azure_connect.refresh)
    except azure_connect.ConnectError as e:
        raise HTTPException(400, str(e))


@app.post("/api/azure/disconnect")
def azure_disconnect() -> dict:
    return azure_connect.disconnect()


# ------------------------------------------------------------------ skills: how Claude does each step
from ..workflow import skills as skill_store  # noqa: E402


class SkillIn(BaseModel):
    text: str
    mode: str = "add"


def _skill_call(fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/skills")
def skills_overview(project: str = "") -> dict:
    key = project.strip().upper() or (WorkflowConfig.load().jira_project if not WorkflowConfig.load().is_mock else "")
    try:
        return skill_store.overview(key or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/skills/general/{step}")
def skill_save_general(step: str, body: SkillIn) -> dict:
    _skill_call(skill_store.save_general, step, body.text)
    return {"ok": True}


@app.delete("/api/skills/general/{step}")
def skill_reset_general(step: str) -> dict:
    _skill_call(skill_store.reset_general, step)
    return {"ok": True}


@app.put("/api/skills/project/{key}/{step}")
def skill_save_project(key: str, step: str, body: SkillIn) -> dict:
    _skill_call(skill_store.save_project, key.upper(), step, body.text, body.mode)
    return {"ok": True}


@app.delete("/api/skills/project/{key}/{step}")
def skill_delete_project(key: str, step: str) -> dict:
    _skill_call(skill_store.delete_project, key.upper(), step)
    return {"ok": True}


# ------------------------------------------------------------------ static
class _Static(StaticFiles):
    """The app's own files: the browser checks for a newer copy on every load (cheap, by ETag),
    so an update shows after a reload instead of a stale cached script."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", _Static(directory=str(STATIC)), name="static")


@app.get("/")
def index():
    # Version the script and styles by file time, so a changed file is a new URL the browser must fetch.
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "app.css", "tokens.css"):
        f = STATIC / name
        if f.exists():
            page = page.replace(f"/static/{name}\"", f"/static/{name}?v={int(f.stat().st_mtime)}\"")
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


__all__ = ["app", "SECRET_KEYS"]
