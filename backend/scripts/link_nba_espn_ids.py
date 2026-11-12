#!/usr/bin/env python3
"""Link parked NBA ESPN IDs to existing players through the legacy nba_id.

hoopR's athlete_id is ESPN's athlete ID. Legacy imports stored it in
players.nba_id, while the current ingesters look only at players.espn_id. So a
player can exist, with the right ID in the wrong column, and have every game log
parked in unresolved_players.

This script links ONLY the exact cases: an unresolved NBA ESPN ID that equals
exactly one NBA player's nba_id, where that player has no espn_id, and where no
other row owns the ESPN ID. It never matches by name, never creates players,
and never changes players.id, nba_id, active, or roster membership.

Usage:
  python3 link_nba_espn_ids.py --db /abs/picks.dev.db --plan
  python3 link_nba_espn_ids.py --db /abs/picks.dev.db --apply \
      --expect-links 57 --preimage /abs/preimage.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys


def connect(path: str, read_only: bool) -> sqlite3.Connection:
    if not os.path.isabs(path) or not os.path.isfile(path):
        raise SystemExit("database must be an existing absolute file: " + path)
    mode = "ro" if read_only else "rw"
    con = sqlite3.connect("file:{}?mode={}".format(path, mode), uri=True,
                          timeout=120)
    con.execute("PRAGMA busy_timeout = 120000")
    return con


def build_plan(con: sqlite3.Connection):
    parked = con.execute(
        "SELECT DISTINCT source_player_key FROM unresolved_players "
        "WHERE league = 'nba' AND source_player_key IS NOT NULL "
        "AND source_player_key != ''").fetchall()
    keys = sorted({str(r[0]) for r in parked})
    espn_owner = {}
    # ESPN reuses athlete numbers across sports, and the table's rule is
    # UNIQUE(espn_id, league). Only an NBA owner is a conflict.
    for pid, espn in con.execute(
            "SELECT id, espn_id FROM players WHERE league = 'nba' "
            "AND espn_id IS NOT NULL AND espn_id != ''"):
        espn_owner.setdefault(str(espn), []).append(pid)
    nba_rows = {}
    for row in con.execute(
            "SELECT id, name, espn_id, nba_id FROM players "
            "WHERE league = 'nba' AND nba_id IS NOT NULL AND nba_id != ''"):
        nba_rows.setdefault(str(row[3]), []).append(row)
    source_owner = {}
    for source_key, pid in con.execute(
            "SELECT source_player_key, player_id FROM player_source_ids "
            "WHERE league = 'nba' AND source = 'espn'"):
        source_owner.setdefault(str(source_key), set()).add(pid)

    plan, skipped = [], []
    for key in keys:
        if key in espn_owner:
            skipped.append((key, "espn_id_already_owned"))
            continue
        matches = nba_rows.get(key, [])
        if not matches:
            skipped.append((key, "no_legacy_nba_id_match"))
            continue
        if len(matches) > 1:
            skipped.append((key, "more_than_one_legacy_row"))
            continue
        pid, name, espn, _nba = matches[0]
        if espn not in (None, ""):
            skipped.append((key, "player_already_has_other_espn_id"))
            continue
        owners = source_owner.get(key, set())
        if owners and owners != {pid}:
            skipped.append((key, "source_id_owned_by_another_player"))
            continue
        plan.append((key, pid, name))
    return plan, skipped


def summarize(plan, skipped):
    reasons = {}
    for _key, why in skipped:
        reasons[why] = reasons.get(why, 0) + 1
    print("links planned:", len(plan))
    print("skipped distinct ids:", len(skipped))
    for why, count in sorted(reasons.items()):
        print("  {}: {}".format(why, count))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-links", type=int)
    parser.add_argument("--preimage")
    parser.add_argument("--plan-csv")
    args = parser.parse_args(argv)

    con = connect(args.db, read_only=args.plan)
    plan, skipped = build_plan(con)
    summarize(plan, skipped)
    if args.plan_csv:
        with open(args.plan_csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["espn_id_to_write", "players_id", "name"])
            writer.writerows(plan)
    if args.plan:
        return 0

    if args.expect_links is None or not args.preimage:
        raise SystemExit("--apply requires --expect-links and --preimage")
    if args.expect_links != len(plan):
        raise SystemExit("expected {} links, planned {}".format(
            args.expect_links, len(plan)))
    if not os.path.isabs(args.preimage):
        raise SystemExit("--preimage must be an absolute path")

    ids = [pid for _k, pid, _n in plan]
    marks = ",".join("?" for _ in ids)
    columns = [r[1] for r in con.execute("PRAGMA table_info(players)")]
    rows = con.execute(
        "SELECT * FROM players WHERE id IN ({})".format(marks), ids).fetchall()
    with open(args.preimage, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    print("pre-image rows saved:", len(rows), "->", args.preimage)

    con.isolation_level = None
    con.execute("BEGIN IMMEDIATE")
    try:
        for key, pid, _name in plan:
            cursor = con.execute(
                "UPDATE players SET espn_id = ? WHERE id = ? "
                "AND league = 'nba' AND (espn_id IS NULL OR espn_id = '')",
                (key, pid))
            if cursor.rowcount != 1:
                raise RuntimeError(
                    "update touched {} rows for players.id {}".format(
                        cursor.rowcount, pid))
        done = con.execute(
            "SELECT COUNT(*) FROM players WHERE id IN ({}) AND espn_id IS NOT "
            "NULL AND espn_id != ''".format(marks), ids).fetchone()[0]
        if done != len(plan):
            raise RuntimeError("post-check found {} of {}".format(done, len(plan)))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    print("applied:", len(plan), "links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
