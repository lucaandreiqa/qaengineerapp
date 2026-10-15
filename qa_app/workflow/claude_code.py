"""Claude through the Claude Code CLI on this computer, signed in with your own Claude plan.

For personal use: each step runs one non-interactive `claude -p` call, like a script you'd write yourself.
It answers from the step's instructions and skill only:

  --system-prompt-file   the step's instructions + skill replace Claude Code's own system prompt
  --tools "" , --strict-mcp-config, --disallowedTools mcp__*   no tools, no MCP servers: just the answer
  --max-turns 1, --no-session-persistence                      one answer, nothing saved as a session
  --output-format json                                         the answer plus token usage

API-key variables are removed from its environment so the call uses your Claude login, not an API account.
Docs: https://code.claude.com/docs/en/headless and https://code.claude.com/docs/en/cli-reference
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

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
