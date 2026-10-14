"""Interactive SSO sign-in: opens a real browser window, then saves the session for the spec runs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

_open: dict[str, Any] = {}  # ticket key -> (playwright, browser, context)


def storage_state_path(auth_dir: Path) -> Path:
    return auth_dir / "storage-state.json"


def has_session(auth_dir: Path) -> bool:
    return storage_state_path(auth_dir).exists()


async def open_login(key: str, url: str) -> None:
    """Open a headed Chromium window on the environment so the user can sign in with SSO."""
    from playwright.async_api import async_playwright

    await close_login(key)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto(url)
    _open[key] = (pw, browser, context)


async def save_login(key: str, auth_dir: Path) -> bool:
    """Persist cookies and local storage from the open window. Returns False if no window was open."""
    entry = _open.get(key)
    if not entry:
        return has_session(auth_dir)
    _, _, context = entry
    auth_dir.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(storage_state_path(auth_dir)))
    await close_login(key)
    return True


async def close_login(key: str) -> None:
    entry = _open.pop(key, None)
    if not entry:
        return
    pw, browser, _ = entry
    try:
        await browser.close()
    finally:
        await pw.stop()
