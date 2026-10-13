#!/usr/bin/env python3
"""repair_reviewed_player_names.py — the stored names a publisher contradicts outright.

WHY THIS IS A LIST AND NOT A REFRESH
------------------------------------
`refresh_soccer_player_teams.py` copies a club from the publisher because a club is a
definition. The obvious next step is to do the same for names, and it is wrong.

Measured on prod 2026-09-07: of 1,514 bound players, 14 have a stored name that no
publisher spelling folds to. Thirteen of those are OUR rendering of the same human, and in
several the publisher's is worse:

    JT Marcinkowski      published "James Marcinkowski"
    Evander              published "Evander Da Silva Ferreira"
    AJ Marcucci          published "Anthony Marcucci"
    Drew Baiera          published "Andrew Baiera"
    Kim Kee-Hee          published "Kee-Hee Kim"      (name order)
    Serge Ngoma          published "Serge Ngoma Jr."  (suffix)
    Artem Smolyakov      published "Artem Smoliakov"  (transliteration)

A blanket refresh would rename all of them, which is why this is a reviewed list instead.
Each entry is checked once, by a person, against a published source, and written down with
that source. Anyone can check any line. Same reasoning as
`published_roster.REVIEWED_ALIASES`: a judgment call belongs in version control where its
evidence travels with it.

Usage:
  cd backend && python3 repair_reviewed_player_names.py --db data/picks.db [--apply]

Dry run by default. Idempotent, and it refuses to act on a row that does not still hold the
exact wrong name, so a later correct value is never overwritten.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys

# (league, publisher id source, source key, wrong stored name, published name, evidence)
#
# Keyed on the PUBLISHER'S id, not on the name, so this repairs the person rather than
# whichever row happens to carry a string today.
REVIEWED_NAMES = [
    (
        "mls", "mlssoccer", "563259", "Alisa Randell", "Darius Randell",
        # mlssoccer.com displays "Darius Randell" and files him at /players/alisa-randell/;
        # /players/darius-randell/ is a 404. FotMob 1666617 and MLSsoccer 563259 both
        # publish "Darius Randell". Our row carries espn_id 381237 and Minnesota game logs,
        # so it is the right person under a spelling that looks slug-derived. Bovada sent
        # "Darius Randell" 96 times from 2026-08-17 and every one went unresolved.
        "mlssoccer.com/players/alisa-randell/ displays Darius Randell; FotMob 1666617 agrees",
    ),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.db):
        print("no such database: {}".format(args.db))
        return 2

    con = sqlite3.connect(args.db, timeout=30)
    try:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        changed = skipped = 0
        print("{}:".format(args.db))
        for league, source, key, wrong, right, evidence in REVIEWED_NAMES:
            row = con.execute(
                "SELECT p.id, p.name FROM player_source_ids s JOIN players p ON p.id=s.player_id "
                "WHERE s.source=? AND s.league=? AND s.source_player_key=?",
                (source, league, key)).fetchone()
            if row is None:
                print("  {} {}: no player bound to that publisher id; skipped".format(
                    source, key))
                skipped += 1
                continue
            player_id, current = row
            if current == right:
                print("  {} (id {}): already correct".format(right, player_id))
                continue
            if current != wrong:
                # Somebody or something has changed it since this line was reviewed. That
                # is a new fact, and overwriting it would discard a review nobody has done.
                print("  {} (id {}): holds {!r}, not the reviewed {!r}; SKIPPED".format(
                    right, player_id, current, wrong))
                skipped += 1
                continue
            print("  id {}: {!r} -> {!r}".format(player_id, current, right))
            print("      {}".format(evidence))
            changed += 1
            if args.apply:
                con.execute("UPDATE players SET name=?, updated_at=? WHERE id=?",
                            (right, now, player_id))
        if args.apply and changed:
            con.commit()
            print("  applied {} rename(s), {} skipped".format(changed, skipped))
        elif changed:
            print("  {} rename(s) would apply, {} skipped (dry run)".format(changed, skipped))
        else:
            print("  nothing to do ({} skipped)".format(skipped))
        return 1 if skipped else 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
