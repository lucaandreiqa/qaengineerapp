"""Integration failures in plain words: which service, what happened, how to fix it, and where.

explain(text, service=None, doing="") turns a raw error (an exception message, an HTTP error, a CLI line) into
{service, name, kind, title, message, fix, action, target, retry, detail}, or None when the error isn't about a
connected service (a step stopped by you, nothing to build). `target` is the Integrations card to open
(#/integrations?open=<target>); `service` can be given when the caller knows it (the step, the card) and the error
text doesn't say. The raw error is kept in `detail`.
"""
from __future__ import annotations

import re
from typing import Optional

NAMES = {
    "jira": "Jira", "azure": "Azure Boards", "claude": "Claude", "github": "GitHub", "testrail": "TestRail",
    "slack": "Slack", "teams": "Microsoft Teams", "xray": "Xray", "zephyr": "Zephyr Scale", "confluence": "Confluence",
    "workflow": "Testing board", "mcp": "MCP server",
}
# What each service signs in with, for "enter a new …".
CREDS = {"jira": "API token", "confluence": "API token", "azure": "personal access token", "testrail": "API key",
         "claude": "API key", "github": "token", "slack": "webhook URL", "teams": "webhook URL", "xray": "API key",
         "zephyr": "API token", "mcp": "token"}
# Confluence is reached through the Jira connection.
TARGETS = {"confluence": "jira"}

_SERVICE_HINTS = [
    ("azure", r"dev\.azure\.com|visualstudio\.com|azure devops|azure boards|\bTF\d{5,}"),
    ("confluence", r"confluence"),
    ("jira", r"atlassian|\bjira\b|/rest/api/\d"),
    ("testrail", r"testrail|get_cases|add_case|get_sections"),
    ("slack", r"slack"),
    ("teams", r"webhook\.office|office\.com/webhook|microsoft teams|\bteams\b"),
    ("github", r"github|\bgh:|\bgh\b"),
    ("xray", r"\bxray\b"),
    ("zephyr", r"zephyr"),
    ("claude", r"anthropic|claude|x-api-key|credit balance|overloaded"),
    ("mcp", r"\bmcp\b"),
]

_KINDS = [  # first match wins
    ("billing", r"credit balance|insufficient (credit|funds|quota)|billing|quota exceeded|usage limit"),
    ("missing", r"not configured|not connected|isn't connected|no api key|api key is (missing|required)|is required"
                r"|command not found|no such file or directory: '?claude|not installed|not set up"),
    ("auth", r"\b401\b|unauthori[sz]ed|invalid[ _-]?(api[ _-]?key|x-api-key|token|grant|credentials)|bad credentials"
             r"|authentication|not logged in|log ?in again|sign[- ]?in (again|has ended|expired)|token (has )?expired"
             r"|expired token|refresh token"),
    ("permission", r"\b403\b|forbidden|not allowed|permission|not authori[sz]ed|access denied"),
    ("rate", r"\b429\b|rate[ -]?limit|too many requests"),
    ("notfound", r"\b404\b|not found|does not exist|doesn't exist|no such (project|board|section|channel)"),
    ("network", r"timed? ?out|timeout|connection (refused|reset|aborted|error)|connecterror|max retries exceeded"
                r"|name ?resolution|name or service not known|nodename nor servname|getaddrinfo|network is unreachable"
                r"|failed to establish|ssl|certificate|could not resolve|unreachable"),
    ("server", r"\b5\d\d\b|overloaded|internal server error|bad gateway|service unavailable|gateway time"),
]

_NOT_INTEGRATION = re.compile(r"stopped by you|no checks to build|nothing to build|^verification with get_cases", re.I)


def _service(text: str) -> Optional[str]:
    for sid, pat in _SERVICE_HINTS:
        if re.search(pat, text, re.I):
            return sid
    return None


def _kind(text: str) -> str:
    for kind, pat in _KINDS:
        if re.search(pat, text, re.I):
            return kind
    return "other"


