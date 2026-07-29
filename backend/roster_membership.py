#!/usr/bin/env python3
"""Versioned canonical roster membership snapshots.

``players`` owns durable person identity.  These tables own time-varying team
membership and retain the exact normalized source population that was
published.  A caller must resolve the complete population before publishing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime


ROSTER_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS roster_snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  league TEXT NOT NULL,
  season INTEGER NOT NULL,
  source TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  published_at TEXT NOT NULL,
  source_checksum TEXT NOT NULL,
  source_payload TEXT NOT NULL,
  team_count INTEGER NOT NULL,
  player_count INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('published','superseded'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_roster_snapshots_current
  ON roster_snapshots(league) WHERE status='published';
CREATE INDEX IF NOT EXISTS idx_roster_snapshots_history
  ON roster_snapshots(league, captured_at DESC);
CREATE TABLE IF NOT EXISTS roster_memberships(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id INTEGER NOT NULL REFERENCES roster_snapshots(id),
  player_id INTEGER NOT NULL REFERENCES players(id),
  source_player_key TEXT NOT NULL,
  team TEXT NOT NULL,
  position TEXT,
  jersey TEXT,
  roster_status TEXT NOT NULL DEFAULT 'active',
  display_name TEXT NOT NULL,
  UNIQUE(snapshot_id, player_id),
  UNIQUE(snapshot_id, source_player_key)
);
CREATE INDEX IF NOT EXISTS idx_roster_memberships_player
  ON roster_memberships(player_id, snapshot_id);
""".strip()


class RosterContractError(ValueError):
    """A roster population cannot be safely published."""


def create_roster_schema(connection: sqlite3.Connection) -> None:
    """Create the schema for a fresh DB or explicit migration."""
    # sqlite3.executescript() implicitly commits pending work. Execute each DDL
    # statement separately so schema creation can participate in the caller's
    # atomic roster publication transaction.
    for statement in ROSTER_SCHEMA_SQL.split(";"):
        if statement.strip():
            connection.execute(statement)


