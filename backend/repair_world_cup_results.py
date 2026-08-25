#!/usr/bin/env python3
"""Repair legacy World Cup NULL placeholders from durable player game logs.

Dry-run is the default. ``--apply`` updates only existing World Cup result rows
whose actual and verdict are both NULL. Rows with one unique numeric player log
become graded outcomes; rows with no participant log remain explicit voids.
"""
import os
import sqlite3
import sys

from settlement.wc_settle import _settle_wc_props, _wc_actual


DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def repair(con: sqlite3.Connection, apply: bool = False) -> dict:
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT p.id, p.game_id, p.player_id, p.market, p.line, p.side,
               pg.espn_event_id
        FROM prop_results pr
        JOIN props p ON p.id=pr.prop_id
        JOIN prop_games pg ON pg.id=p.game_id
        WHERE pg.league='wc' AND pr.actual_value IS NULL AND pr.hit IS NULL
        ORDER BY p.id
    """).fetchall()
    gradeable = []
    reasons = {}
    for row in rows:
        actual, reason = _wc_actual(
            con, row["espn_event_id"], row["player_id"], row["market"])
        if actual is not None:
            gradeable.append(row)
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
    result = {
        "legacy_null_rows": len(rows),
        "gradeable": len(gradeable),
        "retained_voids": reasons.get("no_player_log", 0),
        "other_unresolved": len(rows) - len(gradeable) - reasons.get("no_player_log", 0),
        "updated": 0,
        "errors": 0,
    }
    if apply and gradeable:
        by_event = {}
        for row in gradeable:
            by_event.setdefault(row["espn_event_id"], []).append(row)
        for event_id, props in by_event.items():
            settled = _settle_wc_props(con, event_id, props, overwrite=True)
            result["updated"] += settled["settled"]
            result["errors"] += settled["errors"]
    return result


def main() -> int:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    result = repair(con, apply=apply)
    con.close()
    print("World Cup legacy result repair" + (" [APPLY]" if apply else " [DRY RUN]"))
    for key, value in result.items():
        print(f"  {key}: {value}")
    if result["other_unresolved"] or result["errors"]:
        print("  REFUSING success: unresolved rows are not proven voids", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
