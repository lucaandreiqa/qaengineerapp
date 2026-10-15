"""Claude through the Claude Code CLI on this computer (your Claude plan), with a stand-in `claude` command."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys

import pytest

from qa_app.workflow import agent, claude_code, costs
from qa_app.workflow.settings import WorkflowConfig as Config

FAKE = r'''#!{python}
import json, os, sys
args = sys.argv[1:]
log = os.environ["FAKE_CLAUDE_LOG"]
if args[:2] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": True, "authMethod": os.environ.get("FAKE_AUTH", "claude.ai"), "email": "luca@example.com"}}))
    sys.exit(0 if os.environ.get("FAKE_AUTH", "claude.ai") != "none" else 1)
prompt = sys.stdin.read()
system = open(args[args.index("--system-prompt-file") + 1]).read()
json.dump({{"args": args, "prompt": prompt, "system": system, "cwd": os.getcwd(),
           "api_key_seen": "ANTHROPIC_API_KEY" in os.environ}}, open(log, "w"))
if os.environ.get("FAKE_MODE") == "logged_out":
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"}}))
    sys.exit(1)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "QA result: 2/2 checks pass.",
                  "total_cost_usd": 0.0123, "usage": {{"input_tokens": 3000, "output_tokens": 400, "cache_read_input_tokens": 0}},
                  "modelUsage": {{"claude-sonnet-5-5": {{"inputTokens": 3000, "outputTokens": 400}}}}}}))
'''


@pytest.fixture()
def fake_cli(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(FAKE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "call.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")
    monkeypatch.setattr(claude_code, "APP_DIR", tmp_path / "app")
    return tmp_path / "call.json"


def test_one_step_runs_claude_print_mode_on_the_users_plan(fake_cli):
    text, model, usage = claude_code.ask("claude-sonnet-5-5", "You write QA comments.\n<skill step=\"jira-comment\">…</skill>", "Results: …")
    assert text == "QA result: 2/2 checks pass." and model == "claude-sonnet-5-5" and usage["input_tokens"] == 3000
    call = json.loads(fake_cli.read_text())
    a = call["args"]
    assert a[0] == "-p" and a[a.index("--output-format") + 1] == "json" and a[a.index("--model") + 1] == "claude-sonnet-5-5"
    assert a[a.index("--tools") + 1] == "" and "--strict-mcp-config" in a and a[a.index("--disallowedTools") + 1] == "mcp__*"
    assert a[a.index("--max-turns") + 1] == "1" and "--no-session-persistence" in a and "--bare" not in a  # bare ignores the plan login
    assert call["system"].startswith("You write QA comments.") and call["prompt"] == "Results: …"  # prompt on stdin
    assert not call["api_key_seen"]  # API keys removed, so it bills the Claude plan, not an API account
    assert call["cwd"].endswith("claude-code")  # an empty folder: no project hooks, CLAUDE.md or MCP servers
    assert not list((fake_cli.parent / "app" / "claude-code").glob("system-*.txt"))  # system prompt file cleaned up


def test_signed_out_and_auth_status_give_clear_messages(fake_cli, monkeypatch):
    assert claude_code.auth_status()["ok"] and "Claude account (luca@example.com)" in claude_code.auth_status()["text"]
    monkeypatch.setenv("FAKE_AUTH", "api_key")
    assert "billed there, not to your Claude plan" in claude_code.auth_status()["text"]
    monkeypatch.setenv("FAKE_AUTH", "none")
    assert not claude_code.auth_status()["ok"]
    monkeypatch.setenv("FAKE_MODE", "logged_out")
    with pytest.raises(claude_code.ClaudeCodeError, match="isn't signed in"):
        claude_code.ask("claude-sonnet-5-5", "s", "p")


def test_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_code, "find_cli", lambda: None)
    with pytest.raises(claude_code.ClaudeCodeError, match="isn't installed"):
        claude_code.ask("m", "s", "p")


def test_steps_use_claude_code_mode_and_costs_say_plan(fake_cli):
    cfg = Config(demo=False, claude_mode="claude_code")
    assert cfg.claude_ready and not Config(demo=False).claude_ready and Config(anthropic_api_key="k").claude_ready
    seen = []
    agent.usage_listeners.append(lambda *a: seen.append(a))
    try:
        out = asyncio.new_event_loop().run_until_complete(agent.ask_claude(cfg, 'x <skill step="jira-comment">', "p"))
    finally:
        agent.usage_listeners.pop()
    assert out == "QA result: 2/2 checks pass."
    (key, step, model, usage, billing), = seen
    assert (step, model, billing) == ("jira-comment", "claude-sonnet-5-5", "plan")
    s = costs.summary([costs.entry(step, model, usage, billing=billing)])
    assert s["plan_calls"] == 1 and s["cost"] == pytest.approx((3000 * 2 + 400 * 10) / 1e6)  # API-price equivalent


FETCH = r'''#!{python}
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["mcp", "list"]:
    print("Checking MCP server health...\n")
    print("atlassian: https://mcp.atlassian.com/v1/mcp (HTTP) - ✓ Connected")
    print("claude.ai Linear: https://mcp.linear.app/mcp (HTTP) - ✓ Connected")
    print("broken: npx broken-server - ✗ Failed to connect")
    sys.exit(0)
prompt = sys.stdin.read()
json.dump({{"args": args, "prompt": prompt, "cwd": os.getcwd()}}, open(os.environ["FAKE_CLAUDE_LOG"], "w"))
def out(o): print(json.dumps(o), flush=True)
out({{"type": "system", "subtype": "init", "tools": ["Bash", "Read"]}})
out({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "t1", "name": "Bash", "input": {{"command": "gh pr diff 512 --repo acme/admin"}}}}]}}}})
out({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "t1", "content": "diff --git a/x b/x"}}]}}}})
out({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "t2", "name": "Bash", "input": {{"command": "gh api -X POST repos/acme/admin/issues"}}}}]}}}})
out({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": "Permission to use Bash has been denied."}}]}}}})
out({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "t3", "name": "mcp__atlassian__getConfluencePage", "input": {{"pageId": "12345"}}}}]}}}})
out({{"type": "result", "subtype": "success", "is_error": False, "result": "## PR acme/admin#512\nAdds UsageLimit (1-999).",
      "usage": {{"input_tokens": 9000, "output_tokens": 700}}, "modelUsage": {{"claude-sonnet-5-5": {{}}}}}})
'''


@pytest.fixture()
def fetch_cli(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(FETCH.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "call.json"))
    monkeypatch.setattr(claude_code, "APP_DIR", tmp_path / "app")
    return tmp_path / "call.json"


def test_connected_mcp_servers_are_found_with_their_tool_prefixes(fetch_cli):
    assert claude_code.mcp_servers() == ["atlassian", "claude_ai_Linear"]


def test_fetching_is_read_only_enforced_by_claude_code_and_every_action_is_shown(fetch_cli, tmp_path):
    seen = []
    ws = tmp_path / "workspace"
    ws.mkdir()
    text, model, usage = claude_code.fetch("claude-sonnet-5-5", "You fetch facts.", "Get the diff of PR 512",
                                           key="OPTR-77", domains=["acme.atlassian.net", "www.figma.com"],
                                           read_dirs=[ws], on_event=lambda kind, line: seen.append((kind, line)))
    assert text.startswith("## PR acme/admin#512") and usage["input_tokens"] == 9000
    a = json.loads(fetch_cli.read_text())["args"]
    assert a[a.index("--permission-mode") + 1] == "dontAsk"          # anything not allowed is refused, no prompts
    assert a[a.index("--output-format") + 1] == "stream-json" and "--verbose" in a
    assert "--strict-mcp-config" not in a                             # your Claude Code MCP servers are available
    def values(flag):  # the rules after a flag, one argument each, up to the next flag
        i, out = a.index(flag) + 1, []
        while i < len(a) and not a[i].startswith("--"):
            out.append(a[i]); i += 1
        return out
    allowed = values("--allowedTools")
    assert "Bash(gh pr diff *)" in allowed and "Bash(git log *)" in allowed and "Read" in allowed
    assert "mcp__atlassian__get*" in allowed and "mcp__claude_ai_Linear__search*" in allowed and "mcp__atlassian__executeRead" in allowed
    assert "WebFetch(domain:acme.atlassian.net)" in allowed and "WebFetch(domain:www.figma.com)" in allowed
    assert not any(r.startswith("Bash(gh api") for r in allowed)
    denied = values("--disallowedTools")
    assert a[a.index("--tools") + 1] == "Bash,Read,Grep,Glob,WebFetch"   # no edit or write tools at all
    assert {"Edit", "Write", "NotebookEdit", "Bash(gh api *)", "Bash(git push *)"} <= set(denied)
    assert a[a.index("--add-dir") + 1] == str(ws) and a[a.index("--max-turns") + 1] == "15"
    assert json.loads(fetch_cli.read_text())["cwd"].endswith(os.path.join("fetch", "OPTR-77"))  # a scratch folder per ticket
    lines = [l for _, l in seen]
    assert "▸ gh pr diff 512 --repo acme/admin" in lines
    assert any(k == "denied" and "gh api -X POST" in l for k, l in seen)  # refused, and you can see it was
    assert "▸ atlassian · getConfluencePage pageId=12345" in lines
