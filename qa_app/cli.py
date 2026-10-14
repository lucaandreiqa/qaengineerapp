"""Headless command-line runner, intended for CI pipelines.

    python -m qa_app.cli https://example.com --checks functional,accessibility --max-pages 20 --publish

Exit code is 1 when findings at/above --fail-on exist, so the pipeline fails.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import integrations
from .config import load_settings
from .models import RunConfig, Severity
from .runner import Runner

ALL_CHECKS = ["functional", "visual", "accessibility", "seo", "performance"]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):   # Windows consoles default to cp1252
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="qa-app", description="Automated website QA checks")
    ap.add_argument("url")
    ap.add_argument("--checks", default="functional,accessibility,seo,visual",
                    help=f"comma list from: {','.join(ALL_CHECKS)} (or 'all')")
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--viewports", default="desktop,mobile", help="desktop,tablet,mobile")
    ap.add_argument("--visual-threshold", type=float, default=0.5, help="%% of pixels allowed to differ")
    ap.add_argument("--update-baselines", action="store_true")
    ap.add_argument("--no-lighthouse", action="store_true")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--publish", nargs="?", const="all", default=None,
                    help="send results to enabled integrations (optionally a comma list, e.g. jira,slack)")
    ap.add_argument("--fail-on", choices=["critical", "major", "minor", "never"], default="major")
    ap.add_argument("--out", help="copy report.html, junit.xml and result.json to this folder")
    args = ap.parse_args(argv)

    checks = ALL_CHECKS if args.checks == "all" else [c.strip() for c in args.checks.split(",") if c.strip()]
    unknown = set(checks) - set(ALL_CHECKS)
    if unknown:
        ap.error(f"unknown checks: {', '.join(unknown)}")

    cfg = RunConfig(url=args.url, checks=checks, max_pages=args.max_pages,
                    viewports=[v.strip() for v in args.viewports.split(",")],
                    visual_threshold=args.visual_threshold, use_lighthouse=not args.no_lighthouse,
                    headless=not args.headed, update_baselines=args.update_baselines)
    result = Runner(cfg).run()

    if args.publish:
        only = None if args.publish == "all" else args.publish.split(",")
        integrations.publish(result, load_settings(), only=only)

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name in ("report.html", "junit.xml", "result.json"):
            shutil.copy(Path(result.output_dir) / name, out / name)
        for sub in ("screenshots", "visual", "lighthouse"):
            if (Path(result.output_dir) / sub).exists():
                shutil.copytree(Path(result.output_dir) / sub, out / sub, dirs_exist_ok=True)

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## YourQA\n\n{result.summary_line()}\n\n| Severity | Check | Finding | Page |\n|---|---|---|---|\n")
            for f in sorted(result.findings, key=lambda f: f.severity.rank)[:50]:
                fh.write(f"| {f.severity.value} | {f.check} | {f.title} | {f.url} |\n")

    if args.fail_on == "never":
        return 0
    limit = Severity(args.fail_on).rank
    return 1 if any(f.severity.rank <= limit for f in result.findings) else 0


if __name__ == "__main__":
    sys.exit(main())
