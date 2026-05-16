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
