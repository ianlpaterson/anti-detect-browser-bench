#!/usr/bin/env bash
# Phase 6 N=3 sweep orchestrator. Run via nohup; safe to disconnect.
# Each iteration:
#   1) clean stats/ + results/
#   2) python stats_sweep.py --seed $i  (i=1,2,3)
#   3) mv stats -> stats_run_$i, results -> results_run_$i
# Logs to phase6.log. Resumable: if stats_run_$i exists, skips that run.

set -uo pipefail  # no -e: a single bad run shouldn't kill the loop
cd "$(dirname "$0")"
source .venv/bin/activate
export PYTHONUNBUFFERED=1

ts() { date +"%Y-%m-%dT%H:%M:%S%z"; }
LOG=phase6.log
echo "[$(ts)] Phase 6 START -- N=3 over 7 browsers x 31 targets" | tee -a "$LOG"

for i in 1 2 3; do
  RUN_DIR="stats_run_$i"
  RES_DIR="results_run_$i"
  if [ -d "$RUN_DIR" ]; then
    echo "[$(ts)] run $i already has $RUN_DIR, skipping" | tee -a "$LOG"
    continue
  fi
  echo "[$(ts)] run $i: seed=$i, starting stats_sweep" | tee -a "$LOG"
  rm -rf stats results
  mkdir -p stats results
  python stats_sweep.py --seed "$i" >> "$LOG" 2>&1
  rc=$?
  echo "[$(ts)] run $i: stats_sweep exit=$rc" | tee -a "$LOG"
  mv stats "$RUN_DIR"
  mv results "$RES_DIR"
  echo "[$(ts)] run $i: archived to $RUN_DIR + $RES_DIR" | tee -a "$LOG"
done

echo "[$(ts)] Phase 6 DONE" | tee -a "$LOG"
