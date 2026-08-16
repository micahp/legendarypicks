#!/usr/bin/env python3
"""Add `team_game_stats.stats` and backfill it from the frozen stat columns.

Additive and idempotent. Adds the column if missing, then writes a JSON blob per
row from that league's DECLARED keys (team_stats_contract.STAT_FIELDS). No
column is dropped and no existing value is changed, so a rollback is "ignore the
new column" rather than a table rebuild.

    python3 migrate_team_game_stats_to_json.py --db data/picks.dev.db
    python3 migrate_team_game_stats_to_json.py --db data/picks.dev.db --apply

Dry-run by default: it reports what it WOULD write and exits without a
transaction. --apply performs the write.

Refuses a production database unless --i-know-this-is-prod is passed as well.
Prod holds the nba/nfl/nhl rows the deployed backend serves, and the deployed
backend has no reader for this column yet — migrating it early buys nothing and
puts a write on the file the live site reads.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing

from team_stats_schema import all_stat_keys, stat_keys_for

PROD_MARKERS = ("picks.db",)


def _is_prod(path: str) -> bool:
    return os.path.basename(path) in PROD_MARKERS


def _columns(con: sqlite3.Connection) -> set[str]:
    return {r[1] for r in con.execute("PRAGMA table_info(team_game_stats)")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry-run")
    ap.add_argument("--i-know-this-is-prod", action="store_true")
    args = ap.parse_args()

    if _is_prod(args.db) and not args.i_know_this_is_prod:
        print(f"REFUSING: {args.db} looks like PRODUCTION.", file=sys.stderr)
        print("  The deployed backend has no reader for `stats` yet, so this", file=sys.stderr)
        print("  migration would write to the live file for no benefit.", file=sys.stderr)
        print("  Land the readers first. Then --i-know-this-is-prod.", file=sys.stderr)
        return 2

    if not os.path.exists(args.db):
        print(f"no such database: {args.db}", file=sys.stderr)
        return 2

    with closing(sqlite3.connect(args.db)) as con:
        con.row_factory = sqlite3.Row
        cols = _columns(con)
        if not cols:
            print("team_game_stats does not exist in this database", file=sys.stderr)
            return 2

        has_stats = "stats" in cols
        if not has_stats:
            print("column `stats` is MISSING and will be added")
            if args.apply:
                con.execute("ALTER TABLE team_game_stats ADD COLUMN stats TEXT")
                cols = _columns(con)
                has_stats = True

        # A league whose keys are all absent from this database would silently
        # serialise {} for every row. Say so instead.
        present = {k for k in all_stat_keys() if k in cols}
        missing = set(all_stat_keys()) - present
        if missing:
            print(f"note: {len(missing)} declared stat columns absent here: "
                  f"{', '.join(sorted(missing))}")

        rows = con.execute("SELECT * FROM team_game_stats").fetchall()
        by_league: dict[str, list[tuple[str, str, str, str]]] = {}
        unknown: dict[str, int] = {}
        empty: dict[str, int] = {}

        for r in rows:
            lg = (r["league"] or "").lower()
            keys = stat_keys_for(lg)
            if not keys:
                unknown[lg] = unknown.get(lg, 0) + 1
                continue
            payload = {}
            for k in keys:
                if k not in present:
                    continue
                v = r[k]
                if v is not None and v != "":
                    payload[k] = v
            if not payload:
                empty[lg] = empty.get(lg, 0) + 1
                continue
            by_league.setdefault(lg, []).append(
                (json.dumps(payload, separators=(",", ":"), sort_keys=True),
                 r["league"], r["game_id"], r["team_abbrev"])
            )

        print(f"\n{'league':<10}{'rows->json':>12}{'keys/row':>10}")
        total = 0
        for lg in sorted(by_league):
            batch = by_league[lg]
            avg = sum(len(json.loads(b[0])) for b in batch) / len(batch)
            print(f"{lg:<10}{len(batch):>12}{avg:>10.1f}")
            total += len(batch)
        for lg, n in sorted(empty.items()):
            print(f"{lg:<10}{'0':>12}{'':>10}  (all declared stats NULL — left alone)")
        for lg, n in sorted(unknown.items()):
            print(f"{lg:<10}{'SKIPPED':>12}{'':>10}  ({n} rows, no STAT_FIELDS entry)")

        if unknown:
            print("\nA league with no vocabulary is UNVERIFIED, not empty. Add it to")
            print("STAT_FIELDS (team_stats_contract) before its rows can be migrated.")

        if not args.apply:
            print(f"\nDRY RUN — would write {total} rows. Re-run with --apply.")
            return 0

        if not has_stats:
            print("cannot write: `stats` column absent", file=sys.stderr)
            return 2

        for lg in sorted(by_league):
            con.executemany(
                "UPDATE team_game_stats SET stats=? "
                "WHERE league=? AND game_id=? AND team_abbrev=?",
                by_league[lg],
            )
        con.commit()

        written = con.execute(
            "SELECT COUNT(*) FROM team_game_stats WHERE stats IS NOT NULL AND stats!='{}'"
        ).fetchone()[0]
        print(f"\nwrote {total} rows; {written} rows now carry a non-empty blob")
        # Reconcile rather than trust the rowcount: the UPDATE matches on the
        # identity triple, and a duplicate row would make written > total.
        if written < total:
            print(f"MISMATCH: expected at least {total}, found {written}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
