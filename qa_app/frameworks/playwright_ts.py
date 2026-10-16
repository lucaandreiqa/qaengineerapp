"""Playwright in TypeScript or JavaScript: what YourQA writes and runs today (see workflow/playwright_run.py)."""
from __future__ import annotations

import re

from .base import Adapter


class PlaywrightTS(Adapter):
    name = "playwright-ts"
    label = "Playwright (TypeScript)"
    spec_pattern = re.compile(r"\.(spec|test)\.[cm]?[jt]sx?$")

    def matches(self, profile: dict) -> bool:
        text = " ".join(str(profile.get(k) or "") for k in ("framework", "runner", "language")).lower()
        return "playwright" in text and "python" not in text and "pytest" not in text

    def spec_files(self, key: str) -> list[str]:
        return [f"{key}.spec.ts", f"{key}.serial.spec.ts"]
