"""Visual regression: full-page screenshots per viewport compared against stored baselines."""
from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageChops

from ..config import BASELINES_DIR
from ..models import Finding, Severity
from . import VIEWPORTS, PageContext, slug

PIXEL_TOLERANCE = 16   # per-channel difference ignored (anti-aliasing noise)


def compare(baseline: Path, current: Path, diff_out: Path) -> tuple[float, bool]:
    """Return (% differing pixels, size_changed) and write a highlighted diff image."""
    a = Image.open(baseline).convert("RGB")
    b = Image.open(current).convert("RGB")
    size_changed = a.size != b.size
    w, h = max(a.width, b.width), max(a.height, b.height)
    canvas_a = Image.new("RGB", (w, h), (255, 0, 255)); canvas_a.paste(a)
    canvas_b = Image.new("RGB", (w, h), (255, 0, 255)); canvas_b.paste(b)

    diff = ImageChops.difference(canvas_a, canvas_b).convert("L")
    mask = diff.point(lambda v: 255 if v > PIXEL_TOLERANCE else 0)
    changed = sum(mask.histogram()[255:])
    percent = changed / (w * h) * 100

    if changed:
        overlay = Image.blend(canvas_b, Image.new("RGB", (w, h), (255, 255, 255)), 0.6)
        overlay.paste(Image.new("RGB", (w, h), (230, 30, 30)), mask=mask)
        diff_out.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(diff_out)
    return percent, size_changed


def run(ctx: PageContext) -> None:
    page = ctx.page
    original = page.viewport_size
    host_dir = BASELINES_DIR / slug(urlparse(ctx.url).netloc)
    for vp_name in ctx.config.viewports:
        vp = VIEWPORTS.get(vp_name)
        if not vp:
            continue
        page.set_viewport_size(vp)
        page.wait_for_timeout(400)   # let responsive layout settle
        name = f"{slug(ctx.url)}__{vp_name}.png"
        current = ctx.run_dir / "visual" / name
        current.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(current), full_page=True, animations="disabled")

        baseline = host_dir / name
        if ctx.config.update_baselines or not baseline.exists():
            baseline.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(current, baseline)
            ctx.add(Finding("visual", f"Baseline saved ({vp_name})", Severity.INFO, ctx.url,
                            "New baseline stored; future runs will be compared against it.", str(current)))
            continue

        diff_path = ctx.run_dir / "visual" / f"diff__{name}"
        percent, size_changed = compare(baseline, current, diff_path)
        if size_changed or percent > ctx.config.visual_threshold:
            severity = Severity.MAJOR if percent > 5 or size_changed else Severity.MINOR
            detail = f"{percent:.2f}% of pixels changed (threshold {ctx.config.visual_threshold}%)."
            if size_changed:
                detail += " Page dimensions changed."
            ctx.add(Finding("visual", f"Visual change detected ({vp_name})", severity, ctx.url, detail,
                            str(diff_path) if diff_path.exists() else str(current)))
    if original:
        page.set_viewport_size(original)
