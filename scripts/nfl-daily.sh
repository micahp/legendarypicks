#!/usr/bin/env bash
# nfl-daily.sh — the daily NFL refresh: ADP then transactions, DEV then PROD.
#
# Replaces FOUR units — legendarypicks-nfl-adp{,-prod} and
# legendarypicks-nfl-transactions{,-prod} — that ran the same two scripts against
# two databases on four schedules five minutes apart (04:10/04:15/04:20/04:25).
# The split was per ENVIRONMENT, never per league: both scripts already cover the
# whole league in one run.
#
# Sequential on purpose. Those five-minute offsets existed to stop DEV and PROD
# hitting ESPN in the same minute, and 2026-08-24 proved an offset only MOVES a
# collision rather than removing it (CONTEXT-2026-08-24 §11: "I moved the
# collision, I did not remove it"). One job running the environments in order
# GUARANTEES they never overlap.
#
# Step accounting is news-lib.sh's, not a second copy of it: every step runs even
# when an earlier one failed, and the JOB still exits non-zero naming what failed.
# LP_STEP_LABEL is what keeps DEV and PROD distinguishable in that list.
set -uo pipefail
cd /root/legendarypicks/backend

PY=/root/legendarypicks/backend/venv/bin/python
LOG="${LP_NFL_LOG:-/var/log/legendarypicks-nfl-daily.log}"
DEV_DB=/root/legendarypicks/backend/data/picks.dev.db
PROD_DB=/root/legendarypicks/backend/data/picks.db

. /root/legendarypicks/scripts/news-lib.sh   # log(), run_step(), finish()

log "=== nfl daily start ==="

for env_name in DEV PROD; do
  case "$env_name" in
    DEV)  export LP_DB_PATH="$DEV_DB" ;;
    PROD) export LP_DB_PATH="$PROD_DB" ;;
  esac
  export LP_STEP_LABEL="$env_name"

  # A missing database is fatal for THIS environment only. Skipping to the next
  # one is deliberate: losing dev must never cost prod its daily refresh, which
  # is the whole reason the old units were separate.
  if [ ! -f "$LP_DB_PATH" ]; then
    log "  SKIP $env_name: $LP_DB_PATH does not exist"
    STEP_FAILURES=$(( STEP_FAILURES + 1 ))
    FAILED_STEPS="$FAILED_STEPS $env_name(no-db)"
    continue
  fi

  log "--- $env_name ($LP_DB_PATH)"
  before=$STEP_FAILURES
  run_step 300 ingest_nfl_adp.py
  run_step 120 nfl_transactions_sync.py
  log "--- $env_name: $(( STEP_FAILURES - before )) step(s) failed"
done

unset LP_STEP_LABEL
log "=== nfl daily done ==="
finish
