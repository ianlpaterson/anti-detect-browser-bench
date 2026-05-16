"""Camoufox: Firefox fork with C-level fingerprint spoofing."""
from contextlib import contextmanager
from camoufox.sync_api import Camoufox


@contextmanager
def session(headless: bool = False):
    with Camoufox(headless=headless) as browser:
        yield browser
