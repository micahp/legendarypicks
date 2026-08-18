#!/usr/bin/env python3
"""Copy ESPN's published weekly fantasy points for kickers and defenses.

Why this exists
---------------
`player_game_logs` carries `fpts` and `fpts_ppr` for every NFL player, and for
every kicker in the table both are **0**. Not null -- zero. The logs come from
nflverse, whose `fantasy_points` is defined over passing, rushing and receiving
only, so a kicker's field goals never enter it. Brandon Aubrey kicked 4 field
goals in week 15 and his fantasy line read 0.0.

The instinct is to write a scoring function. Don't: ESPN already publishes the
number, per player per week, and a second implementation of somebody else's
scoring rules is a thing that silently disagrees with them forever. `appliedTotal`
on a `statSourceId=0` entry IS the fantasy points ESPN scored that week. This
copies it.

  Aubrey 2025:  wk1 11.0   wk2 23.0   wk3 8.0   wk4 8.0

Scope
-----
Kickers (slot 17) and D/ST (slot 16) -- the two positions nflverse does not
score. Everyone else already has a real `fpts` from the logs and is left alone.

D/ST is fetched but is NOT yet wired into the profile: `nfl_dst_stats` currently
carries a `fantasy_pts` this project COMPUTES (`ingest_nfl_dst.compute_fantasy_pts`).
Landing both lets the two be compared before anything switches, rather than
quietly replacing a number people may have been reading. `--compare` prints the
disagreement and writes nothing.

Join
----
`players.espn_id` is ESPN's own athlete id and matches the fantasy API's player id
exactly (Aubrey: 3953687 both sides; 87 of 87 active kickers carry one). No name
matching anywhere in this file -- a wrong join key does not raise, it misses
silently, which is how 178 players once vanished.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

import paced_http

BASE = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
        "{season}/segments/0/leaguedefaults/3?view=kona_player_info")

# ESPN lineup slot ids. 17 = K, 16 = D/ST. These are the two positions whose
# fantasy points nflverse does not compute, which is the whole reason for this job.
SLOT_KICKER = 17
SLOT_DST = 16

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS nfl_published_fantasy_points(
  player_id       INTEGER NOT NULL,
  season          INTEGER NOT NULL,
  week            INTEGER NOT NULL,
  points          REAL    NOT NULL,
  espn_player_id  INTEGER NOT NULL,
  slot            INTEGER NOT NULL,
  source          TEXT    NOT NULL,
  ingested_at     TEXT    NOT NULL,
  PRIMARY KEY (player_id, season, week)
)
"""


def fetch_slot(season: int, slot: int, limit: int = 400) -> list:
    """Every player in one lineup slot, with their weekly scored totals."""
    flt = {"players": {
        "filterSlotIds": {"value": [slot]},
        "limit": limit,
        "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
    }}
    # A Fetcher per call, not a module-level one: the x-fantasy-filter header
    # differs per slot while BASE is the SAME url for both, and the shared
    # client's memory cache keys on url — a shared instance would serve the
    # first slot's body to the second. Same headers, timeout and no-retry
    # posture as the raw call it replaces.
    fetch = paced_http.Fetcher(
        headers={"x-fantasy-filter": json.dumps(flt), "User-Agent": "Mozilla/5.0"},
        timeout=90, retry_waits=())
    return (fetch.fetch(BASE.format(season=season)).get("players") or [])


def weekly_points(entry: dict, season: int) -> list[tuple[int, float]]:
    """`(week, points)` for the weeks ESPN actually scored.

    `statSourceId` 0 is what happened; 1 is a projection. `scoringPeriodId` 0 is
    the season roll-up, not a week. Taking either by accident would file a
    projection as a result, so both are filtered rather than assumed.
    """
    out = []
    for stat in entry.get("player", {}).get("stats") or []:
        if stat.get("statSourceId") != 0:
            continue
        week = stat.get("scoringPeriodId") or 0
        if week <= 0 or stat.get("seasonId") != season:
            continue
        total = stat.get("appliedTotal")
        if total is None:
            continue
        out.append((int(week), float(total)))
    return sorted(out)


