"""Claude through the Claude Code CLI on this computer, signed in with your own Claude plan.

For personal use: each step runs one non-interactive `claude -p` call, like a script you'd write yourself.
It answers from the step's instructions and skill only:

  --system-prompt-file   the step's instructions + skill replace Claude Code's own system prompt
  --tools "" , --strict-mcp-config, --disallowedTools mcp__*   no tools, no MCP servers: just the answer
  --max-turns 1, --no-session-persistence                      one answer, nothing saved as a session
  --output-format json                                         the answer plus token usage

API-key variables are removed from its environment so the call uses your Claude login, not an API account.
fetch() is the one exception: when YourQA's own lookups leave gaps, Claude may go and get the data itself, read-only.
Claude Code enforces that, not the prompt: --permission-mode dontAsk refuses every call that isn't on the allowlist
(no prompts), --tools offers no edit or write tools, and the allowlist holds only read-style gh / git commands, the
read tools of the MCP servers in your Claude Code setup, web pages on the ticket's own domains, and reading files in
the folders YourQA names. Each action is streamed back as it happens, so it can be shown live.

Docs: https://code.claude.com/docs/en/headless, https://code.claude.com/docs/en/cli-reference,
https://code.claude.com/docs/en/permissions
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from ..config import APP_DIR

API_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
TIMEOUT = 600


class ClaudeCodeError(RuntimeError):
    pass


def find_cli() -> Optional[str]:
    """The `claude` command: on PATH, or where the installers put it (apps started from Finder get a short PATH)."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for p in (home / ".local/bin/claude", home / ".claude/local/claude", Path("/opt/homebrew/bin/claude"),
              Path("/usr/local/bin/claude"), home / ".npm-global/bin/claude"):
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return None


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in API_ENV}


def _workdir() -> Path:
    d = APP_DIR / "claude-code"  # an empty folder, so no project's CLAUDE.md, hooks or MCP servers are picked up
    d.mkdir(parents=True, exist_ok=True)
    return d


def _not_installed() -> ClaudeCodeError:
    return ClaudeCodeError("Claude Code isn't installed on this computer. Install it (https://code.claude.com), "
                           "run `claude` in Terminal once and sign in with your Claude account.")


def auth_status() -> dict:
    """{'ok', 'method', 'text'}: is Claude Code signed in, and with what."""
    exe = find_cli()
    if not exe:
        raise _not_installed()
    try:
        p = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=30, env=_env(), cwd=_workdir())
        data = json.loads(p.stdout or "{}")
    except (subprocess.SubprocessError, ValueError) as e:
        raise ClaudeCodeError(f"Couldn't ask Claude Code who is signed in: {e}") from e
    method = data.get("authMethod") or ("none" if p.returncode else "")
    if method == "claude.ai":
        acct = data.get("account") if isinstance(data.get("account"), dict) else {}
        who = data.get("email") or acct.get("email") or ""
        return {"ok": True, "method": method, "text": "Claude Code is signed in with your Claude account" + (f" ({who})" if who else "") +
                " · usage counts against your plan"}
    if method in ("api_key", "api_key_helper", "oauth_token"):
        return {"ok": True, "method": method, "text": f"Claude Code is signed in with {method.replace('_', ' ')}: usage is billed "
                                                       "there, not to your Claude plan. Run `claude auth login` to use your plan."}
    if method == "third_party":
        return {"ok": True, "method": method, "text": "Claude Code uses a cloud provider (Bedrock / Vertex / Foundry) login"}
    return {"ok": False, "method": method or "none",
            "text": "Claude Code isn't signed in. Open Terminal, run `claude auth login`, and sign in with your Claude account."}


