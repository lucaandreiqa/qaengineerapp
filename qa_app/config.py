"""App settings and data directories.

Settings live in ~/.qa_app/settings.json (%USERPROFILE%/.qa_app on Windows). Any value can be overridden by an
environment variable (QA_APP_<SECTION>_<KEY>, e.g. QA_APP_JIRA_API_TOKEN), which is how CI
pipelines should pass secrets instead of storing them on disk.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("QA_APP_HOME", Path.home() / ".qa_app"))
RUNS_DIR = APP_DIR / "runs"
BASELINES_DIR = APP_DIR / "baselines"
VENDOR_DIR = APP_DIR / "vendor"
SETTINGS_FILE = APP_DIR / "settings.json"

DEFAULT_SETTINGS: dict[str, dict] = {
    "slack": {"enabled": False, "webhook_url": "", "only_on_failure": False},
    "teams": {"enabled": False, "webhook_url": "", "only_on_failure": False},
    "jira": {"enabled": False, "base_url": "", "email": "", "api_token": "",
             "project_key": "", "issue_type": "Bug", "min_severity": "major",
             # auth "mcp": signed in with Atlassian (MCP server); "token" or "": email + API token.
             "auth": "", "cloud_id": "", "board_id": "", "link": "", "connection": {},
             # File a bug for each site-check finding after every run (the Run screen's button works either way).
             "bugs_on_runs": False},
    # Azure Boards: board link + personal access token (Work items: read & write).
    "azure": {"enabled": False, "org_url": "", "pat": "", "project": "", "team": "", "board": "", "column_field": "",
              "link": "", "connection": {}},
    "github": {"enabled": False, "token": "", "repos": ""},
    # First-run setup (sign-in, then one page per connection) is shown until finished or skipped.
    "app": {"setup_done": False},
    "testrail": {"enabled": False, "base_url": "", "username": "", "api_key": "",
                 "project_id": "", "suite_id": "", "section_map": {}},
    "xray": {"enabled": False, "client_id": "", "client_secret": "", "project_key": ""},
    "zephyr": {"enabled": False, "api_token": "", "project_key": ""},
    "aws": {"enabled": False, "bucket": "", "prefix": "qa-reports/", "region": "eu-central-1",
            "profile": "", "public_base_url": ""},
    # Testing board: takes tickets from a Jira column through the gated QA workflow.
    # demo=True uses sample tickets and simulated Jira/TestRail, so nothing real is touched.
    "workflow": {"enabled": True, "demo": True, "tracker": "jira",
                 # Pull the board column every N minutes while a real board is connected (0 = only "Sync now").
                 "auto_sync_minutes": 5,
                 # Evidence per run: screenshots for every check (not only failures); how many runs per ticket keep it.
                 "evidence_every_check": False, "evidence_keep_runs": 5,
                 "jira_project": "OPTR", "jira_column": "Testing",
                 "test_account": "", "test_ou": "", "comment_signature": "Commented by YourQA",
                 # Where to test when the ticket names no environment: used only once a ticket is merged/done.
                 "default_env_url": "", "default_env_name": "",
                 # Words or domains that mark your test environments in links, e.g. "preview.myapp.com, staging".
                 "env_hints": "",
                 "workspace": "",
                 # Jira components that make a ticket FE, BE, or FE+BE when it has both.
                 "fe_components": "Frontend, FE, Front-end, UI", "be_components": "Backend, BE, Back-end, Core, API",
                 "both_names": "FE+BE, FE/BE, BE+FE, Fullstack, Full-stack, Full stack",
                 "jira_column_statuses": ""},
    # Claude writes the scenarios, QA checklist and Playwright spec for each ticket.
    # mode "api": an Anthropic API key · "claude_code": the Claude Code CLI on this computer, signed in with your Claude plan
    "claude": {"enabled": False, "mode": "api", "api_key": "", "model": "claude-sonnet-5-5", "fetch_missing": True},
}

SECRET_KEYS = {"api_token", "api_key", "client_secret", "webhook_url"}
WORKFLOW_DIR = APP_DIR / "workflow"


def ensure_dirs() -> None:
    for d in (APP_DIR, RUNS_DIR, BASELINES_DIR, VENDOR_DIR):
        d.mkdir(parents=True, exist_ok=True)


def company_dir() -> Path:
    """What onboarding learned about the company: knowledge.md, profile.json, and each study run."""
    return APP_DIR / "company"


def load_settings() -> dict:
    ensure_dirs()
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if SETTINGS_FILE.exists():
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        for section, values in stored.items():
            settings.setdefault(section, {}).update(values)
    for section, values in settings.items():
        for key, default in values.items():
            env = os.environ.get(f"QA_APP_{section}_{key}".upper())
            if env is not None:
                values[key] = env.lower() in ("1", "true", "yes") if isinstance(default, bool) else env
    return settings


def save_settings(settings: dict) -> None:
    ensure_dirs()
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def save_section(section: str, values: dict) -> None:
    """Save one section without writing env-var overrides (e.g. CI secrets) to disk."""
    ensure_dirs()
    stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}
    stored[section] = {**stored.get(section, {}), **values}
    save_settings(stored)
