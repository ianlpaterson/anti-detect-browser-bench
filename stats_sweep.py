#!/usr/bin/env python3
"""Per-browser perf instrumentation.

For each browser:
  - Disk: pip package size + browser binary cache size
  - Cold-start: time from subprocess launch to first 'OK' line in bench output
  - Peak RSS: max memory of the bench subprocess + all children (the browser stack)
  - Total elapsed: subprocess runtime end-to-end
  - Per-target load_ms: read from bench's records-<browser>.json after

Writes stats/<browser>.json per browser plus stats/summary.md.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).parent
STATS = ROOT / "stats"
RESULTS = ROOT / "results"
BROWSERS = ["vanilla", "patchright", "cloak", "camofox", "rebrowser", "nodriver"]

# Per-browser disk footprint sources (du -sh roots that contribute to "what does this cost")
# These are macOS paths; adjust if running elsewhere.
DISK_PATHS = {
    "vanilla":    [".venv/lib/python3.11/site-packages/playwright",
                   os.path.expanduser("~/Library/Caches/ms-playwright/chromium-1217")],
    "patchright": [".venv/lib/python3.11/site-packages/patchright"],
    "cloak":      [".venv/lib/python3.11/site-packages/cloakbrowser",
                   os.path.expanduser("~/.cloakbrowser")],
    "camofox":    [".venv/lib/python3.11/site-packages/camoufox",
                   os.path.expanduser("~/Library/Caches/camoufox")],
    "rebrowser":  [".venv/lib/python3.11/site-packages/rebrowser_playwright",
                   os.path.expanduser("~/Library/Caches/ms-playwright/chromium-1208")],
    "nodriver":   [".venv/lib/python3.11/site-packages/nodriver"],
}


def du_bytes(path: str) -> int:
    """Total bytes under a path, or 0 if missing."""
    p = Path(path)
    if not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    total = 0
    for dp, _, files in os.walk(p):
        for f in files:
            try:
                total += (Path(dp) / f).stat().st_size
            except OSError:
                pass
    return total


def disk_for(browser: str) -> dict:
    out: dict = {}
    for path in DISK_PATHS.get(browser, []):
        out[path] = du_bytes(path)
    out["_total_bytes"] = sum(v for k, v in out.items() if isinstance(v, int))
    out["_total_mb"] = round(out["_total_bytes"] / (1024 * 1024), 1)
    return out


def measure_browser(browser: str, targets_path: str, out_dir: str) -> dict:
    """Run bench.py --single BROWSER and sample RSS while it runs."""
    print(f"\n=== {browser} ===", flush=True)

    disk = disk_for(browser)
    print(f"  disk: {disk['_total_mb']} MB", flush=True)

    cmd = [sys.executable, "bench.py", "--single", browser,
           "--targets", targets_path, "--out", out_dir]
    t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    parent = psutil.Process(proc.pid)
    samples = []
    peak_rss = 0
    cold_start_s = None
    target_marks = []  # (relative_s, target_name) for each [OK]/[ERR] line

    output_lines = []
    # bench.py prints: `  -> <name:30s> [<best:7s>/<maj:7s>] <ms>ms n=<n>  <err>`
    # where best/maj ∈ {ok, gated, blocked, error}. Verdicts are lowercase and
    # padded to 7 chars; the regex tolerates the padding via \s*.
    line_re = re.compile(
        r"->\s+(\S+)\s+\[\s*(ok|gated|blocked|error)\s*/\s*(ok|gated|blocked|error)\s*\]"
    )

    def reader():
        nonlocal cold_start_s
        for line in proc.stdout:
            stamp = time.monotonic() - t0
            output_lines.append((stamp, line.rstrip()))
            m = line_re.search(line)
            if m:
                # Score the per-target row on `best` verdict (record["best_verdict"]).
                # Treat ok+gated as "got somewhere"; blocked+error count as ERR.
                verdict = m.group(2)
                tag = "OK" if verdict in ("ok", "gated") else "ERR"
                target_marks.append((stamp, m.group(1), tag))
                if cold_start_s is None and verdict == "ok":
                    cold_start_s = stamp
            print(f"  {line.rstrip()}", flush=True)

    reader_t = threading.Thread(target=reader, daemon=True)
    reader_t.start()

    while proc.poll() is None:
        try:
            rss = parent.memory_info().rss
            for c in parent.children(recursive=True):
                try:
                    rss += c.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak_rss = max(peak_rss, rss)
            samples.append((round(time.monotonic() - t0, 2), rss))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        time.sleep(0.5)

    proc.wait()
    reader_t.join(timeout=5)
    elapsed = round(time.monotonic() - t0, 2)

    return {
        "browser": browser,
        "elapsed_s": elapsed,
        "cold_start_s": cold_start_s,
        "peak_rss_mb": round(peak_rss / (1024 * 1024), 1),
        "n_targets_hit": len(target_marks),
        "n_ok": sum(1 for _, _, s in target_marks if s == "OK"),
        "n_err": sum(1 for _, _, s in target_marks if s == "ERR"),
        "target_marks": target_marks,
        "rss_samples": samples,
        "disk": disk,
        "exit_code": proc.returncode,
    }


def render_summary(stats_list: list[dict]) -> str:
    lines = [
        "# Stats sweep summary",
        "",
        f"Run: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| Browser | Disk (MB) | Cold start (s) | Peak RSS (MB) | Total time (s) | OK / N |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for s in stats_list:
        ok_n = f"{s['n_ok']} / {s['n_targets_hit']}"
        cold = f"{s['cold_start_s']:.1f}" if s['cold_start_s'] is not None else "—"
        lines.append(
            f"| {s['browser']:11s} | {s['disk']['_total_mb']:>7} | "
            f"{cold:>5} | {s['peak_rss_mb']:>6} | {s['elapsed_s']:>5.0f} | {ok_n} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    STATS.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    targets_path = str(ROOT / "targets.yaml")

    stats_list = []
    for b in BROWSERS:
        stats = measure_browser(b, targets_path, str(RESULTS))
        (STATS / f"{b}.json").write_text(json.dumps(stats, indent=2, default=str))
        stats_list.append(stats)

    summary = render_summary(stats_list)
    (STATS / "summary.md").write_text(summary)
    print(f"\n=== summary ===\n{summary}")


if __name__ == "__main__":
    sys.exit(main() or 0)
