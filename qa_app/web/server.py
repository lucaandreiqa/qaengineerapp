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
from ..config import APP_DIR, DEFAULT_SETTINGS, RUNS_DIR, SECRET_KEYS, WORKFLOW_DIR, ensure_dirs, load_settings, save_section
from ..workflow import agent, seed
from ..workflow.clients import MockJira, MockTestRail
from ..workflow.engine import GateError, Workflow
from ..workflow.models import Ticket
from ..workflow.settings import WorkflowConfig
from ..workflow.store import TicketStore, bus
from . import jira_connect
from .runs import RunManager

log = logging.getLogger("qa_app.web")
STATIC = Path(__file__).parent / "static"

# Integrations screen. Keys match DEFAULT_SETTINGS in config.py, so the CLI, the classic window
# and this UI all read and write the same settings.json.
SEV_OPTS = [{"v": v, "label": v.title()} for v in ("critical", "major", "minor", "info")]
CATALOGUE: list[dict[str, Any]] = [
    {"key": "workflow", "name": "Testing board", "mono": "QA", "tint": "#5865E0", "desc": "Which Jira column the board takes tickets from",
     "fields": [{"k": "demo", "label": "Demo data (sample tickets, simulated Jira and TestRail)", "check": True, "full": True},
                {"k": "jira_project", "label": "Jira project"}, {"k": "jira_column", "label": "Board column (status)"},
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
    {"key": "claude", "name": "Claude", "mono": "C", "tint": "#C2643F", "desc": "Writes the scenarios, QA checklist and Playwright spec",
     "fields": [{"k": "api_key", "label": "Anthropic API key", "secret": True, "full": True},
                {"k": "model", "label": "Model", "full": True}],
     "required": ["api_key"]},
    {"key": "jira", "name": "Jira · API token", "mono": "J", "tint": "#2F64D6",
     "desc": "Bugs from site-check findings, and the fallback when an admin blocks Atlassian sign-in",
     "fields": [{"k": "base_url", "label": "Base URL", "full": True, "ph": "https://your-site.atlassian.net"},
                {"k": "email", "label": "Email"}, {"k": "api_token", "label": "API token", "secret": True},
                {"k": "project_key", "label": "Project key (for bugs)"},
                {"k": "issue_type", "label": "Issue type", "options": [{"v": v, "label": v} for v in ("Bug", "Task", "Story")]},
                {"k": "min_severity", "label": "Minimum severity", "options": SEV_OPTS, "full": True}],
     "required": ["base_url", "email", "api_token", "project_key"]},
    {"key": "slack", "name": "Slack", "mono": "S", "tint": "#7B3F8C", "desc": "Post a run summary to a channel",
     "fields": [{"k": "webhook_url", "label": "Webhook URL", "secret": True, "full": True, "ph": "https://hooks.slack.com/services/…"},
                {"k": "only_on_failure", "label": "Only on failure", "check": True, "full": True}],
     "required": ["webhook_url"]},
    {"key": "teams", "name": "Microsoft Teams", "mono": "T", "tint": "#4F57C2", "desc": "Post a run summary to a channel",
     "fields": [{"k": "webhook_url", "label": "Webhook URL", "secret": True, "full": True, "ph": "https://…webhook.office.com/…"},
                {"k": "only_on_failure", "label": "Only on failure", "check": True, "full": True}],
     "required": ["webhook_url"]},
    {"key": "testrail", "name": "TestRail", "mono": "TR", "tint": "#1F7F70", "desc": "Run results, and board cases on your go-ahead",
     "fields": [{"k": "base_url", "label": "Base URL", "full": True, "ph": "https://your-org.testrail.io"},
                {"k": "username", "label": "Username"}, {"k": "api_key", "label": "API key", "secret": True},
                {"k": "project_id", "label": "Project ID"}, {"k": "suite_id", "label": "Suite ID"}],
     "required": ["base_url", "username", "api_key", "project_id"]},
    {"key": "xray", "name": "Xray", "mono": "X", "tint": "#2E7D3E", "desc": "Import executions into Xray",
     "fields": [{"k": "client_id", "label": "Client ID"}, {"k": "client_secret", "label": "Client secret", "secret": True},
                {"k": "project_key", "label": "Project key", "full": True}],
     "required": ["client_id", "client_secret", "project_key"]},
    {"key": "zephyr", "name": "Zephyr Scale", "mono": "Z", "tint": "#B5501C", "desc": "Sync test cycles to Zephyr Scale",
     "fields": [{"k": "api_token", "label": "API token", "secret": True, "full": True, "ph": "Paste an API token"},
                {"k": "project_key", "label": "Project key"}],
     "required": ["api_token", "project_key"]},
    {"key": "aws", "name": "AWS S3", "mono": "S3", "tint": "#9A5B00", "desc": "Upload reports and screenshots",
     "fields": [{"k": "bucket", "label": "Bucket"}, {"k": "prefix", "label": "Prefix"},
                {"k": "region", "label": "Region", "options": [{"v": r, "label": r} for r in
                                                               ("us-east-1", "us-west-2", "eu-central-1", "eu-west-1", "eu-north-1")]},
                {"k": "profile", "label": "Profile"}, {"k": "public_base_url", "label": "Public base URL", "full": True}],
     "required": ["bucket"]},
]
STATUS_FILE = WORKFLOW_DIR / "integration-status.json"


def _status() -> dict:
    return json.loads(STATUS_FILE.read_text(encoding="utf-8")) if STATUS_FILE.exists() else {}


def _set_status(key: str, value: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps({**_status(), key: value}, indent=2), encoding="utf-8")


class Services:
    def __init__(self) -> None:
        ensure_dirs()
        WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
        issues, late = seed.jira_issues()
        self.workflow = Workflow(TicketStore(WORKFLOW_DIR / "tickets-demo.json"), TicketStore(WORKFLOW_DIR / "tickets.json"),
                                 MockJira(issues, late), MockTestRail())
        self.runs = RunManager()
        self.jira_pending: dict[str, dict] = {}  # Atlassian sign-ins in progress, by OAuth state

    def seed_demo(self) -> None:
        store = self.workflow.demo_store
        if store.tickets or store.done_keys:
            # Demo boards saved before FE/BE types only had Core/Frontend: take the types from the demo data.
            fresh = {t.key: t for t in seed.seed_tickets() + [seed.late_ticket()]}
            stale = [t for t in store.tickets.values() if t.key in fresh and (not t.components or not t.context or not t.issue_type)]
            for t in stale:
                f = fresh[t.key]
                t.type, t.components, t.context = f.type, f.components, f.context
                t.issue_type, t.priority, t.status_cat = f.issue_type, f.priority, f.status_cat
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
        base = load_settings().get("jira", {}).get("base_url") or "https://example.atlassian.net"
        d["jiraUrl"] = f"{base.rstrip('/')}/browse/{t.key}"
        d["envShort"] = agent.env_name(t, cfg) if t.env else ""
        return d


svc: Optional[Services] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global svc
    svc = Services()
    svc.seed_demo()
    svc.workflow.resume()
    yield
    for task in svc.workflow.tasks.values():
        task.cancel()


app = FastAPI(title="QA Engineer App", lifespan=lifespan)


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
                   "account": cfg.test_account, "ou": cfg.test_ou, "claude": bool(cfg.anthropic_api_key)},
        "tickets": [s.ticket_view(t) for t in store.all()],
        "finishedToday": store.finished_today(),
        "lastSync": store.last_sync,
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


# ------------------------------------------------------------------ runs (your Runner)
@app.get("/api/runs")
def list_runs() -> list[dict]:
    return S().runs.all()


@app.post("/api/runs")
async def start_run(opts: dict[str, Any] = Body(...)) -> dict:
    if not str(opts.get("url", "")).strip():
        raise HTTPException(422, "Enter a URL to test")
    try:
        return S().runs.start(opts)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    r = S().runs.get(run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    return r


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str) -> dict:
    return {"stopping": S().runs.stop(run_id)}


@app.post("/api/runs/{run_id}/publish")
async def publish(run_id: str) -> dict:
    if not (RUNS_DIR / run_id / "result.json").exists():
        raise HTTPException(404, "Run not found")
    return {"result": await asyncio.to_thread(S().runs.publish, run_id)}


@app.post("/api/runs/{run_id}/findings/{fid}/jira")
async def finding_jira(run_id: str, fid: str) -> dict:
    try:
        return {"key": await asyncio.to_thread(S().runs.create_jira, run_id, fid)}
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "Finding not found")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(502, str(e)[:300])


