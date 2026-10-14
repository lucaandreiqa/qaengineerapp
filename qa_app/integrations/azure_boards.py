"""Azure Boards (Azure DevOps): the Testing board's tickets from a board column, with a personal access token.

parse_azure_link()  organization, project, team and board from any Azure Boards URL
discover()          who you are, the project, the team's board and its columns (with work item counts)
AzureBoards         what the Testing board needs: work items in a column, full detail, comment, move

Work items are turned into the same shape as a Jira issue (title, state, type, tags as labels, area as
component, comments, links, attachments), so every step, skill and prompt works the same for both.
Moving a ticket = moving its card to another board column (the column's state is set with it).
The token needs Work Items: Read & write (and Project and Team: Read).
"""
from __future__ import annotations

import html
import re
from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse

import requests

API = "7.1"
COMMENTS_API = "7.1-preview.4"
PRIORITY = {1: "Highest", 2: "High", 3: "Medium", 4: "Low"}
CATEGORY = {"incoming": "new", "outgoing": "done", "inProgress": "indeterminate"}
# Work item fields the context shows under their own name; the rest of the System.* bookkeeping is left out.
NAMED = {"Microsoft.VSTS.Common.AcceptanceCriteria": "Acceptance Criteria", "Microsoft.VSTS.TCM.ReproSteps": "Repro Steps",
         "Microsoft.VSTS.TCM.SystemInfo": "System Info", "Microsoft.VSTS.Scheduling.StoryPoints": "Story Points",
         "Microsoft.VSTS.Scheduling.Effort": "Effort", "Microsoft.VSTS.Common.Severity": "Severity",
         "Microsoft.VSTS.Common.ValueArea": "Value Area", "Microsoft.VSTS.Build.FoundIn": "Found In",
         "Microsoft.VSTS.Build.IntegrationBuild": "Integration Build", "System.IterationPath": "Iteration",
         "System.AreaPath": "Area", "System.Reason": "Reason"}
LIST_FIELDS = ["System.Id", "System.Title", "System.State", "System.WorkItemType", "System.Tags", "System.AreaPath",
               "Microsoft.VSTS.Common.Priority"]


class AzureError(Exception):
    """A message for the user."""


# ------------------------------------------------------------------------------------- links
def parse_azure_link(link: str) -> dict:
    """Organization, project, team and board from an Azure Boards URL. Raises ValueError with a message for the user.

    https://dev.azure.com/acme/Shop/_boards/board/t/Shop%20Team/Stories
    https://acme.visualstudio.com/Shop/_boards/board/t/Shop Team/Backlog%20items
    https://dev.azure.com/acme/Shop/_workitems/edit/123
    https://dev.azure.com/acme/Shop/_boards/board     (the project's default team)
    """
    s = (link or "").strip().strip("<>\"'")
    if not s:
        raise ValueError("Paste a link to your Azure Boards board")
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    p = urlparse(s)
    host = (p.hostname or "").lower()
    parts = [unquote(x) for x in p.path.split("/") if x]
    if host == "dev.azure.com":
        if len(parts) < 2:
            raise ValueError("The link needs the organization and project: https://dev.azure.com/ORG/PROJECT/_boards/…")
        org, rest = parts[0], parts[1:]
        org_url = f"https://dev.azure.com/{quote(org)}"
    elif host.endswith(".visualstudio.com"):
        org = host.split(".")[0]
        rest = [x for x in parts if x.lower() != "defaultcollection"] if parts and parts[0].lower() == "defaultcollection" else parts
        if not rest:
            raise ValueError("The link needs the project: https://ORG.visualstudio.com/PROJECT/_boards/…")
        org_url = f"https://{host}"
    else:
        raise ValueError("That doesn't look like an Azure DevOps link (dev.azure.com/… or ….visualstudio.com/…)")
    project = rest[0]
    if project.startswith("_"):
        raise ValueError("The link has no project in it. Open your board in Azure Boards and copy its link.")
    team = board = item = ""
    tail = rest[1:]
    low = [x.lower() for x in tail]
    if "t" in low and low.index("t") + 1 < len(tail):  # …/_boards/board/t/{team}/{board}
        i = low.index("t")
        team = tail[i + 1]
        board = tail[i + 2] if i + 2 < len(tail) else ""
    if "edit" in low and low.index("edit") + 1 < len(tail) and tail[low.index("edit") + 1].isdigit():
        item = tail[low.index("edit") + 1]
    return {"site": f"{org_url.split('://')[1]}", "org": org, "org_url": org_url, "base_url": org_url, "project": project,
            "team": team, "board": board, "item_id": item}


