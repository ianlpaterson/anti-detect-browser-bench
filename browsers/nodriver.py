"""nodriver: pure-CDP stealth driver, successor to undetected-chromedriver.

nodriver talks directly to Chrome over the DevTools Protocol (no Selenium, no
webdriver binary). The library itself is async-only; this adapter wraps it in a
sync facade that mimics the subset of the Playwright Page/Browser API the bench
actually calls.

Install:
    pip install nodriver        # latest is 0.50.3 (PyPI, May 2026)

System Chrome is REQUIRED. nodriver does NOT download a Chromium binary; it
launches an existing install (default macOS path: /Applications/Google Chrome.app
/Contents/MacOS/Google Chrome). Pass browser_executable_path via uc.start() to
override. nodriver auto-spawns a temp user_data_dir per run and cleans it up.

Headed is the default and recommended mode (per upstream README); headless still
trips a handful of detectors that nodriver otherwise defeats. The bench keeps
headless=False to match the other adapters.

Adapter strategy: ONE long-lived event loop per session, driven by
loop.run_until_complete() on each sync call. This is the pragmatic middle
ground: no per-call loop spin-up cost, no background-thread complexity, and
nodriver's own examples use exactly this pattern via uc.loop(). The downside
(can't share a Page with other asyncio code in the same thread) does not apply
to the bench, which is fully synchronous.

Full-page screenshots: nodriver's Tab.save_screenshot(full_page=True) exists
upstream and uses CDP Page.captureScreenshot with captureBeyondViewport=True
under the hood, so we just delegate. No need for the manual
"resize viewport to scrollHeight then screenshot" dance.

Refs:
    https://github.com/ultrafunkamsterdam/nodriver
    https://pypi.org/project/nodriver/
    https://ultrafunkamsterdam.github.io/nodriver/
"""
from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from typing import Any, Optional

import nodriver as uc


# ---------------------------------------------------------------------------
# Sync facade
# ---------------------------------------------------------------------------


class _GotoResponse:
    """Stand-in for playwright.sync_api.Response. Only `.status` is consumed.

    nodriver's tab.get() returns the Tab itself, not a response object; CDP's
    Page.navigate doesn't surface a top-level HTTP status without a Network
    domain subscription. We return None-status, which the bench tolerates (it
    treats `response is None or response.status is None` as best-effort).
    """

    def __init__(self, status: Optional[int] = None) -> None:
        self.status = status


