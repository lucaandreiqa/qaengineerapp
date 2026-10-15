"""Run a ticket's Playwright spec(s) into a History run folder, reporting each check as it finishes.

Each run gets its own settings file (playwright.config.js) and a small reporter (yourqa-reporter.js) in the run
folder, so it doesn't depend on what is or isn't in the user's Playwright workspace:

  use.baseURL       the ticket's environment
  use.storageState  the saved SSO session, when there is one
  screenshots on failure (or every check), video and trace kept for failing checks
  outputDir         <run>/artifacts · JSON report <run>/results.json · HTML report <run>/report

Both files are plain CommonJS with no imports, so Node can load them from outside the workspace. The specs themselves
stay in the workspace and resolve @playwright/test from there.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Awaitable, Callable, Optional

REPORTER = r"""// YourQA live reporter: one JSON line per event, read by the app while the run is going.
const fs = require('fs');
class YourQAReporter {
  constructor(options) { this.out = options.out; }
  w(ev) { fs.appendFileSync(this.out, JSON.stringify(ev) + '\n'); }
  n(test) { const m = /^\[(\d+)\]/.exec(test.title || ''); return m ? Number(m[1]) : null; }
  onBegin(config, suite) { this.w({ type: 'start', total: suite.allTests().length }); }
  onTestBegin(test) { this.w({ type: 'begin', n: this.n(test), title: test.title }); }
  onTestEnd(test, result) {
    const ann = {};
    (test.annotations || []).forEach((a) => { ann[a.type] = a.description || ''; });
    const err = result.error ? String(result.error.message || result.error.value || '').replace(/\x1b\[[0-9;]*m/g, '') : '';
    this.w({ type: 'end', n: this.n(test), title: test.title, status: result.status, duration: result.duration,
             error: err.slice(0, 2000), qa: ann['qa-result'] || '',
             attachments: (result.attachments || []).filter((a) => a.path).map((a) => ({ name: a.name, path: a.path, contentType: a.contentType || '' })) });
  }
  onEnd(result) { this.w({ type: 'done', status: result.status }); }
}
module.exports = YourQAReporter;
"""

Event = dict
OnEvent = Callable[[Event], Awaitable[None]]


def config_js(run_dir: Path, test_dir: Path, specs: list[str], base_url: str, storage_state: Optional[Path],
              every_check: bool) -> str:
    use = {"screenshot": "on" if every_check else "only-on-failure", "video": "retain-on-failure",
           "trace": "retain-on-failure"}
    if base_url:
        use["baseURL"] = base_url
    if storage_state and storage_state.exists():
        use["storageState"] = str(storage_state)
    cfg = {
        "testDir": str(test_dir),
        "testMatch": specs,
        "outputDir": str(run_dir / "artifacts"),
        "timeout": 60000,
        "workers": 1,
        "reporter": [[str(run_dir / "yourqa-reporter.js"), {"out": str(run_dir / "events.jsonl")}],
                     ["json", {"outputFile": str(run_dir / "results.json")}],
                     ["html", {"outputFolder": str(run_dir / "report"), "open": "never"}]],
        "use": use,
    }
    return "// Written by YourQA for this run.\nmodule.exports = " + json.dumps(cfg, indent=2) + ";\n"


def result_of(status: str, qa: str = "") -> str:
    """A test's outcome as a checklist result (same rules as the JSON report parser)."""
    if qa.startswith("blocked"):
        return "blocked"
    if qa.startswith("partial"):
        return "partial"
    if status == "passed":
        return "pass"
    if status in {"failed", "timedOut", "interrupted"}:
        return "fail"
    return "nt"


def attachment_kind(a: dict) -> str:
    ct, name = (a.get("contentType") or "").lower(), (a.get("name") or "").lower()
    if ct.startswith("image/") or name == "screenshot":
        return "screenshot"
    if ct.startswith("video/") or name == "video":
        return "video"
    if "trace" in name or ct == "application/zip":
        return "trace"
    return "file"


def relative_attachments(run_dir: Path, atts: list[dict]) -> list[dict]:
    out = []
    base = run_dir.resolve()
    for a in atts:
        p = Path(a.get("path", ""))
        try:
            rel = p.resolve().relative_to(base).as_posix()
        except (ValueError, OSError):
            continue  # outside the run folder: not evidence we serve
        out.append({"kind": attachment_kind(a), "path": rel, "name": a.get("name", "")})
    return out


def read_events(path: Path, offset: int) -> tuple[list[Event], int]:
    if not path.exists():
        return [], offset
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
    end = data.rfind(b"\n")
    if end < 0:
        return [], offset
    events = []
    for line in data[:end].splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events, offset + end + 1


PACKAGE_JSON = {"name": "yourqa-workspace", "private": True, "description": "Playwright workspace for YourQA ticket tests",
                "devDependencies": {"@playwright/test": "^1.48.0"}}
OnOutput = Callable[[str, str], Awaitable[None]]


async def _nothing(kind: str, text: str) -> None:
    return None


def local_playwright(workspace: Path) -> Optional[Path]:
    """The workspace's own Playwright CLI, when @playwright/test is installed there."""
    if not (workspace / "node_modules" / "@playwright" / "test").exists():
        return None
    for name in ("playwright.cmd", "playwright") if os.name == "nt" else ("playwright",):
        p = workspace / "node_modules" / ".bin" / name
        if p.exists():
            return p
    return None


async def _stream(cmd: list[str], cwd: Path, env: dict, on_output: OnOutput, label: str) -> tuple[int, list[str]]:
    """Run a setup command with its output shown line by line. Input is closed: nothing can wait for a person."""
    await on_output("sys", f"$ {label}")
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    tail: list[str] = []
    assert proc.stdout
    try:
        async for raw in proc.stdout:
            line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw.decode("utf-8", "replace")).rstrip()
            if line:
                tail = (tail + [line])[-20:]
                await on_output("out", line)
        return await proc.wait(), tail
    except asyncio.CancelledError:  # Stop pressed during setup
        if proc.returncode is None:
            proc.kill()
        raise


