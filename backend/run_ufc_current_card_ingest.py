#!/usr/bin/env python3
"""Scheduled production runner for current-card UFCStats fight history.

The complete UFCStats plan is fetched before any production write. If changes exist,
the runner creates and integrity-checks a timestamped backup beside the database,
then applies one short additive transaction. Backups are never deleted here.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from typing import Callable, Optional

import sqlite3

import history_refresh_common as common
import ingest_ufc_fight_stats as ingest
from ingest_ufc_fight_stats import roster
from ingest_ufc_fight_stats.ufcstats_pipeline import (
    apply_ufcstats_plan,
    build_ufcstats_plan,
    load_ufcstats_state,
)
from ingest_ufc_fight_stats.ufcstats_source import UfcStatsClient
from migrate_ufcstats_history import inspect as inspect_ufcstats_migration



def _connect_readonly(db_path: str):
    """A read-only handle for planning. The plan is built before any write, as with the
    fight-stats plan: nothing is mutated until we know the whole shape of the change."""
    return common.read_only_connection(db_path)


def run(
    db_path: str,
    now: Optional[dt.datetime] = None,
    emit: Callable[[str], None] = print,
    apply: bool = True,
) -> dict:
    now = now or dt.datetime.now()

    # Harvest the spine from the published card BEFORE choosing targets, because
    # `load_targets` reads its work set from `players` and therefore cannot see a fighter
    # it has no row for. Measured 2026-08-24: ESPN's next 21 days named 94 scheduled
    # fighters, all 94 carrying an athlete id, 93 of them absent from the prod spine.
    # Harvesting first means a debut fighter is a target on the same run that discovers
    # them rather than the run after.
    harvest = roster.build_harvest_plan(
        _connect_readonly(db_path),
        today=now.date(),
        lookback_days=14,
        lookahead_days=21,
        emit=emit,
    )
    harvest_backup = None
    if harvest.mutations and apply:
        # A second backup on the same run, accepted deliberately: after the initial
        # catch-up a card window introduces a handful of fighters a week, so this is rare,
        # and a spine write without a restore point is not.
        harvest_backup = common.backup_database(db_path, "ufc-roster", now=now)
        con = sqlite3.connect(db_path)
        try:
            with con:
                inserted = roster.apply_harvest(con, harvest)
        finally:
            con.close()
        emit("  harvested {} new UFC fighters from the card".format(inserted))
    elif harvest.mutations:
        emit("  dry run: {} new UFC fighters would be harvested".format(harvest.mutations))

    migration = inspect_ufcstats_migration(db_path)
    if migration["state"] != "applied":
        raise RuntimeError(
            "UFCStats history migration is {}: {}".format(
                migration["state"], migration["detail"]
            )
        )

    targets, accepted, stored, owners, existing = load_ufcstats_state(
        db_path,
        now.date(),
        lookback_days=0,
        lookahead_days=0,
    )
    if not targets:
        emit("No UFC fighters in the current-card window; nothing to do")
        return {"status": "no_targets"}

    archive_dir = os.path.join(os.path.dirname(db_path), "ufcstats-archive")
    plan = build_ufcstats_plan(
        targets,
        accepted,
        stored,
        owners,
        existing,
        UfcStatsClient(archive_dir),
        limit=5,
        emit=emit,
    )
    if plan.source_errors or plan.conflicts or plan.unresolved:
        # Name them. "19 source errors" with no names is unactionable: on 2026-08-24 the
        # only way to learn that all 49 were `scoreboard_unavailable:HTTPError`, i.e. ESPN
        # returning 403, was to rebuild the plan in-process by hand. A count is a claim
        # ABOUT a failure, not the failure.
        for item in plan.source_errors:
            emit("  SOURCE ERROR {}".format(item))
        for item in plan.conflicts:
            emit("  CONFLICT {}".format(item))
        for item in plan.unresolved:
            emit("  UNRESOLVED {}".format(item))
        raise RuntimeError(
            "UFCStats plan failed: {} source errors, {} conflicts, {} unresolved".format(
                len(plan.source_errors), len(plan.conflicts), len(plan.unresolved)
            )
        )
    mutations = (
        len(plan.inserts)
        + len(plan.updates)
        + len(plan.mappings)
    )
    if mutations == 0:
        emit(
            "UFCStats current-card history is current; {} existing logs retained".format(
                plan.existing_count
            )
        )
        return {
            "status": "current",
            "existing_logs": plan.existing_count,
            "no_history": len(plan.no_history),
        }

    if not apply:
        emit(
            "UFCStats dry run: {} inserts, {} updates, {} mappings would be applied".format(
                len(plan.inserts),
                len(plan.updates),
                len(plan.mappings),
            )
        )
        return {
            "status": "dry_run",
            "logs": len(plan.inserts),
            "updates": len(plan.updates),
            "source_mappings": len(plan.mappings),
            "no_history": len(plan.no_history),
        }

    backup_path = common.backup_database(db_path, "ufc-timer", now=now)
    result = apply_ufcstats_plan(db_path, plan)
    emit(
        "Applied UFCStats timer plan: {} logs, {} updates, {} source mappings".format(
            result["inserted_logs"],
            result["updated_logs"],
            result["mappings_inserted"],
        )
    )
    return {
        "status": "applied",
        "backup": backup_path,
        "harvest_backup": harvest_backup,
        "harvested": len(harvest.new),
        "no_history": len(plan.no_history),
        **result,
    }


def main() -> int:
    db_path = os.environ.get("LP_DB_PATH") or ingest.DB
    if not os.path.isfile(db_path) or os.path.getsize(db_path) <= 0:
        print("ERROR: database is missing or empty: {}".format(db_path))
        return 2
    try:
        run(db_path)
    except Exception as exc:
        print("ERROR: {}: {}".format(type(exc).__name__, str(exc)))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
