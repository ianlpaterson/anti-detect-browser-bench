"""Camoufox: Firefox fork with C-level fingerprint spoofing.

Pin os='macos' so the spoofed fingerprint is consistent with the host. Default
Camoufox can claim Windows on a macOS box, which Cloudflare's consistency checks
catch (canadianinsider.com blocks it). fingerprint_preset=True selects from
real in-the-wild macOS Firefox profiles bundled with v150+ binaries.
"""
from contextlib import contextmanager
from camoufox.sync_api import Camoufox


@contextmanager
def session(headless: bool = False):
    with Camoufox(headless=headless, os="macos") as browser:
        yield browser
