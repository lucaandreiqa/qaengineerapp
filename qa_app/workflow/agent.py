"""The work behind each lane: context, environment, checklist, spec, run, report, TestRail draft.

Claude (via the Anthropic API) writes the scenarios, checklist and spec when the Claude integration is on.
Without a key the app falls back to deterministic templates, so the workflow still runs end to end.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import requests

from .models import CheckItem, CleanupItem, DraftCase, Env, Section, Ticket, has_fe, type_label
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
    """Where to test, from what the ticket says (see environments.py). Sets issue["env_candidates"] for the drawer.

    1. Merged or done, and a default environment is set in settings: the default environment.
    2. A link on the ticket that is clearly the test environment: that link (and its API link if one is given).
    3. Otherwise stop at "Needs environment": every link is listed, the best one suggested, and the user confirms it,
       picks another or types one, instead of the app guessing between several.
    """
    from . import environments

    ctx = issue.get("context") or {"description": issue.get("description", ""), "status": issue.get("status", ""),
                                   "comments": [{"body": c} for c in issue.get("comments", [])]}
    found = environments.find(ctx, list(cfg.env_hints), cfg.jira_host)
    sug = environments.suggest(found, issue.get("type", ""))
    issue["env_candidates"] = [c.public() for c in found[:30]]
    if environments.looks_released(ctx, bool(issue.get("merged"))) and cfg.default_env_url:
        why = "merged" if issue.get("merged") else (ctx.get("status") or "done").lower()
        return Env(kind=f"{cfg.shared_env_name} · ticket is {why}", url=cfg.default_env_url, shared=True, source="settings",
                   api="Default environment from settings: confirm before changing sensitive settings"), ""
    app, api = environments.choose(found, issue.get("type", ""))
    if app:
        kind = "API" if app.api else "Test environment"
        return Env(kind=kind, url=app.url, source=app.source,
                   api=f"API: {api.url}" if api else ("Backend link from the ticket" if app.api else "API: whatever this site calls")), ""
    ttype = type_label(issue.get("type", ""))
    n = len(environments.likely(found))
    if sug and n > 1:
        return None, (f"Found {n} links that could be where to test this {ttype} ticket. Suggested: "
                      f"{re.sub(r'^https?://', '', sug.url).rstrip('/')}. Use it, pick another, or type the address.")
    if sug:
        return None, (f"Found {len(found)} link{'s' if len(found) != 1 else ''} on the ticket, but none says it's where to test "
                      f"this {ttype} ticket. Suggested: {re.sub(r'^https?://', '', sug.url).rstrip('/')}. Use it, pick another, "
                      "or type the address.")
    if found:
        return None, (f"The links on this {ttype} ticket look like tools or files, not a test environment. "
                      "Pick one below if it is, or type the address.")
    return None, (f"No test environment link in this {ttype} ticket's description, comments, fields or links. "
                  "Paste the URL to test on.")


def who(cfg: Config) -> str:
    """The test account, plus the test scope (store, tenant, workspace…) when one is set."""
    return (cfg.test_account or "the signed-in test account") + (f" in {cfg.test_ou}" if cfg.test_ou else "")


def env_name(t: Ticket, cfg: Config) -> str:
    if not t.env:
        return "unknown"
    if t.env.shared:
        return cfg.shared_env_name
    return re.sub(r"^https?://", "", t.env.url).rstrip("/")


# --------------------------------------------------------------------------------------
# Claude
# --------------------------------------------------------------------------------------

# The ticket a step is working on, set by the engine, so each Claude call's cost lands on the right ticket.
CURRENT_TICKET: contextvars.ContextVar[str] = contextvars.ContextVar("qa_current_ticket", default="")
# Called after every Claude call with (ticket key, step, model, usage block, billing "api" | "plan").
usage_listeners: list[Callable[[str, str, str, dict, str], None]] = []


def _ask_claude_sync(cfg: Config, system: str, prompt: str, max_tokens: int) -> tuple[str, str, dict]:
    r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, headers={
        "x-api-key": cfg.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json",
    }, json={"model": cfg.anthropic_model, "max_tokens": max_tokens, "system": system,
             "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []))
    return text, data.get("model") or cfg.anthropic_model, data.get("usage") or {}


async def ask_claude(cfg: Config, system: str, prompt: str, max_tokens: int = 4000, step: Optional[str] = None) -> str:
    if cfg.claude_mode == "claude_code":  # the Claude Code CLI on this computer, on the user's own Claude plan
        from . import claude_code
        text, model, usage = await asyncio.to_thread(claude_code.ask, cfg.anthropic_model, system, prompt)
        billing = "plan"
    else:
        text, model, usage = await asyncio.to_thread(_ask_claude_sync, cfg, system, prompt, max_tokens)
        billing = "api"
    found = re.search(r'<skill step="([^"]+)"', system)
    step = step or (found.group(1) if found else "other")
    for listener in list(usage_listeners):
        try:
            listener(CURRENT_TICKET.get(), step, model, usage, billing)
        except Exception:  # cost tracking never breaks a step
            pass
    return text


def _json_block(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Claude did not return JSON")
    return json.loads(m.group(0))


QA_SYSTEM = ("You are a senior QA engineer. You write precise, testable checklist items phrased as capability "
             "statements ('Search ignores letter case'), grouped into short sections. Never invent results.")


def system(base: str, step: str, cfg: Config) -> str:
    """The step's base instructions plus its skill (general, refined for the Jira project when it has its own)."""
    from . import skills
    return base + skills.for_prompt(step, cfg.jira_project)


