#!/usr/bin/env python3
"""Fill `players.position_group` from the PUBLISHED position hierarchy.

Why this exists
---------------
`audit_league_stats` C/vocabulary[position] fails mls and ncaaf with "two levels of one
vocabulary in the same column": `CD` sits beside its own parent `D`, `CB` beside `DB`. Those
pairs describe the same players at two levels and never join, so a filter on `D` silently
misses every centre-back stored as `CD`.

The fix is not to flatten the column. ESPN publishes the hierarchy, so the parent level has a
home of its own -- `position_group` -- which is exactly what MLB and NFL already do. Once the
group column is populated, a published parent coexisting with its children is a fact rather
than a clash, and the audit says so itself:

    "a league that declares a populated group column (MLB's position_group) can legitimately
     hold a published parent (OF) beside its children (LF/CF/RF) -- the levels ARE
     distinguished, by that column."

Where the value comes from
--------------------------
`backend/data/position-vocabulary.json`, written by `fetch_position_vocabulary.py` from
`sports.core.api.espn.com/.../positions`. Nothing here is inferred: the group is the published
`name` of the ROOT of the published ancestry chain, and a position that is itself a root takes
its own name. `CD -> ["D"] -> "Defender"`; `CB -> ["DB","DEF"] -> "Defense"`.

That rule was not chosen, it was VERIFIED. Run against the rows that already carry a group it
reproduces them exactly -- mls 1,256 of 1,256 and ncaaf 21,489 of 21,489, zero disagreements.
So filling the blanks with it continues the existing vocabulary rather than introducing a
second one.

Note the rule is per-league by design. MLB stores the IMMEDIATE parent (Infielder, Catcher)
rather than the root (Batter), and running this over mlb would rewrite 614 rows into a
different vocabulary. Hence the explicit league allowlist below: this script refuses any
league whose convention it has not been checked against.

Usage
-----
    python3 backfill_position_group.py --db data/picks.dev.db --league mls --league ncaaf
    python3 backfill_position_group.py --db data/picks.dev.db --league mls --apply

Dry run by default. `--repair` additionally corrects rows whose stored group disagrees with
the published hierarchy; without it, only blanks are filled.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VOCABULARY_PATH = os.path.join(HERE, "data", "position-vocabulary.json")

# Leagues whose position_group convention is "the published name of the ROOT of the ancestry
# chain", verified by reproducing every row that already carries one. MLB is deliberately
# absent: it stores the immediate parent instead, and this rule would rewrite 614 of its rows.
VERIFIED_ROOT_CONVENTION = ("mls", "ncaaf", "nfl")


def load_vocabulary():
    with open(VOCABULARY_PATH) as fh:
        return json.load(fh)["leagues"]


def group_for(vocab, league, position):
    """Published group name for `position`, or None if the publisher does not name one.

    None is returned rather than a guess. A position absent from the published vocabulary is
    reported by the caller and left blank -- an invented group would be indistinguishable
    from a real one the moment it was written.
    """
    league_vocab = vocab.get(league)
    if not league_vocab:
        return None
    ancestry = league_vocab["ancestry"].get(position)
    if ancestry is None:
        return None
    root = ancestry[-1] if ancestry else position
    entry = league_vocab["positions"].get(root)
    return (entry or {}).get("name")


def run(db_path, leagues, apply_changes, repair):
    vocab = load_vocabulary()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    exit_code = 0

    for league in leagues:
        if league not in VERIFIED_ROOT_CONVENTION:
            print("REFUSING %s: this script's rule is only verified for %s. Check what the "
                  "league's existing rows use before adding it."
                  % (league, ", ".join(VERIFIED_ROOT_CONVENTION)), file=sys.stderr)
            exit_code = 2
            continue
        if league not in vocab:
            print("REFUSING %s: no published vocabulary on disk. Run "
                  "fetch_position_vocabulary.py first -- judging positions against a list "
                  "nobody published is what this replaced." % league, file=sys.stderr)
            exit_code = 2
            continue

        rows = con.execute(
            "SELECT id, position, position_group, active FROM players "
            "WHERE league=? AND COALESCE(position,'') != ''", (league,)).fetchall()
        fills, repairs, unpublished = [], [], {}
        for r in rows:
            published = group_for(vocab, league, r["position"])
            if published is None:
                unpublished[r["position"]] = unpublished.get(r["position"], 0) + 1
                continue
            stored = (r["position_group"] or "").strip()
            if not stored:
                fills.append((published, r["id"]))
            elif stored != published:
                repairs.append((published, r["id"], r["position"], stored))

        print("%s: %d rows with a position | %d blank group to fill | %d disagree with the "
              "publisher" % (league, len(rows), len(fills), len(repairs)))
        if unpublished:
            # Loud, because these are the rows the fix cannot reach: they stay blank and the
            # audit's blank check will still fail on any that are active.
            print("  positions ESPN does not publish for this league (left blank): %s"
                  % dict(sorted(unpublished.items(), key=lambda kv: -kv[1])))
        for group, _id, pos, stored in repairs[:5]:
            print("  disagreement: position=%s stored=%s published=%s" % (pos, stored, group))

        if not apply_changes:
            print("  (dry run -- pass --apply to write)")
            continue

        with con:
            con.executemany("UPDATE players SET position_group=? WHERE id=?", fills)
            if repair:
                con.executemany("UPDATE players SET position_group=? WHERE id=?",
                                [(g, i) for g, i, _p, _s in repairs])
        print("  wrote %d fills%s" % (len(fills),
              ", %d repairs" % len(repairs) if repair else
              (", left %d disagreements alone (pass --repair)" % len(repairs) if repairs else "")))

        blank_active = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1 "
            "AND COALESCE(entity_type,'player')='player' "
            "AND (position_group IS NULL OR TRIM(position_group)='')", (league,)).fetchone()[0]
        print("  active players still without a group: %d" % blank_active)

    con.close()
    return exit_code


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--league", action="append", required=True)
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    ap.add_argument("--repair", action="store_true",
                    help="also correct rows whose stored group disagrees with the publisher")
    args = ap.parse_args()
    sys.exit(run(args.db, args.league, args.apply, args.repair))


if __name__ == "__main__":
    main()