class _NoDriverLocator:
    """Minimal Playwright-shape locator. Only `.first.inner_text(timeout=ms)`.

    nodriver's selector API is async + element-based; we wrap a CSS selector
    and resolve it lazily on inner_text() so the bench's `.first` chain works.
    """

    def __init__(self, page: "_NoDriverPage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "_NoDriverLocator":
        # nodriver query_selector already returns the first match.
        return self

    def inner_text(self, timeout: int = 5000) -> str:
        async def _run() -> str:
            # wait_for raises asyncio.TimeoutError if it never appears.
            try:
                await self._page._tab.wait_for(
                    selector=self._selector, timeout=timeout / 1000.0
                )
            except Exception:
                return ""
            el = await self._page._tab.query_selector(self._selector)
            if el is None:
                return ""
            # Element has .text_all / .text; text_all gathers nested text nodes.
            txt = getattr(el, "text_all", None) or getattr(el, "text", None) or ""
            if callable(txt):
                txt = txt()
            return str(txt or "").strip()

        return self._page._run(_run())


class _NoDriverPage:
    """Playwright-shape Page over a nodriver Tab."""

    def __init__(self, browser: "_NoDriverBrowser", tab: Any) -> None:
        self._browser = browser
        self._tab = tab
        self._default_timeout_ms: int = 30_000

    # --- helpers --------------------------------------------------------
    def _run(self, coro):
        return self._browser._run(coro)

    # --- API ------------------------------------------------------------
    def set_default_timeout(self, timeout: int) -> None:
        self._default_timeout_ms = int(timeout)

    def goto(
        self,
        url: str,
        wait_until: str = "load",
        timeout: Optional[int] = None,
    ) -> _GotoResponse:
        timeout_ms = timeout if timeout is not None else self._default_timeout_ms

        async def _go() -> None:
            # browser.get() navigates the current/first tab and waits for the
            # initial DOM event; refresh our tab handle to whatever it returns.
            new_tab = await self._browser._browser.get(url)
            self._tab = new_tab
            # Map Playwright wait_until verbs onto a sleep / readyState poll.
            if wait_until == "domcontentloaded":
                await self._wait_ready("interactive", timeout_ms / 1000.0)
            elif wait_until == "networkidle":
                # nodriver has no first-class networkidle. Best-effort: wait
                # for readyState complete, then a short idle pause.
                await self._wait_ready("complete", timeout_ms / 1000.0)
                await asyncio.sleep(0.5)
            else:  # "load" or anything else
                await self._wait_ready("complete", timeout_ms / 1000.0)

        self._run(_go())
        return _GotoResponse(status=None)

    async def _wait_ready(self, target: str, timeout_s: float) -> None:
        # Poll document.readyState. nodriver's evaluate returns the JS value
        # directly when return_by_value (default) is True.
        deadline = asyncio.get_event_loop().time() + max(timeout_s, 0.1)
        while True:
            try:
                state = await self._tab.evaluate("document.readyState")
            except Exception:
                state = None
            if state == "complete" or (target == "interactive" and state in ("interactive", "complete")):
                return
            if asyncio.get_event_loop().time() >= deadline:
                return  # best-effort, do not raise
            await asyncio.sleep(0.1)

    def wait_for_load_state(self, state: str = "load", timeout: int = 30_000) -> None:
        async def _w() -> None:
            target = "complete" if state != "domcontentloaded" else "interactive"
            await self._wait_ready(target, timeout / 1000.0)
            if state == "networkidle":
                await asyncio.sleep(0.5)

        try:
            self._run(_w())
        except Exception:
            pass  # best-effort

    def title(self) -> str:
        async def _t() -> str:
            try:
                v = await self._tab.evaluate("document.title")
                return str(v or "")
            except Exception:
                return ""

        return self._run(_t())

    def content(self) -> str:
        async def _c() -> str:
            try:
                return await self._tab.get_content()
            except Exception:
                # Fallback: pull outerHTML directly.
                v = await self._tab.evaluate("document.documentElement.outerHTML")
                return str(v or "")

        return self._run(_c())

    def screenshot(self, path: str, full_page: bool = True) -> None:
        async def _s() -> None:
            # Ensure parent dir exists; nodriver does this internally but we
            # want a clean failure mode if `path` is unexpected.
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            fmt = "png" if path.lower().endswith(".png") else "jpeg"
            await self._tab.save_screenshot(
                filename=path, format=fmt, full_page=full_page
            )

        self._run(_s())

    def locator(self, selector: str) -> _NoDriverLocator:
        return _NoDriverLocator(self, selector)

    def evaluate(self, expression: str) -> Any:
        # Playwright accepts a JS arrow expression; nodriver wants a plain
        # expression. Strip a leading "() =>" if present so both shapes work.
        expr = expression.strip()
        if expr.startswith("() =>"):
            expr = expr[len("() =>") :].strip()
        elif expr.startswith("()=>"):
            expr = expr[len("()=>") :].strip()
        # Wrap in IIFE so multi-statement bodies still return a value.
        if expr.startswith("{") and expr.endswith("}"):
            wrapped = f"(function(){expr})()"
        else:
            wrapped = expr

        async def _e() -> Any:
            return await self._tab.evaluate(wrapped)

        return self._run(_e())

    @property
    def url(self) -> str:
        # tab.url is a CDP-cached property; refresh via a no-op sleep so the
        # post-redirect URL is current.
        async def _u() -> str:
            try:
                await self._tab.sleep(0)
            except Exception:
                pass
            return str(getattr(self._tab, "url", "") or "")

        return self._run(_u())


class _NoDriverBrowser:
    """Playwright-shape Browser over a nodriver Browser + dedicated event loop."""

    def __init__(self, browser: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._browser = browser
        self._loop = loop

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def new_page(self) -> _NoDriverPage:
        async def _new() -> Any:
            # Open a fresh tab; about:blank avoids any default-page noise.
            return await self._browser.get("about:blank", new_tab=True)

        tab = self._run(_new())
        return _NoDriverPage(self, tab)

    def new_context(self) -> "_NoDriverBrowser":
        # nodriver's "context" abstraction is per-Browser; reuse the browser
        # so .new_context().new_page() in the bench still works.
        return self


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


@contextmanager
def session(headless: bool = False):
    loop = uc.loop()  # asyncio.new_event_loop() + set_event_loop()
    browser = None
    try:
        browser = loop.run_until_complete(uc.start(headless=headless))
        yield _NoDriverBrowser(browser, loop)
    finally:
        if browser is not None:
            try:
                # stop() is synchronous in nodriver (it signals the chrome
                # process and reaps it). Wrapping in try/except because
                # racing teardown can raise ConnectionClosedError.
                browser.stop()
            except Exception:
                pass
        try:
            # Drain any leftover tasks so loop.close() doesn't warn.
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass
