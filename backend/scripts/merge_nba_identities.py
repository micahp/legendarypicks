#!/usr/bin/env python3
"""Merge split NBA identities through the shared ESPN/hoopR athlete ID.

hoopR's ``athlete_id`` is ESPN's athlete ID. Legacy imports stored that value
in ``players.nba_id`` while current roster/log jobs stored it in
``players.espn_id``. When those columns live on different ``players.id`` rows,
one real player is split between historical stats and current game history.

This repair keeps the ESPN row, moves only stable-ID-backed dependencies from
the hoopR row, and requires exact operator-provided counts plus a verified
backup before applying.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import migrate_schema
from league_stats import normalize_player_name


class NBAMergeError(RuntimeError):
    """The NBA identity split cannot be repaired without guessing."""


_MOVABLE_TABLES = (
    "player_game_logs",
    "player_stats",
    "props",
    "name_alias",
    "roster_memberships",
)
_PROTECTED_TABLES = ("props", "prop_results", "prop_games")


MIGRATION_ID = "20260805_001_merge_nba_identities"
MIGRATION_CHECKSUM = hashlib.sha256(
    json.dumps(
        {
            "migration_id": MIGRATION_ID,
            "reason": "hoopR athlete_id == ESPN athlete id; legacy nba_id rows "
                      "split from espn_id rows must collapse to the ESPN row",
            "movable_tables": sorted(_MOVABLE_TABLES),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


def _absolute_db(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_file():
        raise NBAMergeError(
            f"database must be an existing absolute file: {path!r}"
        )
    return str(candidate)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def _fingerprint(connection: sqlite3.Connection, table: str) -> str | None:
    if not _table_exists(connection, table):
        return None
    rows = connection.execute(
        f'SELECT * FROM "{table}" ORDER BY rowid'
    ).fetchall()
    payload = json.dumps(
        [list(row) for row in rows],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _pairs(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT e.id AS winner_id,h.id AS loser_id,
                  CAST(e.espn_id AS TEXT) AS source_id,
                  e.name AS winner_name,h.name AS loser_name,
                  e.nba_id AS winner_nba_id,h.espn_id AS loser_espn_id
           FROM players e
           JOIN players h
             ON h.league='nba'
            AND e.league='nba'
            AND e.id<>h.id
            AND CAST(e.espn_id AS TEXT)=CAST(h.nba_id AS TEXT)
           WHERE e.espn_id IS NOT NULL
             AND TRIM(CAST(e.espn_id AS TEXT))!=''
             AND h.nba_id IS NOT NULL
             AND TRIM(CAST(h.nba_id AS TEXT))!=''
           ORDER BY e.id,h.id"""
    ).fetchall()


def build_plan(db_path: str) -> dict:
    absolute = _absolute_db(db_path)
    connection = sqlite3.connect(
        f"file:{absolute}?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    try:
        pairs = _pairs(connection)
        if not pairs:
            return {
                "pairs": [],
                "pair_count": 0,
                "moved": {},
                "protected": {
                    table: _fingerprint(connection, table)
                    for table in _PROTECTED_TABLES
                },
            }
        winners = [int(row["winner_id"]) for row in pairs]
        losers = [int(row["loser_id"]) for row in pairs]
        source_ids = [str(row["source_id"]) for row in pairs]
        if (
            len(set(winners)) != len(pairs)
            or len(set(losers)) != len(pairs)
            or len(set(source_ids)) != len(pairs)
        ):
            raise NBAMergeError(
                "NBA ESPN/hoopR identity bridge is not one-to-one"
            )
        conflicts = [
            row for row in pairs
            if (
                row["winner_nba_id"] is not None
                and str(row["winner_nba_id"]) != str(row["source_id"])
            )
            or (
                row["loser_espn_id"] is not None
                and str(row["loser_espn_id"]) != str(row["source_id"])
            )
        ]
        if conflicts:
            raise NBAMergeError(
                f"{len(conflicts)} bridge pairs contain conflicting source IDs"
            )

        placeholders = ",".join("?" for _ in losers)
        moved = {}
        unexpected = {}
        tables = [
            str(row[0])
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' ORDER BY name"""
            )
        ]
        for table in tables:
            if "player_id" not in _columns(connection, table):
                continue
            count = connection.execute(
                f"""SELECT COUNT(*) FROM "{table}"
                    WHERE player_id IN ({placeholders})""",
                losers,
            ).fetchone()[0]
            if not count:
                continue
            if table in _MOVABLE_TABLES:
                moved[table] = int(count)
            else:
                unexpected[table] = int(count)
        if unexpected:
            raise NBAMergeError(
                "unexpected loser dependencies: "
                + ", ".join(
                    f"{table}={count}"
                    for table, count in sorted(unexpected.items())
                )
            )

        for row in pairs:
            duplicate_stat = connection.execute(
                """SELECT 1
                   FROM player_stats loser
                   JOIN player_stats winner
                     ON winner.player_id=?
                    AND loser.player_id=?
                    AND winner.league=loser.league
                    AND winner.season=loser.season
                    AND winner.stat_type=loser.stat_type
                   LIMIT 1""",
                (row["winner_id"], row["loser_id"]),
            ).fetchone()
            if duplicate_stat is not None:
                raise NBAMergeError(
                    "NBA identity merge would collide in player_stats for "
                    f"source ID {row['source_id']}"
                )

        return {
            "pairs": [dict(row) for row in pairs],
            "pair_count": len(pairs),
            "moved": dict(sorted(moved.items())),
            "protected": {
                table: _fingerprint(connection, table)
                for table in _PROTECTED_TABLES
            },
        }
    finally:
        connection.close()