def skill_key(project: str) -> str:
    """A project key for per-project skills (A-Z, 0-9, _), from an Azure project name."""
    k = re.sub(r"[^A-Z0-9]+", "_", project.upper()).strip("_")
    k = ("P_" + k) if k and not k[0].isalpha() else k
    return (k or "AZURE")[:20]


# ------------------------------------------------------------------------------------- text
def html_text(v: Any) -> str:
    """Azure's rich-text (HTML) fields as plain text with line breaks and bullets."""
    if v is None:
        return ""
    if not isinstance(v, str):
        return str(v)
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", v)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)</(p|div|h\d|tr|ul|ol|table|blockquote|pre)>", "\n", s)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = re.sub(r'(?i)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: m.group(2) if m.group(1) in m.group(2) else f"{m.group(2)} ({m.group(1)})", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", "\n".join(line.rstrip() for line in s.splitlines())).strip()


def comment_html(text: str) -> str:
    """The QA comment (markdown-ish) as the HTML Azure comments take."""
    out = []
    for line in (text or "").splitlines():
        e = html.escape(line)
        e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)
        e = re.sub(r"`([^`]+)`", r"<code>\1</code>", e)
        e = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', e)
        out.append(e)
    return "<br>".join(out)


def _person(v: Any) -> dict:
    if isinstance(v, dict):
        return {"displayName": v.get("displayName") or v.get("uniqueName") or ""}
    return {"displayName": str(v or "")}


def _date(v: Any) -> str:
    return str(v or "")


# ------------------------------------------------------------------------------------- HTTP
class Azure:
    def __init__(self, org_url: str, pat: str, http: Optional[requests.Session] = None) -> None:
        if not pat:
            raise AzureError("Azure Boards needs a personal access token")
        self.org_url = org_url.rstrip("/")
        self.s = http or requests.Session()
        self.s.auth = ("", pat)
        self.s.headers.update({"Accept": "application/json"})

    def req(self, method: str, path: str, *, version: str = API, params: Optional[dict] = None, json: Any = None,
            headers: Optional[dict] = None) -> Any:
        url = f"{self.org_url}/{path.lstrip('/')}"
        q = {**(params or {}), **({"api-version": version} if version else {})}
        try:
            r = self.s.request(method, url, params=q, json=json, headers=headers, timeout=30)
        except requests.RequestException as e:
            raise AzureError(f"Can't reach {self.org_url}: {e.__class__.__name__}") from e
        ctype = r.headers.get("Content-Type", "")
        if r.status_code in (401, 203) or (r.ok and "json" not in ctype and r.text.lstrip().startswith("<")):
            raise AzureError("Azure DevOps didn't accept the personal access token. Check it hasn't expired, that it's for this "
                             "organization, and that it has Work Items: Read & write.")
        if r.status_code == 403:
            raise AzureError("The personal access token can't do this. Give it Work Items: Read & write, and Project and Team: Read.")
        if r.status_code == 404:
            raise AzureError(f"Not found on {self.org_url}: {unquote(path.split('?')[0])}")
        if not r.ok:
            try:
                msg = r.json().get("message", "")
            except ValueError:
                msg = r.text[:150]
            raise AzureError(f"Azure DevOps answered HTTP {r.status_code}: {msg}")
        return r.json() if r.content else {}


