"""Jira through Atlassian's MCP server: the user pastes a board link and signs in with Atlassian.

parse_jira_link()  site, project, board and ticket from any Jira URL
discover()         who signed in, the site's cloudId, the project, the board and its columns
McpJira            what the Testing board needs (tickets in a column, ticket detail, comment, move)

Tool names and inputs match Atlassian's MCP server. Tools it exposes directly are called directly;
the rest go through its executeRead / executeWrite runner, so both server layouts work.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .mcp_client import McpError, McpSession, OAuth, TokenStore

ATLASSIAN_MCP_URL = os.environ.get("QA_APP_ATLASSIAN_MCP_URL") or "https://mcp.atlassian.com/v1/mcp/authv2"
WRITE_OPS = {"addOrEditJiraIssueComment", "transitionJiraIssue", "createJiraIssue", "editJiraIssue"}
NO_CLOUD_OPS = {"getAccessibleAtlassianResources", "atlassianUserInfo"}


# ------------------------------------------------------------------------------------- links
def parse_jira_link(link: str) -> dict:
    """Site, project, board and ticket from a Jira URL. Raises ValueError with a message for the user.

    Board:   https://acme.atlassian.net/jira/software/projects/SCRUM/boards/1?filter=
             https://acme.atlassian.net/jira/software/c/projects/OPS/boards/12
             https://acme.atlassian.net/secure/RapidBoard.jspa?rapidView=5&projectKey=OPS
    Ticket:  https://acme.atlassian.net/browse/SCRUM-12, …/boards/1?selectedIssue=SCRUM-3
    Site:    acme.atlassian.net
    """
    s = (link or "").strip().strip("<>\"'")
    if not s:
        raise ValueError("Paste a link to your Jira board")
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    p = urlparse(s)
    host = (p.hostname or "").lower()
    if not host or "." not in host or " " in s:
        raise ValueError("That doesn't look like a Jira link")
    if host.endswith("atlassian.com") and not host.endswith(".atlassian.net"):
        raise ValueError("Use the link of your Jira site (…atlassian.net), not an atlassian.com page")
    q = {k: v[0] for k, v in parse_qs(p.query).items() if v}
    project = board = issue = ""
    m = re.search(r"/projects/([A-Za-z][A-Za-z0-9_]*)", p.path)
    if m:
        project = m.group(1).upper()
    m = re.search(r"/boards?/(\d+)", p.path)
    if m:
        board = m.group(1)
    board = board or (q.get("rapidView", "") if q.get("rapidView", "").isdigit() else "")
    project = project or q.get("projectKey", "").upper()
    m = re.search(r"/browse/([A-Za-z][A-Za-z0-9_]*-\d+)", p.path)
    issue = (m.group(1) if m else q.get("selectedIssue", "")).upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", issue):
        issue = ""
    if issue and not project:
        project = issue.rsplit("-", 1)[0]
    return {"site": host, "base_url": f"https://{host}", "project_key": project, "board_id": board, "issue_key": issue}


# ------------------------------------------------------------------------------------- MCP wrapper
def store_path() -> Path:
    from ..config import APP_DIR
    return APP_DIR / "atlassian-mcp.json"


def oauth(store: Optional[TokenStore] = None) -> OAuth:
    return OAuth(ATLASSIAN_MCP_URL, store or TokenStore(store_path()))


def _unwrap(res: Any) -> Any:
    return res.get("data", res) if isinstance(res, dict) else res


class AtlassianMcp:
    def __init__(self, session: McpSession, cloud_id: str = "") -> None:
        self.s = session
        self.cloud_id = cloud_id

    @classmethod
    def signed_in(cls, cloud_id: str = "", store: Optional[TokenStore] = None) -> "AtlassianMcp":
        o = oauth(store)
        return cls(McpSession(ATLASSIAN_MCP_URL, o.access_token, o.refresh), cloud_id)

    def op(self, name: str, **inputs: Any) -> Any:
        names = self.s.tool_names()
        if name not in NO_CLOUD_OPS:
            if not self.cloud_id:
                raise McpError("No Atlassian site selected yet")
            inputs = {"cloudId": self.cloud_id, **inputs}
        if name in names:
            return _unwrap(self.s.call(name, inputs))
        runner = "executeWrite" if name in WRITE_OPS else "executeRead"
        if runner in names:
            rest = {k: v for k, v in inputs.items() if k != "cloudId"}
            return _unwrap(self.s.call(runner, {"name": name, "cloudId": self.cloud_id, "inputs": rest}))
        raise McpError(f"Atlassian's MCP server has no '{name}' tool for this account")

    # ---- reads used when connecting
    def sites(self) -> list[dict]:
        res = self.op("getAccessibleAtlassianResources")
        return res.get("resources", []) if isinstance(res, dict) else list(res or [])

    def me(self) -> dict:
        for name in ("getJiraCurrentUser", "atlassianUserInfo"):
            try:
                u = self.op(name)
            except McpError:
                continue
            if isinstance(u, dict) and u:
                return {"name": u.get("displayName") or u.get("name") or "", "email": u.get("emailAddress") or u.get("email") or "",
                        "account_id": u.get("accountId") or u.get("account_id") or ""}
        return {"name": "", "email": "", "account_id": ""}


def _columns(cfg: dict) -> list[dict]:
    cols = (cfg.get("columnConfig") or {}).get("columns") or []
    return [{"name": c.get("name", ""), "status_ids": [str(s.get("id")) for s in c.get("statuses", []) if s.get("id")],
             "statuses": [s.get("name", "") for s in c.get("statuses", [])]} for c in cols if c.get("name")]


def _count(res: Any) -> Optional[int]:
    if not isinstance(res, dict):
        return None
    for k in ("count", "total", "approximateCount"):
        if isinstance(res.get(k), int):
            return res[k]
    if isinstance(res.get("issues"), list) and res.get("isLast"):
        return len(res["issues"])
    return None


def discover(mcp: AtlassianMcp, link: dict) -> dict:
    """Everything the connect screen shows, read with the user's own Atlassian access."""
    sites = mcp.sites()
    site = next((s for s in sites if (urlparse(s.get("url", "")).hostname or "").lower() == link["site"]), None)
    if not site:
        seen = ", ".join(urlparse(s.get("url", "")).hostname or "" for s in sites) or "none"
        raise McpError(f"The Atlassian account you signed in with can't open {link['site']}. Sites it can open: {seen}.")
    mcp.cloud_id = site.get("id") or site.get("cloudId") or ""
    if "jira" not in {p.get("id") for p in site.get("products", []) if isinstance(p, dict)} and site.get("products"):
        raise McpError(f"{link['site']} has no Jira access for this account.")
    me = mcp.me()

    board_id, project_key = link.get("board_id", ""), link.get("project_key", "")
    boards: list[dict] = []
    if not board_id:
        if not project_key:
            raise McpError("The link has no project or board in it. Paste the link of the board you test from.")
        res = mcp.op("listJiraBoards", projectKeyOrId=project_key, maxResults=50)
        boards = [{"id": str(b.get("id")), "name": b.get("name", "")} for b in (res.get("values", []) if isinstance(res, dict) else [])]
        if not boards:
            raise McpError(f"No board found for project {project_key}. Paste the board's link instead.")
        board_id = boards[0]["id"]
    try:
        cfg = mcp.op("getJiraBoardConfig", boardId=int(board_id))
    except McpError as e:
        raise McpError(f"Can't open board {board_id} on {link['site']}: {e}") from e
    loc = cfg.get("location") or {}
    project_key = project_key or loc.get("key") or loc.get("projectKey") or ""
    project = {"key": project_key, "name": loc.get("name") or loc.get("projectName") or project_key, "style": ""}
    try:
        res = mcp.op("listJiraProjects", query=project_key, maxResults=10)
        hit = next((p for p in (res.get("values", []) if isinstance(res, dict) else []) if p.get("key") == project_key), None)
        if hit:
            project = {"key": project_key, "name": hit.get("name", project_key),
                       "style": "team-managed" if hit.get("style") == "next-gen" else "company-managed"}
    except McpError:
        pass
    columns = _columns(cfg)
    for c in columns:
        c["count"] = None
        if c["status_ids"]:
            try:
                c["count"] = _count(mcp.op("getJiraBoardIssueData", boardId=int(board_id), dataset="board",
                                           jql=f"status in ({','.join(c['status_ids'])})", searchResultMode="count"))
            except McpError:
                pass
    components: list[str] = []
    try:
        res = mcp.op("listJiraProjectComponents", projectIdOrKey=project_key)
        components = [c.get("name", "") for c in (res.get("values", []) if isinstance(res, dict) else []) if c.get("name")]
    except McpError:
        pass
    return {"site": link["site"], "base_url": link["base_url"], "cloud_id": mcp.cloud_id, "user": me,
            "project": project, "board": {"id": str(board_id), "name": cfg.get("name", f"Board {board_id}"), "type": cfg.get("type", "")},
            "boards": boards, "columns": columns, "components": components, "link": link}


