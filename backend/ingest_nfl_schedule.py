#!/usr/bin/env python3
"""ingest_nfl_schedule.py -- the NFL schedule, COPIED from nflverse's maintained
games file rather than reconstructed from a live scoreboard API.

Why this exists
---------------
Nothing in the database held an NFL schedule. `team_game_results` had 544 rows
(2025 regular season, written by `backfill_team_parity.py`) and every one of them
was a *completed* game -- that script only accepts events whose ESPN status is
`post`, so by construction it can never produce a future fixture. The schedule
tab is served live from ESPN per request (`espn.nfl_schedule_weeks`) and stores
nothing. Result: with the 2026 season 44 days out, the database could not answer
"who does this player face in week 1."

nflverse publishes the whole thing, 1999 through 2026, free:

    https://github.com/nflverse/nfldata/raw/master/data/games.csv

2026 is complete at 272 REG games, opener 2026-09-09 (NE at SEA, 20:20).
Postseason rows do not exist yet and will not until the brackets are set.

Scope: what this does NOT write
-------------------------------
The handoff that motivated this named three tables -- `prop_games`,
`team_game_results`, `game_context`. Only the middle one is a schedule table.

  * `prop_games` is the props board's game table; `props.game_id` is a foreign
    key into it and `settle_props.py` settles from it. Rows appear when props
    appear. Seeding 272 propless NFL games into it months before an NFL prop
    exists would put junk in front of the settlement path. NFL has never had a
    row there -- for any season.
  * `game_context` is a live post-game snapshot (`_core._snapshot_game_context`,
    fed from an ESPN summary). It stores attendance and officials, which are
    unknowable for a future game. It holds 16 rows total, all mlb/nba/nhl.

Writing the schedule into either would have been cargo-culting the shape of the
request instead of the intent.

Team abbreviations
------------------
Written in nflverse vocabulary, matching `player_game_logs` and the source. Note
this disagrees with the existing 2025 `team_game_results` rows on exactly two
teams -- ESPN says `LAR`/`WSH`, nflverse says `LA`/`WAS` -- so those two teams
already fail to join between the two tables. See ESPN_ALIASES; reconciling the
2025 rows is a separate change and is deliberately not done here.

Usage:
  cd backend && LP_DB_PATH=/abs/path/picks.dev.db \\
      venv/bin/python ingest_nfl_schedule.py [--season 2026] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import sqlite3
import sys
import urllib.request

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

SOURCE = "nflverse_games"
URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"

# nflverse abbrev -> the ESPN abbrev used by the 2025 team_game_results rows.
# Recorded, not applied: this module writes nflverse vocabulary throughout.
ESPN_ALIASES = {"LA": "LAR", "WAS": "WSH"}

# CSV column -> (sqlite column, type). The point of this module is a copy, not a
# computation; the only derived value is `status`, from whether a result exists.
_INT = "INTEGER"
_REAL = "REAL"
_TEXT = "TEXT"
COLUMNS: tuple[tuple[str, str], ...] = (
    ("game_id", _TEXT), ("season", _INT), ("game_type", _TEXT), ("week", _INT),
    ("gameday", _TEXT), ("weekday", _TEXT), ("gametime", _TEXT),
    ("away_team", _TEXT), ("home_team", _TEXT), ("location", _TEXT),
    ("away_score", _INT), ("home_score", _INT), ("result", _REAL),
    ("total", _REAL), ("overtime", _INT), ("espn", _TEXT),
    ("away_rest", _INT), ("home_rest", _INT),
    ("away_moneyline", _INT), ("home_moneyline", _INT),
    ("spread_line", _REAL), ("total_line", _REAL), ("div_game", _INT),
    ("roof", _TEXT), ("surface", _TEXT), ("temp", _INT), ("wind", _INT),
    ("away_qb_id", _TEXT), ("home_qb_id", _TEXT),
    ("away_qb_name", _TEXT), ("home_qb_name", _TEXT),
    ("away_coach", _TEXT), ("home_coach", _TEXT), ("referee", _TEXT),
    ("stadium_id", _TEXT), ("stadium", _TEXT),
)
_NUMERIC = {name for name, kind in COLUMNS if kind in (_INT, _REAL)}
_IS_INT = {name for name, kind in COLUMNS if kind == _INT}


def fetch(cache_dir: str, refresh: bool = False) -> tuple[str, str]:
    """Download games.csv once and report its sha256.

    nfldata tracks master, so the file moves whenever a game finishes or a line
    updates. The digest is what makes a run reproducible -- print it.
    """
    path = os.path.join(cache_dir, "games.csv")
    if refresh or not os.path.exists(path):
        urllib.request.urlretrieve(URL, path)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("  artifact: {} ({} bytes)".format(path, os.path.getsize(path)))
    print("  sha256  : {}".format(digest))
    return path, digest


def ensure_schema(con: sqlite3.Connection) -> None:
    cols = ",\n            ".join(
        "{} {}{}".format(name, kind, " PRIMARY KEY" if name == "game_id" else "")
        for name, kind in COLUMNS)
    con.execute(
        "CREATE TABLE IF NOT EXISTS nfl_schedule (\n            {},\n"
        "            source TEXT,\n"
        "            ingested_at TEXT DEFAULT (datetime('now'))\n        )".format(cols))
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_schedule_season_week "
                "ON nfl_schedule(season, week)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_schedule_gameday "
                "ON nfl_schedule(gameday)")
    # team_game_results predates this ingest; backfill_team_parity.py added
    # season/status. Tolerate a database where it has not run.
    existing = {r[1] for r in con.execute("PRAGMA table_info(team_game_results)")}
    if existing:
        for coldef in ("season INTEGER", "status TEXT"):
            if coldef.split()[0] not in existing:
                con.execute("ALTER TABLE team_game_results ADD COLUMN " + coldef)
    con.commit()


def _cell(name: str, raw: str):
    """'' means absent, not zero -- a scheduled game has no score, and treating
    that as 0 would make every 2026 fixture look like a 0-0 tie."""
    raw = (raw or "").strip()
    if raw == "":
        return None
    if name not in _NUMERIC:
        return raw
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if name in _IS_INT else value


def read_games(path: str, seasons: set[int] | None):
    with io.open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [name for name, _ in COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise RuntimeError("games.csv is missing expected columns: {}".format(missing))
        rows = []
        for raw in reader:
            row = {name: _cell(name, raw.get(name, "")) for name, _ in COLUMNS}
            if row["season"] is None or row["game_id"] is None:
                continue
            if seasons and row["season"] not in seasons:
                continue
            rows.append(row)
    return rows


def write(con: sqlite3.Connection, rows: list[dict]) -> tuple[int, int]:
    names = [name for name, _ in COLUMNS]
    placeholders = ",".join("?" * (len(names) + 1))
    updates = ",".join(
        "{0}=excluded.{0}".format(n) for n in names if n != "game_id")
    con.executemany(
        "INSERT INTO nfl_schedule ({},source) VALUES ({}) "
        "ON CONFLICT(game_id) DO UPDATE SET {},source=excluded.source,"
        "ingested_at=datetime('now')".format(",".join(names), placeholders, updates),
        [[r[n] for n in names] + [SOURCE] for r in rows])

    # Reciprocal per-team rows, so "who does this team play in week N" is one
    # query and future fixtures sit in the same table as finished ones.
    pairs = []
    for r in rows:
        if not r["home_team"] or not r["away_team"]:
            continue
        status = "completed" if r["result"] is not None else "scheduled"
        for team, opp, side, sf, sa in (
            (r["home_team"], r["away_team"], "home", r["home_score"], r["away_score"]),
            (r["away_team"], r["home_team"], "away", r["away_score"], r["home_score"]),
        ):
            win = None
            if sf is not None and sa is not None:
                win = 1 if sf > sa else (0 if sf < sa else None)
            pairs.append((r["game_id"], team, r["gameday"], opp, side,
                          sf, sa, win, r["season"], status))

    # COALESCE on the score columns: re-running with a not-yet-played season must
    # never blank out a real result that another ingest already recorded.
    con.executemany(
        "INSERT INTO team_game_results"
        "(league,game_id,team,game_date,opponent,home_away,score_for,score_against,"
        " win,season,status) VALUES('nfl',?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(league,game_id,team) DO UPDATE SET "
        "  game_date=excluded.game_date, opponent=excluded.opponent,"
        "  home_away=excluded.home_away,"
        "  score_for=COALESCE(excluded.score_for, team_game_results.score_for),"
        "  score_against=COALESCE(excluded.score_against, team_game_results.score_against),"
        "  win=COALESCE(excluded.win, team_game_results.win),"
        "  season=excluded.season,"
        "  status=CASE WHEN excluded.score_for IS NULL"
        "              AND team_game_results.score_for IS NOT NULL"
        "         THEN team_game_results.status ELSE excluded.status END",
        pairs)
    con.commit()
    return len(rows), len(pairs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", action="append", type=int,
                    help="repeatable; default 2026 only")
    ap.add_argument("--all-seasons", action="store_true",
                    help="load 1999-present instead of --season")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    ap.add_argument("--refresh", action="store_true",
                    help="re-download even if cached")
    ap.add_argument("--cache-dir", default="/tmp")
    args = ap.parse_args()

    seasons = None if args.all_seasons else set(args.season or [2026])
    print("nflverse games.csv -> nfl_schedule + team_game_results  (seasons={})".format(
        "all" if seasons is None else sorted(seasons)))
    path, _digest = fetch(args.cache_dir, args.refresh)
    rows = read_games(path, seasons)
    if not rows:
        raise SystemExit("no rows matched -- is the season present in the file?")

    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["game_type"] or "?"] = by_type.get(r["game_type"] or "?", 0) + 1
    scheduled = sum(1 for r in rows if r["result"] is None)
    print("  {} games ({}), {} not yet played".format(
        len(rows), ", ".join("{} {}".format(v, k) for k, v in sorted(by_type.items())),
        scheduled))
    print("  first kickoff: {} {}  {} at {}".format(
        rows[0]["gameday"], rows[0]["gametime"] or "",
        rows[0]["away_team"], rows[0]["home_team"]))
    if args.dry_run:
        print("  dry run: nothing written")
        return

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    ensure_schema(con)
    games, pairs = write(con, rows)
    con.close()
    print("  wrote {} nfl_schedule rows, {} team_game_results rows".format(games, pairs))
    print("  NOTE: no team_stats_coverage manifest is written. The NFL team-stats")
    print("        contract bounds its aggregate by that manifest's season range;")
    print("        a 2026 manifest would pull unplayed games into season totals.")


if __name__ == "__main__":
    main()
