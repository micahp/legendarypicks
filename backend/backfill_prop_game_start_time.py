#!/usr/bin/env python3
"""Copy `prop_games.start_time` from ESPN's published scoreboard.

Why this exists: `start_time` is the exact key every downstream link and lookup
needs, and 396 of 712 MLB rows did not have it — every one dated 2026-07-12 or
earlier, because the props ingest only started recording it on 2026-07-17.
Without it, `_fetch_mlb_gamepk` and the prop_games linker fell back to
date + teams, which is not an identity: a series plays the same two clubs on
consecutive days. All 117 rows that share an ESPN event id with another row have
a blank start_time. The correlation is total.

Method — a copy, not a derivation (published-first §2, rung 2):

  * ESPN's scoreboard publishes the event's instant, one request per DATE for
    every game that day. 55 requests covers the whole table; asking per event
    would cost 279 and the host budget is ~100 (see the espn-request-budget
    skill).
  * Only rows whose `espn_event_id` is UNIQUE across prop_games are filled. A
    shared event id means the link itself is unresolved, and copying a time
    through a wrong link would launder a bad link into an exact-looking key.
  * A failed fetch aborts. "No events published that day" and "the request
    failed" are not the same fact, and the second must never write.

Validated before it wrote anything: for the 280 rows that already carried a
start_time, ESPN's published event instant agreed with all 280 to within 60
seconds, 0 disagreements. Re-run `--verify` to reproduce that.

Usage:
  venv/bin/python backfill_prop_game_start_time.py --db data/picks.dev.db [--verify] [--dry-run]
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

import espn_client as espn

TOLERANCE_SECONDS = 60


def _instant(text):
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def published_events(dates, league="mlb"):
    """{event_id: published instant} for every game on these dates. One request per date."""
    out = {}
    for i, d in enumerate(dates, 1):
        try:
            for g in espn.games(league, d):
                out[str(g["game_id"])] = g["date"]
        except Exception as e:
            raise RuntimeError(
                f"scoreboard fetch failed for {d} after {i - 1} of {len(dates)} dates "
                f"({type(e).__name__}: {e}) — refusing to treat a failed request as an "
                f"empty day") from e
    return out


def verify(con, league="mlb"):
    """Compare the publisher against the rows that already carry a start_time."""
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM prop_games WHERE league=? AND start_time IS NOT NULL "
        "AND start_time!='' ORDER BY date", (league,))]
    print(f"verify: {len(dates)} dates -> {len(dates)} requests")
    pub = published_events(dates, league)
    rows = con.execute(
        "SELECT id, espn_event_id, start_time FROM prop_games WHERE league=? AND "
        "start_time IS NOT NULL AND start_time!='' AND espn_event_id!=''", (league,)).fetchall()
    agree = disagree = missing = 0
    for r in rows:
        p = pub.get(str(r["espn_event_id"]))
        if not p:
            missing += 1
            continue
        a, b = _instant(p), _instant(r["start_time"])
        if a and b and abs((a - b).total_seconds()) <= TOLERANCE_SECONDS:
            agree += 1
        else:
            disagree += 1
            print(f"  row {r['id']} event {r['espn_event_id']}: ours {r['start_time']} "
                  f"published {p}")
    print(f"verify: checked {len(rows)}  agree={agree}  disagree={disagree}  "
          f"not-published={missing}")
    return disagree == 0


def backfill(con, league="mlb", dry_run=False):
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM prop_games WHERE league=? AND (start_time IS NULL OR "
        "start_time='') ORDER BY date", (league,))]
    print(f"backfill: {len(dates)} dates -> {len(dates)} requests")
    pub = published_events(dates, league)
    print(f"backfill: {len(pub)} events published")

    shared = {r[0] for r in con.execute(
        "SELECT espn_event_id FROM prop_games WHERE espn_event_id IS NOT NULL AND "
        "espn_event_id!='' GROUP BY 1 HAVING COUNT(*)>1")}
    rows = con.execute(
        "SELECT id, espn_event_id FROM prop_games WHERE league=? AND (start_time IS NULL "
        "OR start_time='')", (league,)).fetchall()

    filled = skipped_shared = skipped_unlinked = skipped_unpublished = 0
    for r in rows:
        event_id = str(r["espn_event_id"] or "")
        if not event_id:
            skipped_unlinked += 1
            continue
        if event_id in shared:
            # The link is unresolved; copying through it would launder a bad link.
            skipped_shared += 1
            continue
        instant = pub.get(event_id)
        if not instant:
            skipped_unpublished += 1
            continue
        if not dry_run:
            con.execute("UPDATE prop_games SET start_time=? WHERE id=?", (instant, r["id"]))
        filled += 1
    if not dry_run:
        con.commit()
    print(f"backfill: filled={filled}  skipped: shared-event-id={skipped_shared} "
          f"no-link={skipped_unlinked} not-published={skipped_unpublished}")
    remaining = con.execute(
        "SELECT COUNT(*) FROM prop_games WHERE league=? AND (start_time IS NULL OR "
        "start_time='')", (league,)).fetchone()[0]
    print(f"backfill: {remaining} rows still without a start_time")
    return filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/picks.dev.db")
    ap.add_argument("--league", default="mlb")
    ap.add_argument("--verify", action="store_true",
                    help="only check the publisher against rows that already have one")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(os.path.abspath(args.db))
    con.row_factory = sqlite3.Row
    if args.verify:
        return 0 if verify(con, args.league) else 1
    if not verify(con, args.league):
        print("verification failed — not writing")
        return 1
    backfill(con, args.league, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
