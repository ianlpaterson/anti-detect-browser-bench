#!/usr/bin/env python3
"""Anti-detect browser bench: loop browsers x targets, screenshot + scrape scores.

Each browser runs in its own subprocess because sync_playwright() is a
single-shot module-level singleton — it refuses to restart cleanly in the
same Python process, especially when different Playwright forks (patchright,
camoufox) are involved.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def extract_score(page, target: dict) -> dict:
    out: dict = {}
    for key, selector in target.get("extract", {}).items():
        try:
            el = page.locator(selector).first
            out[key] = el.inner_text(timeout=5_000).strip()
        except Exception as e:
            out[key] = f"<extract-fail: {type(e).__name__}>"
    return out


def run_one(browser_name: str, target: dict, headless: bool, out_dir: Path) -> dict:
    slug = slugify(target["name"])
    target_dir = out_dir / slug
    target_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "browser": browser_name,
        "target": target["name"],
        "url": target["url"],
        "ts": int(time.time()),
        "ok": False,
        "load_ms": None,
        "title": None,
        "status": None,
        "score": {},
        "error": None,
    }

    mod = importlib.import_module(f"browsers.{browser_name}")
    t0 = time.time()
    try:
        with mod.session(headless=headless) as browser:
            ctx = browser.new_context() if hasattr(browser, "new_context") else browser
            page = ctx.new_page() if hasattr(ctx, "new_page") else browser.new_page()
            page.set_default_timeout(target.get("timeout_ms", 60_000))
            resp = page.goto(target["url"], wait_until=target.get("wait_until", "load"))
            record["status"] = resp.status if resp else None
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            time.sleep(target.get("settle_s", 2))
            record["title"] = page.title()
            record["score"] = extract_score(page, target)
            page.screenshot(path=str(target_dir / f"{browser_name}.png"), full_page=True)
            (target_dir / f"{browser_name}.html").write_text(page.content())
            record["ok"] = True
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
    record["load_ms"] = int((time.time() - t0) * 1000)
    return record


def run_browser_subprocess(browser: str, targets_path: str, out_root: str, headless: bool) -> list:
    """Spawn `python bench.py --single BROWSER ...` and collect its JSON."""
    cmd = [
        sys.executable, __file__,
        "--single", browser,
        "--targets", targets_path,
        "--out", out_root,
    ]
    if headless:
        cmd.append("--headless")
    print(f"\n=== {browser} (subprocess) ===", flush=True)
    proc = subprocess.run(cmd, capture_output=False)
    records_file = Path(out_root) / f"records-{browser}.json"
    if records_file.exists():
        return json.loads(records_file.read_text())
    return [{"browser": browser, "error": f"subprocess exit {proc.returncode}; no records file"}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("browsers", nargs="+", help="vanilla patchright cloak camofox")
    ap.add_argument("--targets", default=str(ROOT / "targets.yaml"))
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--single", action="store_true",
                    help="Internal: this process runs ONE browser only.")
    args = ap.parse_args()

    targets = yaml.safe_load(Path(args.targets).read_text())["targets"]
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    if args.single:
        # We are the worker subprocess for one browser
        if len(args.browsers) != 1:
            print("--single requires exactly one browser", file=sys.stderr)
            return 2
        b = args.browsers[0]
        records = []
        for t in targets:
            print(f"  -> {t['name']:30s}", end=" ", flush=True)
            rec = run_one(b, t, headless=args.headless, out_dir=out_root)
            tag = "OK " if rec["ok"] else "ERR"
            score_str = ", ".join(f"{k}={v[:40]}" for k, v in rec["score"].items()) if rec["score"] else ""
            err_str = rec["error"] or ""
            print(f"[{tag}] {rec['load_ms']:>5}ms {score_str}{err_str}", flush=True)
            records.append(rec)
        (out_root / f"records-{b}.json").write_text(json.dumps(records, indent=2))
        return 0

    # Top-level orchestrator: subprocess per browser
    all_records = []
    for b in args.browsers:
        all_records.extend(run_browser_subprocess(b, args.targets, args.out, args.headless))

    summary = out_root / f"run-{int(time.time())}.json"
    summary.write_text(json.dumps(all_records, indent=2))
    print(f"\nWrote {summary}")
    # Per-browser ok counts
    from collections import Counter
    counts = Counter()
    for r in all_records:
        counts[(r.get("browser"), "ok" if r.get("ok") else "err")] += 1
    print("\nPer-browser results:")
    for b in args.browsers:
        ok = counts.get((b, "ok"), 0)
        err = counts.get((b, "err"), 0)
        print(f"  {b:12s}  ok={ok}  err={err}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