def skill_source(step: str, cfg: Config) -> str:
    from . import skills
    return skills.effective(step, cfg.jira_project)[1]


async def plan_checklist(cfg: Config, issue: dict, env: Env) -> tuple[str, list[Section], bool]:
    """Returns (scenarios markdown, checklist sections, serial_needed)."""
    if cfg.claude_ready:
        if issue.get("context"):  # the whole ticket: every field, all comments, links, attachments
            from .ticket_context import for_prompt
            ticket = for_prompt(issue["context"], extra={
                "QA type": f"{type_label(issue.get('type', ''))} (Jira components: {', '.join(issue.get('components', [])) or 'none'})"})
        else:
            ticket = (f"Ticket {issue['key']}: {issue['title']}\nType: {type_label(issue.get('type', ''))}\nStatus: {issue.get('status')}\n\n"
                      f"Description:\n{issue.get('description', '')}\n\nComments:\n" + "\n---\n".join(issue.get("comments", [])))
        prompt = (f"{ticket}\n\nTest environment: {env.kind} {env.url}\n\n"
                  "Use everything above: description, acceptance criteria, every comment (later comments can change "
                  "what was agreed), labels, versions, linked tickets and attachments by name."
                  "\n\nReturn JSON only: {\"scenarios\": \"markdown\", \"serial\": bool (true if multi-user or "
                  "concurrency scenarios exist), \"sections\": [{\"name\": str, \"items\": [str]}]}. 2-4 sections, 2-5 items each.")
        data = _json_block(await ask_claude(cfg, system(QA_SYSTEM, "gather", cfg), prompt))
        sections = [Section(name=s["name"], items=[CheckItem(text=i) for i in s["items"]]) for s in data["sections"]]
        return data.get("scenarios", ""), sections, bool(data.get("serial"))
    # Template fallback: one section from the description's bullet points, plus regression basics.
    ctx = issue.get("context") or {}
    source = "\n".join(x for x in (ctx.get("acceptance_criteria", ""), issue.get("description", "")) if x)
    bullets = []
    for b in source.splitlines():  # acceptance criteria first, then the description's bullet points, no repeats
        b = b.strip()
        if b.startswith(("-", "*", "•")) or re.match(r"^\d+[.)]\s", b):
            item = re.sub(r"^([-*•]|\d+[.)])\s*", "", b).strip()
            if item and item not in bullets:
                bullets.append(item)
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
        f"// Runs as {who(cfg)}. Test data is prefixed {t.key}.",
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
    if cfg.claude_ready and not cfg.is_mock:
        prompt = (f"Ticket {t.key}: {t.title}\nBase URL: {t.env.url if t.env else 'process.env.BASE_URL'}\n"
                  f"Test account (SSO, storage state is preloaded): {who(cfg)}\n\n"
                  f"Checklist:\n{checklist_md(t)}")
        spec = await ask_claude(cfg, system(SPEC_SYSTEM, "create-tests", cfg), prompt, max_tokens=8000)
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


