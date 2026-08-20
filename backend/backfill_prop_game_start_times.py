#!/usr/bin/env python3
"""Give `prop_games` rows the kickoff ESPN already published for them.

    LP_DB_PATH=data/picks.dev.db python backfill_prop_game_start_times.py --dry-run
    LP_DB_PATH=data/picks.dev.db python backfill_prop_game_start_times.py --apply

## Why

The props board places a game by its kickoff, so a row with no `start_time` cannot be put
on a day at all. Measured 2026-08-19 on the live board: **17 of 30 upcoming MLS rows had
no start_time**, against 0 of 30 NFL, 0 of 10 MLB and 0 of 11 ATP, so MLS games silently
went missing from the slate. Every one of those 17 already carried an `espn_event_id`, and
ESPN publishes the kickoff on the scoreboard we fetch anyway. We were not missing the data,
we were not storing it.

## The date trap, which is the reason this needs neighbour days

A row's `date` is not reliably the day ESPN files the game under. `prop_games.date` carries
two conventions: some rows hold the UTC date of kickoff, so a 21:30 ET game is filed under
tomorrow. Looking that row up on its own stored date finds nothing:

    espn.games('mls', '2026-08-20')  ->  0 games
    espn.games('mls', '2026-08-19')  ->  761736 at 2026-08-20T01:30Z, 761739 at 02:30Z

**ESPN files a 02:30Z kickoff under Aug 19**, which is the answer to which convention is
correct: the local slate day, the same rule `_slate_day` already applies to the scoreboard.
So this searches the stored date and its neighbours, and matches on the event id, never on
the date.

## Cost

One scoreboard request per distinct (league, day) in the scan, times three for the
neighbours. Set `LP_ESPN_CACHE_DIR` and the repeats are free. The budget is printed before
any request is issued.
"""
import argparse
import collections
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn
from espn_client.scoreboard import _slate_day

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


def rows_missing_start_time(con, since=None):
    sql = ("SELECT id, league, date, home, away, espn_event_id FROM prop_games "
           "WHERE (start_time IS NULL OR start_time='') "
           "AND espn_event_id IS NOT NULL AND espn_event_id != ''")
    params = []
    if since:
        sql += " AND date >= ?"
        params.append(since)
    return con.execute(sql + " ORDER BY date, id", params).fetchall()


def published_start_times(rows):
    """{espn_event_id: published instant}, for the days those rows might sit on."""
    days = collections.defaultdict(set)
    for row in rows:
        for day in espn.neighbor_dates(row["date"]):
            days[row["league"]].add(day)
    budget = sum(len(d) for d in days.values())
    print("  budget: {} scoreboard requests ({})".format(
        budget, ", ".join("{} x{}".format(lg, len(d)) for lg, d in sorted(days.items()))))
    print("  LP_ESPN_CACHE_DIR is {}".format(
        "set" if os.environ.get("LP_ESPN_CACHE_DIR") else "NOT set, so repeats cost"))

    published = {}
    for league, league_days in sorted(days.items()):
        for day in sorted(league_days):
            try:
                for game in espn.games(league, day):
                    if game.get("date"):
                        published[str(game.get("game_id"))] = game["date"]
            except Exception as exc:
                print("    {} {}: {} ({})".format(league, day, type(exc).__name__, exc))
    return published


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write; otherwise report only")
    parser.add_argument("--since", default=None,
                        help="only rows dated on or after this (default: all)")
    args = parser.parse_args(argv)

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    rows = rows_missing_start_time(con, args.since)
    print("{} rows carry an espn_event_id and no start_time.".format(len(rows)))
    by_league = collections.Counter(r["league"] for r in rows)
    print("  by league: {}".format(dict(by_league)))
    if not rows:
        return 0

    published = published_start_times(rows)

    filled, misdated, unfound = [], [], []
    for row in rows:
        start = published.get(str(row["espn_event_id"]))
        if not start:
            unfound.append(row)
            continue
        filled.append((row, start))
        slate = _slate_day(row["league"], start)
        if slate and slate != row["date"]:
            misdated.append((row, slate))

    print("\n  {} resolved, {} not found on ESPN's board for those days".format(
        len(filled), len(unfound)))
    for row, start in filled[:8]:
        print("    game {:>5}  {} @ {:<24} {}".format(
            row["id"], row["away"][:18], row["home"][:24], start))
    if len(filled) > 8:
        print("    ... and {} more".format(len(filled) - 8))
    for row in unfound[:5]:
        print("    NOT FOUND  game {} {} espn {} dated {}".format(
            row["id"], row["league"], row["espn_event_id"], row["date"]))

    if misdated:
        # Reported, never silently corrected. `date` feeds settlement and a dozen other
        # modules, so re-dating rows is its own decision with its own evidence.
        print("\n  {} of those rows are ALSO filed under the wrong day. Not changed here:"
              .format(len(misdated)))
        for row, slate in misdated[:8]:
            print("    game {:>5}  stored {}  but ESPN plays it {}".format(
                row["id"], row["date"], slate))

    if not args.apply:
        print("\ndry run, nothing written. Re-run with --apply.")
        return 0

    for row, start in filled:
        con.execute("UPDATE prop_games SET start_time=? WHERE id=? "
                    "AND (start_time IS NULL OR start_time='')", (start, row["id"]))
    con.commit()
    remaining = len(rows_missing_start_time(con, args.since))
    print("\n  wrote {} start times; {} rows still without one.".format(
        len(filled), remaining))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
