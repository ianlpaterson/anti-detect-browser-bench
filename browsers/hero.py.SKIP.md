# Ulixee Hero — SKIPPED

Source of truth: https://github.com/ulixee/hero (MIT, 1.5K stars, last push 2026-05-16,
latest release v2.0.0-alpha.34). Primary language TypeScript / Node.js.

## Why skip

Hero is technically interesting for this bench — it is one of the few stealth
stacks that actually rewrites the TLS ClientHello, not just JS-level fingerprints.
But the integration cost does not fit a Python-Playwright bench:

1. **Node-only runtime.** No Python client exists on PyPI. No bindings. No FFI.
   See https://github.com/ulixee/hero — entire monorepo is `client/`, `core/`,
   `agent/` in TypeScript. The closest thing to a non-Node entry point is
   the Hero Core WebSocket RPC (`WsTransportToCore`), but the wire protocol
   is undocumented — re-implementing a Python client would mean reverse-
   engineering the RPC framing, the awaited-DOM call serialization, and the
   command-meta-queue protocol that Hero uses to round-trip every
   `document.querySelector` etc. across processes.

2. **API shape is wrong.** Hero is *not* Playwright-compatible. Its top-level
   object is `Hero` itself (`hero.goto(...)`, `hero.document.querySelector(...)`
   — awaited DOM), not `browser.new_context().new_page()`. Every bench harness
   that touches `browser.new_context` / `page.locator` would need a per-call
   adapter, not a thin shim.

3. **TLS rewrite is real but Node-side.** Hero ships its own MITM proxy
   (Node.js) that intercepts the browser's traffic and replays the
   ClientHello against `github.com/ulixee/utls` (their fork of refraction-
   networking's uTLS — a Go library exposing low-level ClientHello mimicry).
   The `tlsClientHelloId` config maps to uTLS values — `HelloChrome_Auto`,
   etc. Their ROADMAP-Hero.md has an explicit item "Convert Man-in-the-Middle
   from NodeJs to Chrome's network stack", which confirms TLS rewriting
   currently happens in Node, outside Chrome. Verified, not marketing.

4. **No prebuilt darwin-arm64 binary story.** The repo does not publish per-
   platform binaries — install pulls a chromium build via Puppeteer-style
   download. Apple Silicon works but is not first-class; release notes don't
   call it out. Manageable, but adds yet another moving piece.

## What a future integration would require

If TLS-rewrite signal becomes important enough to justify the cost:

**Architecture: Node sidecar + Python adapter.**

- Install: `npm i @ulixee/hero-playground` in a sibling dir (vendored Node
  project, not pip).
- Boot a Hero Core process via subprocess on a fixed port (e.g. `1818`),
  passing `tlsClientHelloId: 'HelloChrome_Auto'`.
- Either:
  - (a) write a small Node bridge that exposes a JSON-over-stdio API
    (`{cmd: 'goto', url: ...}` → `{ok: true, ...}`) wrapping Hero's TS
    client, and shell out from Python. **OR**
  - (b) reverse-engineer the WsTransportToCore JSON-RPC frames and speak
    them from Python over `websockets`. High effort, brittle to alpha
    releases.
- Build a NotPlaywright shim object that fakes `browser.new_context()` /
  `context.new_page()` / `page.goto()` / `page.locator()` by translating
  each call to Hero's flat `hero.goto / hero.document.querySelector / ...`
  API. The bench's test functions assume Playwright semantics; without
  this layer every test needs a hero-specific branch.

**Effort estimate:** Hard. Realistically 1-2 days of glue + ongoing
breakage as Hero is still 2.0.0-alpha. Compare: cloak / camoufox / patchright
each cost <15 lines of factory code because they ship a Playwright-shape
Python API.

## Decision

SKIP for now. Revisit if a TLS-fingerprint axis becomes load-bearing in the
bench results AND no lighter-weight option exists (e.g. curl-impersonate
for non-browser fetches, or a Playwright proxy plugin that rewrites the
ClientHello without swapping the whole runtime).
