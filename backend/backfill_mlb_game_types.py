#!/usr/bin/env python3
"""Stamp `player_game_logs.game_type` for MLB from the publisher that keys the rows.

Why this exists
---------------
MLB was the one league whose log ingest never wrote a game type. Prod carried
45,551 rows of NULL; dev carried PRE/REG that a human had typed in, correct but
reproducible by nothing. A value only a person can produce is a value that stops
being produced -- and `AND game_type='REG'` over NULL does not raise, it returns
zero, which reads as "this player did not play" rather than "we never asked".

`ingest_mlb_logs.py` keys every row by statcast's `game_pk`, which IS the MLB
Stats API's game id, so the phase is one lookup away and always has been. One
schedule request covers a whole season -- 2,948 games for 2026 -- so this is
cheap enough to re-run rather than something to do once and hope.

Idempotent and additive: it only writes rows whose game_type disagrees with the
publisher, and it never invents a phase for a game the publisher does not list.

    venv/bin/python backfill_mlb_game_types.py --db data/picks.db --season 2026 --dry-run
    venv/bin/python backfill_mlb_game_types.py --db data/picks.db --season 2026 --apply
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
import urllib.request
from typing import Dict

import game_types

SCHEDULE = (
    "https://statsapi.mlb.com/api/v1/schedule?sportId=1"
    "&startDate={start}&endDate={end}&gameTypes=S,R,F,D,L,W,A,E"
)
HDR = {"User-Agent": "Mozilla/5.0 (legendarypicks ingest)"}


def published_phases(season: int, *, timeout: int = 45) -> Dict[str, str]:
    """game_pk -> our phase, for every game the publisher lists in `season`.

    The window is deliberately wider than the season: spring training starts in
    February and the World Series can reach November. Asking for a narrower one
    would silently drop the phases at both ends -- exactly the games whose phase
    matters most, since those are the ones that must NOT be counted as regular
    season.
    """
    url = SCHEDULE.format(start=f"{season}-02-01", end=f"{season}-11-15")
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=timeout) as fh:
        doc = json.load(fh)
    # 2,948 listings collapse to 2,920 ids: a postponed game is listed under BOTH
    # its original date and the makeup date it was actually played on. Measured
    # 2026-08-03: 28 such ids, and the published gameType agrees on every one, so
    # the last writer wins harmlessly. If that ever stops being true the phase is
    # ambiguous and this map is the wrong shape -- hence the assertion below.
    out: Dict[str, str] = {}
    conflicts = []
    for day in doc.get("dates") or []:
        for game in day.get("games") or []:
            pk, kind = game.get("gamePk"), game.get("gameType")
            if pk is None or not kind:
                continue
            # Raises on an unmeasured letter rather than defaulting to REG. A
            # phase we have never seen is a question, not a regular-season game.
            phase = game_types.normalize_game_type("statsapi", "mlb", kind)
            if out.get(str(pk), phase) != phase:
                conflicts.append((str(pk), out[str(pk)], phase))
            out[str(pk)] = phase
    if conflicts:
        raise SystemExit(
            f"{len(conflicts)} game(s) published under two different phases "
            f"({conflicts[:3]}): the phase is ambiguous, refusing to write"
        )
    if not out:
        raise SystemExit(f"publisher listed no games for {season}: refusing to write")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--season", type=int, required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    phases = published_phases(args.season)
    print(f"publisher lists {len(phases)} games for {args.season}: "
          f"{dict(collections.Counter(phases.values()))}")

    con = sqlite3.connect(args.db)
    rows = con.execute(
        "SELECT game_id, game_type, COUNT(*) FROM player_game_logs"
        " WHERE league='mlb' AND season=? GROUP BY game_id, game_type",
        (args.season,),
    ).fetchall()

    to_write: Dict[str, str] = {}
    unlisted = []
    stats = collections.Counter()
    for game_id, ours, n in rows:
        theirs = phases.get(str(game_id))
        if theirs is None:
            # Never guess. A game we hold that the publisher does not list is a
            # key problem or a phase outside the window, and both need a human.
            unlisted.append((game_id, ours, n))
            stats["not published"] += n
            continue
        if ours == theirs:
            stats["already correct"] += n
            continue
        stats["would change" if args.dry_run else "changed"] += n
        to_write[str(game_id)] = theirs

    for label, n in sorted(stats.items()):
        print(f"  {label:16s} {n:7d} rows")
    if unlisted:
        print(f"  WARNING: {len(unlisted)} game_id(s) the publisher does not list, "
              f"left untouched: {[g for g, _, _ in unlisted[:5]]}")

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    with con:
        con.executemany(
            "UPDATE player_game_logs SET game_type=?"
            " WHERE league='mlb' AND season=? AND game_id=?",
            [(phase, args.season, gid) for gid, phase in to_write.items()],
        )
    after = dict(con.execute(
        "SELECT COALESCE(game_type,'<NULL>'), COUNT(DISTINCT game_id)"
        " FROM player_game_logs WHERE league='mlb' AND season=? GROUP BY 1",
        (args.season,),
    ).fetchall())
    print(f"after: {after}")
    # The claim this script exists to make good on, asserted rather than assumed.
    if after.get("<NULL>"):
        print(f"FAIL: {after['<NULL>']} games still hold NULL", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
