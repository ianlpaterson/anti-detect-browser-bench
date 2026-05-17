# Phase 6 N=3 sweep dataset

Generated 2026-05-16/17 on Mac Studio (macOS 26.3 arm64, residential BC IP, headed mode).
Bench commit at sweep start: `86713d3` (run_phase6.sh orchestrator).
Backfill commit: `c840351` (rebrowser run-1 backfill script).
Total cells: 651 = 7 browsers × 31 targets × 3 runs.
Sweep total wall time: 5h11m (22:39:39 -> 03:51:17 PT).

Schemas:
- `results_run_$i/records-$browser.json` — list of 31 per-target records (per-attempt verdict, status, title, body_len, score, error)
- `stats_run_$i/$browser.json` — per-browser perf snapshot (cold_start_s, peak_rss_mb, elapsed_s, rss_samples, target_marks, engine_version, n_detached)
- `stats_run_$i/summary.md` — rendered table
- `phase6.log` — full bench stdout for forensics (~108KB)

Engine versions by run (probed at session entry, recorded in each record's engine_version field):

Run 1:
- `vanilla       ` Chromium 147.0.7727.15
- `patchright    ` Chrome 148.0.7778.168 (patchright + channel=chrome)
- `cloak         ` Chromium 145.0.7632.109 (cloak)
- `camofox       ` Firefox 135.0.1-beta.24 (camoufox)
- `rebrowser     ` Chromium 136.0.7103.25 (rebrowser bundle)
- `nodriver      ` Google Chrome 148.0.7778.168 (nodriver, system browser)
- `curl_baseline ` curl_cffi 0.15.0 (impersonate=chrome)

Run 2:
- `vanilla       ` Chromium 147.0.7727.15
- `patchright    ` Chrome 148.0.7778.168 (patchright + channel=chrome)
- `cloak         ` Chromium 145.0.7632.109 (cloak)
- `camofox       ` Firefox 135.0.1-beta.24 (camoufox)
- `rebrowser     ` Chromium 136.0.7103.25 (rebrowser bundle)
- `nodriver      ` Google Chrome 148.0.7778.168 (nodriver, system browser)
- `curl_baseline ` curl_cffi 0.15.0 (impersonate=chrome)

Run 3:
- `vanilla       ` Chromium 147.0.7727.15
- `patchright    ` Chrome 148.0.7778.168 (patchright + channel=chrome)
- `cloak         ` Chromium 145.0.7632.109 (cloak)
- `camofox       ` Firefox 135.0.1-beta.24 (camoufox)
- `rebrowser     ` Chromium 136.0.7103.25 (rebrowser bundle)
- `nodriver      ` Google Chrome 148.0.7778.168 (nodriver, system browser)
- `curl_baseline ` curl_cffi 0.15.0 (impersonate=chrome)

## Verdict matrix (best_verdict per cell, ok/gated/blocked/error)

### Run 1
| Browser | ok | gated | blocked | error |
|---|---:|---:|---:|---:|
| vanilla | 24 | 2 | 5 | 0 |
| patchright | 25 | 3 | 3 | 0 |
| cloak | 26 | 3 | 2 | 0 |
| camofox | 25 | 3 | 3 | 0 |
| rebrowser | 24 | 2 | 5 | 0 |
| nodriver | 28 | 3 | 0 | 0 |
| curl_baseline | 26 | 3 | 2 | 0 |

### Run 2
| Browser | ok | gated | blocked | error |
|---|---:|---:|---:|---:|
| vanilla | 24 | 2 | 5 | 0 |
| patchright | 25 | 3 | 3 | 0 |
| cloak | 26 | 3 | 2 | 0 |
| camofox | 25 | 3 | 3 | 0 |
| rebrowser | 24 | 2 | 5 | 0 |
| nodriver | 28 | 3 | 0 | 0 |
| curl_baseline | 26 | 3 | 2 | 0 |

### Run 3
| Browser | ok | gated | blocked | error |
|---|---:|---:|---:|---:|
| vanilla | 24 | 2 | 5 | 0 |
| patchright | 25 | 3 | 3 | 0 |
| cloak | 26 | 3 | 2 | 0 |
| camofox | 25 | 3 | 3 | 0 |
| rebrowser | 24 | 2 | 5 | 0 |
| nodriver | 28 | 3 | 0 | 0 |
| curl_baseline | 26 | 3 | 2 | 0 |

## Cross-run consistency
Cells where all 3 runs agree on best_verdict (per browser × target).

- `vanilla       ` 31/31 targets unanimous across N=3
- `patchright    ` 31/31 targets unanimous across N=3
- `cloak         ` 31/31 targets unanimous across N=3
- `camofox       ` 31/31 targets unanimous across N=3
- `rebrowser     ` 31/31 targets unanimous across N=3
- `nodriver      ` 31/31 targets unanimous across N=3
- `curl_baseline ` 31/31 targets unanimous across N=3