def espn_id_map(con: sqlite3.Connection) -> dict[int, int]:
    """`espn_id -> players.id`, for NFL rows that carry one."""
    rows = con.execute(
        "SELECT id, espn_id FROM players WHERE league='nfl' "
        "AND espn_id IS NOT NULL AND espn_id != 0 AND espn_id != ''"
    ).fetchall()
    mapping = {}
    for pid, espn in rows:
        try:
            mapping[int(espn)] = int(pid)
        except (TypeError, ValueError):
            continue
    return mapping


def collect(con: sqlite3.Connection, season: int, slots) -> tuple[list, list]:
    """Returns `(rows, unmatched)`. Unmatched is reported, never swallowed."""
    by_espn = espn_id_map(con)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows, unmatched = [], []
    for slot in slots:
        for entry in fetch_slot(season, slot):
            espn_id = entry.get("id")
            player_id = by_espn.get(int(espn_id)) if espn_id is not None else None
            weeks = weekly_points(entry, season)
            if player_id is None:
                if weeks:
                    unmatched.append((espn_id, entry.get("player", {}).get("fullName")))
                continue
            for week, points in weeks:
                rows.append((player_id, season, week, points, int(espn_id),
                             slot, "espn_fantasy_applied", now))
    return rows, unmatched


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--kickers-only", action="store_true",
                        help="skip D/ST (slot 16)")
    parser.add_argument("--compare", action="store_true",
                        help="print published vs computed D/ST points and write nothing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    slots = [SLOT_KICKER] if args.kickers_only else [SLOT_KICKER, SLOT_DST]
    con = sqlite3.connect(args.db)
    try:
        rows, unmatched = collect(con, args.season, slots)
        by_slot = {}
        for row in rows:
            by_slot.setdefault(row[5], set()).add(row[0])
        for slot in slots:
            print("slot %-3s %-5s players=%-4d weekly rows=%d" % (
                slot, "K" if slot == SLOT_KICKER else "D/ST",
                len(by_slot.get(slot, ())),
                sum(1 for r in rows if r[5] == slot)))
        if unmatched:
            # Not fatal, but never silent: an espn_id we cannot resolve is a player
            # whose points we are about to not have, and saying nothing is how that
            # becomes "the data is just like that".
            print("UNMATCHED espn ids with published points: %d  e.g. %s"
                  % (len(unmatched), unmatched[:5]))

        if args.compare:
            published = {(r[0], r[2]): r[3] for r in rows if r[5] == SLOT_DST}
            computed = {
                (r[0], r[1]): r[2] for r in con.execute(
                    "SELECT player_id, week, fantasy_pts FROM nfl_dst_stats WHERE season=?",
                    (args.season,))
            }
            shared = set(published) & set(computed)
            diffs = [(k, published[k], computed[k]) for k in sorted(shared)
                     if abs(published[k] - computed[k]) > 0.01]
            print("D/ST compared: %d overlapping team-weeks, %d disagree"
                  % (len(shared), len(diffs)))
            for key, pub, comp in diffs[:10]:
                print("   player %-6s wk%-3s published=%-7s computed=%s"
                      % (key[0], key[1], pub, comp))
            return 0

        if args.dry_run:
            print("dry-run: nothing written")
            return 0

        con.execute(TABLE_SQL)
        con.executemany(
            """INSERT INTO nfl_published_fantasy_points
                 (player_id, season, week, points, espn_player_id, slot,
                  source, ingested_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(player_id, season, week) DO UPDATE SET
                 points=excluded.points, espn_player_id=excluded.espn_player_id,
                 slot=excluded.slot, source=excluded.source,
                 ingested_at=excluded.ingested_at""",
            rows,
        )
        con.commit()
        print("wrote %d row(s) to nfl_published_fantasy_points (%s)"
              % (len(rows), args.db))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
