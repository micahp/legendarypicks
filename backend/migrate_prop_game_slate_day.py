#!/usr/bin/env python3
"""Re-date `prop_games` rows onto the local slate day, once.

    LP_DB_PATH=data/picks.dev.db venv/bin/python migrate_prop_game_slate_day.py --dry-run
    LP_DB_PATH=data/picks.dev.db venv/bin/python migrate_prop_game_slate_day.py --apply

## Why this exists, and why it is a migration rather than a backfill

`prop_games.date` carried two conventions. `bovada_scraper._wc_event_date`
returned the **UTC** date of the kickoff; `_slate_day`, which the scoreboard
and every ESPN lookup use, returns the **local** day. A 9:30pm Central kickoff
is 02:30Z the next day, so the props board filed tonight's late games under
tomorrow while the scoreboard correctly said tonight. Two identical 9:30
kickoffs sat on different board days depending only on which ingest wrote them.

The ingest itself was fixed in the same commit as this script. That fix is what
makes this a migration and not a backfill, in both directions:

  - It is REQUIRED. `_wc_direct_ingest` and the API path both match an existing
    fixture on `league + date + home + away`. Once the ingest starts computing
    the local day, every stored row still on the UTC day stops matching, and the
    next run MINTS A DUPLICATE for each one. Fixing the ingest without this
    would be worse than fixing neither.
  - It is NOT re-runnable from the source. Bovada prices today's board, not June's.
    For a game already played there is nothing left to re-ingest, so the stored
    value has to be repaired in place. That is the distinction: fix the ingest and
    re-run where the publisher can still answer, migrate where it cannot.

## What it will not do

A row with no `start_time` is left alone and reported. Its date is the only
temporal thing it has, and guessing a local day from a date is how the wrong
convention got in. Fill `start_time` first (`backfill_prop_game_start_times.py`).

Collisions are checked BEFORE anything is written. Re-dating can make two rows
agree on `(league, date, home, away)`, which is the ingest's own match key; the
table has no unique index on it, so nothing would raise. Any collision aborts
the run and prints the pair, because folding two fixtures is a separate
decision with its own tool (`prop_game_merge.py`).
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from espn_client.scoreboard import _slate_day  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def plan(con: sqlite3.Connection):
    """(moves, no_start_time) without touching anything."""
    moves, missing = [], []
    for row in con.execute(
            "SELECT id, league, date, home, away, start_time FROM prop_games"):
        if not row["start_time"]:
            missing.append(dict(row))
            continue
        slate = _slate_day(row["league"], row["start_time"])
        if slate and slate != row["date"]:
            moves.append((dict(row), slate))
    return moves, missing


def collisions(con: sqlite3.Connection, moves):
    """Pairs that would share the ingest's match key after the move."""
    after = collections.defaultdict(list)
    for row in con.execute("SELECT id, league, date, home, away FROM prop_games"):
        after[(row["league"], row["date"], row["home"], row["away"])].append(row["id"])
    for row, slate in moves:
        key_before = (row["league"], row["date"], row["home"], row["away"])
        after[key_before].remove(row["id"])
        after[(row["league"], slate, row["home"], row["away"])].append(row["id"])
    return {key: ids for key, ids in after.items() if len(ids) > 1}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--accept-shared-keys", action="store_true",
        help="proceed even though some rows will share (league, date, home, away). "
             "Only after reading each pair: a shared key is correct for a "
             "doubleheader and wrong for a duplicate, and this tool cannot tell "
             "them apart. Duplicates are folded with prop_game_merge.py, which is "
             "a separate decision because folding also merges their props.")
    args = ap.parse_args(argv)
    if args.apply == args.dry_run:
        ap.error("pass exactly one of --apply or --dry-run")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    moves, missing = plan(con)

    by_league = collections.Counter(row["league"] for row, _ in moves)
    print("database: %s" % DB)
    print("rows whose date disagrees with the local slate day: %d" % len(moves))
    for league in sorted(by_league):
        print("   %-6s %d" % (league, by_league[league]))
    for row, slate in moves[:8]:
        print("     e.g. %s %s %s -> %s  (%s @ %s)" % (
            row["id"], row["league"], row["date"], slate, row["away"], row["home"]))
    if missing:
        print("rows with no start_time, left alone: %d "
              "(run backfill_prop_game_start_times.py first)" % len(missing))

    clash = collisions(con, moves)
    if clash:
        print("\n%d key(s) will be shared after the move:" % len(clash))
        for key, ids in sorted(clash.items())[:20]:
            print("   %s  ids=%s" % (list(key), ids))
        if not args.accept_shared_keys:
            print("ABORT. Read each pair first. A shared key is CORRECT for a "
                  "doubleheader and WRONG for a duplicate, and nothing here can "
                  "tell them apart: on 2026-08-19 four of five such pairs were "
                  "one game stored twice, and the fifth was a real doubleheader "
                  "ESPN confirms (the 07-27 game was Postponed and replayed as "
                  "two on 07-28).")
            print("Re-run with --accept-shared-keys once you have, or fold the "
                  "duplicates with prop_game_merge.py first.")
            con.close()
            return 2
        # Worth being exact about what accepting costs. These rows already
        # collide in every way that matters -- a duplicate pair is two rows for
        # one game today, on two dates, and the ingest already picks one of them
        # arbitrarily. Re-dating does not create the defect and does not deepen
        # it; it stops hiding it behind a date that was wrong anyway.
        print("proceeding: shared keys accepted, no rows folded")

    if not moves:
        print("nothing to do")
        con.close()
        return 0

    if args.dry_run:
        print("\ndry run, nothing written")
        con.close()
        return 0

    with con:
        con.executemany("UPDATE prop_games SET date=? WHERE id=?",
                        [(slate, row["id"]) for row, slate in moves])
    left, _ = plan(con)
    print("\napplied %d; rows still disagreeing: %d" % (len(moves), len(left)))
    con.close()
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
