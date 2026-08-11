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

Measured on picks.dev.db 2026-08-11, dry run against a warm backend: of 316 MLB
rows carrying a start_time, **191 correct, 89 bound to the wrong event, 36
unresolved**. (An earlier note said "85 of 286" from a different query; the
89/316 figure is this script's own ruler and supersedes it.)

Every one of the 89 is off by exactly 15 event ids — MLB's slate size — i.e.
bound to the same time slot on the FOLLOWING day's card. That regular offset is
the UTC/local boundary showing through, and it is what makes the team match
succeed on the wrong game rather than fail.

Two harms:

  1. The played game shows NO props (Micah opened /game/mlb/401816477 — empty,
     while its props sat on 401816492, which had not been played).
  2. Those props can never settle. Settlement looks for a final on an event that
     has not happened, so they stay ungraded indefinitely.

`link_prop_games.py` now prefers `start_time` and fails closed, which stops NEW
bad links. This script corrects the rows already written.

WHY IT READS SLATES FROM THE LOCAL BACKEND
-----------------------------------------
Not because ESPN blocks this box — it does not. `site.web.api.espn.com` (what
`_SITE` uses) and `sports.core.api.espn.com` both answer 200; only `site.api`
is walled and we stopped using it. The backend already has the slate cache and
the per-host budget, so a warm cache costs ESPN nothing at all. Requires the dev
backend running.

The ceiling is a request COUNT per host, ~100 then a cooldown — not a rate. A
sweep of these dates tripped it and made every date 500, which reads exactly
like an ESPN outage and is not one. See reference_espn_host_map.

So the cost is stated before it is spent: one request per DISTINCT day (not per
row), printed up front, and the script refuses outright above 100. There is no
pacing and no retry ladder — neither buys budget, and a retry spends more of it
to rediscover that it is gone. A slate that cannot be read is FATAL, because an
empty slate is indistinguishable from "no games that day" and would quietly
turn every blocked request into a row this script claims it could not resolve.

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


class SlateUnavailable(RuntimeError):
    """A slate could not be read. Fatal, never absorbed into an empty slate."""


def _load_slates(api, league, days, cache_path=""):
    """Fetch every needed slate ONCE, up front, and fail loudly.

    ESPN's ceiling is a request COUNT per host (~100, then a cooldown), not a
    rate. Two consequences the earlier version of this function got wrong:

      * Pacing does not buy budget. A sleep between requests spends the same
        count more slowly, so `pace=` was pure cost. Removed.
      * A retry ladder makes it WORSE. Each retry is another request against
        the same exhausted host, so backing off "into the cooldown" spends
        budget to discover the budget is spent. Removed.

    The only lever is issuing fewer requests: one per DISTINCT day, resolved
    before the row loop, so a 30-row series costs one fetch and not thirty.

    A failure raises. The previous version returned `[]`, which is
    indistinguishable from "ESPN listed no games that day" -- so every swallowed
    403 silently demoted its row to `unresolved` and the script still printed a
    tidy summary. `total CORRECTED: 0` could mean the matcher found nothing or
    that no slate was ever read, and the output could not tell you which.

    See the espn-request-budget skill and reference_espn_host_map.
    """
    slates = {}
    # Rung 4 of the skill's ladder: a cached slate costs the publisher nothing.
    # A dry run, an analysis pass and the --apply run all want the SAME 29
    # slates; re-fetching them per invocation is three times the spend for one
    # question. The backend's own cache is in-memory with a 12h TTL, so it does
    # not survive a restart and cannot be relied on across sittings.
    if cache_path and os.path.exists(cache_path):
        with open(cache_path) as f:
            slates = {k: v for k, v in json.load(f).items() if k in days}
        if slates:
            print("slate cache             : %d/%d from %s (0 requests)"
                  % (len(slates), len(days), cache_path))

    todo = [d for d in sorted(days) if d not in slates]
    if cache_path:
        print("slates to FETCH         : %d" % len(todo))
    for day in todo:
        url = "%s/api/%s/games?date=%s" % (api, league, day)
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                slates[day] = json.load(r)
        except Exception as e:
            if cache_path and slates:   # keep what we paid for
                with open(cache_path, "w") as f:
                    json.dump(slates, f)
            raise SlateUnavailable(
                "%s returned %s.\nThe host budget may be spent (~100 requests, then a "
                "cooldown) or the backend is down. Do NOT retry in a loop -- that spends "
                "more of the same budget. Wait out the cooldown, or warm the backend's "
                "slate cache, then re-run.\nRead %d/%d slates before failing."
                % (url, e, len(slates), len(days))) from e
    if cache_path:
        with open(cache_path, "w") as f:
            json.dump(slates, f)
    return slates


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
    ap.add_argument("--slate-cache", default="",
                    help="JSON file of slates, reused across runs at zero request cost")
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

    # Every distinct day these rows could sit on, resolved BEFORE the row loop.
    # The request count is a function of the calendar, not of the row count: a
    # 30-row series shares one slate. State the number before spending it, per
    # the espn-request-budget skill.
    days = set()
    for r in rows:
        if _instant(r["start_time"]) is not None:
            days |= set(_neighbour_days(r["date"]))
    print("%s rows with start_time: %d" % (args.league, len(rows)))
    print("distinct slates to read : %d  (1 request each, to %s)" % (len(days), args.api))
    if len(days) > 100:
        sys.exit("refusing: %d requests exceeds the ~100-per-host budget. Narrow the "
                 "date range and run it in sittings." % len(days))
    slates = _load_slates(args.api, args.league, days, args.slate_cache)
    print("slates read             : %d" % len(slates))

    fixes, already, unresolved = [], 0, []
    for r in rows:
        want = _instant(r["start_time"])
        if want is None:
            continue
        found = None
        for day in _neighbour_days(r["date"]):
            for eg in slates.get(day, []):
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
