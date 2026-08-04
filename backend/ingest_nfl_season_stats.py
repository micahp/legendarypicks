#!/usr/bin/env python3
"""Publish NFL regular-season totals from nflverse's season summary artifact.

The source already publishes one regular-season row per player. Counting stats
are copied verbatim; only fields explicitly labelled ``/G`` are divided by the
source-published games value.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import urllib.request
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from league_stats import publish_player_stats  # noqa: E402
from nfl_rankings import NFL_REGULAR_SEASON_SOURCE  # noqa: E402
from team_codes import normalize_optional  # noqa: E402


URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_reg_{year}.parquet"
)
POSITIONS = frozenset(("QB", "RB", "WR", "TE"))
REQUIRED_COLUMNS = frozenset((
    "player_id", "player_display_name", "position", "season", "season_type",
    "recent_team", "games", "completions", "passing_yards", "passing_tds",
    "passing_interceptions", "passing_epa", "carries", "rushing_yards",
    "receptions", "receiving_yards", "targets", "fantasy_points",
    "fantasy_points_ppr",
    # The artifact publishes 143 columns and this set read 19 of them. These
    # three were among the 124 dropped, which is the entire reason
    # A/required-stats[season] failed on "no such column: rush_td, rec_td" and
    # E/qualifier could not measure "passer rating 14 att x team games". The
    # data was arriving on every run and being discarded before anyone looked.
    "attempts", "rushing_tds", "receiving_tds",
))


def _number(value):
    if value is None or value != value:
        return None
    return int(value) if float(value).is_integer() else float(value)


def _per_game(value, games):
    value = _number(value)
    games = _number(games)
    if value is None or not games:
        return None
    return float(
        (Decimal(str(value)) / Decimal(str(games))).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    )


def fetch_artifact(year: int, cache_dir: str) -> tuple[str, str]:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"stats_player_reg_{year}.parquet")
    if not os.path.exists(path):
        urllib.request.urlretrieve(URL.format(year=year), path)
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    return path, digest


def load_source_rows(path: str, year: int) -> list[dict]:
    import pyarrow.parquet as parquet

    file = parquet.ParquetFile(path)
    missing = sorted(REQUIRED_COLUMNS - set(file.schema.names))
    if missing:
        raise RuntimeError("regular-season artifact is missing: " + ", ".join(missing))
    source_rows = parquet.read_table(path, columns=sorted(REQUIRED_COLUMNS)).to_pylist()
    rows = [
        row for row in source_rows
        if row["season"] == year
        and row["season_type"] == "REG"
        and row["position"] in POSITIONS
    ]
    source_ids = [str(row["player_id"] or "").strip() for row in rows]
    if any(not source_id for source_id in source_ids):
        raise RuntimeError("regular-season skill-player population has a blank player_id")
    if len(set(source_ids)) != len(source_ids):
        raise RuntimeError("regular-season artifact has duplicate skill-player IDs")
    if any(not _number(row["games"]) for row in rows):
        raise RuntimeError("regular-season skill-player population has a missing games value")
    if not rows:
        raise RuntimeError("regular-season artifact has no skill-player rows")
    return rows


def resolve_rows(connection: sqlite3.Connection, source_rows: list[dict]) -> list[dict]:
    player_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(players)")
    }
    if "nfl_gsis_id" not in player_columns:
        raise RuntimeError("players.nfl_gsis_id is required")
    identity_rows = connection.execute(
        """SELECT id, name, nfl_gsis_id
             FROM players
            WHERE league='nfl' AND nfl_gsis_id IS NOT NULL"""
    ).fetchall()
    duplicate_ids = {
        row[0] for row in connection.execute(
            """SELECT nfl_gsis_id
                 FROM players
                WHERE league='nfl' AND nfl_gsis_id IS NOT NULL
                GROUP BY nfl_gsis_id HAVING COUNT(*) > 1"""
        )
    }
    if duplicate_ids:
        raise RuntimeError(
            f"players has {len(duplicate_ids)} duplicate NFL GSIS identities"
        )
    identity = {str(row["nfl_gsis_id"]): row for row in identity_rows}
    unresolved = [
        row for row in source_rows if str(row["player_id"]) not in identity
    ]
    if unresolved:
        sample = ", ".join(
            f"{row['player_display_name']} ({row['player_id']})"
            for row in unresolved[:5]
        )
        raise RuntimeError(
            f"unresolved regular-season identities: {len(unresolved)}; {sample}"
        )
    return [
        {**row, "canonical_player_id": identity[str(row["player_id"])]["id"]}
        for row in source_rows
    ]


def _values(row: dict) -> dict:
    position = row["position"]
    values = {
        "nfl_position": position,
        "nfl_team": normalize_optional("nfl", row["recent_team"]),
        "fantasy_pts_g": _per_game(row["fantasy_points"], row["games"]),
        "fantasy_ppr_g": _per_game(row["fantasy_points_ppr"], row["games"]),
    }
    if position == "QB":
        values.update({
            "pass_yds_g": _per_game(row["passing_yards"], row["games"]),
            "pass_td": _number(row["passing_tds"]),
            "interceptions": _number(row["passing_interceptions"]),
            "cmp_g": _per_game(row["completions"], row["games"]),
            "pass_epa": _number(row["passing_epa"]),
            "carries_g": _per_game(row["carries"], row["games"]),
            "rush_yds_g": _per_game(row["rushing_yards"], row["games"]),
            # `attempts` is the published qualifier's unit -- "passer rating 14
            # att x team games". It was in this artifact the whole time and was
            # dropped on the floor, so the gate could not ask the published
            # question at all.
            "attempts": _number(row["attempts"]),
            "rush_td": _number(row["rushing_tds"]),
        })
    elif position == "RB":
        values.update({
            "carries_g": _per_game(row["carries"], row["games"]),
            "rush_yds_g": _per_game(row["rushing_yards"], row["games"]),
            "receptions": _number(row["receptions"]),
            "rec_yds_g": _per_game(row["receiving_yards"], row["games"]),
            "targets": _number(row["targets"]),
            "rush_td": _number(row["rushing_tds"]),
            "rec_td": _number(row["receiving_tds"]),
        })
    else:
        values.update({
            "receptions": _number(row["receptions"]),
            "rec_yds_g": _per_game(row["receiving_yards"], row["games"]),
            "targets": _number(row["targets"]),
            # A receiver's rushing touchdown is rare and real (end-arounds),
            # and it is published per player -- so it is written per player
            # rather than assumed away by position.
            "rec_td": _number(row["receiving_tds"]),
            "rush_td": _number(row["rushing_tds"]),
        })
    return values


def publish(db_path: str, year: int, rows: list[dict]) -> None:
    if not os.path.isabs(db_path) or not os.path.isfile(db_path):
        raise RuntimeError("--db must be an absolute path to an existing database")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM player_stats WHERE league='nfl' AND season=?",
            (year,),
        )
        for row in rows:
            publish_player_stats(
                connection,
                player_id=row["canonical_player_id"],
                league="nfl",
                season=year,
                stat_type="season",
                source=NFL_REGULAR_SEASON_SOURCE,
                games=int(row["games"]),
                values=_values(row),
            )
        count = connection.execute(
            """SELECT COUNT(*) FROM player_stats
                WHERE league='nfl' AND season=? AND stat_type='season'
                  AND source=?""",
            (year, NFL_REGULAR_SEASON_SOURCE),
        ).fetchone()[0]
        if count != len(rows):
            raise RuntimeError(f"publication count mismatch: {count} != {len(rows)}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--cache-dir", default="/tmp/lp-nflverse-player-stats")
    parser.add_argument("--db", default=os.environ.get("LP_DB_PATH"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.db:
        raise RuntimeError("--db or LP_DB_PATH is required")

    path, digest = fetch_artifact(args.year, args.cache_dir)
    source_rows = load_source_rows(path, args.year)
    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        resolved = resolve_rows(connection, source_rows)
    finally:
        connection.close()

    print(f"artifact={path}")
    print(f"sha256={digest}")
    print(f"source_rows={len(source_rows)} resolved={len(resolved)}")
    if not args.apply:
        print("dry_run=ok (pass --apply to publish)")
        return
    publish(args.db, args.year, resolved)
    print(f"published={len(resolved)} season={args.year}")


if __name__ == "__main__":
    main()
