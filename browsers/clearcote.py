"""Clearcote: stealth Chromium with engine-level patches. Playwright-compatible.

Runs the open build without a key; set CLEARCOTE_LICENSE_KEY to run the
licensed build (newer Chromium major, recorded human input). humanize=True
turns on human-like mouse, keyboard and scroll input. geoip=True matches the
timezone, languages and Accept-Language to the proxy or local IP, like the
cloak adapter.

bench.py opens a fresh new_context() per target. On Windows and Linux,
launch() defaults to a persistent context (a throwaway profile), which has no
new_context(), so ephemeral_profile=False asks for a plain Browser there. On
macOS, launch() runs the Clearcote Docker image (Docker must be running) and
already returns a Browser.
"""
import sys
from contextlib import contextmanager
import clearcote


@contextmanager
def session(headless: bool = False):
    opts = {} if sys.platform == "darwin" else {"ephemeral_profile": False}
    browser = clearcote.launch(headless=headless, humanize=True, geoip=True, **opts)
    try:
        yield browser
    finally:
        try:
            browser.close()
        except Exception:
            pass


def version(browser) -> str:
    """Engine version (Clearcote bundled Chromium). Best-effort."""
    try:
        # launch() can hand back a BrowserContext; its .browser has the version.
        owner = getattr(browser, "browser", None) or browser
        v = getattr(owner, "version", None)
        if v and isinstance(v, str):
            return f"Chromium {v} (clearcote)"
    except Exception:
        pass
    return "Chromium unknown (clearcote)"