async def prepare_workspace(workspace: Path, on_output: OnOutput, npm: Optional[str] = None) -> Path:
    """Make sure the workspace can run Playwright: package.json, @playwright/test and Chromium. Done once."""
    found = local_playwright(workspace)
    if found:
        return found
    npm = npm or shutil.which("npm")
    if not npm:
        raise RuntimeError("Node.js isn't installed (npm not found). Install Node.js from https://nodejs.org, then run the tests again.")
    workspace.mkdir(parents=True, exist_ok=True)
    pkg = workspace / "package.json"
    if not pkg.exists():
        pkg.write_text(json.dumps(PACKAGE_JSON, indent=2) + "\n", encoding="utf-8")
        await on_output("sys", f"Created {pkg}")
    env = {**os.environ, "CI": "1", "npm_config_yes": "true"}
    await on_output("sys", "Playwright isn't installed in the test workspace yet. Installing it (once, about a minute)…")
    code, tail = await _stream([npm, "install", "--no-audit", "--no-fund"], workspace, env, on_output, "npm install")
    found = local_playwright(workspace)
    if code != 0 or not found:
        raise RuntimeError("Installing Playwright failed (npm install exited " + str(code) + "): " + " / ".join(tail[-3:]))
    code, tail = await _stream([str(found), "install", "chromium"], workspace, env, on_output, "npx playwright install chromium")
    if code != 0:
        raise RuntimeError("Installing the Chromium browser failed: " + " / ".join(tail[-3:]))
    await on_output("sys", "Playwright is ready.")
    return found


