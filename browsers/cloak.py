"""CloakBrowser: stealth Chromium with C++-level patches. Playwright-compatible.

humanize=True is required for the auto-resolve-Turnstile claim to fire (maintainer
confirms on CloakHQ/CloakBrowser#216). Still requires a clean residential IP;
datacenter IPs fail regardless. geoip=True auto-matches timezone/locale to the
proxy or local IP, which Cloudflare cross-checks.
"""
from contextlib import contextmanager
import cloakbrowser


@contextmanager
def session(headless: bool = False):
    browser = cloakbrowser.launch(headless=headless, humanize=True, geoip=True)
    try:
        yield browser
    finally:
        try:
            browser.close()
        except Exception:
            pass


def version(browser) -> str:
    """Engine version (CloakBrowser bundled Chromium). Best-effort."""
    try:
        v = getattr(browser, "version", None)
        if v and isinstance(v, str):
            return f"Chromium {v} (cloak)"
    except Exception:
        pass
    return "Chromium unknown (cloak)"
