"""Website checks. Each per-page check exposes `run(ctx: PageContext)`."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page

from ..models import Finding, RunConfig

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 390, "height": 844},
}


@dataclass
class PageContext:
    page: Page
    url: str
    config: RunConfig
    run_dir: Path
    add: Callable[[Finding], None]
    log: Callable[[str], None]


def slug(text: str, max_len: int = 80) -> str:
    s = re.sub(r"^https?://", "", text)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return (s or "root")[:max_len]
