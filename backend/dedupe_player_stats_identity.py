#!/usr/bin/env python3
"""Retire `player_stats` rows stranded under a placeholder identity.

Why this exists
---------------
`player_stats` is keyed `UNIQUE(name_norm, league, season, stat_type)` -- by the
NAME, not by the player. The statcast ingest writes a row under a placeholder
name_norm (`mlbam_664238`) for a player the spine has not resolved yet, and
writes the real one (`dylan moore`) once it has. Those are two different keys,
so the second write cannot update the first: it inserts, and the stale snapshot
survives forever under the same `player_id`.

That is not a cosmetic duplicate. Measured on prod 2026-08-03, all 71 affected
MLB batters had a placeholder row that was strictly older than its resolved twin
-- Zack Gelof at 54 games beside the current 66, Lawrence Butler at 63 beside 87.
`/api/mlb/leaders` fails closed on it (503, "duplicate ownership ... rebuild
required"), which took the whole Stats tab down: the tab defaults to Batting, so
one 503 rendered zero tables and Pitching was never reached.

What it does
------------
Deletes a placeholder row only when a resolved twin exists for the same
(player_id, league, season, stat_type, source), and only after asserting the
placeholder is not the fresher of the two. If a placeholder ever leads on games
played, that inverts the assumption this repair rests on and it refuses to write.

Idempotent: a second run finds nothing. Safe to call after every ingest, which is
the intent -- the schema will keep producing these until the unique key includes
the player, and a repair nobody runs is a repair that does not exist.

    venv/bin/python dedupe_player_stats_identity.py --db data/picks.db --league mlb --dry-run
    venv/bin/python dedupe_player_stats_identity.py --db data/picks.db --league mlb --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from typing import List, Tuple

PLACEHOLDER = "name_norm LIKE 'mlbam!_%' ESCAPE '!'"


def find_stranded(con: sqlite3.Connection, league: str, season: int | None) -> List[Tuple]:
    """Placeholder rows that have a resolved twin under the same player_id.

    Grouped by the full ownership tuple rather than by player_id alone: two rows
    that differ by stat_type or source are not duplicates of each other and the
    503 guard does not consider them so either.
    """
    where = "ps.league=? AND ps.player_id IS NOT NULL"
    params: list = [league]
    if season is not None:
        where += " AND ps.season=?"
        params.append(season)
    return con.execute(
        f"""SELECT ps.id, ps.player_id, ps.season, ps.stat_type, ps.source,
                   ps.name_norm, ps.player_name, ps.games,
                   twin.id, twin.name_norm, twin.games
            FROM player_stats ps
            JOIN player_stats twin
              ON  twin.player_id = ps.player_id
              AND twin.league    = ps.league
              AND twin.season    = ps.season
              AND twin.stat_type = ps.stat_type
              AND IFNULL(twin.source,'') = IFNULL(ps.source,'')
              AND twin.id != ps.id
              AND NOT ({PLACEHOLDER.replace('name_norm', 'twin.name_norm')})
            WHERE {where} AND {PLACEHOLDER.replace('name_norm', 'ps.name_norm')}
            ORDER BY ps.id""",
        params,
    ).fetchall()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True)
    ap.add_argument("--league", required=True)
    ap.add_argument("--season", type=int, default=None, help="default: every season")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    stranded = find_stranded(con, args.league.strip().lower(), args.season)
    if not stranded:
        print("nothing stranded: no placeholder row has a resolved twin")
        return 0

    # The claim: the placeholder is the stale one. Checked before writing, not
    # assumed -- deleting the fresher row would silently roll a season back.
    fresher = [r for r in stranded if (r[7] or 0) > (r[10] or 0)]
    print(f"{len(stranded)} stranded placeholder row(s) for {args.league}"
          f"{f' {args.season}' if args.season else ''}")
    for row in stranded[:5]:
        print(f"  {row[6]}: {row[5]} ({row[7]} games) -> keeping {row[9]} ({row[10]} games)")
    if len(stranded) > 5:
        print(f"  ... and {len(stranded) - 5} more")
    if fresher:
        print(f"REFUSING: {len(fresher)} placeholder row(s) lead their twin on games played, "
              f"so the stale-placeholder assumption does not hold here: "
              f"{[(r[6], r[7], r[10]) for r in fresher[:3]]}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    with con:
        con.executemany("DELETE FROM player_stats WHERE id=?", [(r[0],) for r in stranded])
    left = len(find_stranded(con, args.league.strip().lower(), args.season))
    print(f"deleted {len(stranded)} stranded row(s); {left} remain")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