@app.post("/api/runs/{run_id}/open-folder")
def open_folder(run_id: str) -> dict:
    d = RUNS_DIR / run_id
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
        cards.append({**c, "values": values, "enabled": bool(settings.get(c["key"], {}).get("enabled")),
                      "result": status.get(c["key"])})
    return {"cards": cards, "mode": "mock" if WorkflowConfig.load().is_mock else "live"}


class IntegrationIn(BaseModel):
    values: dict[str, Any]
    enabled: bool


@app.put("/api/integrations/{key}")
def save_integration(key: str, body: IntegrationIn) -> dict:
    if key not in DEFAULT_SETTINGS:
        raise HTTPException(404)
    allowed = set(DEFAULT_SETTINGS[key])
    values = {k: v for k, v in body.values.items() if k in allowed}
    save_section(key, {**values, "enabled": body.enabled})
    return {"ok": True}


@app.post("/api/integrations/{key}/test")
async def test_integration(key: str, values: dict[str, Any] = Body(...)) -> dict:
    card = next((c for c in CATALOGUE if c["key"] == key), None)
    if not card:
        raise HTTPException(404)
    missing = [f["label"] for f in card["fields"] if f["k"] in card["required"] and not str(values.get(f["k"], "")).strip()]
    if missing:
        res = {"ok": False, "text": ", ".join(missing) + (" is required" if len(missing) == 1 else " are required")}
    elif key == "workflow":
        ws = str(values.get("workspace") or "").strip()
        res = {"ok": True, "text": "Demo data is on" if values.get("demo") else
               f"Live · {values['jira_project']} / {values['jira_column']}" + (f" · workspace {ws}" if ws else "")}
    elif key == "claude":
        res = await asyncio.to_thread(_test_claude, values)
    else:
        try:
            res = {"ok": True, "text": await asyncio.to_thread(integrations.test_connection, key, values)}
        except Exception as e:  # show the service's own error on the card
            res = {"ok": False, "text": (str(e).splitlines() or ["error"])[0][:300]}
    _set_status(key, res)
    return res


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
<p>{html.escape(text)}</p><p><a href="{html.escape(back)}">Back to QA Engineer App</a></p></body>""", status_code=200 if ok else 400)


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
@app.get("/files/{path:path}")
def app_file(path: str):
    """Screenshots, diffs and baselines for the Run screen. Only files inside the app folder."""
    p = (APP_DIR / path).resolve()
    if APP_DIR.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


app.mount("/runs", StaticFiles(directory=str(RUNS_DIR), html=True, check_dir=False), name="runs")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


__all__ = ["app", "SECRET_KEYS"]
