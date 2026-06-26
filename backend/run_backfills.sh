#!/bin/bash
# Sequential full backfills — one at a time to avoid concurrent SQLite write locks.
set -u
cd /root/legendarypicks/backend
export LP_DB_PATH=data/picks.dev.db
PY=venv/bin/python

echo "=== BACKFILL START $(date) ==="

# Enable WAL so the running dev server (:8095) keeps reading during writes.
$PY -c "import sqlite3; c=sqlite3.connect('$LP_DB_PATH'); print('journal:', c.execute('PRAGMA journal_mode=WAL').fetchone()); c.execute('PRAGMA busy_timeout=15000'); c.close()"

echo; echo "=== [1/3] MLB Statcast 200d ($(date +%H:%M:%S)) ==="
$PY ingest_mlb_logs.py --days 200 2>&1 | grep -vE "DEBUG|^\s*[0-9]+%|it/s|Cryptography|cryptography"

echo; echo "=== [2/3] NHL all players 2025-26 ($(date +%H:%M:%S)) ==="
$PY ingest_nhl_logs.py --season 20252026 2>&1 | grep -vE "DEBUG"

echo; echo "=== [3/3] NBA full 2025-26 season ($(date +%H:%M:%S)) ==="
$PY ingest_nba_logs.py --start 2025-10-21 --end 2026-06-22 2>&1 | grep -vE "DEBUG"

echo; echo "=== BACKFILL DONE $(date) ==="
$PY - <<'PYEOF' 2>&1 | grep -vE "DEBUG"
import sqlite3
c=sqlite3.connect('data/picks.dev.db')
print('FINAL player_game_logs coverage:')
for r in c.execute("SELECT league,COUNT(*),COUNT(DISTINCT player_id),COUNT(DISTINCT game_id) FROM player_game_logs GROUP BY league ORDER BY 2 DESC"):
    print(f'  {r[0]:4} logs={r[1]:7} players={r[2]:5} games={r[3]:5}')
print('  TOTAL:', c.execute('SELECT COUNT(*) FROM player_game_logs').fetchone()[0])
PYEOF
