"""The work behind each lane: context, environment, checklist, spec, run, report, TestRail draft.

Claude (via the Anthropic API) writes the scenarios, checklist and spec when the Claude integration is on.
Without a key the app falls back to deterministic templates, so the workflow still runs end to end.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

import requests

from ..integrations.jira import find_pr_environment
from .models import CheckItem, CleanupItem, DraftCase, Env, Section, Ticket
from .settings import WorkflowConfig as Config

RES_LABEL = {"pass": "PASS", "partial": "PARTIAL", "fail": "FAIL", "blocked": "BLOCKED", "nt": "NOT TESTED"}
RES_ICON = {"pass": "✅", "partial": "⚠️", "fail": "❌", "blocked": "🚫", "nt": "⬜"}


# --------------------------------------------------------------------------------------
# Files in tests/tickets/<KEY>/
# --------------------------------------------------------------------------------------

def ticket_files(cfg: Config, t: Ticket) -> list[dict]:
    d = cfg.ticket_dir(t.key)
    names = [f"{t.key}-context.md", f"{t.key}-scenarios.md", f"{t.key}-qa-checklist.md", f"{t.key}.spec.ts"]
    if t.serial:
        names.append(f"{t.key}.serial.spec.ts")
    names += [f"{t.key}-report.md", f"{t.key}-testrail-cases.md"]
    return [{"name": n, "ok": (d / n).exists()} for n in names]


def write_file(cfg: Config, key: str, name: str, text: str) -> Path:
    d = cfg.ticket_dir(key)
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


def checklist_md(t: Ticket) -> str:
    lines = [f"# {t.key} QA checklist", "", f"{t.title}", ""]
    n = 0
    for si, sec in enumerate(t.checklist, 1):
        lines.append(f"## {si}. {sec.name}")
        for it in sec.items:
            n += 1
            lines.append(f"{n}. [{RES_LABEL[it.result]}] {it.text}")
            if it.bug:
                lines.append(f"   - Bug: {it.bug}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Environment resolution (Phase 1)
# --------------------------------------------------------------------------------------

def resolve_environment(issue: dict, cfg: Config) -> tuple[Optional[Env], str]:
    """Merged tickets use the shared environment. Otherwise a PR or preview link is required;
    the workflow stops rather than falling back to the shared one, because the change may not be there yet."""
    if issue.get("merged"):
        return Env(kind=f"Shared {cfg.shared_env_name} · ticket is merged", url=f".env defaults ({cfg.shared_env_name})",
                   api="Shared environment rules: confirm before changing sensitive settings", shared=True), ""
    pr_env = find_pr_environment(issue.get("comments", []))
    if pr_env:
        return Env(kind="PR environment", url=pr_env, api="Found in the ticket comments"), ""
    if issue.get("comp") == "Frontend" and issue.get("preview_url"):
        url = issue["preview_url"]
        kind = "Cloudflare Pages preview" if "pages.dev" in url else "Frontend preview"
        return Env(kind=kind, url=url, api="API: paired from the preview's network requests"), ""
    return None, (f"{issue.get('comp', 'Core')} ticket, status {issue.get('status')}, and no PR environment link "
                  f"in its comments. Stopped instead of falling back to {cfg.shared_env_name}.")


def env_name(t: Ticket, cfg: Config) -> str:
    if not t.env:
        return "unknown"
    if t.env.shared:
        return cfg.shared_env_name
    return re.sub(r"^https?://", "", t.env.url).rstrip("/")


# --------------------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------------------

def _ask_claude_sync(cfg: Config, system: str, prompt: str, max_tokens: int) -> str:
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, headers={
        "x-api-key": cfg.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json",
    }, json={"model": cfg.anthropic_model, "max_tokens": max_tokens, "system": system,
             "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []))


async def ask_claude(cfg: Config, system: str, prompt: str, max_tokens: int = 4000) -> str:
    return await asyncio.to_thread(_ask_claude_sync, cfg, system, prompt, max_tokens)


def _json_block(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Claude did not return JSON")
    return json.loads(m.group(0))


QA_SYSTEM = ("You are a senior QA engineer. You write precise, testable checklist items phrased as capability "
             "statements ('Search ignores letter case'), grouped into short sections. Never invent results.")


async def plan_checklist(cfg: Config, issue: dict, env: Env) -> tuple[str, list[Section], bool]:
    """Returns (scenarios markdown, checklist sections, serial_needed)."""
    if cfg.anthropic_api_key:
        prompt = (f"Ticket {issue['key']}: {issue['title']}\nComponent: {issue.get('comp')}\nStatus: {issue.get('status')}\n"
                  f"Environment: {env.kind} {env.url}\n\nDescription:\n{issue.get('description', '')}\n\n"
                  f"Comments:\n" + "\n---\n".join(issue.get("comments", [])[-10:]) +
                  "\n\nReturn JSON only: {\"scenarios\": \"markdown\", \"serial\": bool (true if multi-user or "
                  "concurrency scenarios exist), \"sections\": [{\"name\": str, \"items\": [str]}]}. 2-4 sections, 2-5 items each.")
        data = _json_block(await ask_claude(cfg, QA_SYSTEM, prompt))
        sections = [Section(name=s["name"], items=[CheckItem(text=i) for i in s["items"]]) for s in data["sections"]]
        return data.get("scenarios", ""), sections, bool(data.get("serial"))
    # Template fallback: one section from the description's bullet points, plus regression basics.
    bullets = [b.strip(" -*•\t") for b in issue.get("description", "").splitlines() if b.strip().startswith(("-", "*", "•"))]
    main = Section(name="Acceptance criteria", items=[CheckItem(text=b) for b in bullets] or [CheckItem(text=f"{issue['title']} works as described")])
    reg = Section(name="Regression", items=[CheckItem(text="Existing behaviour on the same screen is unchanged"),
                                             CheckItem(text="No console errors while using the feature")])
    scen = "\n".join(f"- Scenario: {i.text}" for s in (main, reg) for i in s.items)
    return scen, [main, reg], False


SPEC_SYSTEM = ("You write Playwright Test specs in TypeScript. Each checklist item becomes exactly one test whose title "
               "starts with its number in brackets, e.g. test('[3] Search ignores letter case', ...). For a partial or "
               "blocked outcome call test.info().annotations.push({type: 'qa-result', description: 'partial'|'blocked: reason'}). "
               "Prefix every piece of test data with the ticket key. Every setting you change must be reverted and "
               "re-read in afterAll, and appended as JSON lines {name, value, reread} to process.env.QA_CLEANUP_FILE. "
               "Output only the TypeScript file.")


def spec_template(t: Ticket, cfg: Config, serial: bool = False) -> str:
    base = t.env.url if t.env and t.env.url.startswith("http") else "process.env.BASE_URL"
    base_expr = f"'{base}'" if base.startswith("http") else base
    lines = [
        "import { test, expect } from '@playwright/test';",
        "import fs from 'node:fs';",
        "",
        f"// {t.key}: {t.title}",
        f"// Runs as {cfg.test_account} in OU {cfg.test_ou}. Test data is prefixed {t.key}.",
        f"const BASE = {base_expr};",
        "const cleanup: { name: string; value: string; reread: boolean }[] = [];",
        "",
        f"test.describe{'.serial' if serial else ''}('{t.key}', () => {{",
        "  test.afterAll(async () => {",
        "    // Revert every setting changed above, re-read it, then record it for the report.",
        "    if (process.env.QA_CLEANUP_FILE) fs.writeFileSync(process.env.QA_CLEANUP_FILE, cleanup.map((c) => JSON.stringify(c)).join('\\n'));",
        "  });",
        "",
    ]
    n = 0
    for sec in t.checklist:
        lines.append(f"  // {sec.name}")
        for it in sec.items:
            n += 1
            title = it.text.replace("'", "\\'")
            lines += [f"  test('[{n}] {title}', async ({{ page }}) => {{",
                      "    await page.goto(BASE);",
                      "    test.fixme(true, 'Steps not written yet');",
                      "  });", ""]
    lines.append("});")
    return "\n".join(lines) + "\n"


async def build_spec(cfg: Config, t: Ticket) -> list[str]:
    files = []
    if cfg.anthropic_api_key and not cfg.is_mock:
        prompt = (f"Ticket {t.key}: {t.title}\nBase URL: {t.env.url if t.env else 'process.env.BASE_URL'}\n"
                  f"Test account (SSO, storage state is preloaded): {cfg.test_account}, OU {cfg.test_ou}\n\n"
                  f"Checklist:\n{checklist_md(t)}")
        spec = await ask_claude(cfg, SPEC_SYSTEM, prompt, max_tokens=8000)
        spec = re.sub(r"^```\w*\n|```\s*$", "", spec.strip(), flags=re.M)
    else:
        spec = spec_template(t, cfg)
    files.append(str(write_file(cfg, t.key, f"{t.key}.spec.ts", spec)))
    if t.serial:
        files.append(str(write_file(cfg, t.key, f"{t.key}.serial.spec.ts", spec_template(t, cfg, serial=True))))
    return files


# --------------------------------------------------------------------------------------
# Running the spec (Phase 2)
# --------------------------------------------------------------------------------------

def _walk_specs(suite: dict):
    for s in suite.get("suites", []):
        yield from _walk_specs(s)
    for spec in suite.get("specs", []):
        yield spec


def parse_playwright_json(report: dict, n_items: int) -> list[tuple[str, str]]:
    """Map Playwright JSON reporter output to checklist results by the [n] title prefix."""
    out: list[tuple[str, str]] = [("nt", "") for _ in range(n_items)]
    for suite in report.get("suites", []):
        for spec in _walk_specs(suite):
            m = re.match(r"\[(\d+)\]", spec.get("title", ""))
            if not m:
                continue
            idx = int(m.group(1)) - 1
            if not 0 <= idx < n_items:
                continue
            for test in spec.get("tests", []):
                notes = {a.get("type"): a.get("description", "") for a in test.get("annotations", [])}
                res = (test.get("results") or [{}])[-1]
                status = res.get("status", "skipped")
                err = (res.get("error") or {}).get("message", "")
                err = re.sub(r"\x1b\[[0-9;]*m", "", err).strip().splitlines()[0][:300] if err else ""
                qa = notes.get("qa-result", "")
                if qa.startswith("blocked"):
                    out[idx] = ("blocked", qa.partition(":")[2].strip())
                elif qa.startswith("partial"):
                    out[idx] = ("partial", qa.partition(":")[2].strip())
                elif status == "passed":
                    out[idx] = ("pass", "")
                elif status in {"failed", "timedOut", "interrupted"}:
                    out[idx] = ("fail", err)
                else:  # skipped / fixme
                    out[idx] = ("nt", "")
    return out


async def run_spec(cfg: Config, t: Ticket, log) -> tuple[list[tuple[str, str]], list[CleanupItem]]:
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("npx is not installed; Node.js and @playwright/test are needed to run ticket specs")
    tdir = cfg.ticket_dir(t.key)
    cleanup_file = tdir / f"{t.key}-cleanup.jsonl"
    cleanup_file.unlink(missing_ok=True)
    specs = [str(tdir / f"{t.key}.spec.ts")] + ([str(tdir / f"{t.key}.serial.spec.ts")] if t.serial else [])
    env = {**os.environ, "QA_CLEANUP_FILE": str(cleanup_file), "PLAYWRIGHT_JSON_OUTPUT_NAME": str(tdir / "results.json")}
    if t.env and t.env.url.startswith("http"):
        env["BASE_URL"] = t.env.url
    state = cfg.auth_dir / "storage-state.json"
    if state.exists():
        env["QA_STORAGE_STATE"] = str(state)
    proc = await asyncio.create_subprocess_exec(npx, "playwright", "test", *specs, "--reporter=json", cwd=str(cfg.workspace),
                                                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    raw = (tdir / "results.json").read_text(encoding="utf-8") if (tdir / "results.json").exists() else stdout.decode("utf-8", "replace")
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("Playwright did not produce a JSON report: " + stderr.decode("utf-8", "replace")[-400:])
    results = parse_playwright_json(report, len(t.items()))
    cleanup = []
    if cleanup_file.exists():
        for line in cleanup_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                c = json.loads(line)
                cleanup.append(CleanupItem(name=c["name"], value=str(c["value"]), reread=bool(c.get("reread", True))))
    log(f"Playwright exited {proc.returncode}")
    return results, cleanup


def apply_results(t: Ticket, results: list[tuple[str, str]]) -> None:
    for item, (res, bug) in zip(t.items(), results):
        item.result = res  # type: ignore[assignment]
        item.bug = bug
        item.severity = None
        if res == "fail":
            item.severity = "Major" if re.search(r"\b(major|critical)\b", bug, re.I) else "Minor"


def report_md(t: Ticket, cfg: Config) -> str:
    items = t.items()
    c = {k: sum(1 for i in items if i.result == k) for k in RES_LABEL}
    lines = [f"# {t.key} QA report", "", f"{t.title}", "",
             f"- Environment: {t.env.kind if t.env else 'unknown'} · {t.env.url if t.env else ''}",
             f"- Account: {cfg.test_account} · OU {cfg.test_ou}",
             f"- Result: {c['pass']} pass · {c['partial']} partial · {c['fail']} fail · {c['blocked']} blocked · {c['nt']} not tested", "",
             checklist_md(t), "## Cleanup"]
    lines += [f"- {cl.name}: reverted to {cl.value}{' · re-read ✓' if cl.reread else ' · NOT re-read'}" for cl in t.cleanup] or ["- No settings were changed."]
    if t.left:
        lines.append(f"- Left behind: {t.left}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Jira comment (Phase 3)
# --------------------------------------------------------------------------------------

def comment_text(t: Ticket, cfg: Config, today: Optional[date] = None) -> str:
    today = today or date.today()
    items = t.items()
    passed = sum(1 for i in items if i.result == "pass")
    out = (f"QA result: {passed}/{len(items)} checks pass. Verified {today.day} {today.strftime('%b %Y')} against "
           f"{env_name(t, cfg)} (SSO account {cfg.test_account}, OU {cfg.test_ou}).")
    if t.left:
        out += f" All test data created this pass is isolated and traceable, prefixed {t.key}."
    for sec in t.checklist:
        ok = [i for i in sec.items if i.result == "pass"]
        if ok:
            out += f"\n\n**{sec.name}**\n" + "\n".join(f"✅ {i.text}" for i in ok)
    other = [i for i in items if i.result != "pass"]
    if other:
        out += "\n\n**Not covered this pass**\n" + "\n".join(
            f"{RES_ICON[i.result]} {i.text}" + (f" ({i.severity or 'Minor'})" if i.result == "fail" else "") for i in other)
    return out + f"\n\n{cfg.signature}"


def exact_transition(transitions: list[dict], target: str) -> Optional[dict]:
    """Exact, case-sensitive name match. Never fuzzy-match a Jira transition."""
    for tr in transitions:
        if tr["name"] == target:
            return tr
    return None


# --------------------------------------------------------------------------------------
# TestRail draft (Phase 4)
# --------------------------------------------------------------------------------------

def draft_cases(t: Ticket) -> list[DraftCase]:
    return [DraftCase(title=i.text, steps=f"Ticket {t.key}. Verify: {i.text}", expected=i.text)
            for i in t.items() if i.result == "pass"]


def cases_md(t: Ticket) -> str:
    lines = [f"# {t.key} TestRail cases (draft)", "", f"Section: {t.section}", ""]
    lines += [f"{n}. {c.title}" for n, c in enumerate(t.cases, 1)]
    return "\n".join(lines) + "\n"
