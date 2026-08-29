#!/usr/bin/env python3
"""Remove Set Betting props. They were never player props.

`set_betting___2_0` is "<Player> 2 - 0" -- the MATCH's scoreline, told from one
side. Bovada's tennis feed names a player in the outcome string, which is why the
parser read it as player-attributed, but it measures nothing about that player,
nothing in player_game_logs can chart it, and it belongs with the match-level
markets that parser already defers (Total Sets, game/set spreads, tie-break).

The parser stopped emitting them on 2026-08-26. This removes the rows already
stored, and NOTHING ELSE: the delete is keyed on `market LIKE 'set_betting%'`
and touches exactly two tables -- `props` and the `prop_results` rows that
reference them. It reports the counts it will remove before removing them, and
takes a verified backup first.

Prod carries 76 GRADED prop_results for these props. That settled history goes
with them; it is history for a market we do not want to carry.

  python3 scripts_drop_set_betting_props.py --db data/picks.dev.db --check
  python3 scripts_drop_set_betting_props.py --db data/picks.dev.db --apply
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone

PATTERN = "set_betting%"


def survey(con):
    props = con.execute(
        "SELECT COUNT(*) FROM props WHERE market LIKE ?", (PATTERN,)).fetchone()[0]
    results = con.execute(
        "SELECT COUNT(*) FROM prop_results WHERE prop_id IN"
        " (SELECT id FROM props WHERE market LIKE ?)", (PATTERN,)).fetchone()[0]
    graded = con.execute(
        "SELECT COUNT(*) FROM prop_results WHERE actual_value IS NOT NULL AND prop_id IN"
        " (SELECT id FROM props WHERE market LIKE ?)", (PATTERN,)).fetchone()[0]
    markets = [r[0] for r in con.execute(
        "SELECT DISTINCT market FROM props WHERE market LIKE ? ORDER BY 1", (PATTERN,))]
    leagues = con.execute(
        "SELECT DISTINCT g.league FROM props p JOIN prop_games g ON g.id=p.game_id"
        " WHERE p.market LIKE ?", (PATTERN,)).fetchall()
    return props, results, graded, markets, [l[0] for l in leagues]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    props, results, graded, markets, leagues = survey(con)
    total_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    total_results = con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0]
    print(f"{args.db}")
    print(f"  props table          : {total_props}")
    print(f"  prop_results table   : {total_results}")
    print(f"  set_betting props    : {props}")
    print(f"  their prop_results   : {results}  (graded: {graded})")
    print(f"  markets              : {markets}")
    print(f"  leagues              : {leagues}")

    if args.check:
        print("  check only -- nothing written")
        return 0
    if not props:
        print("  nothing to remove")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{args.db}.pre-drop-setbetting-{stamp}.bak"
    con.execute("VACUUM INTO ?", (backup,))
    ok = sqlite3.connect(backup).execute("PRAGMA quick_check").fetchone()[0]
    print(f"  backup: {backup} (quick_check={ok})")
    if ok != "ok":
        raise SystemExit("backup failed quick_check; nothing removed")

    con.execute("BEGIN IMMEDIATE")
    dropped_results = con.execute(
        "DELETE FROM prop_results WHERE prop_id IN"
        " (SELECT id FROM props WHERE market LIKE ?)", (PATTERN,)).rowcount
    dropped_props = con.execute(
        "DELETE FROM props WHERE market LIKE ?", (PATTERN,)).rowcount
    con.commit()

    after_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    after_results = con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0]
    left = con.execute("SELECT COUNT(*) FROM props WHERE market LIKE ?", (PATTERN,)).fetchone()[0]
    print(f"  removed {dropped_props} props and {dropped_results} prop_results")
    print(f"  props {total_props} -> {after_props} (delta {total_props - after_props},"
          f" expected {props})")
    print(f"  prop_results {total_results} -> {after_results}"
          f" (delta {total_results - after_results}, expected {results})")
    print(f"  set_betting remaining: {left}")
    if total_props - after_props != props or total_results - after_results != results:
        raise SystemExit("REMOVED MORE THAN EXPECTED -- restore from the backup above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
