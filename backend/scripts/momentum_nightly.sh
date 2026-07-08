#!/usr/bin/env bash
# Nightly momentum refresh: team results (ESPN), player logs (Statcast), then
# recompute momentum_state/momentum_crosses. Scheduled after the last MLB game
# ends (~06:00 UTC); Statcast posts same night.
set -u
cd /root/legendarypicks/backend
export LP_DB_PATH="/root/legendarypicks/backend/data/picks.dev.db"
LOG="/root/legendarypicks/logs/momentum-nightly.log"
{
  echo "=== $(date -u +%FT%TZ) ==="
  python3 ingest_team_results.py --league mlb
  venv/bin/python3 ingest_mlb_logs.py --days 3
  venv/bin/python3 ingest_mlb_pitcher_logs.py --days 3
  python3 compute_momentum.py --league mlb
} >> "$LOG" 2>&1
