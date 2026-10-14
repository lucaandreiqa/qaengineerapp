"""Workflow settings, read fresh from the app settings (Integrations screen) on every use."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import APP_DIR, WORKFLOW_DIR, load_settings
from .models import DEFAULT_BE_COMPONENTS, DEFAULT_FE_COMPONENTS, classify_type, component_list


@dataclass
class WorkflowConfig:
    demo: bool = True
    jira_project: str = "OPTR"
    jira_column: str = "Testing"
    test_account: str = ""
    test_ou: str = ""
    signature: str = "Commented by Claude"
    shared_env_name: str = "euw"
    fe_components: tuple[str, ...] = tuple(component_list(DEFAULT_FE_COMPONENTS))
    be_components: tuple[str, ...] = tuple(component_list(DEFAULT_BE_COMPONENTS))
    workspace: Path = APP_DIR / "workspace"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    mock_speed: float = 1.0
    data_dir: Path = WORKFLOW_DIR

    @property
    def is_mock(self) -> bool:
        return self.demo

    def ticket_type(self, components: list[str]) -> str:
        return classify_type(components, list(self.fe_components), list(self.be_components))

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
        return cls(
            demo=bool(w.get("demo", True)), jira_project=w.get("jira_project") or "OPTR",
            jira_column=w.get("jira_column") or "Testing", test_account=w.get("test_account", ""),
            test_ou=w.get("test_ou", ""), signature=w.get("comment_signature") or "Commented by Claude",
            shared_env_name=w.get("shared_env") or "euw",
            fe_components=tuple(component_list(w.get("fe_components") or DEFAULT_FE_COMPONENTS)),
            be_components=tuple(component_list(w.get("be_components") or DEFAULT_BE_COMPONENTS)),
            # Demo tickets write their files to a scratch folder, never into a real Playwright repo.
            workspace=WORKFLOW_DIR / "demo-workspace" if w.get("demo", True) else (Path(ws).expanduser() if ws else APP_DIR / "workspace"),
            anthropic_api_key=c.get("api_key", "") if c.get("enabled") else "",
            anthropic_model=c.get("model") or "claude-sonnet-5-5",
            mock_speed=float(os.environ.get("QA_APP_WORKFLOW_MOCK_SPEED", "1") or 1),
        )