def parse_playwright_json(report: dict, n_items: int, details: Optional[dict] = None) -> list[tuple[str, str]]:
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
                full = re.sub(r"\x1b\[[0-9;]*m", "", (res.get("error") or {}).get("message", "")).strip()
                err = full.splitlines()[0][:300] if full else ""
                if full and details is not None:
                    details[idx] = full[:2000]
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


async def run_spec(cfg: Config, t: Ticket, run_dir: Path, on_event, on_output=None) -> dict:
    """Run the ticket's spec(s) into a History run folder (see playwright_run.py), each check reported as it ends.
    Returns {results [(result, bug)] per item, cleanup, errors {n: text}, attachments {n: [...]}, exit_code}."""
    from . import playwright_run
    tdir = cfg.ticket_dir(t.key)
    cleanup_file = tdir / f"{t.key}-cleanup.jsonl"
    cleanup_file.unlink(missing_ok=True)
    specs = [f"{t.key}.spec.ts"] + ([f"{t.key}.serial.spec.ts"] if t.serial else [])
    out = await playwright_run.run(
        run_dir=run_dir, test_dir=tdir, specs=specs, workspace=cfg.workspace,
        base_url=t.env.url if t.env and t.env.url.startswith("http") else "",
        storage_state=cfg.auth_dir / "storage-state.json", every_check=cfg.evidence_every_check,
        extra_env={"QA_CLEANUP_FILE": str(cleanup_file)}, on_event=on_event, on_output=on_output)
    if out["report"] is None:
        raise RuntimeError("Playwright did not produce a report: " + (out["stderr"] or f"exit code {out['exit_code']}")[-400:])
    details: dict[int, str] = {}
    results = parse_playwright_json(out["report"], len(t.items()), details)
    (tdir / f"{t.key}-errors.json").write_text(json.dumps(details, indent=1), encoding="utf-8")
    cleanup = []
    if cleanup_file.exists():
        for line in cleanup_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                c = json.loads(line)
                cleanup.append(CleanupItem(name=c["name"], value=str(c["value"]), reread=bool(c.get("reread", True))))
    errors = {i + 1: v for i, v in details.items()}
    errors.update(out["errors"])
    return {"results": results, "cleanup": cleanup, "errors": errors, "attachments": out["attachments"],
            "exit_code": out["exit_code"]}


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
             f"- Account: {who(cfg)}",
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
           f"{env_name(t, cfg)}" + (f" (account {who(cfg)})" if cfg.test_account else "") + ".")
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

# --------------------------------------------------------------------------------------
# Steps 3–5 with Claude and their skills (templates when Claude isn't set up)
# --------------------------------------------------------------------------------------

REVIEW_SYSTEM = ("You review automated test results for a QA engineer. You never change a result; you explain failed, "
                 "partial and blocked items so a developer can act on them.")
COMMENT_SYSTEM = "You write the QA result comment for a Jira ticket from approved test results."
CASES_SYSTEM = "You turn passing QA checklist items into reusable TestRail test cases."


def _results_md(t: Ticket) -> str:
    return checklist_md(t) + "\n## Cleanup\n" + ("\n".join(f"- {c.name}: reverted to {c.value}{'' if c.reread else ' (NOT re-read)'}"
                                                         for c in t.cleanup) or "- No settings were changed.") + \
        (f"\n- Left behind: {t.left}" if t.left else "")


