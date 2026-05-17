#!/usr/bin/env python3
"""Anti-detect browser bench v2: hardened.

Changes from v1 (commit 10a2b48 and earlier):
- Gate classifier (_classify) — `ok` no longer just means "no exception fired"
- Retries (3x with exponential jitter) — single-shot CF/site flakiness no longer
  reported as a real pass/fail
- Fresh `new_context()` per target — kills cookie/clearance/session carryover
  between targets within a single browser run
- Status tracking — `page.on("response")` captures main-frame status codes,
  so a 200-then-403 redirect (canadianinsider exact case) is no longer scored
  as OK
- Standardized `wait_until=domcontentloaded` + optional post-load gate check,
  so the comparison across targets is fair
- `set_default_navigation_timeout` set explicitly in addition to
  `set_default_timeout` (the latter does NOT govern page.goto reliably)
- `BROWSER_READY <ts>` marker printed after session enter + before first goto,
  so stats_sweep can measure true cold-start vs "time to first OK"

Record schema (per target):
{
  "browser": str, "target": str, "url": str, "ts": int,
  "attempts": [
    {
      "ok": bool,              # no Python exception
      "verdict": str,          # ok | gated | blocked | error
      "load_ms": int,
      "final_url": str,
      "status": int | None,    # final main-frame status
      "main_statuses": [...],  # all main-frame responses observed
      "title": str,
      "body_len": int,
      "error": str | None,
    },
  ],
  "majority_verdict": str,
  "score": {...},              # last attempt's extract
}
"""
from __future__ import annotations

import argparse
import importlib
import json
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"

# Gate signals (case-insensitive substring match against title)
GATE_TITLE_PATTERNS = re.compile(
    r"(just a moment|attention required|access denied|cloudflare|verifying|"
    r"performing security verification|support id|please verify|"
    r"are you a human|robot check|captcha|radware block page|"
    r"shieldsquare|access to this page has been denied|"
    r"security check|incapsula|imperva|^error$|blocked by|"
    r"checking your browser)",
    re.I,
)
# Body signals (case-insensitive substring; for cases where title is the real
# site title but body is the gate)
GATE_BODY_PATTERNS = re.compile(
    r"(your support id is:|enable javascript and cookies to continue|"
    r"cf-error-details|cdn-cgi/challenge-platform|/cdn-cgi/bm/cv/|"
    r"data:image/svg.*cloudflare|"
    r"shieldsquare|perfdrive\.com|aperture\.js|ssjsinternal|"
    r"_incapsula_resource|datadome|px-cdn\.net|/_px/|"
    r"akamaitechnologies\.com.{0,200}block|"
    r"window\.location\.reload.{0,100}cookie)",
    re.I,
)
# Body signals that indicate a redirect/shim — body is small and points us to
# re-read after a settle (Radware, F5 use this pattern: tiny page sets a cookie
# then reloads to the real block page).
SHIM_BODY_PATTERNS = re.compile(
    r"(perfdrive|shieldsquare|aperture\.js|cf_chl_opt|_incapsula_)",
    re.I,
)
BLOCKED_STATUSES = {403, 406, 429, 451, 503}
RETRY_DELAYS_S = (0, 4.0, 10.0)  # 3 attempts total; delay BEFORE attempt n

WAIT_UNTIL_DEFAULT = "domcontentloaded"
NAV_TIMEOUT_DEFAULT_MS = 45_000


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _classify(status: int | None, main_statuses: list[int], title: str, body: str) -> str:
    """Verdict: ok | gated | blocked | error.

    - error  : no useful response captured at all (no status AND no title AND no body).
               Relaxed so nodriver adapter (which can't capture status) is not
               permanently `error` when it does manage to capture title/body.
    - blocked: hard block — HTTP 4xx/5xx in BLOCKED_STATUSES anywhere in
               main-frame chain, OR final status in BLOCKED_STATUSES
    - gated  : 200 OK but body/title indicates a challenge page (CF, Radware,
               Akamai, F5, DataDome, Imperva). Body scanned to 50KB to catch
               vendor signals that appear after initial markup.
    - ok     : everything else (real content rendered)
    """
    if status is None and not main_statuses and not title and not body:
        return "error"
    if status in BLOCKED_STATUSES:
        return "blocked"
    if any(s in BLOCKED_STATUSES for s in main_statuses):
        return "blocked"
    if GATE_TITLE_PATTERNS.search(title or ""):
        return "gated"
    # Scan to 50KB so vendor signals later in the page still hit (F5 Support
    # ID lives around 6-10KB into the response, perfdrive shim has signals
    # in the inline script body, etc.)
    if GATE_BODY_PATTERNS.search(body[:50_000] if body else ""):
        return "gated"
    # Body-length heuristic: very short body with no <script> often means
    # error/redirect/empty-response.
    if body and len(body) < 800 and "<script" not in body.lower():
        return "gated"
    return "ok"


