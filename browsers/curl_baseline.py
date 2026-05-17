"""curl_baseline: no-JS HTTP floor for the bench.

REQUIRES: curl_cffi, lxml, cssselect. Selector resolution in
`_Locator.inner_text` calls `lxml.html.cssselect`, which needs the
`cssselect` package alongside lxml — installing lxml alone is not
enough.

Not a real browser; a curl_cffi.Session that impersonates Chrome's TLS+H2
fingerprint without launching anything that can execute JavaScript. The
purpose is to set the "what does a raw GET return" baseline against which
the real browser results can be judged:

- If curl_baseline gets ok and vanilla Playwright gets gated, the gate is
  JS-triggered (CF challenge, Akamai bm, F5 Support ID page, etc).
- If curl_baseline gets blocked (403/429) and all browsers also get
  blocked, the gate fires on the initial request — TLS/JA3 or IP-level —
  before any browser-specific code matters.
- If curl_baseline gets ok and an "anti-detect" browser is gated/blocked,
  the browser is FAILING to look human; raw curl beats the patched
  Chromium. Embarrassing finding for the patched browser.

curl_cffi impersonates Chrome 124's TLS fingerprint (JA3) and HTTP/2
SETTINGS. Default impersonation is `chrome` which currently maps to a
recent Chrome version.

Exposes the same Page/Browser surface bench.py uses, so the adapter
plugs straight into the bench's verdict + records flow.
"""
from __future__ import annotations

import html as _html
import os
import re
import time
from contextlib import contextmanager
from typing import Any, Optional
from urllib.parse import urlparse

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests.exceptions import (
        RequestException as _CurlRequestException,
    )
except ImportError:  # pragma: no cover - tested by skip
    curl_requests = None  # type: ignore
    _CurlRequestException = Exception  # type: ignore


# Default Chrome impersonation. curl_cffi >=0.7 accepts "chrome" as a
# stable alias; older releases require the explicit version string.
IMPERSONATE = "chrome"


# ---------------------------------------------------------------------------
# Page surface
# ---------------------------------------------------------------------------


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class _Response:
    def __init__(self, status: Optional[int]) -> None:
        self.status = status


class _Locator:
    """Minimal locator over a parsed HTML body.

    Supports `.first.inner_text(timeout=ms)` which is the only call
    bench.extract_score makes. Selector goes through `lxml.html.cssselect`
    if lxml is available; if not, the selector falls through and the
    extract is logged as an extract-fail (which is the bench's documented
    behavior for missing data).
    """

    def __init__(self, body: str, selector: str) -> None:
        self._body = body
        self._selector = selector

    @property
    def first(self) -> "_Locator":
        return self

    def inner_text(self, timeout: int = 5000) -> str:
        del timeout  # curl_baseline is synchronous; no waiting to do
        if not self._body:
            # No body to search means the selector has nothing to match;
            # Playwright raises TimeoutError in this case. We do the same
            # so bench.extract_score records <extract-fail: TimeoutError>
            # instead of a misleading empty string.
            raise TimeoutError(
                f"curl_baseline: empty body, cannot resolve selector "
                f"{self._selector!r}"
            )
        try:
            from lxml import html  # type: ignore
        except ImportError:
            raise RuntimeError(
                "lxml not installed; cannot resolve selector on static HTML"
            )
        tree = html.fromstring(self._body)
        matches = tree.cssselect(self._selector)
        if not matches:
            # Matches Playwright Locator.inner_text() contract: raise
            # rather than return empty when the selector did not bind.
            # extract_score catches and stores <extract-fail: TimeoutError>.
            raise TimeoutError(
                f"curl_baseline: selector {self._selector!r} matched no "
                f"element"
            )
        text = matches[0].text_content() or ""
        return text.strip()


