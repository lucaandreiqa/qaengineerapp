"""Everything a Jira ticket says, in one shape, whichever way it was read.

build()        raw issue (Jira REST, or Atlassian MCP current/classic tools) + comments + remote links → context dict
to_markdown()  the <KEY>-context.md file
for_prompt()   the same, trimmed to a size Claude can take, newest comments kept

Only the ticket itself: its fields, custom fields, comments, attachments (names), links to other tickets
(key, title, status) and web links. Linked tickets and attachments are not opened.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .models import status_category

# Jira bookkeeping that says nothing about what to test.
NOISE = {"rank", "workratio", "watches", "votes", "progress", "aggregateprogress", "issuerestriction", "statuscategorychangedate",
         "timetracking", "worklog", "lastviewed", "aggregatetimespent", "aggregatetimeestimate", "aggregatetimeoriginalestimate",
         "timespent", "timeestimate", "timeoriginalestimate", "thumbnail", "statuscategory", "creator", "development",
         "issue color", "team", "vulnerability", "design", "atlassian project", "goals", "start date"}
STANDARD = {"summary", "description", "issuetype", "status", "priority", "labels", "components", "fixversions", "versions",
            "reporter", "assignee", "created", "updated", "duedate", "resolution", "resolutiondate", "environment",
            "parent", "subtasks", "issuelinks", "attachment", "comment", "project", "security", "customfields"}


# ------------------------------------------------------------------------------------- values to text
def adf_text(node: Any) -> str:
    """Atlassian Document Format → plain text with line breaks and bullets."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "hardBreak":
        return "\n"
    if t in ("mention", "emoji", "status", "date", "inlineCard"):
        a = node.get("attrs") or {}
        return a.get("text") or a.get("shortName") or a.get("url") or ""
    inner = adf_text(node.get("content") or [])
    if t == "listItem":
        return "- " + inner.strip().replace("\n", "\n  ") + "\n"
    if t in ("paragraph", "heading", "codeBlock", "blockquote", "panel", "rule", "mediaSingle", "table", "tableRow"):
        return inner.rstrip() + "\n"
    if t in ("tableCell", "tableHeader"):
        return inner.strip() + " | "
    return inner


def text(v: Any) -> str:
    """Any Jira field value as short readable text ('' when empty)."""
    if v is None or v == "" or v == [] or v == {}:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return f"{v:g}"
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return ", ".join(t for t in (text(x) for x in v) if t)
    if isinstance(v, dict):
        if v.get("type") == "doc" or ("content" in v and "type" in v):
            return adf_text(v).strip()
        if "value" in v and set(v) <= {"id", "value", "self", "child", "disabled"}:
            child = text(v.get("child"))
            return text(v["value"]) + (f" › {child}" if child else "")
        for k in ("displayName", "name", "value", "key", "title"):
            if v.get(k) not in (None, ""):
                out = text(v[k])
                if k == "name" and v.get("state"):  # a sprint
                    out += f" ({v['state']})"
                return out
    return ""


def _person(v: Any) -> str:
    if isinstance(v, dict):
        return v.get("displayName") or v.get("emailAddress") or ""
    return text(v)


def _issue_ref(i: dict) -> dict:
    f = i.get("fields") or {}
    return {"key": i.get("key", ""), "title": f.get("summary", ""), "status": text(f.get("status")),
            "type": text(f.get("issuetype"))}


def _date(v: Any) -> str:
    s = text(v)
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?", s)
    return f"{m.group(1)} {m.group(2) or ''}".strip() if m else s


# ------------------------------------------------------------------------------------- build
def custom_fields(raw: dict) -> dict[str, Any]:
    """{field name: value} for custom fields, from the MCP 'customFields' map or REST customfield_* + names."""
    f = raw.get("fields") or {}
    out: dict[str, Any] = {}
    for name, v in (f.get("customFields") or {}).items():
        out[name] = v.get("value") if isinstance(v, dict) and "value" in v else v
    names = raw.get("names") or {}
    for k, v in f.items():
        if k.startswith("customfield_"):
            out.setdefault(names.get(k, k), v)
    return out