def apply_plan(
    db_path: str,
    plan: dict,
    *,
    expected_pairs: int,
    expected_moved: dict[str, int],
) -> str:
    absolute = _absolute_db(db_path)
    if int(expected_pairs) != int(plan["pair_count"]):
        raise NBAMergeError(
            f"expected {expected_pairs} pairs, planned {plan['pair_count']}"
        )
    if expected_moved != plan["moved"]:
        raise NBAMergeError(
            f"expected moved rows {expected_moved}, planned {plan['moved']}"
        )
    if not plan["pairs"]:
        raise NBAMergeError("no split NBA identities remain to merge")

    backup = migrate_schema.create_verified_backup(absolute)
    connection = sqlite3.connect(absolute)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")
        connection.execute("BEGIN IMMEDIATE")
        for pair in plan["pairs"]:
            winner_id = int(pair["winner_id"])
            loser_id = int(pair["loser_id"])
            source_id = str(pair["source_id"])
            winner_name = str(pair["winner_name"])

            if _table_exists(connection, "player_stats"):
                stat_columns = _columns(connection, "player_stats")
                assignments = ["player_id=?", "player_name=?"]
                params = [winner_id, winner_name]
                if "name_norm" in stat_columns:
                    assignments.append("name_norm=?")
                    params.append(normalize_player_name(winner_name))
                params.append(loser_id)
                connection.execute(
                    f"""UPDATE player_stats SET {','.join(assignments)}
                        WHERE player_id=?""",
                    params,
                )
            for table in (
                "player_game_logs",
                "props",
                "name_alias",
                "roster_memberships",
            ):
                if "player_id" in _columns(connection, table):
                    connection.execute(
                        f'UPDATE "{table}" SET player_id=? WHERE player_id=?',
                        (winner_id, loser_id),
                    )
            connection.execute(
                """UPDATE players SET nba_id=?
                   WHERE id=? AND league='nba'""",
                (source_id, winner_id),
            )
            connection.execute(
                "DELETE FROM players WHERE id=? AND league='nba'",
                (loser_id,),
            )

        if _pairs(connection):
            raise NBAMergeError(
                "NBA split identities remain after merge"
            )
        duplicates = connection.execute(
            """SELECT COUNT(*) FROM (
                 SELECT espn_id FROM players
                 WHERE league='nba' AND espn_id IS NOT NULL
                 GROUP BY CAST(espn_id AS TEXT) HAVING COUNT(*)>1
               )"""
        ).fetchone()[0]
        if duplicates:
            raise NBAMergeError(
                f"{duplicates} duplicate NBA ESPN IDs remain"
            )
        for table, before in plan["protected"].items():
            after = _fingerprint(connection, table)
            if before != after:
                raise NBAMergeError(
                    f"protected table {table} changed"
                )
        connection.execute(migrate_schema.REGISTRY_SQL)
        connection.execute(
            """INSERT INTO app_schema_migrations(
                 migration_id, checksum
               ) VALUES(?,?)
               ON CONFLICT(migration_id) DO UPDATE SET checksum=excluded.checksum""",
            (MIGRATION_ID, MIGRATION_CHECKSUM),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return backup


def _counts(value: str) -> dict[str, int]:
    output = {}
    for item in str(value or "").split(","):
        if not item.strip():
            continue
        key, separator, raw_count = item.partition("=")
        if not separator:
            raise argparse.ArgumentTypeError(
                "counts must look like player_stats=264"
            )
        output[key.strip()] = int(raw_count)
    return dict(sorted(output.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-pairs", type=int)
    parser.add_argument("--expect-moved", type=_counts)
    arguments = parser.parse_args()
    try:
        plan = build_plan(arguments.db)
        print(
            f"NBA identity bridge: {plan['pair_count']} split pairs; "
            f"moved rows={plan['moved']}"
        )
        if arguments.plan:
            return 0
        if arguments.expect_pairs is None or arguments.expect_moved is None:
            raise NBAMergeError(
                "--apply requires --expect-pairs and --expect-moved"
            )
        backup = apply_plan(
            arguments.db,
            plan,
            expected_pairs=arguments.expect_pairs,
            expected_moved=arguments.expect_moved,
        )
        print(f"backup: {backup} (quick_check=ok)")
        return 0
    except (NBAMergeError, sqlite3.Error, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