class _Page:
    """Playwright-shape Page over a curl_cffi.Session.

    We do NOT follow JS redirects (there is no JS), but we do follow HTTP
    redirects via curl. The classifier's `main_statuses` list is filled by
    walking response.history.
    """

    def __init__(self, session: Any) -> None:
        self._session = session
        self._default_timeout_ms: int = 30_000
        self._on_response = None
        self._final_url: str = ""
        self._status: Optional[int] = None
        self._body: str = ""
        self._history: list[int] = []

    # --- Playwright API surface ----------------------------------------
    def set_default_timeout(self, timeout: int) -> None:
        self._default_timeout_ms = int(timeout)

    def set_default_navigation_timeout(self, timeout: int) -> None:
        self._default_timeout_ms = int(timeout)

    def on(self, event: str, handler) -> None:
        """Mimic Playwright's response listener.

        bench._attempt_once subscribes to "response" to capture main-frame
        status codes. We invoke the handler synthetically for each
        response in the redirect chain so the bench sees the full
        main-frame status sequence.
        """
        if event == "response":
            self._on_response = handler

    def goto(
        self,
        url: str,
        wait_until: str = "load",
        timeout: Optional[int] = None,
    ) -> _Response:
        del wait_until  # no equivalent; HTTP is synchronous
        timeout_ms = timeout if timeout is not None else self._default_timeout_ms
        timeout_s = max(timeout_ms / 1000.0, 1.0)
        try:
            resp = self._session.get(
                url,
                timeout=timeout_s,
                allow_redirects=True,
                impersonate=IMPERSONATE,
            )
            self._status = resp.status_code
            self._final_url = str(resp.url) or url
            self._history = [r.status_code for r in (resp.history or [])]
            try:
                self._body = resp.text or ""
            except Exception:
                # Some content-types raise on .text; fall back to bytes -> utf8.
                try:
                    self._body = (resp.content or b"").decode(
                        "utf-8", errors="replace"
                    )
                except Exception:
                    self._body = ""
            # Synthesize per-response callbacks: one for each redirect hop,
            # then one for the final response. Each gets a tiny shim that
            # exposes `frame.parent_frame is None` so bench's listener
            # records all entries as main-frame statuses.
            chain = self._history + [self._status]
            if self._on_response is not None:
                for s in chain:
                    self._on_response(_HttpResponseShim(s))
            return _Response(status=self._status)
        except _CurlRequestException as e:
            # Surface as Playwright-style exception so the bench's
            # try/except wraps it normally.
            raise RuntimeError(f"curl_baseline goto: {type(e).__name__}: {e}")
        except Exception as e:
            raise RuntimeError(f"curl_baseline goto: {type(e).__name__}: {e}")

    def wait_for_load_state(self, state: str = "load", timeout: int = 30_000) -> None:
        del state, timeout  # no-op; HTTP is already done

    @property
    def url(self) -> str:
        return self._final_url

    def title(self) -> str:
        if not self._body:
            return ""
        m = _TITLE_RE.search(self._body)
        if not m:
            return ""
        # html.unescape covers the full HTML5 entity table including the
        # ones a real browser resolves (&copy;, &hellip;, &nbsp;, numeric
        # entities like &#xA0;). Hand-rolled mapping previously missed
        # those and could let block-page titles like "Access&nbsp;Denied"
        # bypass the gate-title regex.
        raw = _html.unescape(m.group(1))
        # Real browsers collapse internal whitespace runs in document.title.
        return " ".join(raw.split()).strip()

    def content(self) -> str:
        return self._body

    def screenshot(self, path: str, full_page: bool = True) -> None:
        del full_page
        # curl_baseline has no rendered output. Write a 1-byte sentinel so
        # the per-target dir layout stays uniform with browser runs (the
        # bench's screenshot step is best-effort and never fails the cell).
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            # 1x1 transparent PNG so any viewer can open the file; better
            # than a 0-byte file for human-driven inspection.
            tiny_png = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\rIDATx\x9cc\xfc\xff\xff?\x03\x00\x05\xfe"
                b"\x02\xfeP\xcc\xe3\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            with open(path, "wb") as f:
                f.write(tiny_png)
        except Exception:
            pass

    def locator(self, selector: str) -> _Locator:
        return _Locator(self._body, selector)

    def evaluate(self, expression: str) -> Any:
        del expression
        return None  # no JS

    def close(self) -> None:
        pass


class _HttpResponseShim:
    """Stand-in shape for the bench's `response.frame.parent_frame is None`
    main-frame test. We pretend every HTTP response is a main-frame event,
    which is accurate for curl_baseline since there are no subframes.
    """

    class _Frame:
        parent_frame = None

    def __init__(self, status: int) -> None:
        self.status = status
        self.frame = self._Frame()


class _Context:
    """Playwright-shape BrowserContext. One session per context so cookies
    do not leak between targets (bench creates a fresh context per cell)."""

    def __init__(self) -> None:
        if curl_requests is None:
            raise RuntimeError("curl_cffi not installed")
        self._session = curl_requests.Session()

    def new_page(self) -> _Page:
        return _Page(self._session)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


class _Browser:
    """Playwright-shape Browser. Just a factory of _Context handles."""

    def new_context(self) -> _Context:
        return _Context()

    def new_page(self) -> _Page:
        # Bench falls back to browser.new_page if no context; provide a
        # context-less page so the fallback works.
        return _Context().new_page()

    @property
    def version(self) -> str:
        return _curl_cffi_version() or ""


def _curl_cffi_version() -> str:
    try:
        import curl_cffi  # type: ignore
        return getattr(curl_cffi, "__version__", "")
    except ImportError:
        return ""


# ---------------------------------------------------------------------------
# Factory entrypoints (match the contract of the other browsers/*.py)
# ---------------------------------------------------------------------------


@contextmanager
def session(headless: bool = False):
    del headless  # no concept of headed for HTTP
    if curl_requests is None:
        raise RuntimeError(
            "curl_cffi not installed; pip install curl_cffi"
        )
    browser = _Browser()
    try:
        yield browser
    finally:
        pass


def version(browser) -> str:
    """Engine version (curl_cffi package + Chrome impersonate label)."""
    try:
        v = getattr(browser, "version", None)
        if v and isinstance(v, str):
            return f"curl_cffi {v} (impersonate={IMPERSONATE})"
    except Exception:
        pass
    cv = _curl_cffi_version()
    if cv:
        return f"curl_cffi {cv} (impersonate={IMPERSONATE})"
    return f"curl_cffi unknown (impersonate={IMPERSONATE})"
