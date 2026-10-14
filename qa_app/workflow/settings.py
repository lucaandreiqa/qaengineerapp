"""Workflow settings, read fresh from the app settings (Integrations screen) on every use."""
from __future__ import annotations

import os
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import APP_DIR, WORKFLOW_DIR, load_settings
from .models import DEFAULT_BE_COMPONENTS, DEFAULT_BOTH_NAMES, DEFAULT_FE_COMPONENTS, classify_type, component_list


@dataclass
class WorkflowConfig:
    demo: bool = True
    jira_project: str = "OPTR"
    jira_column: str = "Testing"
    test_account: str = ""
    test_ou: str = ""
    signature: str = "Commented by Claude"
    default_env_url: str = ""   # used only for merged/done tickets that name no environment
    default_env_name: str = ""
    env_hints: tuple[str, ...] = ()
    jira_host: str = ""
    fe_components: tuple[str, ...] = tuple(component_list(DEFAULT_FE_COMPONENTS))
    be_components: tuple[str, ...] = tuple(component_list(DEFAULT_BE_COMPONENTS))
    both_names: tuple[str, ...] = tuple(component_list(DEFAULT_BOTH_NAMES))
    workspace: Path = APP_DIR / "workspace"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    claude_mode: str = "api"  # api (API key) | claude_code (the Claude Code CLI on this computer, your Claude plan) | off
    mock_speed: float = 1.0
    data_dir: Path = WORKFLOW_DIR

    @property
    def is_mock(self) -> bool:
        return self.demo

    def ticket_type(self, components: list[str], labels: Optional[list[str]] = None) -> str:
        """FE / BE / FE+BE from the ticket's Jira components and labels."""
        return classify_type(components, list(self.fe_components), list(self.be_components), labels, list(self.both_names))

    @property
    def claude_ready(self) -> bool:
        """Claude can be used for the steps: an API key, or Claude Code on this computer."""
        return self.claude_mode == "claude_code" or (self.claude_mode == "api" and bool(self.anthropic_api_key))

    @property
    def shared_env_name(self) -> str:
        return self.default_env_name or "default environment"

    @property
    def auth_dir(self) -> Path:
        return self.data_dir / "auth"

    def ticket_dir(self, key: str) -> Path:
        return self.workspace / "tests" / "tickets" / key

    @classmethod
    def load(cls) -> "WorkflowConfig":
        s = load_settings()
        w, c = s.get("workflow", {}), s.get("claude", {})
        ws = str(w.get("workspace") or "").strip()
        demo = bool(w.get("demo", True))
        if demo:  # the sample tickets use a sample staging site
            w = {**w, "default_env_url": "https://staging.shop-demo.test/", "default_env_name": "shared staging"}
        return cls(
            demo=demo, jira_project=w.get("jira_project") or "OPTR",
            jira_column=w.get("jira_column") or "Testing", test_account=w.get("test_account", ""),
            test_ou=w.get("test_ou", ""), signature=w.get("comment_signature") or "Commented by QA Engineer App",
            default_env_url=str(w.get("default_env_url") or "").strip(),
            default_env_name=str(w.get("default_env_name") or "").strip(),
            env_hints=tuple(component_list(w.get("env_hints") or "")),
            jira_host=(urlparse(str(s.get("jira", {}).get("base_url") or "")).hostname or "").lower(),
            fe_components=tuple(component_list(w.get("fe_components") or DEFAULT_FE_COMPONENTS)),
            be_components=tuple(component_list(w.get("be_components") or DEFAULT_BE_COMPONENTS)),
            both_names=tuple(component_list(w.get("both_names") or DEFAULT_BOTH_NAMES)),
            # Demo tickets write their files to a scratch folder, never into a real Playwright repo.
            workspace=WORKFLOW_DIR / "demo-workspace" if w.get("demo", True) else (Path(ws).expanduser() if ws else APP_DIR / "workspace"),
            anthropic_api_key=c.get("api_key", "") if c.get("enabled") else "",
            claude_mode=(c.get("mode") or "api") if c.get("enabled") else "off",
            anthropic_model=c.get("model") or "claude-sonnet-5-5",
            mock_speed=float(os.environ.get("QA_APP_WORKFLOW_MOCK_SPEED", "1") or 1),
        )
