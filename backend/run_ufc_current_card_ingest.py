#!/usr/bin/env python3
"""Scheduled production runner for incremental UFC current-card statistics.

The complete ESPN plan is fetched before any production write. If changes exist,
the runner creates and integrity-checks a timestamped backup beside the database,
then applies one short additive transaction. Backups are never deleted here.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from typing import Callable, Optional

import history_refresh_common as common
import ingest_ufc_fight_stats as ingest


def run(
    db_path: str,
    now: Optional[dt.datetime] = None,
    emit: Callable[[str], None] = print,
    apply: bool = True,
) -> dict:
    now = now or dt.datetime.now()
    targets, existing_keys, owners = ingest.load_targets(
        db_path,
        now.date(),
        lookback_days=14,
        lookahead_days=21,
    )
    if not targets:
        emit("No UFC fighters in the current-card window; nothing to do")
        return {"status": "no_targets"}

    plan = ingest.build_current_card_plan(
        targets, existing_keys, owners, emit=emit
    )
    if plan.source_errors or plan.conflicts:
        # Name them. "19 source errors" with no names is unactionable: on 2026-08-24 the
        # only way to learn that all 49 were `scoreboard_unavailable:HTTPError`, i.e. ESPN
        # returning 403, was to rebuild the plan in-process by hand. A count is a claim
        # ABOUT a failure, not the failure.
        for item in plan.source_errors:
            emit("  SOURCE ERROR {}".format(item))
        for item in plan.conflicts:
            emit("  CONFLICT {}".format(item))
        raise RuntimeError(
            "UFC plan failed: {} source errors, {} conflicts".format(
                len(plan.source_errors), len(plan.conflicts)
            )
        )
    mutations = (
        len(plan.logs)
        + len(plan.identity_updates)
        + len(plan.game_links)
    )
    if mutations == 0:
        emit(
            "UFC current-card plan is current; {} existing logs retained".format(
                plan.existing_count
            )
        )
        return {
            "status": "current",
            "existing_logs": plan.existing_count,
            "unresolved": len(plan.unresolved),
        }

    if not apply:
        emit(
            "UFC dry run: {} logs, {} identities, {} links would be applied".format(
                len(plan.logs),
                len(plan.identity_updates),
                len(plan.game_links),
            )
        )
        return {
            "status": "dry_run",
            "logs": len(plan.logs),
            "identity_updates": len(plan.identity_updates),
            "game_links": len(plan.game_links),
            "unresolved": len(plan.unresolved),
        }

    backup_path = common.backup_database(db_path, "ufc-timer", now=now)
    result = ingest.apply_plan(db_path, plan)
    emit(
        "Applied UFC timer plan: {} logs, {} identities, {} links".format(
            result["inserted_logs"],
            result["identity_updates"],
            result["game_links"],
        )
    )
    return {
        "status": "applied",
        "backup": backup_path,
        "unresolved": len(plan.unresolved),
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
