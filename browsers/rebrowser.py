"""Rebrowser: playwright-python pre-patched with rebrowser-patches.

Drop-in via the `rebrowser-playwright` PyPI wheel (no manual patcher required).

Install:
    pip install rebrowser-playwright
    rebrowser_playwright install chromium

The wheel ships its own browser binaries under a separate cache, so the
`rebrowser_playwright install` step is required even if vanilla Playwright
is already installed in the same venv. Import path is `rebrowser_playwright`
(underscore) to coexist with vanilla `playwright`.

Optional runtime tuning via env vars (set before process start):
    REBROWSER_PATCHES_RUNTIME_FIX_MODE = addBinding | alwaysIsolated | enableDisable | 0
    REBROWSER_PATCHES_DEBUG = 1
Defaults are fine for the bench; leave unset unless probing a specific leak.

Refs:
    https://github.com/rebrowser/rebrowser-patches
    https://github.com/rebrowser/rebrowser-playwright-python
    https://pypi.org/project/rebrowser-playwright/
"""
from contextlib import contextmanager
from rebrowser_playwright.sync_api import sync_playwright


@contextmanager
def session(headless: bool = False):
    p = sync_playwright().start()
    # Patches live in the bundled Chromium build; no channel override.
    # Using the bundled binary (not system Chrome) is what the rebrowser
    # patches are validated against.
    browser = p.chromium.launch(headless=headless)
    try:
        yield browser
    finally:
        browser.close()
        p.stop()


def version(browser) -> str:
    """Engine version (rebrowser bundled Chromium build)."""
    try:
        v = getattr(browser, "version", None)
        if v and isinstance(v, str):
            return f"Chromium {v} (rebrowser bundle)"
    except Exception:
        pass
    return "Chromium unknown (rebrowser bundle)"
