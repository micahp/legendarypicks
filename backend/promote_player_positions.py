#!/usr/bin/env python3
"""Copy `position` / `position_group` between databases, matched on the PUBLISHER id.

Why matched on the publisher id
-------------------------------
`players.id` is a per-database AUTOINCREMENT counter. Prod and dev are not a replica pair --
they are two databases forked from a common ancestor, both written to independently -- so the
same integer names different people on each side. Measured 2026-08-17: of 44,450 ids present
in both, 1,379 sit on a different LEAGUE on each side. `id=29174` is Paul George on dev and
Max Kepler on prod.

So a promotion keyed on `players.id` does not fail loudly, it silently attributes one
athlete's data to another. This script therefore joins on `espn_id` and on nothing else. A row
without one is skipped and counted, never guessed at.

What it does NOT do
-------------------
It fills blanks only. A row whose target already carries a position is left alone even when
the source disagrees, because "the other database says something different" is not evidence
about which one is right -- that is a reconciliation, and it needs its own decision. Those
disagreements are reported so they cannot hide.

Usage
-----
    python3 promote_player_positions.py --from data/picks.dev.db --to data/picks.db \
        --league ncaaf
    python3 promote_player_positions.py --from data/picks.dev.db --to data/picks.db \
        --league ncaaf --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys


def run(src_path, dst_path, leagues, apply_changes):
    src = sqlite3.connect("file:%s?mode=ro" % src_path, uri=True)
    dst = sqlite3.connect(dst_path)
    for league in leagues:
        source = {
            r[0]: (r[1], r[2]) for r in src.execute(
                "SELECT espn_id, position, position_group FROM players WHERE league=? "
                "AND COALESCE(espn_id,'') != '' AND COALESCE(position,'') != ''", (league,))
        }
        targets = dst.execute(
            "SELECT id, espn_id, name, position FROM players WHERE league=?", (league,)
        ).fetchall()

        fills, no_publisher_id, unanswered, disagree = [], 0, 0, []
        for pid, espn_id, name, position in targets:
            if (position or "").strip():
                if espn_id in source and source[espn_id][0] != position:
                    disagree.append((name, position, source[espn_id][0]))
                continue
            if not espn_id:
                no_publisher_id += 1
                continue
            if espn_id not in source:
                unanswered += 1
                continue
            fills.append((source[espn_id][0], source[espn_id][1], pid))

        print("%s: %d blank rows the source can answer | %d blank with NO publisher id "
              "(unmatchable) | %d blank whose id the source does not hold"
              % (league, len(fills), no_publisher_id, unanswered))
        if disagree:
            print("  %d rows where both databases have a position and they DIFFER "
                  "(left alone): %s" % (len(disagree), disagree[:3]))
        if not apply_changes:
            print("  (dry run -- pass --apply to write)")
            continue
        with dst:
            dst.executemany(
                "UPDATE players SET position=?, position_group=? WHERE id=?", fills)
        left = dst.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1 "
            "AND COALESCE(entity_type,'player')='player' "
            "AND (position IS NULL OR TRIM(position)='')", (league,)).fetchone()[0]
        print("  wrote %d | active players still with no position: %d" % (len(fills), left))

    src.close()
    dst.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--to", dest="dst", required=True)
    ap.add_argument("--league", action="append", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    sys.exit(run(args.src, args.dst, args.league, args.apply))


if __name__ == "__main__":
    main()
