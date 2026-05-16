"""CloakBrowser: stealth Chromium with C++-level patches. Playwright-compatible."""
from contextlib import contextmanager
import cloakbrowser


@contextmanager
def session(headless: bool = False):
    browser = cloakbrowser.launch(headless=headless)
    try:
        yield browser
    finally:
        try:
            browser.close()
        except Exception:
            pass
