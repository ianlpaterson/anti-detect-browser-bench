#!/usr/bin/env bash
# Backfill stats_run_1/rebrowser.json + results_run_1/ rebrowser data.
# Run 1's rebrowser slot was empty because rebrowser_playwright's bundled
# Chromium (build v1169 = Chrome 136) wasn't installed when the sweep
# started; the BrowserType.launch raised before any target was hit.
# Binary was installed mid-run-2; runs 2 and 3 succeed; this script
# fills the run-1 gap with a standalone rebrowser pass.

set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONUNBUFFERED=1

ts() { date +"%Y-%m-%dT%H:%M:%S%z"; }

# Sanity: refuse to clobber a non-empty rebrowser slot from a real run.
if [ -f stats_run_1/rebrowser.json ]; then
  cells=$(python3 -c "import json; d=json.load(open('stats_run_1/rebrowser.json')); print(d.get('n_targets_hit', 0))")
  if [ "$cells" -gt 0 ]; then
    echo "[$(ts)] stats_run_1/rebrowser.json already has $cells cells; refusing to overwrite. Delete it first if you really mean to."
    exit 1
  fi
fi

# Build a temp scratch dir so we don't collide with an in-flight run.
SCRATCH=$(mktemp -d -t rebrowser-backfill)
echo "[$(ts)] backfill scratch: $SCRATCH"

# Invoke measure_browser directly so the resulting stats/<browser>.json
# matches the schema run 2 + run 3 produced.
python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from stats_sweep import measure_browser, ROOT

scratch = Path("$SCRATCH")
results_dir = scratch / "results"
results_dir.mkdir(parents=True, exist_ok=True)
stats = measure_browser("rebrowser", str(ROOT / "targets.yaml"), str(results_dir))
out = scratch / "rebrowser.json"
out.write_text(json.dumps(stats, indent=2, default=str))
print(f"wrote {out} ({stats.get('n_targets_hit', 0)} cells)")
PY

echo "[$(ts)] merging into stats_run_1 / results_run_1"
mkdir -p stats_run_1 results_run_1
cp "$SCRATCH/rebrowser.json" stats_run_1/rebrowser.json
# Per-target dirs (one per target name) and records-rebrowser.json
cp "$SCRATCH/results/records-rebrowser.json" results_run_1/records-rebrowser.json
# Per-target screenshots / html dumps land in results/<target>/<browser>.png etc.
for d in "$SCRATCH/results"/*/; do
  name=$(basename "$d")
  [ "$name" = "records-rebrowser.json" ] && continue
  mkdir -p "results_run_1/$name"
  cp -n "$d"/rebrowser.* "results_run_1/$name/" 2>/dev/null || true
done

echo "[$(ts)] DONE -- backfilled rebrowser into stats_run_1 + results_run_1"
rm -rf "$SCRATCH"
