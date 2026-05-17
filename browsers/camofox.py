"""Camoufox: Firefox fork with C-level fingerprint spoofing.

Pin os='macos' so the spoofed fingerprint is consistent with the host (default
Camoufox can claim Windows on a macOS box, which Cloudflare's consistency checks
catch, e.g. canadianinsider.com).

`fingerprint_preset=True` opts into a real in-the-wild Firefox profile (canvas,
WebGL, audio, fonts, screen, timezone) instead of BrowserForge's synthesized
defaults. This kwarg was added in the cloverlabs-camoufox fork at v0.5.0
(2026-03-14). It does NOT exist in the mainline `camoufox` PyPI package, which
is frozen at v0.4.11 (2025-01-29).

REQUIRES: cloverlabs-camoufox >= 0.5.0 (NOT the upstream `camoufox` package).
  pip uninstall -y camoufox
  pip install -U cloverlabs-camoufox
  python -m camoufox fetch

Notes on binary compatibility:
- We use the v135 Firefox binary. cloverlabs ships two preset bundles:
  fingerprint-presets.json (30 macOS presets, pre-v149) and
  fingerprint-presets-v150.json (67 macOS presets, v149+). With a v135 binary,
  the older 30-preset bundle is auto-selected and the UA is regex-rewritten to
  match the binary version, so presets are still applied correctly.
- locale, geoip, humanize are deliberately left off here. Add geoip=True if
  the proxy/exit-IP needs lat/long/timezone consistency for Cloudflare.
"""
from contextlib import contextmanager
from camoufox.sync_api import Camoufox


@contextmanager
def session(headless: bool = False):
    with Camoufox(
        headless=headless,
        os="macos",
        fingerprint_preset=True,
    ) as browser:
        yield browser
