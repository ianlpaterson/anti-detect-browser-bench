"""CloakBrowser: stealth Chromium with C++-level patches. Playwright-compatible.

humanize=True is required for the auto-resolve-Turnstile claim to fire (maintainer
confirms on CloakHQ/CloakBrowser#216). Still requires a clean residential IP;
datacenter IPs fail regardless. geoip=True auto-matches timezone/locale to the
proxy or local IP, which Cloudflare cross-checks.

PLATFORM VERSION DRIFT (verified 2026-05-16):
cloakbrowser==0.3.28 pins different Chromium versions per platform. From
the package's config.py PLATFORM_CHROMIUM_VERSIONS:
  linux-x64    : 146.0.7680.177.3
  linux-arm64  : 146.0.7680.177.3
  darwin-arm64 : 145.0.7632.109.2   <-- this bench's host
  darwin-x64   : 145.0.7632.109.2
  windows-x64  : 146.0.7680.177.4

CloakHQ's GitHub release history shows their last darwin-arm64 binary was
chromium-v145.0.7632.109.2 (published 2026-03-04). Since then they have
shipped 14 Linux/Windows-only releases but no new macOS build. There is
no in-pip upgrade path to Chromium 146 on darwin-arm64; would require
building from source. For the blog: report Cloak as 145 on darwin-arm64
and note that 146 results may differ when CloakHQ ships a new mac build.
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