def extract_score(page, target: dict) -> dict:
    out: dict = {}
    for key, selector in target.get("extract", {}).items():
        try:
            el = page.locator(selector).first
            out[key] = el.inner_text(timeout=5_000).strip()
        except Exception as e:
            out[key] = f"<extract-fail: {type(e).__name__}>"
    return out


def _attempt_once(browser, target: dict, target_dir: Path, browser_name: str) -> dict:
    """One attempt: fresh context, navigate, classify, screenshot. Never raises."""
    main_statuses: list[int] = []
    final_status: int | None = None
    final_url = ""
    title = ""
    body = ""
    score: dict = {}
    error: str | None = None
    ok = False
    t0 = time.time()
    ctx = None
    try:
        ctx = browser.new_context() if hasattr(browser, "new_context") else browser
        page = ctx.new_page() if hasattr(ctx, "new_page") else browser.new_page()

        # Track main-frame status codes via response listener.
        # Use `frame.parent_frame is None` instead of identity comparison to
        # `page.main_frame` — identity comparison is unreliable across the
        # Playwright Python proxy boundary and across adapters.
        def on_response(response):
            try:
                if response.frame.parent_frame is None:
                    main_statuses.append(response.status)
            except Exception:
                pass
        try:
            page.on("response", on_response)
        except Exception:
            pass

        page.set_default_timeout(target.get("timeout_ms", NAV_TIMEOUT_DEFAULT_MS))
        # CRITICAL: set_default_timeout does NOT reliably govern page.goto for
        # all backends. set_default_navigation_timeout is the one that matters.
        try:
            page.set_default_navigation_timeout(target.get("timeout_ms", NAV_TIMEOUT_DEFAULT_MS))
        except Exception:
            pass

        wait_until = target.get("wait_until", WAIT_UNTIL_DEFAULT)
        resp = page.goto(target["url"], wait_until=wait_until)
        final_status = resp.status if resp else None
        try:
            final_url = page.url
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        settle_s = target.get("settle_s", 2)
        time.sleep(settle_s)

        # First read of title + body
        try:
            title = page.title() or ""
        except Exception:
            pass
        try:
            body = page.content() or ""
        except Exception:
            pass

        # Shim re-read: if the initial body is a known redirect/cookie-set shim
        # (Radware/Shieldsquare/Imperva/F5), wait + re-read to capture the
        # actual gate page or final destination. Without this, we score a
        # cookie-setting shim as `ok` because it has <script> tags and isn't
        # short enough to trip the length heuristic.
        if body and len(body) < 5000 and SHIM_BODY_PATTERNS.search(body):
            time.sleep(3)
            try:
                title = page.title() or title
            except Exception:
                pass
            try:
                body = page.content() or body
            except Exception:
                pass

        # Score extraction (selectors per target) — needs live page; do this
        # BEFORE context close.
        try:
            score = extract_score(page, target)
        except Exception:
            pass

        # Screenshot and HTML dump (best-effort; do not fail the attempt over these)
        try:
            page.screenshot(path=str(target_dir / f"{browser_name}.png"), full_page=True)
        except Exception:
            pass
        try:
            (target_dir / f"{browser_name}.html").write_text(
                body, encoding="utf-8", errors="replace"
            )
        except Exception:
            pass
        ok = True
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        # Close context to kill cookies/storage for next target.
        # NOTE: for adapters whose new_context() returns the same browser
        # (nodriver stub), ctx is browser → we skip close to keep the session
        # alive. Cookie carryover is a known limitation, documented per-adapter.
        if ctx is not None and hasattr(ctx, "close") and ctx is not browser:
            try:
                ctx.close()
            except Exception:
                pass
    verdict = _classify(final_status, main_statuses, title, body) if ok else "error"
    return {
        "ok": ok,
        "verdict": verdict,
        "load_ms": int((time.time() - t0) * 1000),
        "final_url": final_url,
        "status": final_status,
        "main_statuses": main_statuses[:20],  # cap to keep records lean
        "title": title[:200],
        "body_len": len(body) if body else 0,
        "score": score,
        "error": error,
    }


