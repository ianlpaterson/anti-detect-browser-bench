"""Vanilla Playwright. No stealth. The baseline that gets flagged."""
from contextlib import contextmanager
from playwright.sync_api import sync_playwright


@contextmanager
def session(headless: bool = False):
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=headless)
    try:
        yield browser
    finally:
        browser.close()
        p.stop()


def version(browser) -> str:
    """Engine version string (e.g. 'Chromium 147.0.7049.0'). Best-effort."""
    try:
        v = getattr(browser, "version", None)
        if v and isinstance(v, str):
            return f"Chromium {v}"
    except Exception:
        pass
    return "Chromium unknown"
