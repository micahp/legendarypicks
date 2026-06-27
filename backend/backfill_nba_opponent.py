#!/usr/bin/env python3
"""
backfill_nba_opponent.py — populate opponent + home_away for existing NBA player_game_logs.

Groups 24K+ NBA log rows by game_date, calls espn_client.games('nba', date) once
per date to get home/away team abbrevs, then derives opponent/home_away per player row
from the player's team column.

Safe: only UPDATEs rows where opponent IS NULL (idempotent re-run = no-op).
"""
import sys, os, sqlite3, time, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# All log rows where opponent IS NULL, grouped by date
dates = con.execute("""
    SELECT DISTINCT game_date
    FROM player_game_logs
    WHERE league='nba' AND opponent IS NULL
    ORDER BY game_date
""").fetchall()

print(f"Dates to backfill: {len(dates)}")
updated = 0
misses = 0
for i, row in enumerate(dates):
    date_str = row["game_date"]
    try:
        games = espn.games("nba", date_str)
    except Exception as e:
        print(f"  {date_str}: ESPN error {e}")
        continue

    # Build game_id → (home_abbrev, away_abbrev) map
    ha = {}
    for g in games:
        gid = str(g.get("game_id") or "")
        home = (g.get("home") or {}).get("abbrev", "")
        away = (g.get("away") or {}).get("abbrev", "")
        if gid and home and away:
            ha[gid] = (home, away)

    if not ha:
        print(f"  {date_str}: no games returned from ESPN")
        continue

    # Find all NULL-opponent NBA log rows for games on this date
    null_rows = con.execute("""
        SELECT id, game_id, team
        FROM player_game_logs
        WHERE league='nba' AND game_date=? AND opponent IS NULL
    """, (date_str,)).fetchall()

    date_updated = 0
    for lr in null_rows:
        gid = lr["game_id"]
        team = (lr["team"] or "").upper()
        info = ha.get(gid)
        if not info or not team:
            misses += 1
            continue
        home_abbrev, away_abbrev = info[0].upper(), info[1].upper()
        if team == home_abbrev:
            opp, ha_str = away_abbrev, "away"
        elif team == away_abbrev:
            opp, ha_str = home_abbrev, "home"
        else:
            # Team not matching home or away — possibly a renamed team or edge case
            misses += 1
            continue
        con.execute("UPDATE player_game_logs SET opponent=?, home_away=? WHERE id=?",
                    (opp, ha_str, lr["id"]))
        date_updated += 1

    if date_updated:
        updated += date_updated
        print(f"  {date_str}: {len(ha)} games, {date_updated} rows updated")

    time.sleep(0.1)  # gentle on ESPN

con.commit()
print(f"\nDone. {updated} rows updated, {misses} misses (team mismatch or no ESPN data)")

# Verify
remaining = con.execute("SELECT COUNT(*) c FROM player_game_logs WHERE league='nba' AND opponent IS NULL").fetchone()["c"]
total = con.execute("SELECT COUNT(*) c FROM player_game_logs WHERE league='nba'").fetchone()["c"]
print(f"NBA logs: {total} total, {remaining} still NULL opponent ({100*remaining//max(1,total)}%)")
con.close()
