#!/usr/bin/env python3
"""refresh_soccer_player_teams.py — copy each soccer player's club from the publisher.

WHY THIS EXISTS
---------------
Nothing owns "current club" for soccer. `published_roster.publish_identities` writes
`team=COALESCE(NULLIF(team,''),?)`, which fills a blank and never corrects a wrong one, so
a transfer updates a player's identity and leaves their club as whatever we last saw.
Measured on prod 2026-09-07, 45 of 1,031 bound MLS players disagree with the roster their
own publisher is currently serving:

    Caden Clark      ours=DC   published=SEA   37 game logs
    Dante Sealy      ours=COL  published=MTL   41 game logs
    Dejan Jovelic    ours=SKC  published=SEA   42 game logs

This is the same defect `refresh_mlb_player_teams.py` was written for on 2026-08-11, and
its argument applies unchanged: **a team is a DEFINITION, not a computation.** The
publisher states it; we copy it. The only difference is that soccer needs no request at
all, because `ingest_published_rosters` already stores the current squad in
`published_roster` on a daily cadence.

WHAT IT WILL NOT TOUCH
----------------------
**A row it cannot corroborate.** Only players bound to a roster row are considered, and the
club comes from `team_code`, which `club_crosswalk` already resolved into the vocabulary
`players.team` uses. A blank code is skipped rather than blanking a team.

**A competition that owns nobody.** Leagues Cup rows are excluded by name. Their people
live in MLS and Liga MX, so a cup entry restating their club would let a July tournament
overwrite a fact that belongs to the league season.

**A player two clubs both claim.** If the roster rows bound to one person disagree about
the club, that is a question about a transfer in progress, and answering it by picking one
publisher is a guess. Counted and skipped.

Usage:
  cd backend && python3 refresh_soccer_player_teams.py --db data/picks.db [--apply]

Dry run by default. Idempotent.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from published_roster import NO_MINT_LEAGUES

LEAGUES = ("mls", "ligamx")


def plan(con: sqlite3.Connection):
    """[(player_id, name, ours, published)], and the count refused as contested."""
    claims = collections.defaultdict(set)
    names = {}
    ours = {}
    for player_id, name, team, code in con.execute(
            "SELECT p.id, p.name, p.team, r.team_code FROM published_roster r "
            "JOIN players p ON p.id = r.player_id "
            "WHERE r.league IN ({}) AND r.player_id IS NOT NULL "
            "AND COALESCE(r.team_code,'') <> ''".format(
                ",".join("?" * len(LEAGUES))), LEAGUES):
        claims[player_id].add(str(code).strip().upper())
        names[player_id] = name
        ours[player_id] = str(team or "").strip().upper()

    changes, contested = [], 0
    for player_id, codes in claims.items():
        if len(codes) > 1:
            contested += 1
            continue
        published = next(iter(codes))
        if ours[player_id] != published:
            changes.append((player_id, names[player_id], ours[player_id], published))
    return sorted(changes, key=lambda row: row[1]), contested


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=25, help="how many to print")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.db):
        print("no such database: {}".format(args.db))
        return 2
    assert "lcup" in NO_MINT_LEAGUES and "lcup" not in LEAGUES, \
        "a competition that owns nobody must not restate a club"

    con = sqlite3.connect(args.db, timeout=30)
    try:
        changes, contested = plan(con)
        print("{}: {} club(s) to refresh, {} contested and skipped".format(
            args.db, len(changes), contested))
        for player_id, name, was, now_ in changes[:args.limit]:
            print("  {:<28} {:>5} -> {}".format(name[:28], was or "(blank)", now_))
        if len(changes) > args.limit:
            print("  ... and {} more".format(len(changes) - args.limit))
        if not changes:
            return 0
        if not args.apply:
            print("  dry run: nothing written")
            return 0
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        con.executemany("UPDATE players SET team=?, updated_at=? WHERE id=?",
                        [(published, now, player_id)
                         for player_id, _n, _w, published in changes])
        con.commit()
        left, _ = plan(con)
        print("  applied {}; {} still disagree".format(len(changes), len(left)))
        return 1 if left else 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
