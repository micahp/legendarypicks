#!/usr/bin/env python3
"""Retain a curated nflverse play-by-play table for play-level analysis.

Per-player game logs come from ``ingest_nfl_weekly_stats.py``.  This ingest owns
only the additive ``nfl_pbp`` table.

Usage:
  python3 ingest_nfl_pbp_logs.py [--year 2025]
  LP_DB_PATH=<dev db> python3 ingest_nfl_pbp_logs.py --backfill-file /abs/play_by_play_2015.parquet
      --season 2015 [--allow-new-games] [--apply]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys


from team_codes import normalize


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


# A curated query layer, not all 372 source columns and not an archival copy.
# The selection keeps game/play context plus the passing, rushing, receiving,
# lateral, eligibility, and efficiency fields used by play-level analysis, plus the QB hit,
# scramble, dropback and no-huddle flags.
# nflverse rewrites historical files in place, so retaining the raw artifact
# with a checksum remains a separate concern.
_PLAY_COLS = [
    "game_id", "play_id", "season", "week", "posteam", "defteam",
    "home_team", "away_team", "game_date",
    "qtr", "down", "ydstogo", "yardline_100", "game_seconds_remaining",
    "play_type", "epa", "wpa", "qb_epa", "air_yards", "yards_gained", "cpoe",
    "passer_player_id", "rusher_player_id", "receiver_player_id",
    "pass_location", "run_location", "run_gap", "complete_pass", "touchdown",
    "series", "series_result", "drive", "success", "shotgun",
    "sack", "two_point_attempt",
    "pass_attempt", "rush_attempt", "passing_yards", "rushing_yards",
    "receiving_yards", "pass_touchdown", "rush_touchdown", "interception",
    "lateral_receiver_player_id", "lateral_receiver_player_name",
    "lateral_receiving_yards",
    "lateral_rusher_player_id", "lateral_rusher_player_name",
    "lateral_rushing_yards",
    # Added 2026-10-11 (docs/RESEARCH-nfl-model-inputs-2026-10-11.md). Appended last so a
    # widened existing table and a freshly created one have the same column order.
    "qb_hit", "qb_scramble", "qb_dropback", "no_huddle",
]

# The columns added after 2010-2026 were stored. backfill_columns() fills them on stored
# plays from a published file without rewriting any other column.
_ADDED_COLS = ["qb_hit", "qb_scramble", "qb_dropback", "no_huddle"]

# Each flag belongs on known kinds of play; values joined onto the wrong plays break this.
# On the 2010-2023 files (measured 2026-10-11) every season is at least 0.9964.
_ALIGNMENT = [
    ("qb_hit", ("pass",)),
    ("qb_scramble", ("run", "no_play")),
    ("qb_dropback", ("pass", "run", "no_play")),
]
_MIN_ALIGNED = 0.99


def ensure_pbp_table(con: sqlite3.Connection) -> None:
    """Create nfl_pbp (additive, idempotent). One row per play."""
    cols = ", ".join('"{}"'.format(column) for column in _PLAY_COLS)
    con.execute(
        "CREATE TABLE IF NOT EXISTS nfl_pbp ({}, UNIQUE(game_id, play_id))".format(
            cols
        )
    )
    # CREATE TABLE IF NOT EXISTS is a no-op against a table built from an older,
    # shorter _PLAY_COLS, so widen it explicitly.
    have = {row[1] for row in con.execute("PRAGMA table_info(nfl_pbp)")}
    for column in _PLAY_COLS:
        if column not in have:
            con.execute('ALTER TABLE nfl_pbp ADD COLUMN "{}"'.format(column))

    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_game ON nfl_pbp(game_id, play_id)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_passer "
        "ON nfl_pbp(passer_player_id, season)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_rusher "
        "ON nfl_pbp(rusher_player_id, season)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_pbp_receiver "
        "ON nfl_pbp(receiver_player_id, season)"
    )
    con.commit()


def ingest(year: int = 2025) -> int:
    import warnings

    warnings.filterwarnings("ignore")
    import nfl_data_py as nfl

    print("Loading nflverse pbp {}...".format(year))
    frame = nfl.import_pbp_data([year])
    if "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]
    print("  {} regular-season plays".format(len(frame)))

    missing = sorted(set(_PLAY_COLS) - set(frame.columns))
    if missing:
        # Fail loud rather than silently persisting a narrower table than the
        # readers expect.
        raise RuntimeError(
            "pbp source is missing expected columns: {}".format(missing)
        )

    con = sqlite3.connect(DB)
    ensure_pbp_table(con)
    plays = frame[_PLAY_COLS].astype(object).where(
        frame[_PLAY_COLS].notna(), None
    )
    # Normalise team columns to ESPN vocabulary before writing.
    for col in ("posteam", "defteam", "home_team", "away_team"):
        if col in plays.columns:
            plays[col] = plays[col].apply(
                lambda x: normalize("nfl", x) if x is not None else None
            )
    con.executemany(
        "INSERT OR REPLACE INTO nfl_pbp ({}) VALUES ({})".format(
            ",".join('"{}"'.format(column) for column in _PLAY_COLS),
            ",".join("?" for _ in _PLAY_COLS),
        ),
        plays.itertuples(index=False, name=None),
    )
    con.commit()
    retained = con.execute(
        "SELECT COUNT(*) FROM nfl_pbp WHERE season=?", (year,)
    ).fetchone()[0]
    con.close()
    print("  retained {} plays".format(retained))
    return retained


def read_added_columns(path, season):
    """REG plays of one nflverse play_by_play parquet as {(game_id, play_id): values}.

    values follow _ADDED_COLS. Raises if a column is missing, the file holds another season,
    a play has no key, a key repeats, or a value is not 0, 1 or null.
    """
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    need = ["game_id", "play_id", "season", "season_type"] + _ADDED_COLS
    missing = [c for c in need if c not in pf.schema_arrow.names]
    if missing:
        raise RuntimeError("{}: file lacks columns {}".format(path, missing))
    data = pf.read(columns=need).to_pydict()
    seasons = {int(s) for s in data["season"] if s is not None}
    if seasons != {season}:
        raise RuntimeError("{}: file holds seasons {}, expected only {}".format(
            path, sorted(seasons), season))
    plays = {}
    for i, season_type in enumerate(data["season_type"]):
        if season_type != "REG":
            continue
        key = (data["game_id"][i], data["play_id"][i])
        if None in key:
            raise RuntimeError("{}: REG play without a key: {}".format(path, key))
        if key in plays:
            raise RuntimeError("{}: play key {} appears twice".format(path, key))
        values = tuple(data[c][i] for c in _ADDED_COLS)
        if any(v not in (None, 0, 1) for v in values):
            raise RuntimeError("{}: play {} has a value outside 0, 1, null: {}".format(
                path, key, values))
        plays[key] = values
    return plays, pf.metadata.num_rows


def backfill_columns(con, path, season, apply=False, allow_new_games=False):
    """Fill _ADDED_COLS on the stored nfl_pbp plays of one season from a published file.

    Updates stored rows only, matched on (game_id, play_id). Writes no other column and
    inserts or deletes no row, so values already stored (and results pinned to them) stay as
    they are. Refuses, writing nothing, unless every stored play of the season is in the file.
    File plays that are not stored are refused too, except with allow_new_games for games that
    are not stored at all (an in-progress season). Dry run unless apply. `con` must be opened
    with isolation_level=None.
    """
    plays, file_rows = read_added_columns(path, season)
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    keys = con.execute(
        "SELECT game_id, play_id FROM nfl_pbp WHERE season=?", (season,)).fetchall()
    stored = set(keys)
    matched = sorted(stored & set(plays))
    stored_only = sorted(stored - set(plays))
    file_only = sorted(set(plays) - stored)
    stored_games = {game for game, _ in stored}
    file_only_in_stored_games = [k for k in file_only if k[0] in stored_games]
    new_games = sorted({game for game, _ in file_only if game not in stored_games})
    report = {
        "season": season, "file": os.path.basename(path), "sha256": sha,
        "file_rows": file_rows, "file_reg_rows": len(plays), "stored_rows": len(keys),
        "matched": len(matched), "stored_only": len(stored_only),
        "file_only": len(file_only), "new_games_skipped": new_games,
    }
    for i, col in enumerate(_ADDED_COLS):
        values = [plays[k][i] for k in matched]
        report[col] = {"null": sum(v is None for v in values),
                       "one": sum(v == 1 for v in values)}
    problems = []
    if not keys:
        problems.append("no stored plays for season {}".format(season))
    if len(stored) != len(keys):
        problems.append("stored play keys repeat")
    if stored_only:
        problems.append("{} stored plays are not in the file, e.g. {}".format(
            len(stored_only), stored_only[:5]))
    if file_only_in_stored_games:
        problems.append("{} file plays are missing from stored games, e.g. {}".format(
            len(file_only_in_stored_games), file_only_in_stored_games[:5]))
    if file_only and not allow_new_games:
        problems.append("{} file plays are not stored (games {}); --allow-new-games is for an "
                        "in-progress season only".format(len(file_only), new_games[:5]))
    print(json.dumps(report, sort_keys=True))
    if problems:
        raise RuntimeError("; ".join(problems))
    if not apply:
        print("dry run: nothing written")
        return report

    ensure_pbp_table(con)  # adds any _PLAY_COLS column the stored table lacks
    sets = ", ".join('"{}"=?'.format(col) for col in _ADDED_COLS)
    checks = []
    for col in _ADDED_COLS:
        checks.append('COALESCE(SUM("{}" IS NULL), 0)'.format(col))
        checks.append('COALESCE(SUM("{}"=1), 0)'.format(col))
    for col, kinds in _ALIGNMENT:
        checks.append('COALESCE(SUM("{}"=1 AND play_type IN ({})), 0)'.format(
            col, ", ".join("'{}'".format(kind) for kind in kinds)))
    before = con.total_changes
    con.execute("BEGIN IMMEDIATE")
    try:
        con.executemany(
            "UPDATE nfl_pbp SET {} WHERE game_id=? AND play_id=?".format(sets),
            [plays[k] + k for k in matched])
        updated = con.total_changes - before
        if updated != len(matched):
            raise RuntimeError("updated {} rows, expected {}".format(updated, len(matched)))
        got = con.execute("SELECT {} FROM nfl_pbp WHERE season=?".format(", ".join(checks)),
                          (season,)).fetchone()
        for i, col in enumerate(_ADDED_COLS):
            stored_counts = {"null": got[2 * i], "one": got[2 * i + 1]}
            if stored_counts != report[col]:
                raise RuntimeError("{}: stored {} but the file has {}".format(
                    col, stored_counts, report[col]))
        for j, (col, kinds) in enumerate(_ALIGNMENT):
            ones = report[col]["one"]
            share = got[2 * len(_ADDED_COLS) + j] / ones if ones else None
            report["aligned_" + col] = share
            if share is not None and share < _MIN_ALIGNED:
                raise RuntimeError("{}=1 is on {} plays only {:.4f} of the time".format(
                    col, "/".join(kinds), share))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    print("applied: " + json.dumps(
        {k: v for k, v in report.items()
         if k in ("season", "matched") or k.startswith("aligned_")}, sort_keys=True))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Retain nflverse play-by-play in nfl_pbp")
    ap.add_argument("--year", type=int, default=2025,
                    help="season to ingest via nfl_data_py (rewrites that season's stored plays)")
    ap.add_argument("--backfill-file",
                    help="absolute path of an nflverse play_by_play_<season>.parquet; fills only "
                         "the added columns on the stored plays of --season")
    ap.add_argument("--season", type=int, help="season of --backfill-file")
    ap.add_argument("--allow-new-games", action="store_true",
                    help="in-progress season only: skip file plays whose game is not stored")
    ap.add_argument("--apply", action="store_true",
                    help="write; without it --backfill-file is a dry run")
    a = ap.parse_args(argv)
    if not a.backfill_file:
        ingest(a.year)
        return 0
    db = os.environ.get("LP_DB_PATH")
    if not db or os.path.basename(db) == "picks.db" or not os.path.exists(db):
        raise SystemExit("set LP_DB_PATH to an existing dev DB; picks.db is refused")
    if not os.path.isabs(a.backfill_file) or a.season is None:
        raise SystemExit("--backfill-file needs an absolute path and --season")
    con = sqlite3.connect(db, timeout=120, isolation_level=None)
    con.execute("PRAGMA busy_timeout=120000")
    try:
        backfill_columns(con, a.backfill_file, a.season, apply=a.apply,
                         allow_new_games=a.allow_new_games)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