def ask(model: str, system: str, prompt: str) -> tuple[str, str, dict]:
    """(answer, model that answered, usage) for one prompt."""
    exe = find_cli()
    if not exe:
        raise _not_installed()
    wd = _workdir()
    sysfile = wd / f"system-{uuid.uuid4().hex}.txt"
    sysfile.write_text(system, encoding="utf-8")
    cmd = [exe, "-p", "--output-format", "json", "--system-prompt-file", str(sysfile),
           "--tools", "", "--disallowedTools", "mcp__*", "--strict-mcp-config",
           "--max-turns", "1", "--no-session-persistence", "--disable-slash-commands"]
    if model:
        cmd += ["--model", model]
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=wd, env=_env())
    except subprocess.TimeoutExpired as e:
        raise ClaudeCodeError(f"Claude Code didn't answer within {TIMEOUT // 60} minutes") from e
    finally:
        sysfile.unlink(missing_ok=True)
    try:
        data = json.loads(p.stdout.strip() or "{}")
    except ValueError:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        raise ClaudeCodeError("Claude Code failed: " + (" ".join(tail) or f"exit code {p.returncode}"))
    text = str(data.get("result") or "")
    if data.get("is_error") or p.returncode != 0 or data.get("subtype", "success") != "success":
        low = text.lower()
        said = " ".join((text or (p.stderr or "")).split())[:220]
        if "login" in low or "log in" in low or "authenticat" in low or "api key" in low:
            raise ClaudeCodeError("Claude Code isn't signed in. Open Terminal, run `claude auth login`, and sign in with your Claude account"
                                  + (f" (Claude Code said: {said})" if said else "."))
        if "limit" in low:
            raise ClaudeCodeError(f"Your Claude plan's usage limit was reached: {text[:200]}")
        raise ClaudeCodeError(f"Claude Code failed: {text[:300] or (p.stderr or '').strip()[-300:] or data.get('subtype')}")
    used_model = next(iter(data.get("modelUsage") or {}), "") or model
    return text, used_model, data.get("usage") or {}


# ------------------------------------------------------------------------------------------ fetching missing data
FETCH_TURNS, FETCH_TIMEOUT = 15, 240
BUILTIN_TOOLS = "Bash,Read,Grep,Glob,WebFetch"
BASH_READ = ["gh pr view *", "gh pr diff *", "gh pr list *", "gh pr checks *", "gh search prs *", "gh search code *",
             "gh issue view *", "gh repo view *", "gh release view *",
             "git clone *", "git fetch *", "git log *", "git show *", "git diff *", "git branch *", "git rev-parse *",
             "git ls-remote *", "git grep *"]
DENY = ["Edit", "Write", "NotebookEdit", "Bash(gh api *)", "Bash(git push *)", "Bash(git commit *)", "Bash(git reset *)",
        "Bash(git checkout *)", "Bash(rm *)", "Bash(curl *)", "Bash(wget *)"]
MCP_READ = ["get*", "list*", "search*", "fetch*", "read*", "view*", "query*", "find*", "describe*", "lookup*", "executeRead"]


def mcp_servers() -> list[str]:
    """The connected MCP servers in your Claude Code setup, as their tool-name prefixes (claude.ai Linear -> claude_ai_Linear)."""
    exe = find_cli()
    if not exe:
        return []
    try:
        p = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True, timeout=60, env=_env(), cwd=_workdir())
    except subprocess.SubprocessError:
        return []
    out = []
    for line in (p.stdout or "").splitlines():
        m = re.match(r"^(.+?):\s+\S.*-\s+✓", line)
        if m:
            out.append(re.sub(r"[^A-Za-z0-9_-]", "_", m.group(1).strip()))
    return out


def allow_rules(servers: list[str], domains: list[str]) -> list[str]:
    rules = ["Read", "Grep", "Glob"] + [f"Bash({c})" for c in BASH_READ]
    rules += [f"mcp__{s}__{t}" for s in servers for t in MCP_READ]
    rules += [f"WebFetch(domain:{d})" for d in sorted(set(domains)) if re.fullmatch(r"[A-Za-z0-9.-]+", d or "")]
    return rules


