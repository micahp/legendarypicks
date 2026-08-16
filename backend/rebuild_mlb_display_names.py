#!/usr/bin/env python3
"""Rebuild the MLB 2026 canonical `player_stats` display copy from the spine.

Why this exists
---------------
`/api/mlb/leaders` fails closed (503, "canonical player stats disagree with the
player index for mlb season 2026; rebuild required") because the leaders guard
compares `player_stats.player_name` byte-for-byte with `players.name` for the
same `player_id`. The Aug 4/5 MLB dedupe repointed duplicate `player_stats`
rows onto their canonical `player_id` WITHOUT rewriting each row's `player_name`
-- the duplicate's placeholder spelling (`max muncy`) survived under the
canonical player's id. Measured: 242 canonical 2026 rows disagree (214 batting,
28 pitching; 215 differ only in case, 27 really).

This is exactly what `repair_player_stats_identity.py` R6 repairs for the whole
table; this script is R6 scoped to the served MLB population only, and it does
NOTHING else -- no deletions, no re-keying. `player_name`/`name_norm` are a
denormalized copy of `players.name` that `publish_player_stats` rewrites on
every publish, so the source of truth is not in question.

Scope (the guard's own population, nothing else):
    league='mlb' AND season=2026 AND source='statcast'
    AND stat_type IN ('batting','pitching') AND player_id IS NOT NULL
    AND player_name != players.name

Default is a dry run; --apply commits after a verified backup. Row counts in
`player_stats`, `players`, `props`, `player_game_logs` and `roster_snap` are
compared before and after -- this repair must move nothing but the two name
columns.

Usage:
  cd backend && venv/bin/python rebuild_mlb_display_names.py --db /abs/path/picks.db [--apply]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from league_stats import normalize_player_name  # noqa: E402
from migrate_schema import create_verified_backup  # noqa: E402

POPULATION = """
    ps.league='mlb' AND ps.season=2026 AND ps.source='statcast'
    AND ps.stat_type IN ('batting','pitching')
    AND ps.player_id IS NOT NULL
"""


def count_table(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="absolute path to the database")
    ap.add_argument("--apply", action="store_true",
                    help="back up, then commit the rebuild (default is a dry run)")
    args = ap.parse_args(argv)
    db = os.path.abspath(args.db)

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        mismatches = con.execute(
            f"""SELECT ps.id, ps.player_id, ps.player_name, ps.stat_type, p.name
                FROM player_stats ps
                JOIN players p ON p.id=ps.player_id AND p.league=ps.league
                WHERE {POPULATION} AND ps.player_name != p.name
                ORDER BY ps.player_id"""
        ).fetchall()
        print(f"canonical MLB 2026 rows with drifted display name: {len(mismatches)}")
        for row in mismatches[:8]:
            print(f"  id={row['id']} player_id={row['player_id']} "
                  f"[{row['stat_type']}] '{row['player_name']}' -> '{row['name']}'")
        if not mismatches:
            print("nothing to rebuild")
            return 0

        before = {t: count_table(con, t) for t in
                  ("player_stats", "players", "props", "player_game_logs", "roster_snap")}

        if not args.apply:
            print("dry run -- nothing written")
            return 0

        backup = create_verified_backup(db)
        print(f"verified backup: {backup}")

        con.execute("BEGIN IMMEDIATE")
        con.executemany(
            "UPDATE player_stats SET player_name=?, name_norm=? WHERE id=?",
            [
                (str(row["name"]), normalize_player_name(row["name"]), int(row["id"]))
                for row in mismatches
            ],
        )
        con.execute("COMMIT")
        print(f"rebuilt {len(mismatches)} display name(s)")

        after = {t: count_table(con, t) for t in before}
        drift = con.execute(
            f"""SELECT COUNT(*) FROM player_stats ps
                JOIN players p ON p.id=ps.player_id AND p.league=ps.league
                WHERE {POPULATION} AND ps.player_name != p.name"""
        ).fetchone()[0]
        for t in before:
            state = "unchanged" if before[t] == after[t] else f"CHANGED {before[t]} -> {after[t]}"
            print(f"  {t}: {state}")
        print(f"remaining drift in the guard population: {drift}")
        if drift or any(after[t] != before[t] for t in before):
            print("FAILED SELF-CHECK: drift or row-count movement after rebuild")
            return 1
        print("self-check ok: 0 drift, all row counts unmoved")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