async def review_results(cfg: Config, t: Ticket, details: dict) -> bool:
    """Step 3: Claude writes the bug note and severity for failed / partial / blocked items. True if it did."""
    items = t.items()
    todo = [(n, i) for n, i in enumerate(items, 1) if i.result in ("fail", "partial", "blocked")]
    if not cfg.claude_ready or not todo:
        return False
    lines = [f"[{n}] {RES_LABEL[i.result]} · {i.text}\nRunner said: {details.get(n - 1) or details.get(str(n - 1)) or i.bug or '(nothing)'}"
             for n, i in todo]
    prompt = (f"Ticket {t.key}: {t.title} ({type_label(t.type)})\nEnvironment: {t.env.url if t.env else 'unknown'}\n\n"
              + "\n\n".join(lines) +
              '\n\nReturn JSON only: {"items": [{"n": int, "note": str, "severity": "Critical"|"Major"|"Minor"|null}]} '
              "with one entry per item above. severity only for FAIL items that are product bugs.")
    data = _json_block(await ask_claude(cfg, system(REVIEW_SYSTEM, "run-tests", cfg), prompt, max_tokens=3000))
    for e in data.get("items", []):
        n = int(e.get("n", 0))
        if 1 <= n <= len(items) and items[n - 1].result in ("fail", "partial", "blocked"):
            it = items[n - 1]
            it.bug = str(e.get("note") or it.bug)[:600]
            sev = e.get("severity")
            it.severity = sev if it.result == "fail" and sev in ("Critical", "Major", "Minor") else (it.severity if it.result == "fail" else None)
    return True


async def write_comment(cfg: Config, t: Ticket, today: Optional[date] = None) -> str:
    """Step 4: the QA comment, written by Claude with the jira-comment skill; the template without Claude."""
    if not cfg.claude_ready or cfg.is_mock:
        return comment_text(t, cfg, today)
    today = today or date.today()
    prompt = (f"Ticket {t.key}: {t.title} ({type_label(t.type)})\nVerified: {today.day} {today.strftime('%b %Y')} on "
              f"{env_name(t, cfg)}" + (f" as {who(cfg)}" if cfg.test_account else "") + f"\nSignature line: {cfg.signature}\n\n"
              f"Approved results:\n\n{_results_md(t)}\n\nReturn only the comment text (Markdown).")
    text = (await ask_claude(cfg, system(COMMENT_SYSTEM, "jira-comment", cfg), prompt, max_tokens=3000)).strip()
    return text or comment_text(t, cfg, today)


async def write_cases(cfg: Config, t: Ticket, existing_titles: list[str]) -> list[DraftCase]:
    """Step 5: TestRail cases from the passing items, written by Claude with the testrail skill; the template without."""
    passed = [i for i in t.items() if i.result == "pass"]
    if not cfg.claude_ready or cfg.is_mock or not passed:
        return draft_cases(t)
    prompt = (f"Ticket {t.key}: {t.title} ({type_label(t.type)})\nEnvironment: {t.env.url if t.env else ''}\n\n"
              "Passing checklist items:\n" + "\n".join(f"- {i.text}" for i in passed) +
              "\n\nCases already in the TestRail section (do not repeat):\n" + ("\n".join(f"- {x}" for x in existing_titles) or "- none") +
              '\n\nReturn JSON only: {"cases": [{"title": str, "steps": str, "expected": str}]}')
    data = _json_block(await ask_claude(cfg, system(CASES_SYSTEM, "testrail", cfg), prompt, max_tokens=6000))
    cases = [DraftCase(title=str(c.get("title", "")).strip(), steps=str(c.get("steps", "")), expected=str(c.get("expected", "")))
             for c in data.get("cases", []) if str(c.get("title", "")).strip()]
    return cases or draft_cases(t)


def draft_cases(t: Ticket) -> list[DraftCase]:
    return [DraftCase(title=i.text, steps=f"Ticket {t.key}. Verify: {i.text}", expected=i.text)
            for i in t.items() if i.result == "pass"]


def cases_md(t: Ticket) -> str:
    lines = [f"# {t.key} TestRail cases (draft)", "", f"Section: {t.section}", ""]
    lines += [f"{n}. {c.title}" for n, c in enumerate(t.cases, 1)]
    return "\n".join(lines) + "\n"