def run_one(browser, browser_name: str, target: dict, out_dir: Path) -> dict:
    """Top-level per-target runner. Retries up to len(RETRY_DELAYS_S) times.

    `browser` is the live shared browser handle (factory yielded it once for
    the whole browser run); fresh contexts inside `_attempt_once` provide
    per-target isolation.
    """
    slug = slugify(target["name"])
    target_dir = out_dir / slug
    target_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "browser": browser_name,
        "target": target["name"],
        "url": target["url"],
        "ts": int(time.time()),
        "attempts": [],
        "majority_verdict": "error",
        "score": {},
    }
    for i, delay in enumerate(RETRY_DELAYS_S):
        if delay:
            time.sleep(delay)
        attempt = _attempt_once(browser, target, target_dir, browser_name)
        record["attempts"].append(attempt)
        # Early exit ONLY when 2+ attempts agree on a non-error verdict.
        # This kills the "single misclassification is sticky" failure mode
        # the reviewers flagged — a false-ok on attempt 1 now gets a second
        # opinion. A blocked target that stays blocked exits early at attempt 2.
        if len(record["attempts"]) >= 2:
            last_two = [a["verdict"] for a in record["attempts"][-2:]]
            if last_two[0] == last_two[1] and last_two[0] != "error":
                break
    # Defensive: never minimize an empty list
    if not record["attempts"]:
        record["best_verdict"] = "error"
        return record
    verdicts = [a["verdict"] for a in record["attempts"]]
    record["majority_verdict"] = Counter(verdicts).most_common(1)[0][0]
    # Score from the best attempt (ok > gated > blocked > error). Tie-break
    # toward more conservative (later attempts > earlier): iterate reversed
    # so on equal rank `min` returns the latest attempt, not the earliest.
    rank = {"ok": 0, "gated": 1, "blocked": 2, "error": 3}
    best = min(reversed(record["attempts"]), key=lambda a: rank.get(a["verdict"], 9))
    record["score"] = best.get("score", {})
    record["best_verdict"] = best["verdict"]
    return record


def run_browser_subprocess(browser: str, targets_path: str, out_root: str, headless: bool) -> list:
    cmd = [sys.executable, __file__, "--single", browser,
           "--targets", targets_path, "--out", out_root]
    if headless:
        cmd.append("--headless")
    print(f"\n=== {browser} (subprocess) ===", flush=True)
    # Hard ceiling per browser. Worst-case theoretical for 31 targets at
    # 45s nav-timeout × 3 attempts + 14s retry delays + 10s settle ≈ 5200s.
    # Add headroom for browser launch and slow targets, cap at 90 min so a
    # wedged adapter (nodriver event-loop hang, Camoufox WebGL crash mid-init)
    # can't eat the whole sweep.
    timeout_s = 90 * 60
    try:
        proc = subprocess.run(cmd, capture_output=False, timeout=timeout_s)
        rc = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        rc = -1
        timed_out = True
    records_file = Path(out_root) / f"records-{browser}.json"
    if records_file.exists():
        return json.loads(records_file.read_text())
    err = f"subprocess {'TIMEOUT' if timed_out else f'exit {rc}'}; no records file"
    return [{"browser": browser, "error": err}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("browsers", nargs="+", help="vanilla patchright cloak camofox rebrowser nodriver")
    ap.add_argument("--targets", default=str(ROOT / "targets.yaml"))
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--single", action="store_true",
                    help="Internal: this process runs ONE browser only.")
    ap.add_argument("--shuffle-targets", action="store_true",
                    help="Randomize target order to break warmup-order effects")
    ap.add_argument("--seed", type=int, default=None,
                    help="Random seed for shuffle (reproducibility)")
    args = ap.parse_args()

    targets = yaml.safe_load(Path(args.targets).read_text())["targets"]
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.shuffle_targets:
        rng = random.Random(args.seed)
        rng.shuffle(targets)

    if args.single:
        if len(args.browsers) != 1:
            print("--single requires exactly one browser", file=sys.stderr)
            return 2
        b = args.browsers[0]
        mod = importlib.import_module(f"browsers.{b}")
        records = []
        # Open ONE browser session; reuse across targets, but `_attempt_once`
        # creates a fresh context per target for cookie isolation.
        with mod.session(headless=args.headless) as browser:
            # Emit a marker for stats_sweep to detect true cold-start
            print(f"BROWSER_READY {time.time():.3f}", flush=True)
            for t in targets:
                print(f"  -> {t['name']:30s}", end=" ", flush=True)
                rec = run_one(browser, b, t, out_dir=out_root)
                best = rec["best_verdict"]
                maj = rec["majority_verdict"]
                last_ms = rec["attempts"][-1]["load_ms"]
                err = rec["attempts"][-1].get("error") or ""
                n = len(rec["attempts"])
                print(f"[{best:7s}/{maj:7s}] {last_ms:>5}ms n={n}  {err}", flush=True)
                records.append(rec)
        (out_root / f"records-{b}.json").write_text(json.dumps(records, indent=2))
        return 0

    all_records = []
    for b in args.browsers:
        all_records.extend(run_browser_subprocess(b, args.targets, args.out, args.headless))

    summary = out_root / f"run-{int(time.time())}.json"
    summary.write_text(json.dumps(all_records, indent=2))
    print(f"\nWrote {summary}")
    counts: Counter = Counter()
    for r in all_records:
        v = r.get("best_verdict") or ("error" if r.get("error") else "?")
        counts[(r.get("browser"), v)] += 1
    print("\nPer-browser best-verdict results:")
    for b in args.browsers:
        ok = counts.get((b, "ok"), 0)
        gated = counts.get((b, "gated"), 0)
        blocked = counts.get((b, "blocked"), 0)
        err = counts.get((b, "error"), 0)
        print(f"  {b:12s}  ok={ok}  gated={gated}  blocked={blocked}  error={err}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
