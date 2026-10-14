"""Jira through Atlassian's MCP server: the user pastes a board link and signs in with Atlassian.

parse_jira_link()  site, project, board and ticket from any Jira URL
discover()         who signed in, the site's cloudId, the project, the board and its columns
McpJira            what the Testing board needs (tickets in a column, ticket detail, comment, move)

Atlassian's MCP server does not give every account the same tools. Two sets are handled:
  current  getJiraBoardConfig, listJiraIssueTransitions, addOrEditJiraIssueComment, … (some only
           through its executeRead / executeWrite runner)
  classic  getTransitionsForJiraIssue, addCommentToJiraIssue, getVisibleJiraProjects, and no board
           tools: the columns then come from the project's statuses.
Inputs are fitted to each tool's own input schema (renamed where the sets differ, unknown ones dropped).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .mcp_client import McpError, McpSession, OAuth, TokenStore


class McpMissingTool(McpError):
    """This account's Atlassian MCP tools don't include the operation."""

ATLASSIAN_MCP_URL = os.environ.get("QA_APP_ATLASSIAN_MCP_URL") or "https://mcp.atlassian.com/v1/mcp/authv2"
WRITE_OPS = {"addOrEditJiraIssueComment", "transitionJiraIssue", "createJiraIssue", "editJiraIssue"}
NO_CLOUD_OPS = {"getAccessibleAtlassianResources", "atlassianUserInfo"}
# The same operation in the classic tool set.
ALIASES = {"addOrEditJiraIssueComment": "addCommentToJiraIssue", "listJiraIssueTransitions": "getTransitionsForJiraIssue",
           "listJiraProjects": "getVisibleJiraProjects", "listJiraIssueRemoteIssueLinks": "getJiraIssueRemoteIssueLinks"}
STATUS_ORDER = {"new": 0, "to do": 0, "indeterminate": 1, "in progress": 1, "done": 2}


def status_jql(values: list[str]) -> str:
    """Status ids as numbers, names quoted: 10002, "In Review"."""
    return ", ".join(v if v.isdigit() else '"' + v.replace('"', '\\"') + '"' for v in values)


def _fit(args: dict, tool: dict) -> dict:
    """Shape the arguments for this tool's input schema: rename where the tool sets differ, drop unknown ones."""
    props = (tool.get("inputSchema") or {}).get("properties") or {}
    if not props:
        return args
    a = dict(args)
    if "transitionId" in a and "transition" in props and "transitionId" not in props:
        a["transition"] = {"id": str(a.pop("transitionId"))}
    if "query" in a and "searchString" in props and "query" not in props:
        a["searchString"] = a.pop("query")
    if "commentBody" in a and "contentFormat" in props:
        a.setdefault("contentFormat", "markdown")
    rcf = props.get("responseContentFormat")
    if rcf is not None and "markdown" in (rcf.get("enum") or ["markdown"]):
        a.setdefault("responseContentFormat", "markdown")
    return {k: v for k, v in a.items() if k in props}


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

    def _tools(self) -> dict[str, dict]:
        return {t.get("name", ""): t for t in self.s.tools()}

    def has(self, name: str) -> bool:
        tools = self._tools()
        return name in tools or ALIASES.get(name, "") in tools or "executeRead" in tools

    def op(self, name: str, **inputs: Any) -> Any:
        tools = self._tools()
        if name not in NO_CLOUD_OPS:
            if not self.cloud_id:
                raise McpError("No Atlassian site selected yet")
            inputs = {"cloudId": self.cloud_id, **inputs}
        tool = name if name in tools else ALIASES.get(name) if ALIASES.get(name) in tools else None
        if tool:
            return _unwrap(self.s.call(tool, _fit(inputs, tools[tool])))
        runner = "executeWrite" if name in WRITE_OPS else "executeRead"
        if runner in tools:
            rest = {k: v for k, v in inputs.items() if k != "cloudId"}
            return _unwrap(self.s.call(runner, {"name": name, "cloudId": self.cloud_id, "inputs": rest}))
        raise McpMissingTool(f"Atlassian's MCP server has no '{name}' tool for this account")

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
    from ..workflow.models import status_category
    return [{"name": c.get("name", ""), "status_ids": [str(s.get("id")) for s in c.get("statuses", []) if s.get("id")],
             "statuses": [s.get("name", "") for s in c.get("statuses", [])],
             "category": status_category({"name": (c.get("statuses") or [{}])[0].get("name", c.get("name", "")),
                                          "statusCategory": {"key": (c.get("statuses") or [{}])[0].get("category", "")}})}
            for c in cols if c.get("name")]


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
    cfg: Optional[dict] = None  # board settings, when this account's tools can read them
    if not board_id and project_key and mcp.has("listJiraBoards"):
        try:
            res = mcp.op("listJiraBoards", projectKeyOrId=project_key, maxResults=50)
            boards = [{"id": str(b.get("id")), "name": b.get("name", "")} for b in (res.get("values", []) if isinstance(res, dict) else [])]
        except McpMissingTool:
            pass
        board_id = boards[0]["id"] if boards else ""
    if board_id:
        try:
            cfg = mcp.op("getJiraBoardConfig", boardId=int(board_id))
        except McpMissingTool:
            cfg = None
        except McpError as e:
            raise McpError(f"Can't open board {board_id} on {link['site']}: {e}") from e
    if cfg:
        loc = cfg.get("location") or {}
        project_key = project_key or loc.get("key") or loc.get("projectKey") or ""
    if not project_key:
        raise McpError("The link has no project in it. Paste the link of the board you test from "
                       "(it contains /projects/KEY/boards/…).")
    project = {"key": project_key, "name": ((cfg or {}).get("location") or {}).get("name") or project_key, "style": ""}
    try:
        res = mcp.op("listJiraProjects", query=project_key, maxResults=50)
        values = res.get("values", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
        hit = next((p for p in values if isinstance(p, dict) and p.get("key") == project_key), None)
        if hit:
            project = {"key": project_key, "name": hit.get("name", project_key),
                       "style": "team-managed" if hit.get("style") == "next-gen" else "company-managed" if hit.get("style") else ""}
        elif not cfg:
            raise McpError(f"Project {project_key} is not on {link['site']}, or your account can't see it.")
    except McpMissingTool:
        pass

    seen_components: list[str] = []
    if cfg:
        columns_from = "board"
        board = {"id": str(board_id), "name": cfg.get("name", f"Board {board_id}"), "type": cfg.get("type", "")}
        columns = _columns(cfg)
        for c in columns:
            c["count"] = None
            if c["status_ids"]:
                try:
                    c["count"] = _count(mcp.op("getJiraBoardIssueData", boardId=int(board_id), dataset="board",
                                               jql=f"status in ({status_jql(c['status_ids'])})", searchResultMode="count"))
                except McpError:
                    pass
    else:  # classic tools: no board settings, so the columns are the project's statuses
        columns_from = "statuses"
        board = {"id": str(board_id), "name": f"{project['name']} board" if board_id else f"{project['name']} statuses", "type": "statuses"}
        columns, seen_components = _status_columns(mcp, project_key)
    components: list[str] = []
    try:
        res = mcp.op("listJiraProjectComponents", projectIdOrKey=project_key)
        components = [c.get("name", "") for c in (res.get("values", []) if isinstance(res, dict) else []) if c.get("name")]
    except McpError:
        components = seen_components
    return {"site": link["site"], "base_url": link["base_url"], "cloud_id": mcp.cloud_id, "user": me,
            "project": project, "board": board, "boards": boards, "columns": columns, "columns_from": columns_from,
            "components": components, "link": link}


def _status_columns(mcp: AtlassianMcp, project_key: str) -> tuple[list[dict], list[str]]:
    """The project's statuses in workflow order (to do, in progress, done), with ticket counts.
    Read from the project's tickets and the transitions open to one of them."""
    res = mcp.op("searchJiraIssuesUsingJql", jql=f'project = "{project_key}" ORDER BY updated DESC',
                 fields=["status", "components"], maxResults=100)
    issues = res.get("issues", []) if isinstance(res, dict) else []
    found: dict[str, dict] = {}

    def add(st: dict) -> None:
        name = (st or {}).get("name", "")
        if not name:
            return
        cat = (st.get("statusCategory") or {})
        rank = STATUS_ORDER.get(str(cat.get("key") or cat.get("name") or "").lower(), 1)
        cur = found.setdefault(name, {"id": "", "rank": rank, "seen": len(found), "count": 0})
        cur["id"] = cur["id"] or str(st.get("id") or "")

    components: list[str] = []
    for i in issues:
        f = i.get("fields") or {}
        add(f.get("status") or {})
        if (f.get("status") or {}).get("name"):
            found[f["status"]["name"]]["count"] += 1
        components += [c for c in _fields_components(f) if c not in components]
    if issues:
        try:
            tr = mcp.op("listJiraIssueTransitions", issueIdOrKey=issues[0]["key"], includeUnavailableTransitions=True)
            for t in (tr.get("transitions", []) if isinstance(tr, dict) else tr or []):
                add(t.get("to") or {})
        except McpError:
            pass
    complete = len(issues) < 100
    cols = []
    for name, v in sorted(found.items(), key=lambda kv: (kv[1]["rank"], kv[1]["seen"])):
        cols.append({"name": name, "status_ids": [v["id"] or name], "statuses": [name], "count": v["count"] if complete else None,
                     "category": ["new", "indeterminate", "done"][min(v["rank"], 2)]})
    return cols, components


# ------------------------------------------------------------------------------------- Testing board client
def _fields_components(f: dict) -> list[str]:
    out = []
    for c in f.get("components") or []:
        out.append(c.get("name", "") if isinstance(c, dict) else str(c))
    return [c for c in out if c]


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
        fields = ["summary", "status", "components", "labels", "issuetype", "priority"]
        if self.board_id and self.status_ids and self.mcp.has("getJiraBoardIssueData"):
            res = self.mcp.op("getJiraBoardIssueData", boardId=int(self.board_id), dataset="board",
                              jql=f"status in ({status_jql(self.status_ids)})", fields=fields, maxResults=50)
        elif self.status_ids:
            jql = f'project = "{project}" AND status in ({status_jql(self.status_ids)}) ORDER BY updated DESC'
            res = self.mcp.op("searchJiraIssuesUsingJql", jql=jql, fields=fields, maxResults=50)
        else:
            jql = f'project = "{project}" AND status = "{column}" ORDER BY updated DESC'
            res = self.mcp.op("searchJiraIssuesUsingJql", jql=jql, fields=fields, maxResults=50)
        issues = res.get("issues", []) if isinstance(res, dict) else []
        from ..workflow.ticket_context import brief
        return [brief(i) for i in issues]

    def get_issue(self, key: str) -> dict:
        """Everything on the ticket: all fields (custom ones by name), every comment, attachments, links."""
        from ..workflow.ticket_context import build
        from .jira import issue_dict

        comments: Optional[list[dict]] = None
        if self.mcp.has("listJiraIssueComments"):  # current tools: full view, comments paged separately
            raw = self.mcp.op("getJiraIssue", issueIdOrKey=key, view="full")
            comments = []
            while len(comments) < 1000:
                try:
                    res = self.mcp.op("listJiraIssueComments", issueIdOrKey=key, startAt=len(comments), maxResults=100, orderBy="created")
                except McpError:
                    comments = None  # fall back to the comments embedded in the issue
                    break
                page = res.get("comments", []) if isinstance(res, dict) else []
                comments += page
                if not page or res.get("isLast", True) or len(comments) >= int(res.get("total") or 0):
                    break
        else:  # classic tools: every field (custom ones resolved by the names map), comments embedded
            raw = self.mcp.op("getJiraIssue", issueIdOrKey=key, fields=["*all"], expand="names")
        links: list[dict] = []
        try:
            res = self.mcp.op("listJiraIssueRemoteIssueLinks", issueIdOrKey=key)
            links = res if isinstance(res, list) else (res.get("values") or res.get("remoteLinks") or res.get("links") or []) if isinstance(res, dict) else []
        except McpError:
            pass
        return issue_dict(build(raw, comments, links))

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
        if not landed:  # the classic tool returns nothing: read the status back
            try:
                f = (self.mcp.op("getJiraIssue", issueIdOrKey=key, fields=["status"]) or {}).get("fields") or {}
                landed = (f.get("status") or {}).get("name", "")
            except McpError:
                pass
        return landed or names.get(str(transition_id), "")
