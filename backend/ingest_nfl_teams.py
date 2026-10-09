#!/usr/bin/env python3
"""ingest_nfl_teams.py -- the 32 NFL franchises, from nflverse's teams file.

Source: nflverse-data release `teams` (teams_colors_logos.csv), 36 rows: the 32 current
franchises plus legacy codes (OAK, SD, STL, LA, WAS). Legacy codes are not written as
separate teams. Every code goes through team_codes.normalize("nfl", ...), the same
boundary the schedule ingest uses, so `nfl_teams.team` matches `nfl_schedule` and the
ESPN-vocabulary `players` table exactly (LA -> LAR, WAS -> WSH, OAK -> LV, SD -> LAC,
STL -> LAR). Where a current code and a legacy alias both name one franchise, the row whose
raw abbreviation is already canonical wins.

Reconcile (fail loudly): the written set must equal the distinct home/away codes in
`nfl_schedule` for that season, and must have exactly 32 rows. Otherwise the run exits
non-zero and writes nothing.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db venv/bin/python ingest_nfl_teams.py
                 [--season 2026] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sqlite3
import sys
import urllib.request

from team_codes import normalize

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

SOURCE = "nflverse_teams_colors_logos"
URL = ("https://github.com/nflverse/nflverse-data/releases/download/teams/"
       "teams_colors_logos.csv")
EXPECTED_TEAMS = 32


def fetch(url: str = URL, timeout: int = 60) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def parse_teams(text: str) -> list[dict]:
    """Return one row per current franchise with canonical codes."""
    chosen: dict[str, dict] = {}
    for raw in csv.DictReader(io.StringIO(text)):
        abbr = (raw.get("team_abbr") or "").strip()
        if not abbr:
            continue
        canonical = normalize("nfl", abbr)  # raises UnknownTeamCode on anything unexpected
        row = {
            "team": canonical,
            "conference": (raw.get("team_conf") or "").strip() or None,
            "division": (raw.get("team_division") or "").strip() or None,
            "team_name": (raw.get("team_name") or "").strip() or None,
        }
        # Prefer the row whose own abbreviation is already the canonical code.
        if canonical not in chosen or abbr == canonical:
            chosen[canonical] = row
    return [chosen[k] for k in sorted(chosen)]


def schedule_codes(con: sqlite3.Connection, season: int) -> set[str]:
    rows = con.execute(
        "SELECT home_team FROM nfl_schedule WHERE season = ? "
        "UNION SELECT away_team FROM nfl_schedule WHERE season = ?",
        (season, season)).fetchall()
    return {r[0] for r in rows if r[0]}


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS nfl_teams ("
        " season INTEGER NOT NULL,"
        " team TEXT NOT NULL,"
        " conference TEXT,"
        " division TEXT,"
        " team_name TEXT,"
        " source TEXT,"
        " ingested_at TEXT DEFAULT (datetime('now')),"
        " PRIMARY KEY (season, team))")
    con.commit()


def reconcile(rows: list[dict], schedule: set[str], season: int) -> None:
    got = {r["team"] for r in rows}
    if len(rows) != EXPECTED_TEAMS:
        raise SystemExit("nfl_teams: expected %d franchises, parsed %d" % (EXPECTED_TEAMS, len(rows)))
    if not schedule:
        raise SystemExit("nfl_teams: nfl_schedule has no games for season %d" % season)
    if got != schedule:
        raise SystemExit("nfl_teams: codes do not match nfl_schedule for %d: only in teams %s, "
                         "only in schedule %s" % (season, sorted(got - schedule),
                                                  sorted(schedule - got)))


def write(con: sqlite3.Connection, season: int, rows: list[dict]) -> None:
    con.execute("DELETE FROM nfl_teams WHERE season = ?", (season,))
    con.executemany(
        "INSERT INTO nfl_teams (season, team, conference, division, team_name, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(season, r["team"], r["conference"], r["division"], r["team_name"], SOURCE)
         for r in rows])
    con.commit()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=None,
                        help="defaults to the newest season in nfl_schedule")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rows = parse_teams(fetch())
    con = sqlite3.connect(DB)
    try:
        season = args.season
        if season is None:
            found = con.execute("SELECT MAX(season) FROM nfl_schedule").fetchone()[0]
            if found is None:
                raise SystemExit("nfl_teams: nfl_schedule is empty; run ingest_nfl_schedule.py first")
            season = int(found)
        reconcile(rows, schedule_codes(con, season), season)
        if args.dry_run:
            print("dry-run season=%d teams=%d db=%s" % (season, len(rows), DB))
            return 0
        ensure_schema(con)
        write(con, season, rows)
        print("wrote season=%d teams=%d db=%s" % (season, len(rows), DB))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
