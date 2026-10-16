"""Onboarding: bounded, read-only samples from each source."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa_app.onboarding import collect
from qa_app.workflow.clients import MockJira

KEYS = {"key", "title", "type", "status", "priority", "components", "labels", "description", "comments"}


def _issue(n, updated):
    return {"key": f"OPTR-{n}", "title": f"Ticket {n}", "status": "Testing", "issue_type": "Story", "priority": "High",
            "components": ["Frontend"], "labels": ["release"], "description": "x" * 3000, "updated": updated,
            "comments": [f"comment {i}" for i in range(8)]}


def test_recent_tickets_are_newest_first_and_brief():
    jira = MockJira([_issue(1, "2026-10-01"), _issue(2, "2026-10-03"), _issue(3, "2026-10-02")])
    got = jira.recent("OPTR", 2)
    assert [t["key"] for t in got] == ["OPTR-2", "OPTR-3"]
    assert set(got[0]) == KEYS
    assert len(got[0]["description"]) <= 2000 and len(got[0]["comments"]) == 5


def test_brief_ticket_reads_a_jira_issue():
    raw = {"key": "SCRUM-1", "fields": {"summary": "Login", "issuetype": {"name": "Bug"}, "status": {"name": "Done"},
           "priority": {"name": "Low"}, "components": [{"name": "Backend"}], "labels": ["a"],
           "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Steps here"}]}]},
           "comment": {"comments": [{"body": "looks good " + "y" * 900}]}}}
    b = collect.brief_ticket(raw)
    assert b["title"] == "Login" and b["type"] == "Bug" and b["components"] == ["Backend"] and "Steps here" in b["description"]
    assert len(b["comments"][0]) <= 400


def test_jira_rest_recent_pages_through_search(monkeypatch):
    from qa_app.integrations import jira as jira_api
    calls = []

    class Resp:
        def __init__(self, data):
            self._d, self.ok, self.status_code = data, True, 200

        def json(self):
            return self._d

        def raise_for_status(self):
            pass

    class S:
        def post(self, url, json=None, timeout=None):
            calls.append(json)
            page = len(calls)
            issues = [{"key": f"SCRUM-{page}{i:02d}", "fields": {"summary": "t"}} for i in range(100)]
            return Resp({"issues": issues, "nextPageToken": "next" if page == 1 else None, "isLast": page == 2})
    monkeypatch.setattr(jira_api, "_session", lambda cfg: S())
    got = jira_api.recent({"base_url": "https://x.atlassian.net", "email": "e", "api_token": "t"}, "SCRUM", 150)
    assert len(got) == 150 and calls[0]["jql"] == 'project = "SCRUM" ORDER BY updated DESC'
    assert calls[1].get("nextPageToken") == "next" and "description" in calls[0]["fields"]


def test_mcp_recent_pages_and_briefs():
    from qa_app.integrations.atlassian_mcp import McpJira
    seen = []

    class Mcp:
        def op(self, name, **a):
            seen.append((name, a))
            page = len(seen)
            return {"issues": [{"key": f"SCRUM-{page}-{i}", "fields": {"summary": "t", "status": {"name": "Done"}}} for i in range(50)],
                    "nextPageToken": "n" if page < 3 else None}
    got = McpJira({"cloud_id": "c"}, {}, mcp=Mcp()).recent("SCRUM", 120)
    assert len(got) == 120 and seen[0][0] == "searchJiraIssuesUsingJql" and seen[1][1].get("nextPageToken") == "n"
    assert seen[0][1]["jql"] == 'project = "SCRUM" ORDER BY updated DESC' and "description" in seen[0][1]["fields"]


def test_azure_recent_reads_newest_work_items_with_acceptance_criteria():
    from qa_app.integrations.azure_boards import AzureBoards
    calls = []

    class Az:
        def req(self, method, path, params=None, json=None, **kw):
            calls.append((method, path, params, json))
            if path.endswith("/wiql"):
                return {"workItems": [{"id": 7}, {"id": 5}]}
            return {"value": [{"id": 5, "fields": {"System.Title": "Old", "System.State": "Done"}},
                              {"id": 7, "fields": {"System.Title": "New", "System.State": "Active", "System.Description": "<p>Do it</p>",
                                                   "Microsoft.VSTS.Common.AcceptanceCriteria": "<ul><li>Works</li></ul>"}}]}
    b = AzureBoards.__new__(AzureBoards)
    b.az, b.project, b.team = Az(), "Shop", ""
    got = b.recent("Shop", 10)
    assert [t["title"] for t in got] == ["New", "Old"] and "Works" in got[0]["description"] and "Do it" in got[0]["description"]
    assert "ChangedDate" in calls[0][3]["query"] and calls[0][2]["$top"] == 10