def _describe(name: str, inp: dict) -> str:
    if name == "Bash":
        return "▸ " + str(inp.get("command", ""))[:300]
    if name == "WebFetch":
        return "▸ fetch " + str(inp.get("url", ""))[:300]
    if name in ("Read", "Grep", "Glob"):
        return f"▸ {name.lower()} " + str(inp.get("file_path") or inp.get("pattern") or inp.get("path") or "")[:300]
    if name.startswith("mcp__"):
        _, server, tool = (name.split("__", 2) + ["", ""])[:3]
        args = " ".join(f"{k}={str(v)[:60]}" for k, v in inp.items() if k != "cloudId")
        return f"▸ {server} · {tool}" + (f" {args}" if args else "")
    return f"▸ {name}"


def fetch(model: str, system: str, prompt: str, *, key: str, domains: list[str], read_dirs: list[Path],
          on_event: Callable[[str, str], None], servers: Optional[list[str]] = None,
          max_turns: int = FETCH_TURNS, timeout: int = FETCH_TIMEOUT) -> tuple[str, str, dict]:
    """Let Claude fetch data with read-only tools. on_event(kind, line): kind 'tool' for each action, 'denied' when Claude
    Code refused one, 'note' for status. Returns (findings markdown, model, usage)."""
    exe = find_cli()
    if not exe:
        raise _not_installed()
    servers = mcp_servers() if servers is None else servers
    wd = APP_DIR / "claude-code" / "fetch" / re.sub(r"[^A-Za-z0-9_-]", "_", key)
    wd.mkdir(parents=True, exist_ok=True)
    sysfile = APP_DIR / "claude-code" / f"system-{uuid.uuid4().hex}.txt"
    sysfile.write_text(system, encoding="utf-8")
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--system-prompt-file", str(sysfile),
           "--permission-mode", "dontAsk", "--tools", BUILTIN_TOOLS,
           "--allowedTools", *allow_rules(servers, domains), "--disallowedTools", *DENY,
           "--max-turns", str(max_turns), "--no-session-persistence", "--disable-slash-commands"]
    for d in read_dirs:
        if Path(d).is_dir():
            cmd += ["--add-dir", str(d)]
    if model:
        cmd += ["--model", model]
    names: dict[str, str] = {}
    final: dict = {}
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            cwd=wd, env=_env())
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        assert proc.stdin and proc.stdout
        proc.stdin.write(prompt)
        proc.stdin.close()
        for raw in proc.stdout:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            kind = ev.get("type")
            content = ((ev.get("message") or {}).get("content") or []) if kind in ("assistant", "user") else []
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_use":
                    names[c.get("id", "")] = _describe(c.get("name", ""), c.get("input") or {})
                    on_event("tool", names[c.get("id", "")])
                elif c.get("type") == "tool_result" and c.get("is_error"):
                    text = c.get("content") if isinstance(c.get("content"), str) else json.dumps(c.get("content"))[:200]
                    what = names.get(c.get("tool_use_id", ""), "an action").removeprefix("▸ ")
                    refused = "denied" in text.lower() or "permission" in text.lower()
                    on_event("denied" if refused else "err", f"{'Refused (not read-only)' if refused else 'Failed'}: {what}"
                             + ("" if refused else f": {text[:160]}"))
            if kind == "result":
                final = ev
        proc.wait(timeout=30)
    finally:
        timer.cancel()
        sysfile.unlink(missing_ok=True)
        if proc.poll() is None:
            proc.kill()
    if not final:
        err = (proc.stderr.read() if proc.stderr else "").strip().splitlines()[-2:]
        raise ClaudeCodeError("Claude couldn't finish fetching" + (f": {' '.join(err)}" if err else f" within {timeout // 60} minutes"))
    if final.get("is_error") and not final.get("result"):
        raise ClaudeCodeError(f"Claude couldn't finish fetching: {final.get('subtype', 'error')}")
    used = next(iter(final.get("modelUsage") or {}), "") or model
    return str(final.get("result") or ""), used, final.get("usage") or {}
