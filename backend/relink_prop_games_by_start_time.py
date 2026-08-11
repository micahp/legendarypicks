#!/usr/bin/env python3
"""relink_prop_games_by_start_time.py — repair prop_games rows bound to the wrong
game of a series.

WHY THIS EXISTS
---------------
`link_prop_games.link_prop_game` matched on `league + date + team abbreviation`
only. That is ambiguous for the case baseball produces constantly: the same two
clubs on consecutive days. `prop_games.date` comes from a UTC first pitch while
ESPN's scoreboard is keyed by LOCAL date, so a 01:40Z start (the previous evening
in the US) is looked up against the NEXT day's slate, which in a series holds the
same two teams. The team match then succeeds on the wrong game.

Measured on picks.dev.db 2026-08-11: 85 of 286 dated MLB rows bound to an event
starting at a different time. Two harms:

  1. The played game shows NO props (Micah opened /game/mlb/401816477 — empty,
     while its props sat on 401816492, which had not been played).
  2. Those props can never settle. Settlement looks for a final on an event that
     has not happened, so they stay ungraded indefinitely.

`link_prop_games.py` now prefers `start_time` and fails closed, which stops NEW
bad links. This script corrects the rows already written.

WHY IT DOES NOT USE espn_client
-------------------------------
`espn_client.games()` returns HTTP 403 from this host when called by a direct
importer — the pacing/cache that makes it work lives on the serving path. The
local backend answers the same query correctly, so slates are read from it. That
also means this script needs the dev backend running.

Usage:
  LP_DB_PATH=data/picks.dev.db python3 relink_prop_games_by_start_time.py \
      --api http://127.0.0.1:8096 [--apply]

Default is a dry run. Takes its own backup before writing.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from link_prop_games import _instant, _norm_team, _neighbour_days  # noqa: E402


def _slate(api, league, day, cache):
    key = (league, day)
    if key in cache:
        return cache[key]
    try:
        with urllib.request.urlopen("%s/api/%s/games?date=%s" % (api, league, day), timeout=30) as r:
            cache[key] = json.load(r)
    except Exception:
        cache[key] = []
    return cache[key]


def _same_matchup(row, eg):
    home_norm = _norm_team(row["home"], row["league"])
    away_norm = _norm_team(row["away"], row["league"])
    if (eg.get("home", {}).get("abbrev", "").upper() == home_norm
            and eg.get("away", {}).get("abbrev", "").upper() == away_norm):
        return True
    return ((eg.get("home", {}).get("displayName") or "").lower() == (row["home"] or "").lower()
            and (eg.get("away", {}).get("displayName") or "").lower() == (row["away"] or "").lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8096")
    ap.add_argument("--league", default="mlb")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """SELECT id, league, date, start_time, home, away, espn_event_id
           FROM prop_games
           WHERE league=? AND start_time IS NOT NULL AND start_time!=''""",
        (args.league,)).fetchall()

    cache = {}
    fixes, already, unresolved = [], 0, []
    for r in rows:
        want = _instant(r["start_time"])
        if want is None:
            continue
        found = None
        for day in _neighbour_days(r["date"]):
            for eg in _slate(args.api, r["league"], day, cache):
                if _same_matchup(r, eg) and _instant(eg.get("date")) == want:
                    found = str(eg["game_id"])
                    break
            if found:
                break
        if not found:
            unresolved.append(r["id"])
        elif found == (r["espn_event_id"] or ""):
            already += 1
        else:
            fixes.append((r["id"], r["date"], r["start_time"], r["espn_event_id"] or "", found,
                          "%s @ %s" % (r["away"], r["home"])))

    print("%s rows with start_time: %d" % (args.league, len(rows)))
    print("  already correct : %d" % already)
    print("  WOULD CORRECT   : %d" % len(fixes))
    print("  unresolved      : %d (left alone)" % len(unresolved))
    for f in fixes[:20]:
        print("    id=%-5s %s start=%s  %s -> %s   (%s)" % f)
    if len(fixes) > 20:
        print("    ... and %d more" % (len(fixes) - 20))

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return

    if not fixes:
        print("\nNothing to write.")
        return

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = "%s.pre-relink-%s.bak" % (db, stamp)
    con.execute("VACUUM INTO ?", (bak,))
    chk = sqlite3.connect(bak).execute("PRAGMA quick_check").fetchone()[0]
    print("\nbackup: %s (quick_check: %s)" % (bak, chk))
    if chk != "ok":
        sys.exit("backup failed integrity check — refusing to write")

    for gid, _d, _s, _old, new, _m in fixes:
        con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (new, gid))
    con.commit()
    print("corrected %d rows" % len(fixes))


if __name__ == "__main__":
    main()
