#!/usr/bin/env python3
"""load_nfl_history.py -- load published nflverse and 538 history files into new model-input
tables of the dev DB, one (source, season) file at a time, and reconcile each load against the
file's own row count. Plan: docs/PLAN-nfl-data-backfill-2026-10-11.md.

- Tables are new (nfl_hist_*, nfl_elo_538, nfl_hist_loads) and created idempotently by
  migrate(). No prod code reads them.
- Rows are stored as published: every row of the file, publisher ids kept, nothing dropped or
  collapsed. Team codes go through team_codes.normalize, which raises on an unknown code.
- A load is delete-then-insert for (source, season) inside one transaction, so a rerun replaces
  rather than duplicates. After insert, stored rows are counted and compared with the file's
  row count; a difference rolls back and raises. Each load writes one nfl_hist_loads row with
  the file's sha256, file rows and stored rows.
- The file is data, never code: parquet via pyarrow, CSV via the csv module.

Usage (LP_DB_PATH must be set; refuses a path named picks.db):
  python load_nfl_history.py --migrate
  python load_nfl_history.py --source injuries --season 2015 --file /abs/injuries_2015.parquet
  python load_nfl_history.py --source elo538 --file /abs/nfl_games.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import os
import sqlite3
import sys

from team_codes import normalize

SOURCES = {
    # source: (table, [columns as stored], {team columns}, file column for each stored column)
    "injuries": ("nfl_hist_injuries",
                 ["season", "game_type", "week", "team", "gsis_id", "position", "full_name",
                  "report_status", "practice_status", "report_primary_injury",
                  "date_modified"], {"team"}),
    "snap_counts": ("nfl_hist_snap_counts",
                    ["game_id", "season", "game_type", "week", "pfr_player_id", "player",
                     "position", "team", "opponent", "offense_snaps", "offense_pct",
                     "defense_snaps", "defense_pct", "st_snaps", "st_pct"],
                    {"team", "opponent"}),
    "depth_charts": ("nfl_hist_depth_charts",
                     ["season", "week", "game_type", "club_code", "depth_team", "formation",
                      "gsis_id", "position", "depth_position", "full_name"], {"club_code"}),
    "ftn_charting": ("nfl_hist_ftn_charting",
                     ["nflverse_game_id", "nflverse_play_id", "season", "week",
                      "starting_hash", "qb_location", "n_offense_backfield", "n_defense_box",
                      "is_no_huddle", "is_motion", "is_play_action", "is_screen_pass",
                      "is_rpo", "is_trick_play", "is_qb_out_of_pocket",
                      "is_interception_worthy", "is_throw_away", "read_thrown",
                      "is_catchable_ball", "is_contested_ball", "is_created_reception",
                      "is_drop", "is_qb_sneak", "n_blitzers", "n_pass_rushers",
                      "is_qb_fault_sack", "date_pulled"], set()),
    "participation": ("nfl_hist_participation",
                      ["nflverse_game_id", "play_id", "season", "possession_team",
                       "offense_formation", "offense_personnel", "defenders_in_box",
                       "defense_personnel", "number_of_pass_rushers", "was_pressure",
                       "defense_man_zone_type", "defense_coverage_type", "time_to_throw",
                       "n_offense", "n_defense"], {"possession_team"}),
    "player_ids": ("nfl_hist_player_ids",
                   ["gsis_id", "pfr_id", "display_name", "position"], set()),
    "elo538": ("nfl_elo_538",
               ["date", "season", "neutral", "playoff", "team1", "team2", "elo1", "elo2",
                "elo_prob1", "score1", "score2", "result1"], set()),
}
# Columns a publisher dropped from some years (injuries 2025 has no date_modified). Stored as
# NULL and announced; any other missing column is an error.
OPTIONAL = {"date_modified"}
NO_SEASON = {"elo538", "player_ids"}
# Files with no season column. The season comes from --season, and every game id must start
# with it (nflverse ids are "<season>_<week>_<away>_<home>"); any other id raises.
SEASON_FROM_ARG = {"participation"}
ATTRIBUTION = {"ftn_charting": "FTN Data via nflverse, CC BY-SA 4.0",
               "elo538": "FiveThirtyEight nfl-elo-game, MIT licence"}


def migrate(con):
    for src, (table, cols, _teams) in SOURCES.items():
        con.execute("CREATE TABLE IF NOT EXISTS %s (%s)" % (table, ", ".join(cols)))
        if "season" in cols:
            con.execute("CREATE INDEX IF NOT EXISTS idx_%s_season ON %s(season)" % (table, table))
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_hist_injuries_key "
                "ON nfl_hist_injuries(season, week, team, gsis_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_hist_snap_key "
                "ON nfl_hist_snap_counts(season, week, team)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_hist_depth_key "
                "ON nfl_hist_depth_charts(season, week, club_code, position)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_nfl_hist_participation_key "
                "ON nfl_hist_participation(nflverse_game_id, play_id)")
    con.execute("CREATE TABLE IF NOT EXISTS nfl_hist_loads (source, season, file, sha256, "
                "file_rows, stored_rows, attribution, loaded_at)")
    con.commit()


def read_rows(src, path, season):
    cols = SOURCES[src][1]
    if path.endswith(".csv"):
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        file_rows = len(rows)
        return [[r[c] for c in cols] for r in rows], file_rows
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    file_rows = pf.metadata.num_rows
    missing = [c for c in cols if c not in pf.schema.names
               and not (src in SEASON_FROM_ARG and c == "season")]
    if set(missing) - OPTIONAL:
        raise RuntimeError("%s: file lacks columns %s" % (path, missing))
    if missing:
        print("  %s: optional columns absent from this file, stored as NULL: %s" % (
            os.path.basename(path), missing))
    data = pf.read(columns=[c for c in cols if c not in missing and c in pf.schema.names]).to_pydict()
    if src in SEASON_FROM_ARG:
        bad = {g for g in data["nflverse_game_id"] if not str(g).startswith("%d_" % season)}
        if bad:
            raise RuntimeError("%s: %d game ids are not season %d, e.g. %s" % (
                path, len(bad), season, sorted(bad)[:3]))
        data["season"] = [season] * pf.metadata.num_rows
    for c in missing:
        data[c] = [None] * pf.metadata.num_rows
    n = len(data[cols[0]])
    seasons = {int(s) for s in data.get("season", ()) if s is not None}
    if season is not None and seasons - {season}:
        raise RuntimeError("%s: file holds seasons %s, expected only %d" % (path, sorted(seasons), season))
    return [[data[c][i] for c in cols] for i in range(n)], file_rows


def load(con, src, path, season):
    table, cols, teams = SOURCES[src]
    rows, file_rows = read_rows(src, path, season)
    tidx = [cols.index(c) for c in teams]
    blank_team = 0
    for r in rows:
        for i in tidx:
            if r[i] is None or r[i] == "":
                blank_team += 1
            else:
                r[i] = normalize("nfl", str(r[i]))
        for i, v in enumerate(r):
            if isinstance(v, (dt.date, dt.datetime)):
                r[i] = v.isoformat()
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    con.execute("BEGIN IMMEDIATE")
    try:
        if season is None:
            con.execute("DELETE FROM %s" % table)
        else:
            con.execute("DELETE FROM %s WHERE season = ?" % table, (season,))
        con.executemany("INSERT INTO %s (%s) VALUES (%s)" % (
            table, ", ".join(cols), ", ".join("?" * len(cols))), rows)
        if season is None:
            stored = con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
        else:
            stored = con.execute("SELECT COUNT(*) FROM %s WHERE season = ?" % table,
                                 (season,)).fetchone()[0]
        print("%s %s: file rows %d, stored rows %d, mismatch %d, blank team values %d" % (
            src, season if season is not None else "all", file_rows, stored,
            stored - file_rows, blank_team))
        if stored != file_rows:
            raise RuntimeError("count mismatch, rolled back")
        con.execute("INSERT INTO nfl_hist_loads VALUES (?,?,?,?,?,?,?,?)",
                    (src, season, os.path.basename(path), sha, file_rows, stored,
                     ATTRIBUTION.get(src, "nflverse"),
                     dt.datetime.now(dt.timezone.utc).isoformat()))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--migrate", action="store_true")
    ap.add_argument("--source", choices=sorted(SOURCES))
    ap.add_argument("--season", type=int)
    ap.add_argument("--file")
    a = ap.parse_args(argv)
    db = os.environ.get("LP_DB_PATH")
    if not db or os.path.basename(db) == "picks.db":
        raise SystemExit("set LP_DB_PATH to the dev DB; picks.db is refused")
    con = sqlite3.connect(db, timeout=120, isolation_level=None)
    con.execute("PRAGMA busy_timeout=120000")
    migrate(con)
    if a.source:
        if not a.file or not os.path.isabs(a.file):
            raise SystemExit("--file must be an absolute path")
        if a.source not in NO_SEASON and a.season is None:
            raise SystemExit("--season is required for %s" % a.source)
        load(con, a.source, a.file, None if a.source in NO_SEASON else a.season)
    return 0


if __name__ == "__main__":
    sys.exit(main())
