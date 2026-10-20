#!/usr/bin/env python3
"""Promote verified tennis match stat overrides from dev to production.

The promotion is additive. It validates each override against a final scoreboard
row in both databases, keeps the source provenance, and refuses to replace a
conflicting production value.

Run from the repository root:
    python3 backend/promote_tennis_match_stats.py                 # preview
    python3 backend/promote_tennis_match_stats.py --apply          # promote
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "data" / "picks.dev.db"
DEFAULT_TARGET = HERE / "data" / "picks.db"
OVERRIDE_COLUMNS = (
    "league", "game_date", "game_id", "home_aces", "away_aces",
    "source", "source_url", "verified_at",
)


class PromotionError(RuntimeError):
    pass


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{quote(str(path), safe='/')}?mode=ro", uri=True, timeout=30,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))


def _scoreboard_is_final(
    connection: sqlite3.Connection, row: sqlite3.Row,
) -> bool:
    match = connection.execute(
        "SELECT state FROM scoreboard_snapshots "
        "WHERE league=? AND game_date=? AND game_id=?",
        (row["league"], row["game_date"], row["game_id"]),
    ).fetchone()
    return match is not None and str(match["state"] or "").lower() == "post"


def _read_source(path: Path) -> list[sqlite3.Row]:
    with _open_read_only(path) as connection:
        if _columns(connection, "tennis_match_stats_overrides") != OVERRIDE_COLUMNS:
            raise PromotionError("source tennis override table has an unexpected schema")
        rows = connection.execute(
            "SELECT league,game_date,game_id,home_aces,away_aces,source,source_url,verified_at "
            "FROM tennis_match_stats_overrides ORDER BY game_date,league,game_id"
        ).fetchall()
        if not rows:
            raise PromotionError("source contains no tennis match stat overrides")
        for row in rows:
            if row["league"] not in ("atp", "wta"):
                raise PromotionError(f"unsupported tour in source row {row['game_id']}")
            if any(not isinstance(row[key], int) or row[key] < 0 for key in ("home_aces", "away_aces")):
                raise PromotionError(f"invalid aces count in source row {row['game_id']}")
            if not row["source"] or not str(row["source_url"] or "").startswith("https://") or not row["verified_at"]:
                raise PromotionError(f"source provenance is incomplete for row {row['game_id']}")
            if not _scoreboard_is_final(connection, row):
                raise PromotionError(f"source row {row['game_id']} has no matching final scoreboard")
    return rows


def _plan(source: Path, target: Path, rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if source.resolve() == target.resolve():
        raise PromotionError("source and target databases must be different")
    with _open_read_only(target) as connection:
        if _columns(connection, "tennis_match_stats_overrides") != OVERRIDE_COLUMNS:
            raise PromotionError("production tennis override table has an unexpected schema")
        missing = []
        already_present = []
        for row in rows:
            if not _scoreboard_is_final(connection, row):
                raise PromotionError(f"production has no matching final scoreboard for row {row['game_id']}")
            existing = connection.execute(
                "SELECT league,game_date,game_id,home_aces,away_aces,source,source_url,verified_at "
                "FROM tennis_match_stats_overrides WHERE league=? AND game_date=? AND game_id=?",
                (row["league"], row["game_date"], row["game_id"]),
            ).fetchone()
            if existing is None:
                missing.append(row)
            elif tuple(existing) == tuple(row):
                already_present.append(row)
            else:
                raise PromotionError(
                    f"conflicting production override for {row['league']} {row['game_id']}; refusing to overwrite"
                )
    return missing, already_present


def promote(source: Path, target: Path, apply: bool) -> tuple[int, int, Path | None]:
    for path in (source, target):
        if not path.is_file():
            raise PromotionError(f"database file does not exist: {path}")
    rows = _read_source(source)
    missing, already_present = _plan(source, target, rows)
    print(f"source overrides: {len(rows)}; production already has: {len(already_present)}; to add: {len(missing)}")
    for row in rows:
        print(
            f"  {row['game_date']} {row['league']} {row['game_id']}: "
            f"{row['home_aces']}-{row['away_aces']} aces ({row['source']})"
        )
    if not apply:
        print("check only; production was not changed. Pass --apply to promote.")
        return len(missing), len(already_present), None
    if not missing:
        print("production already matches the verified source rows")
        return 0, len(already_present), None

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = target.with_name(f"{target.name}.bak-premigrate-tennis-stats-{timestamp}")
    with sqlite3.connect(target, timeout=60) as connection:
        connection.execute("PRAGMA busy_timeout=60000")
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for row in missing:
                connection.execute(
                    "INSERT INTO tennis_match_stats_overrides "
                    "(league,game_date,game_id,home_aces,away_aces,source,source_url,verified_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    tuple(row),
                )
            for row in rows:
                actual = connection.execute(
                    "SELECT league,game_date,game_id,home_aces,away_aces,source,source_url,verified_at "
                    "FROM tennis_match_stats_overrides WHERE league=? AND game_date=? AND game_id=?",
                    (row["league"], row["game_date"], row["game_id"]),
                ).fetchone()
                if actual is None or tuple(actual) != tuple(row):
                    raise PromotionError(f"post-write verification failed for {row['league']} {row['game_id']}")
            connection.commit()
        except Exception:
            connection.rollback()
            print(f"promotion rolled back; production backup is at {backup_path}", file=sys.stderr)
            raise
    print(f"backed up production to {backup_path}")
    print(f"promoted and verified {len(missing)} tennis match stat overrides")
    return len(missing), len(already_present), backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--apply", action="store_true", help="write validated missing rows to production")
    args = parser.parse_args()
    try:
        promote(args.source, args.target, args.apply)
    except (OSError, sqlite3.Error, PromotionError) as exc:
        print(f"tennis stats promotion failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
