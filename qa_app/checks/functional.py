"""Functional checks: crawling, HTTP status, console/JS errors, failed requests, broken links."""
from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlparse

from playwright.sync_api import APIRequestContext, Page

from ..models import Finding, Severity
from . import slug

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#")
NON_PAGE_EXT = (".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".mp4", ".mp3",
                ".doc", ".docx", ".xls", ".xlsx", ".csv", ".xml", ".json", ".css", ".js")


def is_crawlable(url: str) -> bool:
    return not urlparse(url).path.lower().endswith(NON_PAGE_EXT)


def attach_listeners(page: Page, events: dict) -> None:
    """Collect console errors, uncaught exceptions and failed sub-requests for the current page."""
    page.on("console", lambda m: m.type == "error" and events["console"].append(m.text))
    page.on("pageerror", lambda e: events["pageerror"].append(str(e)))
    page.on("requestfailed", lambda r: events["failed"].append(f"{r.url} ({r.failure})"))
    page.on("response", lambda r: r.status >= 400 and r.request.resource_type != "document"
            and events["failed"].append(f"{r.url} (HTTP {r.status})"))


def new_events() -> dict:
    return {"console": [], "pageerror": [], "failed": []}


def report_events(url: str, events: dict, add, screenshot: str | None) -> None:
    for msg in dict.fromkeys(events["pageerror"]):
        add(Finding("functional", "Uncaught JavaScript exception", Severity.MAJOR, url, msg, screenshot))
    for msg in list(dict.fromkeys(events["console"]))[:20]:
        add(Finding("functional", "Console error", Severity.MINOR, url, msg))
    for msg in list(dict.fromkeys(events["failed"]))[:20]:
        add(Finding("functional", "Failed resource request", Severity.MINOR, url, msg))


def extract_links(page: Page, base_url: str) -> list[str]:
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
    links = []
    for href in hrefs:
        if not href or href.strip().lower().startswith(SKIP_SCHEMES):
            continue
        absolute, _ = urldefrag(urljoin(base_url, href.strip()))
        if absolute.startswith(("http://", "https://")):
            links.append(absolute)
    return list(dict.fromkeys(links))


def normalize(url: str) -> str:
    """Treat /, /index.html and trailing slashes as the same page when crawling."""
    p = urlparse(url)
    path = p.path
    for index in ("index.html", "index.htm", "index.php"):
        if path.endswith("/" + index):
            path = path[: -len(index)]
    path = path.rstrip("/") or "/"
    return p._replace(path=path, fragment="").geturl()


def same_site(url: str, root: str) -> bool:
    return urlparse(url).netloc.lower().removeprefix("www.") == urlparse(root).netloc.lower().removeprefix("www.")


def check_links(request: APIRequestContext, links: dict[str, str], root: str, add, log, limit: int = 150) -> None:
    """links maps target -> page it was found on."""
    for i, (target, source) in enumerate(list(links.items())[:limit]):
        try:
            resp = request.head(target, timeout=10000, max_redirects=5)
            status = resp.status
            if status in (405, 403, 501):   # many servers reject HEAD — retry with GET
                status = request.get(target, timeout=15000, max_redirects=5).status
        except Exception as e:  # DNS, TLS, timeout
            status, err = None, str(e).splitlines()[0]
        else:
            err = f"HTTP {status}"
        if status is None or status >= 400:
            internal = same_site(target, root)
            add(Finding("functional", "Broken internal link" if internal else "Broken external link",
                        Severity.MAJOR if internal else Severity.MINOR, source, f"{target} → {err}"))
        if i and i % 25 == 0:
            log(f"  checked {i} links…")


def page_screenshot(page: Page, run_dir, url: str, suffix: str = "") -> str | None:
    path = run_dir / "screenshots" / f"{slug(url)}{suffix}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception:
        return None
