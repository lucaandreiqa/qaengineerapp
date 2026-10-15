"""The ticket runner: generated settings, live events while Playwright runs, evidence mapped to checks."""
from __future__ import annotations

import asyncio
import json
import stat
import sys

from qa_app.workflow import playwright_run as pr

FAKE = r'''#!PYTHON
import json, sys, time, pathlib
args = sys.argv[1:]
cfg_path = pathlib.Path(args[args.index("--config") + 1])
cfg = json.loads(cfg_path.read_text().split("module.exports = ", 1)[1].rstrip().rstrip(";"))
out = pathlib.Path(cfg["reporter"][0][1]["out"]); res = pathlib.Path(cfg["reporter"][1][1]["outputFile"])
art = pathlib.Path(cfg["outputDir"]); art.mkdir(parents=True, exist_ok=True)
def w(ev):
    with out.open("a") as f: f.write(json.dumps(ev) + "\n")
w({"type": "start", "total": 2})
w({"type": "begin", "n": 1, "title": "[1] Search ignores letter case"}); time.sleep(0.3)
w({"type": "end", "n": 1, "title": "[1] Search ignores letter case", "status": "passed", "duration": 5, "error": "", "qa": "", "attachments": []})
w({"type": "begin", "n": 2, "title": "[2] Empty search shows a hint"}); time.sleep(0.3)
shot = art / "t2" / "test-failed-1.png"; shot.parent.mkdir(parents=True, exist_ok=True); shot.write_bytes(b"png")
w({"type": "end", "n": 2, "title": "[2] Empty search shows a hint", "status": "failed", "duration": 7,
   "error": "expect(locator).toBeVisible() failed", "qa": "", "attachments": [
   {"name": "screenshot", "path": str(shot), "contentType": "image/png"},
   {"name": "trace", "path": "/etc/passwd", "contentType": "application/zip"}]})
w({"type": "done", "status": "failed"})
res.write_text(json.dumps({"suites": [{"specs": [
  {"title": "[1] Search ignores letter case", "tests": [{"results": [{"status": "passed"}]}]},
  {"title": "[2] Empty search shows a hint", "tests": [{"results": [{"status": "failed", "error": {"message": "expect(locator).toBeVisible() failed"}}]}]}]}]}))
sys.exit(1)
'''


def test_config_is_plain_commonjs_with_evidence_and_session(tmp_path):
    state = tmp_path / "storage-state.json"
    state.write_text("{}")
    js = pr.config_js(tmp_path / "run", tmp_path / "tickets" / "K-1", ["K-1.spec.ts"], "https://www.google.com/", state, False)
    cfg = json.loads(js.split("module.exports = ", 1)[1].rstrip().rstrip(";"))
    assert "require(" not in js and "import " not in js  # loadable from outside the workspace
    assert cfg["use"] == {"screenshot": "only-on-failure", "video": "retain-on-failure", "trace": "retain-on-failure",
                          "baseURL": "https://www.google.com/", "storageState": str(state)}
    assert cfg["testMatch"] == ["K-1.spec.ts"] and cfg["outputDir"].endswith("run/artifacts") and cfg["workers"] == 1
    every = json.loads(pr.config_js(tmp_path, tmp_path, [], "", None, True).split("module.exports = ", 1)[1].rstrip().rstrip(";"))
    assert every["use"]["screenshot"] == "on" and "storageState" not in every["use"] and "baseURL" not in every["use"]
    assert pr.result_of("passed") == "pass" and pr.result_of("timedOut") == "fail" and pr.result_of("passed", "blocked: no data") == "blocked"


def test_run_streams_events_and_maps_evidence_to_checks(tmp_path):
    npx = tmp_path / "npx"
    npx.write_text(FAKE.replace("#!PYTHON", "#!" + sys.executable))
    npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
    got = []

    async def on_event(ev):
        got.append((ev["type"], ev.get("n"), ev.get("result")))

    run_dir = tmp_path / "history" / "K-1-20261015"
    out = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(pr.run(
        run_dir=run_dir, test_dir=tmp_path, specs=["K-1.spec.ts"], workspace=tmp_path / "ws", base_url="https://x.test/",
        storage_state=None, every_check=False, extra_env={}, on_event=on_event, npx=str(npx), poll=0.05))
    assert got == [("start", None, None), ("begin", 1, None), ("end", 1, "pass"), ("begin", 2, None), ("end", 2, "fail"), ("done", None, None)]
    assert out["exit_code"] == 1 and out["report"]["suites"]
    assert out["attachments"] == {2: [{"kind": "screenshot", "path": "artifacts/t2/test-failed-1.png", "name": "screenshot"}]}  # outside files dropped
    assert out["errors"][2].startswith("expect") and (run_dir / "yourqa-reporter.js").exists()


