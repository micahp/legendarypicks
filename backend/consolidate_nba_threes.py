#!/usr/bin/env python3
"""Fold the NBA `total_made_3_points_shots` market into `threes`.

Bovada names the market "Total Made 3 Points Shots". Until fe5e231c the parser
kept that as its own key, so the board carried two markets for the same stat.
The parser now maps it to `threes`; this repairs the rows already written.

Bovada upserts one row per (game, player, market, line, side, source). A legacy
row whose `threes` twin already exists is an older capture of the same prop, so
it is dropped; every other legacy row is renamed. A legacy row that carries a
prop_results or prop_odds_snapshots row stops the run: those need a merge, not
a delete, and none existed when this was written.

Usage: venv/bin/python consolidate_nba_threes.py --db data/picks.dev.db [--dry-run]
"""
import argparse, os, sqlite3, sys

from migrate_schema import create_verified_backup

LEGACY = ("total_made_3_points_shots", "total_made_3_point_shots")
_IN = f"market IN ({','.join('?' * len(LEGACY))})"
_TWIN = f"""EXISTS (SELECT 1 FROM props q WHERE q.market = 'threes'
             AND q.game_id = props.game_id AND q.player_id = props.player_id
             AND q.line = props.line AND q.side = props.side
             AND q.source IS props.source)"""


def counts(con):
    total = con.execute(f"SELECT COUNT(*) FROM props WHERE {_IN}", LEGACY).fetchone()[0]
    twins = con.execute(f"SELECT COUNT(*) FROM props WHERE {_IN} AND {_TWIN}", LEGACY).fetchone()[0]
    children = con.execute(f"""SELECT
        (SELECT COUNT(*) FROM prop_results WHERE prop_id IN (SELECT id FROM props WHERE {_IN})),
        (SELECT COUNT(*) FROM prop_odds_snapshots WHERE prop_id IN (SELECT id FROM props WHERE {_IN}))""",
        LEGACY + LEGACY).fetchone()
    threes = con.execute("SELECT COUNT(*) FROM props WHERE market = 'threes'").fetchone()[0]
    return total, twins, children, threes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/picks.dev.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = os.path.abspath(args.db)
    con = sqlite3.connect(db)

    total, twins, children, threes = counts(con)
    print(f"database  {db}")
    print(f"legacy    {total} rows: {twins} have a threes twin (drop), {total - twins} rename")
    print(f"children  {children[0]} prop_results, {children[1]} prop_odds_snapshots")
    print(f"threes    {threes} rows before")
    if any(children):
        sys.exit("legacy rows carry results or odds snapshots; merge them first, nothing changed")
    if total == 0 or args.dry_run:
        print("nothing changed")
        return

    backup = create_verified_backup(db)
    print(f"backup    {backup}")

    with con:
        dropped = con.execute(f"DELETE FROM props WHERE {_IN} AND {_TWIN}", LEGACY).rowcount
        renamed = con.execute(f"UPDATE props SET market = 'threes' WHERE {_IN}", LEGACY).rowcount
    left, _, _, after = counts(con)
    print(f"dropped   {dropped}")
    print(f"renamed   {renamed}")
    print(f"threes    {after} rows after (expected {threes + renamed})")
    print(f"legacy    {left} left")
    if left or after != threes + renamed:
        sys.exit("counts do not reconcile; restore from the backup above")
    con.close()


if __name__ == "__main__":
    main()
