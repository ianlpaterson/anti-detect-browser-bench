"""Camoufox: Firefox fork with C-level fingerprint spoofing.

Config notes:
- os='macos' makes UA + navigator.platform consistent with the host (Camoufox
  default can claim Windows on a macOS box, which Cloudflare's consistency
  checks catch).
- webgl_config=('Apple', 'Apple M1, or similar') pins the WebGL renderer to an
  Apple GPU. Without it, Camoufox's random fingerprint sampling can pick an
  Intel-Mac WebGL combo whose entry is missing from cloverlabs's WebGL DB,
  causing `ValueError: No WebGL data found for vendor X and renderer Y` and
  crashing the launch. "Apple M1, or similar" is the 82% mac entry.
- humanize=True enables bezier-cursor + per-char typing entropy.
- locale=['en-CA', 'en-US', 'en'] OVERRIDES geoip-derived locale. With geoip=True
  on a Vancouver IP, Camoufox auto-sets locale to fr-CA which is a real-user
  rarity (fr-CA speakers are nearly all in Quebec). Explicit en-CA avoids that.

NOT used here (and why):
- `fingerprint_preset=True` (cloverlabs feature): crashes on the WebGL DB miss
  mentioned above. The webgl_config pin works around it but the preset
  selection itself is unreliable for some renderer combos.
- `geoip=True`: triggers the fr-CA locale auto-set. Override via explicit
  locale instead. Re-enable if scraping needs TZ/WebRTC coherence.

KNOWN LIMITATION: Camoufox v135's TLS cipher list includes 0xC009
(TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA) which Mozilla removed between Firefox
135 and 150. JA4 doesn't match any current real Firefox; strict-JA4 CF configs
(e.g., canadianinsider.com) flag this. Standard CF sites (reddit, medium,
dev.to, github) pass cleanly.

REQUIRES: cloverlabs-camoufox >= 0.5.0 (Python 3.10+).
  pip install cloverlabs-camoufox[geoip]
  python -m camoufox fetch
"""
from contextlib import contextmanager
from camoufox.sync_api import Camoufox


@contextmanager
def session(headless: bool = False):
    with Camoufox(
        headless=headless,
        os="macos",
        webgl_config=("Apple", "Apple M1, or similar"),
        humanize=True,
        locale=["en-CA", "en-US", "en"],
    ) as browser:
        yield browser


def version(browser) -> str:
    """Engine version (Camoufox bundled Firefox). Best-effort."""
    try:
        v = getattr(browser, "version", None)
        if v and isinstance(v, str):
            return f"Firefox {v} (camoufox)"
    except Exception:
        pass
    return "Firefox unknown (camoufox)"
