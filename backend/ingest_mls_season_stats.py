#!/usr/bin/env python3
"""Publish MLS regular-season totals from the ESPN per-game logs we hold.

``ingest_soccer_logs.py`` writes MLS per-player stats per game into
``player_game_logs.stats`` keyed by the exact vocabulary the gate declares
(``goals, assists, shots, sot``), zero-filled for every line, source ``espn``.
ESPN's per-athlete season aggregate endpoint is not the source this project
uses for MLS (the logs are), so the season aggregate is a sum of the
publisher's own per-game values -- the one value we can honestly roll up
without reimplementing someone's definition (published-first rung 4).

Counting stats are summed across the player's REG games in the season; ``games``
is the number of log rows (one row per game). Only rows whose stats JSON
carries at least one of the mapped keys are written; a player with nothing on
file is not invented. Because the soccer ingest zero-fills every line, a
player with logs always has all four keys, so the zeros are the publisher's
published zeros, not fabricated ones.

Requires ``migrate_mls_season_columns.py`` to have added the ``sot`` column to
``player_stats`` (``goals, assists, shots`` already exist).

Usage:
  python3 ingest_mls_season_stats.py --season 2025 --db <abs path> [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from league_stats import publish_player_stats  # noqa: E402

LEAGUE = "mls"
SOURCE = "espn"
GAME_TYPE = "REG"

# our column <- MLS log stats JSON key. Same vocabulary ingest_soccer_logs
# writes (the gate MANIFEST declares exactly these required columns).
_COLUMN_BY_KEY = {
    "goals": "goals",
    "assists": "assists",
    "shots": "shots",
    "sot": "sot",
}


def _load_log_rows(connection: sqlite3.Connection, season: int) -> list[dict]:
    """One dict per player: summed MLS stats + games count."""
    rows = connection.execute(
        """SELECT player_id, stats
             FROM player_game_logs
            WHERE league=? AND season=? AND game_type=?""",
        (LEAGUE, season, GAME_TYPE),
    ).fetchall()
    aggregated: dict[int, dict] = {}
    for row in rows:
        pid = row["player_id"]
        if pid is None:
            continue
        try:
            stats = json.loads(row["stats"]) if row["stats"] else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(stats, dict):
            continue
        bucket = aggregated.setdefault(pid, {"games": 0, "values": {}})
        bucket["games"] += 1
        for key, column in _COLUMN_BY_KEY.items():
            value = stats.get(key)
            if value is None:
                continue
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            bucket["values"][column] = bucket["values"].get(column, 0) + value
    return [
        {"player_id": pid, "games": b["games"], "values": b["values"]}
        for pid, b in aggregated.items()
        if b["values"]
    ]


def resolve_players(connection: sqlite3.Connection,
                    log_rows: list[dict]) -> list[dict]:
    """Attach canonical player id + name, league-checked."""
    resolved = []
    for row in log_rows:
        player = connection.execute(
            "SELECT id, league FROM players WHERE id=?",
            (row["player_id"],),
        ).fetchone()
        if player is None or str(player["league"]).strip().lower() != LEAGUE:
            continue
        resolved.append(row)
    return resolved


def publish(db_path: str, season: int, log_rows: list[dict]) -> int:
    if not os.path.isabs(db_path) or not os.path.isfile(db_path):
        raise RuntimeError("--db must be an absolute path to an existing database")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM player_stats WHERE league=? AND season=? AND stat_type='season'",
            (LEAGUE, season),
        )
        for row in log_rows:
            publish_player_stats(
                connection,
                player_id=row["player_id"],
                league=LEAGUE,
                season=season,
                stat_type="season",
                source=SOURCE,
                games=row["games"],
                values=row["values"],
            )
        count = connection.execute(
            """SELECT COUNT(*) FROM player_stats
                WHERE league=? AND season=? AND stat_type='season' AND source=?""",
            (LEAGUE, season, SOURCE),
        ).fetchone()[0]
        if count != len(log_rows):
            raise RuntimeError(f"publication count mismatch: {count} != {len(log_rows)}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--db", default=os.environ.get("LP_DB_PATH"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not args.db:
        raise RuntimeError("--db or LP_DB_PATH is required")

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        log_rows = _load_log_rows(connection, args.season)
        resolved = resolve_players(connection, log_rows)
    finally:
        connection.close()

    print(f"log_rows={len(log_rows)} resolved={len(resolved)} season={args.season}")
    if not args.apply:
        print("dry_run=ok (pass --apply to publish)")
        return 0
    count = publish(args.db, args.season, resolved)
    print(f"published={count} season={args.season}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
