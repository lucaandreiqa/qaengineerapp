"""Jira and TestRail as the workflow sees them.

Real*  wrap the app's own integration modules (integrations/jira.py, integrations/testrail.py)
       with the credentials from the Integrations screen.
Mock*  serve the demo tickets, so the board can be tried without touching real systems.
"""
from __future__ import annotations

import copy
from typing import Optional

from ..integrations import jira as jira_api
from ..integrations import testrail as testrail_api


def normalise(title: str) -> str:
    return " ".join(title.lower().replace("’", "'").split()).rstrip(".")


class WorkflowError(Exception):
    pass


# ------------------------------------------------------------------------------------- real
def _need(cfg: dict, keys: list[str], name: str) -> None:
    missing = [k for k in keys if not str(cfg.get(k, "")).strip()]
    if missing:
        raise WorkflowError(f"{name} is not set up: {', '.join(missing)} missing on the Integrations screen")


class RealJira:
    def __init__(self, cfg: dict) -> None:
        _need(cfg, ["base_url", "email", "api_token"], "Jira")
        self.cfg = cfg

    def search_column(self, project: str, column: str) -> list[dict]:
        return jira_api.search_column(self.cfg, project, column)

    def get_issue(self, key: str) -> dict:
        return jira_api.get_issue(self.cfg, key)

    def add_comment(self, key: str, text: str) -> None:
        jira_api.add_comment(self.cfg, key, text)

    def get_transitions(self, key: str) -> list[dict]:
        return jira_api.get_transitions(self.cfg, key)

    def transition(self, key: str, transition_id: str) -> str:
        return jira_api.do_transition(self.cfg, key, transition_id)


class RealTestRail:
    def __init__(self, cfg: dict) -> None:
        _need(cfg, ["base_url", "username", "api_key", "project_id"], "TestRail")
        self.cfg = cfg

    def find_section(self, path: str) -> Optional[int]:
        return testrail_api.find_section(self.cfg, path)

    def ensure_section(self, path: str) -> int:
        return testrail_api.ensure_section(self.cfg, path)

    def get_cases(self, section_id: Optional[int]) -> list[dict]:
        return testrail_api.section_cases(self.cfg, section_id)

    def add_case(self, section_id: Optional[int], title: str, steps: str, expected: str) -> int:
        if section_id is None:
            raise WorkflowError("No TestRail section to add cases to")
        return testrail_api.add_case(self.cfg, section_id, title, steps, expected)


# ------------------------------------------------------------------------------------- mock
_MOCK_TRANSITIONS = ["Docs", "Ready to merge", "Done", "Reopened"]


class MockJira:
    """In-memory Jira with the demo tickets. The first Sync "finds" one more ticket."""

    def __init__(self, issues: list[dict], late_issues: Optional[list[dict]] = None) -> None:
        self.issues = {i["key"]: copy.deepcopy(i) for i in issues}
        self.late = [copy.deepcopy(i) for i in (late_issues or [])]
        self.comments: dict[str, list[str]] = {k: list(v.get("comments", [])) for k, v in self.issues.items()}

    def search_column(self, project: str, column: str) -> list[dict]:
        for i in self.late:
            self.issues[i["key"]] = i
            self.comments[i["key"]] = list(i.get("comments", []))
        self.late = []
        return [self._public(i) for i in self.issues.values()]

    def _public(self, i: dict) -> dict:
        return {"key": i["key"], "title": i["title"], "status": i["status"], "description": i.get("description", ""),
                "components": list(i.get("components", [])), "merged": i.get("merged", i["status"] == "Merged"),
                "pr_url": i.get("pr_url", ""), "preview_url": i.get("preview_url", ""),
                "comments": self.comments.get(i["key"], [])}

    def get_issue(self, key: str) -> dict:
        if key not in self.issues:
            raise WorkflowError(f"{key} not found")
        return self._public(self.issues[key])

    def add_comment(self, key: str, text: str) -> None:
        self.get_issue(key)
        self.comments.setdefault(key, []).append(text)

    def get_transitions(self, key: str) -> list[dict]:
        self.get_issue(key)
        return [{"id": str(i + 11), "name": n} for i, n in enumerate(_MOCK_TRANSITIONS)]

    def transition(self, key: str, transition_id: str) -> str:
        for t in self.get_transitions(key):
            if t["id"] == transition_id:
                self.issues[key]["status"] = t["name"]
                return t["name"]
        raise WorkflowError(f"Transition {transition_id} is not available for {key}")


class MockTestRail:
    def __init__(self) -> None:
        self.sections: dict[str, int] = {"Finance › Gift cards": 101, "Organization units › Settings": 102}
        self.cases: dict[int, list[dict]] = {101: [{"id": 9001, "title": "An unknown card returns not found"}], 102: []}
        self._next = 9100

    def find_section(self, path: str) -> Optional[int]:
        return self.sections.get(path)

    def ensure_section(self, path: str) -> int:
        if path not in self.sections:
            self.sections[path] = 100 + len(self.sections) + 1
            self.cases[self.sections[path]] = []
        return self.sections[path]

    def get_cases(self, section_id: Optional[int]) -> list[dict]:
        return list(self.cases.get(section_id or -1, []))

    def add_case(self, section_id: Optional[int], title: str, steps: str, expected: str) -> int:
        if section_id is None:
            raise WorkflowError("No section to add cases to")
        self._next += 1
        self.cases.setdefault(section_id, []).append({"id": self._next, "title": title})
        return self._next
