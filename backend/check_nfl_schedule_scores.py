#!/usr/bin/env python3
"""check_nfl_schedule_scores.py -- is every finished NFL game actually scored?

monitor_ingest_freshness.py answers "did the schedule ingest run recently?" (ingested_at
within 48h). It cannot see a schedule that refreshes on time with final scores missing,
which is what happened to 2026 week 4 and 5 in early October. This checks the scores.

A game is overdue when its kickoff (gameday + gametime, read as US Eastern, the nflverse
convention) was more than GRACE_HOURS ago and either score is NULL. A game with no
gametime is read as 23:59 Eastern on its gameday, so it is never flagged early.

Exit 1 with one ALERT line per overdue game, so the systemd unit records a failure. Exit 0
prints the count it checked, including the zero.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python check_nfl_schedule_scores.py
                [--grace-hours 36]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

import pytz

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
GRACE_HOURS = 36
EASTERN = pytz.timezone("America/New_York")


def kickoff_utc(gameday, gametime):
    """gameday 'YYYY-MM-DD', gametime 'HH:MM' Eastern (or None) -> aware UTC datetime."""
    day = dt.datetime.strptime(gameday, "%Y-%m-%d").date()
    hhmm = gametime or "23:59"
    hour, minute = (int(x) for x in hhmm.split(":")[:2])
    local = EASTERN.localize(dt.datetime(day.year, day.month, day.day, hour, minute))
    return local.astimezone(pytz.utc)


def overdue_unscored(con, now, grace_hours=GRACE_HOURS):
    """Return (checked_count, overdue_rows). Each overdue row: (game_id, season, week,
    gameday, gametime, away_team, home_team, hours_since_kickoff)."""
    rows = con.execute(
        "SELECT game_id, season, week, gameday, gametime, away_team, home_team, "
        "       away_score, home_score "
        "FROM nfl_schedule WHERE gameday IS NOT NULL").fetchall()
    overdue = []
    for gid, season, week, gameday, gametime, away, home, away_s, home_s in rows:
        kick = kickoff_utc(gameday, gametime)
        hours = (now - kick).total_seconds() / 3600.0
        if hours > grace_hours and (away_s is None or home_s is None):
            overdue.append((gid, season, week, gameday, gametime, away, home, round(hours, 1)))
    return len(rows), overdue


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grace-hours", type=float, default=GRACE_HOURS)
    args = parser.parse_args(argv)
    if not os.path.isfile(DB):
        print("ALERT database missing: %s" % DB)
        return 1
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    try:
        checked, overdue = overdue_unscored(con, dt.datetime.now(pytz.utc), args.grace_hours)
    except sqlite3.Error as exc:
        print("ALERT cannot read nfl_schedule: %s" % exc)
        return 1
    finally:
        con.close()
    for gid, season, week, gameday, gametime, away, home, hours in overdue:
        print("ALERT nfl_schedule unscored: %s (%d wk%d %s %s) %s at %s, kickoff %.1fh ago"
              % (gid, season, week, gameday, gametime or "no-time", away, home, hours))
    if overdue:
        return 1
    print("OK nfl_schedule: %d games checked, 0 overdue unscored (grace %gh)"
          % (checked, args.grace_hours))
    return 0


if __name__ == "__main__":
    sys.exit(main())