def _words(kind: str, sid: str, name: str, doing: str) -> tuple[str, str, str]:
    so = f", so YourQA couldn't {doing}" if doing else ""
    where = f"Open {name} on the Integrations screen"
    cred = CREDS.get(sid, "token")
    if kind == "auth":
        if sid in ("slack", "teams"):
            return (f"{name} didn't accept the webhook", f"The {name} webhook URL was refused{so}.",
                    f"{where}, paste a new webhook URL, then press Test connection.")
        signin = "sign in again or enter a new API token" if sid == "jira" else f"enter a new {cred}"
        if sid == "claude":
            signin = "enter a new API key, or switch to Claude Code and sign in with claude"
        return (f"{name} didn't accept the sign-in", f"Your {name} {'sign-in or ' if sid in ('jira', 'mcp') else ''}{cred} was refused{so}.",
                f"{where}, {signin}, then press Test connection.")
    if kind == "permission":
        return (f"{name} refused access", f"Your {name} account isn't allowed to do this{so}.",
                f"Check that the account has access to the project, or connect with an account that does. {where} to change it.")
    if kind == "notfound":
        return (f"{name} couldn't find it", f"{name} couldn't find the project, board or item YourQA asked for{so}.",
                f"{where} and check the project, board or section in its settings.")
    if kind == "network":
        return (f"Couldn't reach {name}", f"YourQA couldn't connect to {name}{so}.",
                f"Check your internet connection or VPN, and the address in the {name} settings. Then try again.")
    if kind == "rate":
        return (f"{name} is limiting requests", f"{name} asked YourQA to slow down{so}.",
                "Wait a minute, then try again.")
    if kind == "server":
        return (f"{name} had a problem on its side", f"{name} returned a server error{so}.",
                f"Try again in a few minutes. If it keeps failing, check {name}'s status page.")
    if kind == "billing":
        return (f"Your {name} account is out of credit", f"{name} refused the request because of the account's credit or limits{so}.",
                "Add credit in the Anthropic console, or switch the Claude connection to Claude Code (your Claude plan)."
                if sid == "claude" else f"Check the {name} account's plan and limits.")
    if kind == "missing":
        if sid == "claude":
            return ("Claude isn't set up", f"Claude isn't connected{so}.",
                    "Install Claude Code and run claude once to sign in, or enter an API key on the Integrations screen.")
        return (f"{name} isn't set up", f"{name} isn't connected yet{so}.", f"Connect {name} on the Integrations screen.")
    return (f"{name} returned an error", f"Something went wrong with {name}{so}.",
            f"{where}, check its settings and press Test connection. The details below say what {name} answered.")


def explain(text: str, service: Optional[str] = None, doing: str = "") -> Optional[dict]:
    raw = str(text or "").strip()
    if not raw or _NOT_INTEGRATION.search(raw):
        return None
    given = service or ""
    sid = (given.split(":", 1)[0] if given else "") or _service(raw)
    if not sid or sid not in NAMES:
        return None
    name = NAMES[sid]
    if given.startswith("mcp:") and len(given) > 4:
        name = given.split(":", 1)[1]
    kind = _kind(raw)
    title, message, fix = _words(kind, sid, name, doing)
    target = given if given.startswith("mcp:") else TARGETS.get(sid, sid)
    return {"service": sid, "name": name, "kind": kind, "title": title, "message": message, "fix": fix,
            "action": f"Fix {name}", "target": target, "retry": kind in ("network", "rate", "server"),
            "detail": raw[:1000]}


def hint(text: str, service: str) -> str:
    """For a Test connection result on the card itself: just what to do, when the error is recognised."""
    f = explain(text, service)
    if not f or f["kind"] == "other":
        return ""
    fix = f["fix"].replace(f"Open {f['name']} on the Integrations screen, ", "").replace(f" Open {f['name']} on the Integrations screen to change it.", "")
    return fix[:1].upper() + fix[1:]


def for_stage(stage: int, tracker: str = "jira") -> Optional[str]:
    """Which service a board step talks to, for errors that don't name one."""
    return {1: "claude", 3: tracker, 4: "testrail"}.get(stage)


def tracker() -> str:
    from ..config import load_settings
    return "azure" if load_settings().get("workflow", {}).get("tracker") == "azure" else "jira"


def sync_info(error: str) -> Optional[dict]:
    """A board sync error is the tracker's, unless the error names another service."""
    if not error:
        return None
    return explain(error, None, "sync the board") or explain(error, tracker(), "sync the board")