def build(raw: dict, comments: Optional[list[dict]] = None, remote_links: Optional[list[dict]] = None) -> dict:
    f = raw.get("fields") or {}
    cf = custom_fields(raw)
    if comments is None:
        cm = f.get("comment") or {}
        comments = cm.get("comments", []) if isinstance(cm, dict) else list(cm or [])
    links = []
    for l in f.get("issuelinks") or []:
        t = l.get("type") or {}
        if l.get("outwardIssue"):
            links.append({"relation": t.get("outward") or t.get("name", "relates to"), **_issue_ref(l["outwardIssue"])})
        if l.get("inwardIssue"):
            links.append({"relation": t.get("inward") or t.get("name", "relates to"), **_issue_ref(l["inwardIssue"])})
    pick = lambda pat: next((v for k, v in cf.items() if re.search(pat, k, re.I) and text(v)), None)  # noqa: E731
    acceptance = pick(r"acceptance|\bAC\b|definition of done")
    other = {}
    for k, v in cf.items():
        if k.lower() in NOISE or re.search(r"acceptance|\bAC\b|definition of done|story point|^sprint$|^rank$", k, re.I):
            continue
        t = text(v)
        if t and len(t) < 4000 and not (t.startswith("{") and t.endswith("}")):
            other[k] = t
    total = (f.get("comment") or {}).get("total") if isinstance(f.get("comment"), dict) else None
    ctx = {
        "key": raw.get("key", ""), "title": f.get("summary", ""), "issue_type": text(f.get("issuetype")),
        "status": text(f.get("status")), "status_cat": status_category(f.get("status") or {}), "priority": text(f.get("priority")), "resolution": text(f.get("resolution")),
        "labels": [text(x) for x in f.get("labels") or [] if text(x)],
        "components": [text(x) for x in f.get("components") or [] if text(x)],
        "fix_versions": [text(x) for x in f.get("fixVersions") or [] if text(x)],
        "affects_versions": [text(x) for x in f.get("versions") or [] if text(x)],
        "reporter": _person(f.get("reporter")), "assignee": _person(f.get("assignee")),
        "created": _date(f.get("created")), "updated": _date(f.get("updated")), "due": _date(f.get("duedate")),
        "sprint": text(pick(r"^sprint$")), "story_points": text(pick(r"story point")),
        "environment": text(f.get("environment")),
        "description": text(f.get("description")),
        "acceptance_criteria": text(acceptance),
        "parent": _issue_ref(f["parent"]) if isinstance(f.get("parent"), dict) and f["parent"].get("key") else None,
        "subtasks": [_issue_ref(s) for s in f.get("subtasks") or []],
        "links": links,
        "attachments": [{"name": a.get("filename") or a.get("name", ""), "type": a.get("mimeType", ""), "size": a.get("size"),
                         "author": _person(a.get("author")), "created": _date(a.get("created"))} for a in f.get("attachment") or []],
        "web_links": [{"title": (r.get("object") or r).get("title", ""), "url": (r.get("object") or r).get("url", "")}
                      for r in remote_links or [] if (r.get("object") or r).get("url")],
        "fields": other,
        "comments": [{"author": _person(c.get("author")), "created": _date(c.get("created")),
                      "body": text(c.get("body")) if not isinstance(c, str) else c} for c in comments],
    }
    if isinstance(total, int) and total > len(ctx["comments"]):
        ctx["comments_missing"] = total - len(ctx["comments"])
    return ctx


# ------------------------------------------------------------------------------------- output
def _lines(ctx: dict) -> list[tuple[str, str]]:
    rows = [("Type", ctx["issue_type"]), ("Status", ctx["status"]), ("Priority", ctx["priority"]),
            ("Resolution", ctx["resolution"]), ("Labels", ", ".join(ctx["labels"])), ("Components", ", ".join(ctx["components"])),
            ("Fix versions", ", ".join(ctx["fix_versions"])), ("Affects versions", ", ".join(ctx["affects_versions"])),
            ("Sprint", ctx["sprint"]), ("Story points", ctx["story_points"]), ("Reporter", ctx["reporter"]),
            ("Assignee", ctx["assignee"]), ("Created", ctx["created"]), ("Updated", ctx["updated"]), ("Due", ctx["due"])]
    rows += list(ctx["fields"].items())
    return [(k, v) for k, v in rows if v]