def roster_schema_issues(connection: sqlite3.Connection) -> list[str]:
    """Return missing contract pieces without mutating the database."""
    expected = {
        "roster_snapshots": {
            "id", "league", "season", "source", "captured_at",
            "published_at", "source_checksum", "source_payload",
            "team_count", "player_count", "status",
        },
        "roster_memberships": {
            "id", "snapshot_id", "player_id", "source_player_key",
            "team", "position", "jersey", "roster_status", "display_name",
        },
    }
    issues = []
    for table, required_columns in expected.items():
        exists = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name=?""",
            (table,),
        ).fetchone()
        if not exists:
            issues.append(f"missing table {table}")
            continue
        columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        missing = sorted(required_columns - columns)
        if missing:
            issues.append(
                f"{table} missing columns: " + ", ".join(missing)
            )
    for index in (
        "idx_roster_snapshots_current",
        "idx_roster_snapshots_history",
        "idx_roster_memberships_player",
    ):
        exists = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='index' AND name=?""",
            (index,),
        ).fetchone()
        if not exists:
            issues.append(f"missing index {index}")
    current_index = connection.execute(
        """SELECT sql FROM sqlite_master
           WHERE type='index' AND name='idx_roster_snapshots_current'"""
    ).fetchone()
    if current_index:
        normalized_sql = "".join(
            str(current_index[0] or "").lower().split()
        )
        if (
            "createuniqueindex" not in normalized_sql
            or "wherestatus='published'" not in normalized_sql
        ):
            issues.append(
                "idx_roster_snapshots_current is not the required "
                "partial unique index"
            )
    membership_exists = connection.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='roster_memberships'"""
    ).fetchone()
    if membership_exists:
        foreign_keys = {
            (str(row[3]), str(row[2]), str(row[4]))
            for row in connection.execute(
                "PRAGMA foreign_key_list(roster_memberships)"
            )
        }
        for required in (
            ("snapshot_id", "roster_snapshots", "id"),
            ("player_id", "players", "id"),
        ):
            if required not in foreign_keys:
                issues.append(
                    "roster_memberships missing foreign key "
                    + " -> ".join(required)
                )

        unique_keys = set()
        for index_row in connection.execute(
            "PRAGMA index_list(roster_memberships)"
        ):
            if not bool(index_row[2]):
                continue
            unique_keys.add(
                tuple(
                    str(column[2])
                    for column in connection.execute(
                        "PRAGMA index_info("
                        + "'"
                        + str(index_row[1]).replace("'", "''")
                        + "')"
                    )
                )
            )
        for required in (
            ("snapshot_id", "player_id"),
            ("snapshot_id", "source_player_key"),
        ):
            if required not in unique_keys:
                issues.append(
                    "roster_memberships missing unique key "
                    + ", ".join(required)
                )
    return issues


def require_roster_schema(connection: sqlite3.Connection) -> None:
    issues = roster_schema_issues(connection)
    if issues:
        raise RosterContractError(
            "canonical roster schema is not migrated: "
            + "; ".join(issues)
        )


def normalized_source_payload(
    league: str, rosters: Mapping[str, Sequence[Mapping[str, object]]]
) -> str:
    """Return stable JSON representing the complete normalized source input."""
    rows = []
    for team in sorted(rosters):
        for player in rosters[team]:
            rows.append(
                {
                    "league": league,
                    "team": team,
                    "source_player_key": str(
                        player.get("player_id") or ""
                    ),
                    "name": str(player.get("name") or ""),
                    "position": player.get("position"),
                    "jersey": player.get("jersey"),
                }
            )
    rows.sort(
        key=lambda row: (
            row["team"], row["source_player_key"], row["name"]
        )
    )
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def source_checksum(source_payload: str) -> str:
    return hashlib.sha256(source_payload.encode("utf-8")).hexdigest()


def roster_season(league: str, captured_at: str) -> int:
    """Return the conventional season ending year for a capture timestamp."""
    captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    normalized_league = str(league).lower()
    if normalized_league in ("nba", "nhl") and captured.month >= 8:
        return captured.year + 1
    return captured.year


def publish_roster_snapshot(
    connection: sqlite3.Connection,
    *,
    league: str,
    season: int,
    source: str,
    captured_at: str,
    source_payload: str,
    team_count: int,
    memberships: Sequence[Mapping[str, object]],
) -> int:
    """Publish a fully resolved roster within the caller's transaction."""
    normalized_league = str(league or "").strip().lower()
    if not normalized_league or team_count <= 0 or not memberships:
        raise RosterContractError("roster snapshot population is empty")

    source_keys = [str(row["source_player_key"]) for row in memberships]
    player_ids = [int(row["player_id"]) for row in memberships]
    if len(set(source_keys)) != len(source_keys):
        raise RosterContractError(
            "roster snapshot has duplicate source player IDs"
        )
    if len(set(player_ids)) != len(player_ids):
        raise RosterContractError(
            "roster snapshot has duplicate canonical player IDs"
        )
    teams = {str(row["team"]) for row in memberships}
    if len(teams) != int(team_count):
        raise RosterContractError(
            f"roster snapshot has {len(teams)} represented teams, "
            f"expected {team_count}"
        )

    placeholders = ",".join("?" for _ in player_ids)
    owners = connection.execute(
        f"""SELECT id,league FROM players
            WHERE id IN ({placeholders})""",
        player_ids,
    ).fetchall()
    owner_leagues = {
        int(row["id"]): str(row["league"]).lower() for row in owners
    }
    wrong = [
        player_id
        for player_id in player_ids
        if owner_leagues.get(player_id) != normalized_league
    ]
    if wrong:
        raise RosterContractError(
            "roster membership has missing or wrong-league canonical IDs: "
            + ", ".join(str(value) for value in wrong[:10])
        )

    require_roster_schema(connection)
    checksum = source_checksum(source_payload)
    connection.execute(
        """UPDATE roster_snapshots SET status='superseded'
           WHERE league=? AND status='published'""",
        (normalized_league,),
    )
    cursor = connection.execute(
        """INSERT INTO roster_snapshots(
             league,season,source,captured_at,published_at,
             source_checksum,source_payload,team_count,player_count,status
           ) VALUES(?,?,?,?,?,?,?,?,?,'published')""",
        (
            normalized_league,
            int(season),
            source,
            captured_at,
            captured_at,
            checksum,
            source_payload,
            int(team_count),
            len(memberships),
        ),
    )
    snapshot_id = int(cursor.lastrowid)
    connection.executemany(
        """INSERT INTO roster_memberships(
             snapshot_id,player_id,source_player_key,team,position,
             jersey,roster_status,display_name
           ) VALUES(?,?,?,?,?,?,?,?)""",
        [
            (
                snapshot_id,
                int(row["player_id"]),
                str(row["source_player_key"]),
                str(row["team"]),
                row.get("position"),
                row.get("jersey"),
                str(row.get("roster_status") or "active"),
                str(row["display_name"]),
            )
            for row in memberships
        ],
    )
    return snapshot_id
