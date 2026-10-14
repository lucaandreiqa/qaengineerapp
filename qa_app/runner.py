"""Orchestrates a test run: crawl the site, run per-page checks, Lighthouse, reports."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

from playwright.sync_api import sync_playwright

from . import report
from .checks import VIEWPORTS, PageContext, accessibility, functional, lighthouse, seo, visual
from .config import RUNS_DIR, ensure_dirs
from .models import Finding, PageResult, RunConfig, RunResult, Severity

LIGHTHOUSE_MAX_PAGES = 3
PAGE_CHECKS = {"accessibility": accessibility.run, "visual": visual.run}


class Runner:
    def __init__(self, config: RunConfig, log: Callable[[str], None] = print,
                 on_finding: Callable[[Finding], None] | None = None,
                 on_progress: Callable[[int, int], None] | None = None):
        self.config = config
        self.log = log
        self.on_finding = on_finding or (lambda f: None)
        self.on_progress = on_progress or (lambda done, total: None)
        self.cancelled = threading.Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def _add(self, result: RunResult, finding: Finding) -> None:
        result.findings.append(finding)
        self.on_finding(finding)

    def run(self) -> RunResult:
        ensure_dirs()
        cfg = self.config
        if not cfg.url.startswith(("http://", "https://")):
            cfg.url = "https://" + cfg.url
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        result = RunResult(run_id=run_id, config=cfg, started=datetime.now(), output_dir=str(run_dir))
        add = lambda f: self._add(result, f)
        self.log(f"Run {run_id} → {cfg.url}  checks: {', '.join(cfg.checks)}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=cfg.headless)
            context = browser.new_context(viewport=VIEWPORTS["desktop"], ignore_https_errors=False)
            page = context.new_page()
            events = functional.new_events()
            functional.attach_listeners(page, events)

            queue, seen = deque([cfg.url]), {functional.normalize(cfg.url)}
            all_links: dict[str, str] = {}
            while queue and len(result.pages) < cfg.max_pages and not self.cancelled.is_set():
                url = queue.popleft()
                self.on_progress(len(result.pages), cfg.max_pages)
                self.log(f"[{len(result.pages) + 1}/{cfg.max_pages}] {url}")
                for k in events:
                    events[k].clear()
                start = time.perf_counter()
                try:
                    resp = page.goto(url, wait_until="load", timeout=45000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                except Exception as e:
                    add(Finding("functional", "Page failed to load", Severity.CRITICAL, url,
                                str(e).splitlines()[0]))
                    result.pages.append(PageResult(url, None, None))
                    continue
                load_ms = int((time.perf_counter() - start) * 1000)
                status = resp.status if resp else None
                result.pages.append(PageResult(url, status, load_ms, page.title()))

                if status and status >= 400:
                    shot = functional.page_screenshot(page, run_dir, url)
                    add(Finding("functional", f"Page returned HTTP {status}",
                                Severity.CRITICAL if status >= 500 or url == cfg.url else Severity.MAJOR,
                                url, "", shot))
                    continue

                if "functional" in cfg.checks:
                    shot = functional.page_screenshot(page, run_dir, url) if events["pageerror"] else None
                    functional.report_events(url, events, add, shot)

                links = functional.extract_links(page, page.url)
                for link in links:
                    all_links.setdefault(link, url)
                    key = functional.normalize(link)
                    if functional.same_site(link, cfg.url) and functional.is_crawlable(link) and key not in seen:
                        seen.add(key)
                        queue.append(link)

                ctx = PageContext(page, url, cfg, run_dir, add, self.log)
                if "seo" in cfg.checks or "performance" in cfg.checks:
                    page_metrics = result.metrics.setdefault("pages", {})
                    self._safe("seo", lambda: page_metrics.update({url: seo.run(ctx)}))
                for name, fn in PAGE_CHECKS.items():
                    if name in cfg.checks and not self.cancelled.is_set():
                        self._safe(name, lambda fn=fn: fn(ctx))

            if "functional" in cfg.checks and not self.cancelled.is_set():
                self.log(f"Checking {min(len(all_links), 150)} unique links…")
                functional.check_links(context.request, all_links, cfg.url, add, self.log)

            chrome_path = p.chromium.executable_path
            context.close()
            browser.close()

        if "performance" in cfg.checks and cfg.use_lighthouse and not self.cancelled.is_set():
            lh = {}
            for pr in [pg for pg in result.pages if pg.status and pg.status < 400][:LIGHTHOUSE_MAX_PAGES]:
                self.log(f"Lighthouse: {pr.url}")
                scores = lighthouse.run(pr.url, chrome_path, run_dir, add, self.log)
                if scores:
                    lh[pr.url] = scores
            result.metrics["lighthouse"] = lh

        result.finished = datetime.now()
        self.on_progress(cfg.max_pages, cfg.max_pages)
        result.report_path = str(report.write_html(result, run_dir))
        report.write_junit(result, run_dir)
        (run_dir / "result.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        self.log(("Cancelled. " if self.cancelled.is_set() else "") + result.summary_line())
        self.log(f"Report: {result.report_path}")
        return result

    def _safe(self, name: str, fn) -> None:
        try:
            fn()
        except Exception as e:
            self.log(f"  {name} check error: {str(e).splitlines()[0]}")
