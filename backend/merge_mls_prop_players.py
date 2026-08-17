#!/usr/bin/env python3
"""Merge Bovada-minted MLS player rows into their published ESPN identity.

`bovada_scraper.py` mints a `players` row from a sportsbook display name when it
cannot resolve one, so MLS carries 183 rows with **no espn_id, no game logs, and
props attached** -- shadow copies of athletes who already exist in the spine
under their published ESPN identity. Two consequences, measured 2026-08-16 on
the dev DB:

  * `C/vocabulary[position]` reports 183 ACTIVE players with no position. They
    have none because a sportsbook does not publish one.
  * prop -> player -> game_log never joins for those 183, because the row
    holding the props is not the row holding the logs.

This is a MERGE, not a column fill: `players` is UNIQUE(espn_id, league), so the
espn_id cannot simply be copied onto the duplicate. Props are repointed at the
canonical row and the shadow row is deleted. `props` is the only table that
references them (verified across all 15 tables carrying a player_id).

**The matching rule, and what it deliberately refuses.** A candidate must match
on normalized name AND the same team code, and there must be exactly ONE. The
normalization is the repo's existing one (NFKD accent-strip, suffix strip, case
and punctuation fold) -- Bovada writes `Hector Herrera`, ESPN publishes
`Héctor Herrera`. That is the same string, not a fuzzy neighbour.

Cross-team matches are NEVER merged, even when unique. Without a publisher id a
same-name-different-team pair is indistinguishable from a namesake, and this
repo has already paid for that assumption once (see the ambiguous-key memory:
a surname where an athlete id exists misses silently over 601,824 settled
props). They are reported for review instead.

Usage:
  cd backend && venv/bin/python merge_mls_prop_players.py \\
      --db /abs/path/picks.db [--apply]

Dry run by default. Idempotent: a merged shadow row no longer exists, so a
second run finds nothing to do.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sqlite3
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from team_codes import normalize_optional  # noqa: E402

LEAGUE = "mls"


def team_key(code):
    """Compare teams through the repo's alias map, not as raw strings.

    Bovada writes NYRB where ESPN publishes RBNY. Comparing raw strings makes
    that look like a different club and silently refuses a correct merge --
    the team-code vocabulary defect this repo has hit before.
    """
    try:
        return normalize_optional(LEAGUE, code) or code
    except Exception:  # noqa: BLE001 — an unknown code is its own key
        return code


def normalize_name(value: str) -> str:
    """The repository's stored alias normalization. No fuzzy matching."""
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", value.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value)).strip()


def plan(con) -> dict:
    """Classify every shadow row without writing anything."""
    spine = collections.defaultdict(list)
    for row in con.execute(
        "SELECT id, name, team, espn_id, position, position_group FROM players "
        "WHERE league=? AND espn_id IS NOT NULL AND position IS NOT NULL "
        "AND TRIM(position) != ''", (LEAGUE,)
    ):
        spine[normalize_name(row["name"])].append(row)

    shadows = con.execute(
        "SELECT id, name, team FROM players WHERE league=? AND espn_id IS NULL",
        (LEAGUE,)).fetchall()

    out = {"merge": [], "cross_team": [], "ambiguous": [], "no_candidate": []}
    for shadow in shadows:
        candidates = spine.get(normalize_name(shadow["name"]), [])
        key = team_key(shadow["team"])
        same_team = [c for c in candidates if team_key(c["team"]) == key]
        if len(same_team) == 1:
            out["merge"].append((shadow, same_team[0]))
        elif len(same_team) > 1:
            out["ambiguous"].append((shadow, same_team))
        elif len(candidates) == 1:
            out["cross_team"].append((shadow, candidates[0]))
        elif candidates:
            out["ambiguous"].append((shadow, candidates))
        else:
            out["no_candidate"].append(shadow)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        work = plan(con)
        shadows = sum(len(v) for v in work.values())
        print("database: {}".format(args.db))
        print("shadow {} rows (no espn_id): {}".format(LEAGUE, shadows))
        print("  merge into published identity: {}".format(len(work["merge"])))
        print("  REFUSED, different team:      {}".format(len(work["cross_team"])))
        print("  REFUSED, ambiguous:           {}".format(len(work["ambiguous"])))
        print("  no candidate in the spine:    {}".format(len(work["no_candidate"])))
        for shadow, canonical in work["cross_team"]:
            print("    cross-team {!r}: {} vs published {} -- not merged"
                  .format(shadow["name"], shadow["team"], canonical["team"]))

        if not work["merge"]:
            print("FAIL: {} shadow rows and none matched a published identity."
                  .format(shadows))
            return 2

        if not args.apply:
            print("\ndry run -- nothing written. re-run with --apply")
            return 0

        moved = 0
        for shadow, canonical in work["merge"]:
            cur = con.execute("UPDATE props SET player_id=? WHERE player_id=?",
                              (canonical["id"], shadow["id"]))
            moved += cur.rowcount
            con.execute("DELETE FROM players WHERE id=?", (shadow["id"],))
        # A shadow and its canonical row could in principle both hold the same
        # line; collapse exact duplicates rather than leave the prop counted
        # twice.
        deduped = con.execute("""
            DELETE FROM props WHERE id NOT IN (
              SELECT MIN(id) FROM props
              GROUP BY game_id, player_id, market, line, side, source)
            AND player_id IN (SELECT id FROM players WHERE league=?)""",
            (LEAGUE,)).rowcount
        con.commit()

        remaining = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND espn_id IS NULL",
            (LEAGUE,)).fetchone()[0]
        expected = shadows - len(work["merge"])
        print("\nmerged {} rows, repointed {} props, removed {} duplicate props"
              .format(len(work["merge"]), moved, deduped))
        print("shadow rows now: {} (expected {}){}".format(
            remaining, expected, "" if remaining == expected else "  <-- MISMATCH"))
        return 0 if remaining == expected else 2
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