def to_markdown(ctx: dict, extra: Optional[dict] = None, comment_limit: Optional[int] = None) -> str:
    out = [f"# {ctx['key']}: {ctx['title']}", ""]
    out += [f"- **{k}:** {v}" for k, v in _lines(ctx)]
    for k, v in (extra or {}).items():
        out.append(f"- **{k}:** {v}")
    if ctx.get("parent"):
        p = ctx["parent"]
        out.append(f"- **Parent:** {p['key']} {p['title']} ({p['status']})")
    sections = [("Description", ctx["description"]), ("Acceptance criteria", ctx["acceptance_criteria"]),
                ("Environment", ctx["environment"])]
    for title, body in sections:
        if body:
            out += ["", f"## {title}", "", body]
    if ctx["subtasks"]:
        out += ["", "## Subtasks", ""] + [f"- {s['key']} {s['title']} ({s['status']})" for s in ctx["subtasks"]]
    if ctx["links"]:
        out += ["", "## Linked tickets", ""] + [f"- {l['relation']} {l['key']} {l['title']} ({l['status']})" for l in ctx["links"]]
    if ctx["web_links"]:
        out += ["", "## Web links", ""] + [f"- [{w['title'] or w['url']}]({w['url']})" for w in ctx["web_links"]]
    if ctx["attachments"]:
        out += ["", "## Attachments", ""] + [f"- {a['name']} ({a['type'] or 'file'}{', by ' + a['author'] if a['author'] else ''})"
                                             for a in ctx["attachments"]]
    comments = ctx["comments"]
    shown = comments if comment_limit is None else comments[-comment_limit:]
    out += ["", f"## Comments ({len(comments)})", ""]
    if len(shown) < len(comments):
        out.append(f"_{len(comments) - len(shown)} older comments left out for length._\n")
    if ctx.get("comments_missing"):
        out.append(f"_{ctx['comments_missing']} more comments on the ticket could not be read._\n")
    for c in shown:
        out += [f"**{c['author'] or 'Someone'}** · {c['created']}", "", c["body"] or "_(empty)_", ""]
    if not comments:
        out.append("_No comments._")
    return "\n".join(out).rstrip() + "\n"


def for_prompt(ctx: dict, extra: Optional[dict] = None, max_chars: int = 60000) -> str:
    """The context for Claude, dropping the oldest comments first if it is too long."""
    md = to_markdown(ctx, extra)
    n = len(ctx["comments"])
    while len(md) > max_chars and n > 0:
        n = max(0, n - max(1, n // 4))
        md = to_markdown(ctx, extra, comment_limit=n)
    return md[:max_chars]


def brief(i: dict) -> dict:
    """One row of a ticket search: what the board card shows."""
    f = i.get("fields") or {}
    return {"key": i.get("key", ""), "title": f.get("summary", ""), "status": text(f.get("status")),
            "status_cat": status_category(f.get("status") or {}), "issue_type": text(f.get("issuetype")),
            "priority": text(f.get("priority")),
            "components": [text(c) for c in f.get("components") or [] if text(c)]}


def summary(ctx: dict) -> dict:
    """Small version kept on the ticket for the board drawer."""
    return {"issue_type": ctx["issue_type"], "priority": ctx["priority"], "labels": ctx["labels"], "components": ctx["components"],
            "fix_versions": ctx["fix_versions"], "sprint": ctx["sprint"], "reporter": ctx["reporter"], "assignee": ctx["assignee"],
            "parent": ctx["parent"], "links": ctx["links"], "subtasks": ctx["subtasks"], "web_links": ctx["web_links"],
            "attachments": [a["name"] for a in ctx["attachments"]], "comments": len(ctx["comments"]),
            "has_description": bool(ctx["description"]), "has_acceptance": bool(ctx["acceptance_criteria"]),
            "fields": ctx["fields"]}