async def run(*, run_dir: Path, test_dir: Path, specs: list[str], workspace: Path, base_url: str,
              storage_state: Optional[Path], every_check: bool, extra_env: dict, on_event: OnEvent,
              on_output: Optional[OnOutput] = None, npm: Optional[str] = None, npx: Optional[str] = None,
              poll: float = 0.5, stall_after: float = 45.0) -> dict:
    """Run the specs. Every line Playwright prints goes to on_output(kind, line) as it happens (kind: out / err / sys /
    stall), and a silent stretch longer than stall_after seconds is reported with the last line printed.
    Returns {exit_code, report (Playwright JSON or None), attachments {n: [...]}, errors {n: str}, stderr}.
    Raises RuntimeError when Playwright can't be set up or started."""
    on_output = on_output or _nothing
    run_dir.mkdir(parents=True, exist_ok=True)
    if npx:  # an explicit runner (tests)
        cmd_base = [npx, "playwright"]
    else:
        cmd_base = [str(await prepare_workspace(workspace, on_output, npm))]
    (run_dir / "yourqa-reporter.js").write_text(REPORTER, encoding="utf-8")
    cfg_file = run_dir / "playwright.config.js"
    cfg_file.write_text(config_js(run_dir, test_dir, specs, base_url, storage_state, every_check), encoding="utf-8")
    events_file = run_dir / "events.jsonl"
    events_file.unlink(missing_ok=True)
    env = {**os.environ, **extra_env, "PLAYWRIGHT_JSON_OUTPUT_NAME": str(run_dir / "results.json"), "CI": "1",
           "FORCE_COLOR": "0", "PLAYWRIGHT_HTML_OPEN": "never"}
    if base_url:
        env["BASE_URL"] = base_url
    if storage_state and storage_state.exists():
        env["QA_STORAGE_STATE"] = str(storage_state)
    workspace.mkdir(parents=True, exist_ok=True)
    await on_output("sys", f"$ npx playwright test --config {cfg_file}")
    proc = await asyncio.create_subprocess_exec(*cmd_base, "test", "--config", str(cfg_file), cwd=str(workspace), env=env,
                                                stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    attachments: dict[int, list[dict]] = {}
    errors: dict[int, str] = {}
    offset = 0
    loop = asyncio.get_running_loop()
    last = {"t": loop.time(), "line": "", "warned": False}
    out_lines: list[str] = []
    err_lines: list[str] = []

    def active(line: str = "") -> None:
        last["t"], last["warned"] = loop.time(), False
        if line:
            last["line"] = line

    async def pump(stream, kind: str, keep: list[str]) -> None:
        async for raw in stream:
            line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw.decode("utf-8", "replace")).rstrip()
            if not line.strip():
                continue
            keep.append(line)
            del keep[:-400]
            active(line)
            await on_output(kind, line)

    async def drain() -> None:
        nonlocal offset
        evs, offset = read_events(events_file, offset)
        for ev in evs:
            active()
            if ev.get("type") == "end" and ev.get("n"):
                n = int(ev["n"])
                atts = relative_attachments(run_dir, ev.get("attachments") or [])
                if atts:
                    attachments[n] = atts
                    ev["attachments"] = atts
                if ev.get("error"):
                    errors[n] = ev["error"]
                ev["result"] = result_of(ev.get("status", ""), ev.get("qa", ""))
            await on_event(ev)

    pumps = [asyncio.ensure_future(pump(proc.stdout, "out", out_lines)), asyncio.ensure_future(pump(proc.stderr, "err", err_lines))]
    waiter = asyncio.ensure_future(proc.wait())
    try:
        while not waiter.done():
            await asyncio.sleep(poll)
            await drain()
            quiet = loop.time() - last["t"]
            if quiet >= stall_after and not last["warned"]:
                last["warned"] = True
                await on_output("stall", f"No output for {int(quiet)}s. Last line: {last['line'] or '(nothing printed yet)'}")
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        raise
    await asyncio.gather(*pumps, return_exceptions=True)
    await drain()
    report = None
    rj = run_dir / "results.json"
    raw = rj.read_text(encoding="utf-8") if rj.exists() else ""
    try:
        report = json.loads(raw) if raw.strip() else None
    except ValueError:
        report = None
    (run_dir / "terminal.log").write_text("\n".join(out_lines + (["--- stderr ---"] + err_lines if err_lines else [])) + "\n",
                                          encoding="utf-8")
    return {"exit_code": proc.returncode, "report": report, "attachments": attachments, "errors": errors,
            "stderr": "\n".join((err_lines or out_lines)[-15:])[-1500:]}