# ------------------------------------------------------------------------------------- Testing board client
def _fields_components(f: dict) -> list[str]:
    out = []
    for c in f.get("components") or []:
        out.append(c.get("name", "") if isinstance(c, dict) else str(c))
    return [c for c in out if c]


def _body(c: Any) -> str:
    if isinstance(c, str):
        return c
    b = c.get("body", "") if isinstance(c, dict) else ""
    return b if isinstance(b, str) else str(b)


class McpJira:
    """The Testing board's Jira, reached through Atlassian's MCP server with the signed-in user's access."""

    def __init__(self, jira: dict, workflow: dict, mcp: Optional[AtlassianMcp] = None) -> None:
        conn = jira.get("connection") or {}
        self.cloud_id = jira.get("cloud_id") or conn.get("cloud_id", "")
        if not self.cloud_id:
            raise McpError("Jira is not connected. Paste your board link on the Integrations screen and sign in with Atlassian.")
        self.board_id = str(jira.get("board_id") or (conn.get("board") or {}).get("id") or "")
        self.status_ids = [s.strip() for s in str(workflow.get("jira_column_statuses") or "").split(",") if s.strip()]
        self.mcp = mcp or AtlassianMcp.signed_in(self.cloud_id)

    def search_column(self, project: str, column: str) -> list[dict]:
        fields = ["summary", "status", "components", "labels"]
        if self.board_id and self.status_ids:
            res = self.mcp.op("getJiraBoardIssueData", boardId=int(self.board_id), dataset="board",
                              jql=f"status in ({','.join(self.status_ids)})", fields=fields, maxResults=50)
        else:
            jql = f'project = "{project}" AND status = "{column}" ORDER BY updated DESC'
            res = self.mcp.op("searchJiraIssuesUsingJql", jql=jql, fields=fields, maxResults=50)
        issues = res.get("issues", []) if isinstance(res, dict) else []
        return [{"key": i["key"], "title": (i.get("fields") or {}).get("summary", ""),
                 "status": ((i.get("fields") or {}).get("status") or {}).get("name", ""),
                 "components": _fields_components(i.get("fields") or {})} for i in issues]

    def get_issue(self, key: str) -> dict:
        from .jira import preview_url

        raw = self.mcp.op("getJiraIssue", issueIdOrKey=key, view="evidence")
        f = raw.get("fields") or {}
        comments: list[str] = []
        try:
            res = self.mcp.op("listJiraIssueComments", issueIdOrKey=key, maxResults=100, orderBy="created")
            comments = [_body(c) for c in (res.get("comments", []) if isinstance(res, dict) else [])]
        except McpError:
            pass
        description = f.get("description") or ""
        return {"key": raw.get("key", key), "title": f.get("summary", ""), "status": (f.get("status") or {}).get("name", ""),
                "description": description if isinstance(description, str) else str(description),
                "components": _fields_components(f), "comments": comments,
                "merged": False, "pr_url": "", "preview_url": preview_url(comments)}

    def add_comment(self, key: str, text: str) -> None:
        self.mcp.op("addOrEditJiraIssueComment", issueIdOrKey=key, commentBody=text)  # markdown

    def get_transitions(self, key: str) -> list[dict]:
        res = self.mcp.op("listJiraIssueTransitions", issueIdOrKey=key)
        return [{"id": str(t.get("id")), "name": t.get("name", "")} for t in (res.get("transitions", []) if isinstance(res, dict) else [])]

    def transition(self, key: str, transition_id: str) -> str:
        names = {t["id"]: t["name"] for t in self.get_transitions(key)}
        res = self.mcp.op("transitionJiraIssue", issueIdOrKey=key, transitionId=str(transition_id))
        landed = ""
        if isinstance(res, dict):
            st = res.get("status") or res.get("toStatus") or res.get("landedStatus") or {}
            landed = st.get("name", "") if isinstance(st, dict) else str(st)
        return landed or names.get(str(transition_id), "")
