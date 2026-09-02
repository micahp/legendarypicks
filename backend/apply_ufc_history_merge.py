#!/usr/bin/env python3
"""Apply one previously counted UFC dev-history merge in a short transaction.

This companion to ``plan_ufc_history_merge.py`` requires:

* a non-empty, integrity-checked production backup;
* exact expected insert and collision counts from the dry run;
* identity-clean, valid source data.

Network access is never used. Both source databases are read and the complete
row set is materialized before the production write transaction begins.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from contextlib import closing
from typing import Dict, Optional, Sequence

from history_refresh_common import BUSY_TIMEOUT_SECONDS, ROLLBACK_SAFE_JOURNAL_MODES

from plan_ufc_history_merge import (
    DEFAULT_DEV,
    DEFAULT_PROD,
    IdentityAction,
    MergePlan,
    _integrity,
    _name_key,
    _ro_connection,
    build_merge_plan,
)


def _resolve_identity(
    con: sqlite3.Connection,
    action: IdentityAction,
    counts: Dict[str, int],
) -> int:
    by_espn = con.execute(
        "SELECT id,name FROM players WHERE league='ufc' AND espn_id=?",
        (action.athlete_id,),
    ).fetchone()
    if by_espn is not None:
        if action.prod_player_id is not None and int(by_espn["id"]) != action.prod_player_id:
            raise RuntimeError(
                "ESPN {} changed production owner".format(action.athlete_id)
            )
        return int(by_espn["id"])

    players = con.execute(
        "SELECT id,name,espn_id FROM players WHERE league='ufc'"
    ).fetchall()
    name_matches = [
        row for row in players if _name_key(row["name"]) == _name_key(action.name)
    ]
    if len(name_matches) > 1:
        raise RuntimeError(
            "{} now has multiple production name matches".format(action.name)
        )
    if len(name_matches) == 1:
        row = name_matches[0]
        current = str(row["espn_id"] or "").strip()
        if current and current != action.athlete_id:
            raise RuntimeError(
                "{} now owns conflicting ESPN {}".format(action.name, current)
            )
        if action.prod_player_id is not None and int(row["id"]) != action.prod_player_id:
            raise RuntimeError(
                "{} changed production player id".format(action.name)
            )
        if not current:
            cursor = con.execute(
                """
                UPDATE players SET espn_id=?
                WHERE id=? AND league='ufc' AND NULLIF(espn_id,'') IS NULL
                """,
                (action.athlete_id, row["id"]),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "failed to fill ESPN identity for {}".format(action.name)
                )
            counts["identity_fills"] += 1
        return int(row["id"])

    if action.action != "create_player":
        raise RuntimeError(
            "production fighter disappeared before apply: {}".format(action.name)
        )
    cursor = con.execute(
        """
        INSERT INTO players(name,team,league,espn_id,active)
        VALUES(?,NULL,'ufc',?,1)
        """,
        (action.name, action.athlete_id),
    )
    counts["players_created"] += 1
    return int(cursor.lastrowid)


def apply_merge_plan(prod_path: str, plan: MergePlan) -> dict:
    """Apply the already materialized plan; no reads from dev or the network."""
    if plan.identity_conflicts or plan.invalid_source_rows:
        raise RuntimeError("refusing apply: source/identity validation failed")

    con = sqlite3.connect(prod_path, timeout=BUSY_TIMEOUT_SECONDS)
    con.row_factory = sqlite3.Row
    counts = {
        "identity_fills": 0,
        "players_created": 0,
        "logs_inserted": 0,
    }
    try:
        journal_mode = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode not in ROLLBACK_SAFE_JOURNAL_MODES:
            raise RuntimeError(
                "production journal_mode is {}, expected one of {}".format(
                    journal_mode, sorted(ROLLBACK_SAFE_JOURNAL_MODES)
                )
            )
        con.execute("BEGIN IMMEDIATE")

        prod_ids: Dict[str, int] = {}
        for athlete_id, action in sorted(plan.identity_actions.items()):
            prod_ids[athlete_id] = _resolve_identity(con, action, counts)

        before = con.total_changes
        con.executemany(
            """
            INSERT OR IGNORE INTO player_game_logs
              (player_id,league,season,game_no,game_id,game_date,team,opponent,
               home_away,stats,source,source_player_key,ingested_at)
            VALUES(?,'ufc',?,?,?,?,?,?,?,?,?,?,COALESCE(?,datetime('now')))
            """,
            [
                (
                    prod_ids[row.athlete_id],
                    row.season,
                    row.game_no,
                    row.game_id,
                    row.game_date,
                    row.team,
                    row.opponent,
                    row.home_away,
                    row.stats,
                    row.source,
                    row.athlete_id,
                    row.ingested_at,
                )
                for row in plan.planned_logs
            ],
        )
        counts["logs_inserted"] = con.total_changes - before
        if counts["logs_inserted"] != len(plan.planned_logs):
            raise RuntimeError(
                "planned {} inserts but SQLite inserted {}; rolling back".format(
                    len(plan.planned_logs), counts["logs_inserted"]
                )
            )
        if counts["identity_fills"] != len(plan.identity_fills):
            raise RuntimeError(
                "planned {} identity fills but applied {}; rolling back".format(
                    len(plan.identity_fills), counts["identity_fills"]
                )
            )
        if counts["players_created"] != len(plan.new_players):
            raise RuntimeError(
                "planned {} new players but created {}; rolling back".format(
                    len(plan.new_players), counts["players_created"]
                )
            )
        con.commit()
        return counts
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _non_negative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply a guarded additive UFC history merge from dev"
    )
    parser.add_argument("--prod-db", default=DEFAULT_PROD)
    parser.add_argument("--dev-db", default=DEFAULT_DEV)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--expect-inserts", type=_non_negative, required=True)
    parser.add_argument("--expect-collisions", type=_non_negative, required=True)
    args = parser.parse_args(argv)

    prod_path = os.path.abspath(args.prod_db)
    dev_path = os.path.abspath(args.dev_db)
    backup_path = os.path.abspath(args.backup)
    if len({prod_path, dev_path, backup_path}) != 3:
        parser.error("prod, dev, and backup paths must all differ")
    for label, path in (
        ("prod", prod_path),
        ("dev", dev_path),
        ("backup", backup_path),
    ):
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            parser.error("{} database is missing or empty: {}".format(label, path))

    with closing(_ro_connection(prod_path)) as prod_con, closing(
        _ro_connection(dev_path)
    ) as dev_con, closing(_ro_connection(backup_path)) as backup_con:
        prod_integrity = _integrity(prod_con)
        dev_integrity = _integrity(dev_con)
        backup_integrity = _integrity(backup_con)
        plan = build_merge_plan(prod_con, dev_con)

    for label, result in (
        ("prod", prod_integrity),
        ("dev", dev_integrity),
        ("backup", backup_integrity),
    ):
        if result != "ok":
            print("ABORTED: {} integrity_check returned {}".format(label, result))
            return 2
    actual_inserts = len(plan.planned_logs)
    actual_collisions = len(plan.skipped_collisions)
    if actual_inserts != args.expect_inserts:
        print(
            "ABORTED: expected {} inserts, current plan has {}".format(
                args.expect_inserts, actual_inserts
            )
        )
        return 2
    if actual_collisions != args.expect_collisions:
        print(
            "ABORTED: expected {} collisions, current plan has {}".format(
                args.expect_collisions, actual_collisions
            )
        )
        return 2
    if plan.identity_conflicts or plan.invalid_source_rows:
        print("ABORTED: merge plan has identity conflicts or invalid rows")
        return 2

    result = apply_merge_plan(prod_path, plan)
    print(
        "Applied UFC history merge: {logs_inserted} logs, {identity_fills} identity "
        "fills, {players_created} durable players".format(**result)
    )
    print(
        "Skipped collisions: {} (production values preserved)".format(
            len(plan.skipped_collisions)
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
