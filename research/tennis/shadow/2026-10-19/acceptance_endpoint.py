#!/usr/bin/env python3
"""End-to-end write check: the tennis endpoint, on a copy of the database, inside the real pre-match window.

Copies the source database (backup API, source read-only). Then calls routers.games.misc.tennis_model for one slate
with the clock set to a time inside the lock window for each match. The served projection, the odds lookup and the
identities are the real code paths. Only the clock is set, because the real clock is not in the window for these
matches. The copy is then checked: every row that existed before the call is unchanged, and a second call adds nothing.
  python3 -I research/tennis/shadow/2026-10-19/acceptance_endpoint.py --source <DB, read-only> \
      --copy <scratch path> --date 2026-10-20 --tour wta --now 2026-10-20T04:30:00+00:00 --out <json>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE))
import sqlite3  # noqa: E402

import tennis_daily_projections as projections  # noqa: E402
from routers.games import misc  # noqa: E402
from acceptance_write import copy_database  # noqa: E402

NOW = None


class FrozenDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def open_copy(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def snapshot(path: str, table: str) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return [tuple(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3")]
    finally:
        con.close()


def main() -> int:
    global NOW
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--copy", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--tour", required=True, choices=("atp", "wta"))
    parser.add_argument("--now", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    NOW = dt.datetime.fromisoformat(args.now)
    copy_database(args.source, args.copy)
    locks_before = snapshot(args.copy, "tennis_model_locks")
    real_datetime = dt.datetime
    misc.dt.datetime = FrozenDateTime
    misc._db = lambda: open_copy(args.copy)
    try:
        first = misc.tennis_model(date=args.date, tour=args.tour, utc_offset_minutes=0, winner_model="page")
        locks_after_first = snapshot(args.copy, "tennis_model_locks")
        shadow_after_first = snapshot(args.copy, "tennis_shadow_locks")
        second = misc.tennis_model(date=args.date, tour=args.tour, utc_offset_minutes=0, winner_model="page")
        locks_after_second = snapshot(args.copy, "tennis_model_locks")
        shadow_after_second = snapshot(args.copy, "tennis_shadow_locks")
    finally:
        misc.dt.datetime = real_datetime
    existing_unchanged = all(row in locks_after_first for row in locks_before)
    result = {
        "now": NOW.isoformat(), "date": args.date, "tour": args.tour,
        "served_rows_before": len(locks_before), "served_rows_after_first": len(locks_after_first),
        "served_rows_after_second": len(locks_after_second),
        "pre_existing_served_rows_unchanged": existing_unchanged,
        "shadow_rows_after_first": len(shadow_after_first), "shadow_rows_after_second": len(shadow_after_second),
        "second_call_added_rows": (len(locks_after_second) - len(locks_after_first))
                                  + (len(shadow_after_second) - len(shadow_after_first)),
        "matches": [],
    }
    for match in first["matches"]:
        game_id = match["gameId"]
        served = [row for row in locks_after_first if row[2] == game_id]
        shadow_rows = [row for row in shadow_after_first if row[1] == game_id]
        result["matches"].append({
            "game_id": game_id, "event": match.get("event"), "home": match["home"], "away": match["away"],
            "served": [{"model_version": row[6], "locked_at": row[4], "probability": json.loads(row[5]).get("probability")}
                       for row in served],
            "shadow": [{"model_version": row[2], "status": row[6], "locked_at": row[5],
                        "probability": json.loads(row[7]).get("probability"),
                        "surface": json.loads(row[7]).get("surface"),
                        "surface_source": json.loads(row[7]).get("surfaceSource")} for row in shadow_rows],
        })
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n")
    print({k: v for k, v in result.items() if k != "matches"})
    for match in result["matches"]:
        print(match["game_id"], match["event"], "served", [s["model_version"] for s in match["served"]],
              "shadow", [(s["model_version"], round(s["probability"], 6), s["surface_source"]) for s in match["shadow"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
