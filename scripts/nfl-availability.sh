#!/usr/bin/env bash
# Weekly NFL availability inputs, DEV then PROD, in dependency order.
set -uo pipefail
cd /root/legendarypicks/backend

PY=/root/legendarypicks/backend/venv/bin/python
LOG="${LP_NFL_AVAILABILITY_LOG:-/var/log/legendarypicks-nfl-availability.log}"
DEV_DB=/root/legendarypicks/backend/data/picks.dev.db
PROD_DB=/root/legendarypicks/backend/data/picks.db

. /root/legendarypicks/scripts/news-lib.sh

log "=== nfl availability refresh start ==="

for env_name in DEV PROD; do
  case "$env_name" in
    DEV)  export LP_DB_PATH="$DEV_DB" ;;
    PROD) export LP_DB_PATH="$PROD_DB" ;;
  esac
  export LP_STEP_LABEL="$env_name"

  if [ ! -f "$LP_DB_PATH" ]; then
    log "  SKIP $env_name: $LP_DB_PATH does not exist"
    STEP_FAILURES=$(( STEP_FAILURES + 1 ))
    FAILED_STEPS="$FAILED_STEPS $env_name(no-db)"
    continue
  fi

  log "--- $env_name ($LP_DB_PATH)"
  before=$STEP_FAILURES
  run_step 300 ingest_nfl_schedule.py --refresh
  if [ "$STEP_FAILURES" -gt "$before" ]; then
    log "  SKIP $env_name dependent steps: schedule refresh failed"
    continue
  fi
  season=$("$PY" - "$LP_DB_PATH" <<'PY'
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
row = connection.execute("SELECT MAX(season) FROM nfl_schedule").fetchone()
connection.close()
if not row or row[0] is None:
    raise SystemExit("nfl_schedule has no published season")
print(int(row[0]))
PY
  )
  if [ -z "$season" ]; then
    log "  FAIL $env_name: could not select published NFL season"
    STEP_FAILURES=$(( STEP_FAILURES + 1 ))
    FAILED_STEPS="$FAILED_STEPS $env_name(season)"
    continue
  fi
  run_step 300 ingest_nfl_weekly_stats.py --year "$season" --all-positions
  run_step 300 ingest_nfl_snap_counts.py --year "$season"
  run_step 300 ingest_nfl_injuries.py --year "$season"
  # Play-by-play (published EPA, wpa, cpoe). nflverse rewrites the season file as
  # weeks land, so this is INSERT OR REPLACE keyed on (game_id, play_id) and stays idempotent.
  # 2025 was ingested once by hand and then stopped: without this step the EPA table froze.
  run_step 600 ingest_nfl_pbp_logs.py --year "$season"
  log "--- $env_name: $(( STEP_FAILURES - before )) step(s) failed"
done

unset LP_STEP_LABEL
log "=== nfl availability refresh done ==="
finish
