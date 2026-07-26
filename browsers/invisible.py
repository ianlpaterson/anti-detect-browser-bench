"""invisible_playwright: Firefox patched at the C++ level, driven by stock Playwright.

Config notes:
- seed=<int> pins the whole fingerprint. Same seed gives the same navigator /
  screen / WebGL / canvas / audio / font set, so a re-run compares like with
  like instead of rolling a new machine on every launch. Drop the seed for a
  fresh identity per session.
- humanize is on by default: the ordinary Playwright pointer calls follow a
  path drawn from the same seed, so the cursor travels instead of teleporting.
- locale="auto" and timezone="" are the defaults and derive both from the exit
  IP rather than from the host, which keeps the JS locale and timezone
  consistent with wherever the traffic actually leaves from.
- headless=False here to match the rest of the harness. Note that this
  package's headless=True is not a headless engine either: it renders on a
  hidden desktop (CreateDesktop on Windows, Xvfb on Linux) so the fingerprint
  stays that of a headed run.

The fingerprint is set inside the engine, so there are no JS shims on the page
and nothing to detect at the property-descriptor level.

REQUIRES: invisible-playwright >= 0.4 (Python 3.11+), on top of stock Playwright.
  pip install invisible-playwright
The patched Firefox binary is downloaded on first launch and cached.
"""
from contextlib import contextmanager

from invisible_playwright import InvisiblePlaywright


@contextmanager
def session(headless: bool = False):
    with InvisiblePlaywright(seed=42, headless=headless) as browser:
        yield browser


def version(browser) -> str:
    """Engine version (the patched Firefox shipped by invisible-playwright)."""
    try:
        from invisible_playwright import BINARY_VERSION, FIREFOX_UPSTREAM_VERSION

        return f"Firefox {FIREFOX_UPSTREAM_VERSION} (invisible_playwright {BINARY_VERSION})"
    except Exception:
        pass
    try:
        v = getattr(browser, "version", None)
        if v and isinstance(v, str):
            return f"Firefox {v} (invisible_playwright)"
    except Exception:
        pass
    return "Firefox unknown (invisible_playwright)"