# ---------------------------------------------------------------- never hang silently (SCRUM-8, 2026-10-15)
SETUP_NPM = r'''#!PYTHON
import os, sys, pathlib, stat
print("npm", " ".join(sys.argv[1:]), flush=True)
ws = pathlib.Path.cwd()
if sys.argv[1:2] == ["install"]:
    (ws / "node_modules" / "@playwright" / "test").mkdir(parents=True, exist_ok=True)
    b = ws / "node_modules" / ".bin"; b.mkdir(parents=True, exist_ok=True)
    pw = b / "playwright"
    pw.write_text(open(os.environ["FAKE_PW"]).read()); pw.chmod(pw.stat().st_mode | stat.S_IEXEC)
    print("added 3 packages", flush=True)
'''

PROMPTING_PW = r'''#!PYTHON
import sys, time
args = sys.argv[1:]
if args[:1] == ["install"]:
    print("Downloading Chromium 140.0 ... done", flush=True); sys.exit(0)
print("Ok to proceed? (y)", flush=True)
line = sys.stdin.readline()          # must get EOF at once, never wait for a person
print("stdin gave:", repr(line), flush=True)
time.sleep(float(__import__("os").environ.get("FAKE_SILENT", "0")))
sys.exit(3)
'''


def _exe(path, body):
    path.write_text(body.replace("#!PYTHON", "#!" + sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_missing_playwright_is_installed_with_visible_output_and_nothing_waits_for_input(tmp_path, monkeypatch):
    fake_pw = _exe(tmp_path / "fake_pw", PROMPTING_PW)
    monkeypatch.setenv("FAKE_PW", str(fake_pw))
    npm = _exe(tmp_path / "npm", SETUP_NPM)
    ws = tmp_path / "ws"
    out = []

    async def on_output(kind, text):
        out.append((kind, text))

    async def on_event(ev):
        pass

    loop = asyncio.get_event_loop_policy().new_event_loop()
    res = loop.run_until_complete(asyncio.wait_for(pr.run(
        run_dir=tmp_path / "run", test_dir=tmp_path, specs=["K.spec.ts"], workspace=ws, base_url="", storage_state=None,
        every_check=False, extra_env={}, on_event=on_event, on_output=on_output, npm=str(npm), poll=0.05), timeout=20))
    text = [t for _, t in out]
    assert (ws / "package.json").exists() and json.loads((ws / "package.json").read_text())["devDependencies"]["@playwright/test"]
    assert any("npm install" in t for t in text) and any("Downloading Chromium" in t for t in text)  # setup is visible
    assert any("stdin gave: ''" in t for t in text)  # EOF, not a wait
    assert res["exit_code"] == 3 and res["report"] is None


def test_a_silent_run_is_reported_while_it_is_silent(tmp_path, monkeypatch):
    fake_pw = _exe(tmp_path / "fake_pw", PROMPTING_PW)
    ws = tmp_path / "ws"
    (ws / "node_modules" / "@playwright" / "test").mkdir(parents=True)
    (ws / "node_modules" / ".bin").mkdir(parents=True)
    _exe(ws / "node_modules" / ".bin" / "playwright", PROMPTING_PW)
    monkeypatch.setenv("FAKE_SILENT", "1.5")
    out = []

    async def on_output(kind, text):
        out.append((kind, text))

    async def on_event(ev):
        pass

    loop = asyncio.get_event_loop_policy().new_event_loop()
    loop.run_until_complete(pr.run(run_dir=tmp_path / "run", test_dir=tmp_path, specs=["K.spec.ts"], workspace=ws, base_url="",
                                   storage_state=None, every_check=False, extra_env={}, on_event=on_event, on_output=on_output,
                                   poll=0.05, stall_after=0.5))
    stalls = [t for k, t in out if k == "stall"]
    assert stalls and "No output for" in stalls[0] and "stdin gave" in stalls[0]  # says what it last printed
