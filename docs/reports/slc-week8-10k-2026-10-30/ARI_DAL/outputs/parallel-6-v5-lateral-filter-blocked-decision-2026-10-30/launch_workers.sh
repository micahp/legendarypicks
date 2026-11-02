#!/usr/bin/env bash
set -u
set -o pipefail

RUNDIR="/root/slc-week8-missing-10k-2026-10-29/artifacts/ARI_DAL/parallel-6-v5-lateral-filter-blocked-decision-2026-10-30"
PY="/root/slc-week1-7/.venv/bin/python"
SIM="/root/lp-slc-week8-feasibility-run/scripts/nfl_sequence/simulate_pregame_batch.py"
SNAP="/root/lp-slc-week8-feasibility-run/docs/research/slc-week8-2026/snapshots/2026_08_ARI_DAL.json"
PLAYCALL="/root/lp-slc-week8-feasibility-run/docs/research/SLC-PLAYCALL-ARTIFACT-v1.json"
STREAKS="/root/lp-slc-week8-feasibility-run/docs/research/slc-week8-2026/wl-streaks-2026-10-29.json"
DB="/root/slc-week8-missing-10k-2026-10-29/data/simulation-input.sqlite"

pids=()
run_worker() {
  local id="$1"
  local start="$2"
  local count="$3"
  "$PY" "$SIM" \
    --snapshot-file "$SNAP" \
    --slc-profile v1_full_stack \
    --playcall-artifact "$PLAYCALL" \
    --playcall-streak-file "$STREAKS" \
    --slc-blocker-fix run_scramble_backoff \
    --slc-blocker-fix long_field_goal_feasibility \
    --slc-blocker-fix blocked_kick_source_audit \
    --slc-blocker-fix blocked_kick_geometry \
    --slc-blocker-fix safety_free_kick_boundaries \
    --games "$count" \
    --seed-start "$start" \
    --db "$DB" \
    --export-boxscores \
    --progress-every 250 \
    --max-simulation-errors 0 \
    --out "$RUNDIR/worker-$id.json" \
    > "$RUNDIR/worker-$id.log" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$RUNDIR/worker-$id.pid"
  pids+=("$pid")
}

run_worker 01 1 1667
run_worker 02 1668 1667
run_worker 03 3335 1667
run_worker 04 5002 1667
run_worker 05 6669 1666
run_worker 06 8335 1666

status=0
for pid in "${pids[@]}"; do
  wait "$pid" || status=$?
done
exit "$status"
