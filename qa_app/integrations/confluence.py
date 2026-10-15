"""Confluence, read-only, through whichever Jira connection is set up: Atlassian sign-in (MCP) or email + API token
(REST; the same Atlassian token reads Confluence on the same site). Results are normalised to
search -> [{title, id, url, excerpt}] and page -> {title, url, text}."""
from __future__ import annotations

import html
import re
from typing import Any, Optional

PAGE_URL = re.compile(r"https?://[\w.-]+\.atlassian\.net/wiki/\S*?(?:/pages/(\d+)|/x/([\w-]+))", re.I)


def _plain(markup: str) -> str:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup or "", flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</(p|li|h\d|tr|div)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", html.unescape(t))).strip()


def _hits(res: Any, site: str = "") -> list[dict]:
    rows = res.get("results") if isinstance(res, dict) else res
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        c = r.get("content") if isinstance(r.get("content"), dict) else r
        url = r.get("url") or c.get("url") or ((c.get("_links") or {}).get("webui") or "")
        if url and url.startswith("/"):
            url = site.rstrip("/") + ("/wiki" if not url.startswith("/wiki") else "") + url
        title = c.get("title") or r.get("title") or ""
        if title:
            out.append({"title": title, "id": str(c.get("id") or r.get("id") or ""), "url": url,
                        "excerpt": _plain(r.get("excerpt") or "")[:300]})
    return out


class ViaMcp:
    def __init__(self, mcp) -> None:
        self.mcp = mcp

    def search(self, cql: str, limit: int = 5) -> list[dict]:
        tools = self.mcp._tools()
        name = "searchConfluenceUsingCql" if "searchConfluenceUsingCql" in tools and "searchConfluence" not in tools else "searchConfluence"
        return _hits(self.mcp.op(name, cql=cql, limit=limit))

    def page(self, url: str = "", page_id: str = "") -> dict:
        tools = self.mcp._tools()
        if "getConfluencePage" in tools and "getConfluenceContent" not in tools:  # classic tool set
            res = self.mcp.op("getConfluencePage", pageId=page_id or _page_id(url), contentFormat="markdown")
        else:
            loc = {"content_url": url} if url else {"content_id": page_id}
            res = self.mcp.op("getConfluenceContent", **loc, content_format="markdown", detail="full")
        res = res if isinstance(res, dict) else {"body": str(res or "")}
        body = res.get("body")
        if isinstance(body, dict):
            text = body.get("value") or (body.get("storage") or {}).get("value", "")
        else:
            text = body or res.get("content") or ""
        return {"title": res.get("title", ""), "url": url or res.get("url", ""), "text": _plain(str(text)) if "<" in str(text) else str(text)}


class ViaRest:
    def __init__(self, cfg: dict, session=None) -> None:
        from .jira import _session
        self.base = cfg["base_url"].rstrip("/")
        self.s = session or _session(cfg)

    def _get(self, path: str, **params) -> dict:
        r = self.s.get(self.base + path, params=params, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Confluence HTTP {r.status_code}: {r.text[:150]}")
        return r.json()

    def search(self, cql: str, limit: int = 5) -> list[dict]:
        return _hits(self._get("/wiki/rest/api/search", cql=cql, limit=limit), self.base)

    def page(self, url: str = "", page_id: str = "") -> dict:
        pid = page_id or _page_id(url)
        if not pid:
            raise RuntimeError(f"Can't tell the page from {url}")
        res = self._get(f"/wiki/api/v2/pages/{pid}", **{"body-format": "storage"})
        return {"title": res.get("title", ""), "url": url or f"{self.base}/wiki/pages/{pid}",
                "text": _plain(((res.get("body") or {}).get("storage") or {}).get("value", ""))}


def _page_id(url: str) -> str:
    m = PAGE_URL.search(url or "")
    return (m.group(1) or "") if m else ""


def for_jira(jira) -> Optional[Any]:
    """The Confluence reader for the board's Jira connection, or None (Azure Boards, demo data)."""
    if hasattr(jira, "mcp") and getattr(jira, "mcp", None) is not None and hasattr(jira.mcp, "_tools"):
        return ViaMcp(jira.mcp)
    cfg = getattr(jira, "cfg", None)
    if isinstance(cfg, dict) and cfg.get("base_url") and cfg.get("api_token") and "atlassian.net" in cfg.get("base_url", ""):
        return ViaRest(cfg)
    return None
