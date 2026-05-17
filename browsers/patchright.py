"""Patchright: Playwright with Runtime.enable + CDP leak patches. Chrome channel recommended."""
from contextlib import contextmanager
from patchright.sync_api import sync_playwright


@contextmanager
def session(headless: bool = False):
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=headless,
        channel="chrome",  # patchright README: use system Chrome for max stealth
    )
    try:
        yield browser
    finally:
        browser.close()
        p.stop()


def version(browser) -> str:
    """Engine version (system Chrome, channel=chrome). Best-effort."""
    try:
        v = getattr(browser, "version", None)
        if v and isinstance(v, str):
            return f"Chrome {v} (patchright + channel=chrome)"
    except Exception:
        pass
    return "Chrome unknown (patchright + channel=chrome)"
