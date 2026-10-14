"""Google Lighthouse audits via Node (npx). Optional — skipped if Node isn't installed."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ..models import Finding, Severity
from . import slug

LIGHTHOUSE = "lighthouse@12.6.1"
CATEGORIES = ["performance", "accessibility", "best-practices", "seo"]


def available() -> bool:
    return shutil.which("npx") is not None


def run(url: str, chrome_path: str, run_dir: Path, add, log) -> dict | None:
    npx = shutil.which("npx")
    if not npx:
        log("  Lighthouse skipped: Node.js/npx not found")
        return None
    out = run_dir / "lighthouse" / f"{slug(url)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [npx, "--yes", LIGHTHOUSE, url, "--output=json", "--output=html",
           f"--output-path={out.with_suffix('')}", "--quiet",
           f"--only-categories={','.join(CATEGORIES)}",
           "--chrome-flags=--headless=new --no-sandbox --disable-gpu"]
    env = {**os.environ, "CHROME_PATH": chrome_path}
    try:
        subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=240, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        tail = (getattr(e, "stderr", "") or "").strip().splitlines()[-3:]
        log(f"  Lighthouse failed for {url}: {' | '.join(tail) or e}")
        return None

    data = json.loads(out.with_suffix(".report.json").read_text(encoding="utf-8"))
    scores = {k: round((v.get("score") or 0) * 100) for k, v in data["categories"].items()}
    audits = data["audits"]
    scores["lcp_ms"] = round(audits.get("largest-contentful-paint", {}).get("numericValue", 0))
    scores["cls"] = round(audits.get("cumulative-layout-shift", {}).get("numericValue", 0), 3)
    scores["tbt_ms"] = round(audits.get("total-blocking-time", {}).get("numericValue", 0))
    scores["report"] = str(out.with_suffix(".report.html"))

    for cat in CATEGORIES:
        s = scores.get(cat)
        if s is None:
            continue
        if s < 90:
            add(Finding(cat, f"Lighthouse {cat} score {s}/100", Severity.MAJOR if s < 50 else Severity.MINOR,
                        url, f"Full report: {scores['report']}"))
    if scores["lcp_ms"] > 4000:
        add(Finding("performance", "Poor Largest Contentful Paint", Severity.MAJOR, url, f"LCP {scores['lcp_ms']} ms (good < 2500)"))
    if scores["cls"] > 0.25:
        add(Finding("performance", "Poor Cumulative Layout Shift", Severity.MAJOR, url, f"CLS {scores['cls']} (good < 0.1)"))
    return scores
