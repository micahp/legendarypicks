#!/usr/bin/env python3
"""ingest_ufc_dk_pool.py: capture the current DraftKings MMA pool on a cadence.

RotoWire answers 200 from this box all week. Before this job the only thing that
ever asked it was a page view, so the pool existed only while someone was
looking at it, and a publisher blip at that moment emptied the board.

Writes one row per slate date and nothing else. Dry run by default.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dk_pool_store import DKPoolError, ensure_table, publish  # noqa: E402
from routers.games.ufc_optimizer import build_current_pool  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def refresh(db_path: str, *, apply: bool = False, now=None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    payload = build_current_pool(now=now)
    if not payload.get("slate"):
        # No unlocked Classic pool is a real publisher answer, not a failure.
        return {"status": "no_pool", "reason": payload.get("reason")}

    summary = {
        "status": "published" if apply else "ready",
        "slate_date": payload["slate"]["slateDate"],
        "lock_at": payload["slate"]["lockAt"],
        "fights": payload["slate"]["fightCount"],
        "fighters": len(payload["slate"]["fighters"]),
        "excluded_cancelled_fights": payload.get("excluded_cancelled_fights"),
        "excluded_unpriced_fights": payload.get("excluded_unpriced_fights"),
        "excluded_unmatched_fighters": payload.get("excluded_unmatched_fighters"),
        "excluded_unavailable_fighters": payload.get("excluded_unavailable_fighters"),
    }
    if not apply:
        return summary

    captured_at = now.isoformat()
    connection = sqlite3.connect(db_path, timeout=60, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    ensure_table(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        publish(connection, payload, captured_at=captured_at)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    summary["captured_at"] = captured_at
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = refresh(os.path.abspath(args.db), apply=args.apply)
    except (DKPoolError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    if not args.apply:
        print("DRY RUN -- nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