def _p(*parts: str) -> str:
    return "/".join(quote(x, safe="") for x in parts)


def _wiql_str(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


# ------------------------------------------------------------------------------------- connect
def _board(az: Azure, project: str, team: str, board: str) -> dict:
    return az.req("GET", f"{_p(project, team)}/_apis/work/boards/{_p(board)}")


def _columns(az: Azure, project: str, team: str, b: dict) -> list[dict]:
    field = ((b.get("fields") or {}).get("columnField") or {}).get("referenceName", "")
    out = []
    for c in b.get("columns") or []:
        states = list(dict.fromkeys((c.get("stateMappings") or {}).values()))
        count = None
        if field:
            try:
                res = az.req("POST", f"{_p(project, team)}/_apis/wit/wiql", params={"$top": 1000},
                             json={"query": f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
                                            f"AND [{field}] = {_wiql_str(c.get('name', ''))}"})
                count = len(res.get("workItems") or [])
            except AzureError:
                pass
        out.append({"name": c.get("name", ""), "status_ids": [], "statuses": states,
                    "category": CATEGORY.get(c.get("columnType", ""), "indeterminate"), "count": count,
                    "states": c.get("stateMappings") or {}})
    return [c for c in out if c["name"]]


def discover(az: Azure, link: dict) -> dict:
    """Everything the connect screen shows: you, the project, the team's board and its columns."""
    try:
        proj = az.req("GET", f"_apis/projects/{_p(link['project'])}")
    except AzureError as e:
        if "Not found" in str(e):
            raise AzureError(f"Project '{link['project']}' isn't in {link['org']}, or the token can't see it.") from e
        raise
    project = proj.get("name") or link["project"]
    user = {"name": "", "email": "", "account_id": ""}
    try:
        cd = az.req("GET", "_apis/connectionData", version="")
        au = cd.get("authenticatedUser") or {}
        user = {"name": au.get("providerDisplayName") or au.get("customDisplayName") or "", "email": "",
                "account_id": au.get("id", "")}
    except AzureError:
        pass
    team = link.get("team") or (proj.get("defaultTeam") or {}).get("name") or f"{project} Team"
    boards = az.req("GET", f"{_p(project, team)}/_apis/work/boards").get("value") or []
    if not boards:
        raise AzureError(f"Team '{team}' has no boards in {project}.")
    want = (link.get("board") or "").lower()
    pick = next((b for b in boards if b.get("name", "").lower() == want), None) if want else None
    if want and not pick:
        raise AzureError(f"Team '{team}' has no board '{link['board']}'. Its boards: {', '.join(b.get('name', '') for b in boards)}.")
    pick = pick or boards[0]
    b = _board(az, project, team, pick.get("id") or pick.get("name"))
    column_field = ((b.get("fields") or {}).get("columnField") or {}).get("referenceName", "")
    done_field = ((b.get("fields") or {}).get("doneField") or {}).get("referenceName", "")
    return {"site": link["site"], "base_url": az.org_url, "cloud_id": "", "user": user,
            "project": {"key": skill_key(project), "name": project, "style": "", "id": proj.get("id", "")},
            "board": {"id": b.get("id", ""), "name": f"{team} · {b.get('name', pick.get('name', ''))}", "board": b.get("name", ""),
                      "team": team, "type": "azure", "column_field": column_field, "done_field": done_field},
            "boards": [{"id": x.get("id", ""), "name": x.get("name", "")} for x in boards],
            "columns": _columns(az, project, team, b), "columns_from": "board", "components": [], "link": link}


# ------------------------------------------------------------------------------------- work item → Jira-shaped issue
def to_raw(item: dict, column_field: str = "") -> dict:
    """A work item in the shape ticket_context.build() reads (the Jira issue shape)."""
    f = item.get("fields") or {}
    area = str(f.get("System.AreaPath") or "")
    area_leaf = area.split("\\")[-1] if "\\" in area else ""
    tags = [t.strip() for t in str(f.get("System.Tags") or "").split(";") if t.strip()]
    pr = f.get("Microsoft.VSTS.Common.Priority")
    custom: dict[str, Any] = {}
    for ref, name in NAMED.items():
        v = f.get(ref)
        if v not in (None, ""):
            custom[name] = html_text(v) if isinstance(v, str) else v
    if column_field and f.get(column_field):
        custom["Board column"] = f[column_field]
    for ref, v in f.items():
        if ref.startswith("Custom.") and v not in (None, ""):
            custom.setdefault(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", ref[7:]).replace("_", " "),
                              html_text(v) if isinstance(v, str) else _person(v)["displayName"] if isinstance(v, dict) else v)
    desc = html_text(f.get("System.Description"))
    links, parent, attachments = [], None, []
    for r in item.get("relations") or []:
        rel, a = r.get("rel", ""), r.get("attributes") or {}
        wid = (r.get("url") or "").rstrip("/").split("/")[-1]
        if rel == "System.LinkTypes.Hierarchy-Reverse" and wid.isdigit():
            parent = {"key": wid, "fields": {}}
        elif rel == "AttachedFile":
            attachments.append({"filename": a.get("name", ""), "created": a.get("resourceCreatedDate", ""), "size": a.get("resourceSize")})
        elif rel.startswith(("System.LinkTypes", "Microsoft.VSTS.Common", "Microsoft.VSTS.TestCase")) and wid.isdigit():
            links.append({"type": {"outward": a.get("name") or rel.rsplit(".", 1)[-1]}, "outwardIssue": {"key": wid, "fields": {}}})
    return {"key": str(item.get("id", "")), "fields": {
        "summary": f.get("System.Title", ""), "status": {"name": f.get("System.State", "")},
        "issuetype": {"name": f.get("System.WorkItemType", "")}, "priority": {"name": PRIORITY.get(pr, str(pr or ""))},
        "labels": tags, "components": [{"name": area_leaf}] if area_leaf else [],
        "description": desc, "reporter": _person(f.get("System.CreatedBy")), "assignee": _person(f.get("System.AssignedTo")),
        "created": _date(f.get("System.CreatedDate")), "updated": _date(f.get("System.ChangedDate")),
        "resolution": f.get("Microsoft.VSTS.Common.ResolvedReason", ""),
        "parent": parent, "issuelinks": links, "attachment": attachments, "customFields": custom}}


def web_links(item: dict) -> list[dict]:
    out = []
    for r in item.get("relations") or []:
        a = r.get("attributes") or {}
        if r.get("rel") == "Hyperlink" and r.get("url"):
            out.append({"title": a.get("comment") or "", "url": r["url"]})
        elif r.get("rel") == "ArtifactLink" and a.get("name") == "Pull Request":
            out.append({"title": "Pull request", "url": r.get("url", "")})
    return out


# ------------------------------------------------------------------------------------- Testing board client
class AzureBoards:
    """The Testing board's tracker when it is Azure Boards (same calls as the Jira clients)."""

    def __init__(self, cfg: dict, workflow: Optional[dict] = None, http: Optional[requests.Session] = None) -> None:
        conn = cfg.get("connection") or {}
        if not (cfg.get("org_url") and cfg.get("project") and cfg.get("pat")):
            raise AzureError("Azure Boards is not connected. Paste your board link on the Integrations screen.")
        self.az = Azure(cfg["org_url"], cfg["pat"], http)
        self.project, self.team = cfg["project"], cfg.get("team", "")
        board = conn.get("board") or {}
        self.column_field = cfg.get("column_field") or board.get("column_field", "")
        self.done_field = board.get("done_field", "")
        self.columns = {c["name"]: c for c in conn.get("columns") or []}

    def search_column(self, project: str, column: str) -> list[dict]:
        from ..workflow.ticket_context import brief

        field = self.column_field or "System.BoardColumn"
        q = (f"SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project AND [{field}] = {_wiql_str(column)} "
             "ORDER BY [System.ChangedDate] DESC")
        res = self.az.req("POST", f"{_p(self.project, self.team) if self.team else _p(self.project)}/_apis/wit/wiql",
                          params={"$top": 50}, json={"query": q})
        ids = [w["id"] for w in res.get("workItems") or []][:50]
        if not ids:
            return []
        items = self.az.req("POST", f"{_p(self.project)}/_apis/wit/workitemsbatch",
                            json={"ids": ids, "fields": LIST_FIELDS}).get("value") or []
        order = {i: n for n, i in enumerate(ids)}
        return [brief(to_raw(i)) for i in sorted(items, key=lambda i: order.get(i.get("id"), 0))]

    def _item(self, key: str, expand: str = "all") -> dict:
        if not str(key).isdigit():
            raise AzureError(f"'{key}' is not an Azure Boards work item id")
        return self.az.req("GET", f"{_p(self.project)}/_apis/wit/workitems/{key}", params={"$expand": expand})

    def get_issue(self, key: str) -> dict:
        """Everything on the work item: fields, every comment, links, attachments, hyperlinks and pull requests."""
        from ..workflow.ticket_context import build
        from .jira import issue_dict

        item = self._item(key)
        comments: list[dict] = []
        token = ""
        while len(comments) < 1000:
            params = {"$top": 200, "order": "asc"}
            if token:
                params["continuationToken"] = token
            try:
                res = self.az.req("GET", f"{_p(self.project)}/_apis/wit/workItems/{key}/comments", version=COMMENTS_API, params=params)
            except AzureError:
                break
            comments += [{"author": _person(c.get("createdBy")), "created": c.get("createdDate", ""), "body": html_text(c.get("text"))}
                         for c in res.get("comments") or [] if not c.get("isDeleted")]
            token = res.get("continuationToken") or ""
            if not token:
                break
        out = issue_dict(build(to_raw(item, self.column_field), comments, web_links(item)))
        prs = [w["url"] for w in web_links(item) if w["title"] == "Pull request"]
        out["pr_url"] = prs[0] if prs else ""
        return out

    def add_comment(self, key: str, text: str) -> None:
        self.az.req("POST", f"{_p(self.project)}/_apis/wit/workItems/{key}/comments", version=COMMENTS_API,
                    json={"text": comment_html(text)})

    def _current_column(self, key: str) -> tuple[str, str]:
        f = (self._item(key, "none").get("fields") or {})
        return str(f.get(self.column_field, "") if self.column_field else f.get("System.BoardColumn", "")), f.get("System.WorkItemType", "")

    def get_transitions(self, key: str) -> list[dict]:
        """Where the card can go: the board's other columns."""
        cur, _ = self._current_column(key)
        return [{"id": name, "name": name} for name in self.columns if name != cur]

    def transition(self, key: str, transition_id: str) -> str:
        col = self.columns.get(transition_id)
        if not col:
            raise AzureError(f"'{transition_id}' is not a column on the board")
        _, wtype = self._current_column(key)
        ops = []
        if self.column_field:
            ops.append({"op": "add", "path": f"/fields/{self.column_field}", "value": transition_id})
        if self.done_field:
            ops.append({"op": "add", "path": f"/fields/{self.done_field}", "value": False})
        state = (col.get("states") or {}).get(wtype)
        if state:
            ops.append({"op": "add", "path": "/fields/System.State", "value": state})
        if not ops:
            raise AzureError("The board's column field is unknown. Refresh Azure Boards on the Integrations screen.")
        res = self.az.req("PATCH", f"{_p(self.project)}/_apis/wit/workitems/{key}", json=ops,
                          headers={"Content-Type": "application/json-patch+json"})
        f = res.get("fields") or {}
        return str(f.get(self.column_field) or f.get("System.BoardColumn") or transition_id)

    def url(self, key: str) -> str:
        return f"{self.az.org_url}/{_p(self.project)}/_workitems/edit/{key}"
