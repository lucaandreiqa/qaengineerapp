"""What Playwright prints, in plain words: a line for the ticket's feed when something worth knowing happens, and
when the run goes silent, what it last printed and how to unblock it. Checks are reported by the engine itself."""
from __future__ import annotations

import re
from typing import Optional

MAX_LINES = 1500  # kept per ticket for the live terminal; the full output is saved as terminal.log in the run folder

_FRIENDLY: list[tuple[re.Pattern, object]] = [
    (re.compile(r"^\$ npm install"), "Installing Playwright in the test workspace (only the first time, about a minute)…"),
    (re.compile(r"^\$ npx playwright install chromium"), "Installing the Chromium browser Playwright drives…"),
    (re.compile(r"^Downloading (Chromium|Chrome|Firefox|Webkit|FFMPEG)", re.I),
     lambda m: f"Downloading {m.group(1).capitalize()}…"),
    (re.compile(r"^Playwright is ready\.$"), "Playwright is installed and ready."),
    (re.compile(r"^Running (\d+) tests? using (\d+) workers?"),
     lambda m: f"Playwright started: {m.group(1)} test{'s' if m.group(1) != '1' else ''} "
               f"({m.group(2)} worker{'s' if m.group(2) != '1' else ''})."),
    (re.compile(r"^Error: No tests found"), "Playwright found no tests in the spec. The spec file may be empty or misnamed."),
    (re.compile(r"Error: Cannot find module '@playwright/test'"), "Playwright isn't installed in the test workspace."),
]


def friendly(line: str) -> Optional[str]:
    s = line.strip()
    for pat, out in _FRIENDLY:
        m = pat.search(s)
        if m:
            return out(m) if callable(out) else out  # type: ignore[operator]
    return None


_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Ok to proceed\?|Need to install the following packages", re.I),
     "That's npm asking to install Playwright, and nobody can answer it from here. Stop the run and run it again: "
     "YourQA now installs Playwright in the test workspace itself."),
    (re.compile(r"Executable doesn't exist|playwright install", re.I),
     "The Chromium browser isn't installed. Stop the run, then in Terminal run `cd ~/.qa_app/workspace && "
     "npx playwright install chromium`, and run it again."),
    (re.compile(r"ERR_NAME_NOT_RESOLVED|ERR_CONNECTION|ECONNREFUSED|ETIMEDOUT|net::ERR", re.I),
     "The test can't reach the site. Check the environment URL and that you're on the VPN if it needs one."),
    (re.compile(r"\b(sign.?in|log.?in|password|storage.?state|401|403)\b", re.I),
     "It may be stuck on a sign-in page. Sign in again from Integrations (session), then rerun."),
    (re.compile(r"Downloading|added \d+ packages|npm (http|timing|sill)", re.I),
     "It's still installing, which can take a few minutes on a slow connection. Give it a little longer."),
    (re.compile(r"Running \d+ tests?|›|\[\d+\]", re.I),
     "A check is taking a long time, usually waiting for something on the page that never appears. "
     "Playwright gives up on its own when the test's timeout runs out."),
]


def stall_message(stall: str) -> str:
    """'No output for 45s. Last line: …' → the feed message: what it saw, what that likely means, how to unblock."""
    m = re.match(r"No output for (\d+)s\. Last line: (.*)$", stall.strip(), re.S)
    secs, last = (m.group(1), m.group(2).strip()) if m else ("a while", stall.strip())
    hint = next((h for pat, h in _HINTS if pat.search(last)), "")
    if not hint:
        hint = ("Nothing obvious is wrong. It may still be working. If nothing changes, Stop the run "
                "and check the terminal below.") if last and last != "(nothing printed yet)" else \
               "Playwright hasn't printed anything since it started. It may be starting up or stuck before the first test."
    out = f"Playwright has been silent for {secs}s. The last thing it printed was: “{last}”. {hint}"
    if "Stop" not in out:
        out += " You can wait, or press Stop to end the run."
    return out
