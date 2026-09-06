#!/usr/bin/env python3
"""audit_ncaaf_duplicate_players.py: two ids for one person, decided by the publisher.

A name collision is NOT evidence of a duplicate. Two players named Nick Brown play corner
for Utah in the same roster; one is from Orem and one is from Cypress. Merging on a name
match is how MLB rows ended up carrying a pitcher's name, so this never does it.

What it uses instead is the publisher's own description of the athlete. CFBD's
`/roster?year=` publishes jersey, position, height, weight, home city, home state and class
year per athlete id. When two ids share a league, a name, a team AND every one of those
published fields, the publisher is describing one person twice. When any published field
differs, or when either id carries no published description at all, this REFUSES to call it
a duplicate and reports it for a human instead. Evidence unavailable is not a pass.

Measured 2026-09-06 on prod: 10 name+team collisions among 22,843 NCAAF players. Exactly 2
were duplicates by this rule. The other 8 were two real people, a prior-season row, or a
row the publisher no longer describes.

`--apply` deletes ONLY the twin with no references anywhere (props, player_game_logs,
player_source_ids). A twin that is referenced is reported and left alone: folding rows that
carry data is `prop_game_merge`-shaped work and needs its own decision, not a flag on an
audit script.

Usage:
  LP_DB_PATH=.../picks.db venv/bin/python audit_ncaaf_duplicate_players.py
  LP_DB_PATH=.../picks.db venv/bin/python audit_ncaaf_duplicate_players.py --apply
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest_cfbd_logs import _API, _get_json, _season_from_the_schedule

LEAGUE = "ncaaf"
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# Every field CFBD publishes that describes the person rather than the row. `year` is the
# class year, which is why a same-person pair must agree on it too.
_IDENTITY_FIELDS = ("jersey", "position", "height", "weight",
                    "homeCity", "homeState", "year")


def _described(row):
    """The publisher's description, or None when it published nothing usable.

    A row of all-empty fields would otherwise 'match' another empty row and merge two
    strangers, so an undescribed athlete can never take part in a match.
    """
    if not row:
        return None
    values = tuple(str(row.get(field) or "").strip() for field in _IDENTITY_FIELDS)
    # A single populated field is not a description. Keno Jones published only a class year,
    # and comparing that against a fully described twin produced the confident claim "two
    # real people" from one differing field. Three is the floor for an opinion.
    return values if sum(1 for value in values if value) >= 3 else None


def _references(con, player_id):
    counts = {}
    for table in ("props", "player_game_logs", "player_source_ids"):
        try:
            counts[table] = con.execute(
                "SELECT COUNT(*) FROM %s WHERE player_id=?" % table, (player_id,)
            ).fetchone()[0]
        except sqlite3.Error:
            counts[table] = 0
    return counts


def audit(apply_changes=False, season=None):
    season = season if season is not None else _season_from_the_schedule(DB)
    if season is None:
        raise SystemExit("no season could be read from the database")
    published = {str(r.get("id")): r for r in (_get_json(
        "%s/roster?year=%d" % (_API, season)) or [])}
    print("published roster %d: %d athletes described" % (season, len(published)))

    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    collisions = con.execute(
        "SELECT name, team FROM players WHERE league=? AND name IS NOT NULL "
        "GROUP BY name, team HAVING COUNT(*) > 1", (LEAGUE,)).fetchall()

    duplicates, distinct_people, undecidable, deleted = [], [], [], 0
    for collision in collisions:
        rows = con.execute(
            "SELECT id, espn_id FROM players WHERE league=? AND name=? AND team=?",
            (LEAGUE, collision["name"], collision["team"])).fetchall()
        described = {r["id"]: _described(published.get(str(r["espn_id"]))) for r in rows}
        label = "%s (%s)" % (collision["name"], collision["team"])
        if any(value is None for value in described.values()):
            undecidable.append((label, "the publisher does not describe every id"))
            continue
        if len(set(described.values())) != 1:
            distinct_people.append(label)
            continue

        refs = {r["id"]: _references(con, r["id"]) for r in rows}
        empty = [r for r in rows if not any(refs[r["id"]].values())]
        if len(empty) == len(rows):
            # Nobody points at either row, so there is nothing to fold and no way to lose
            # data. Tie-break on the PUBLISHER's id, never on players.id.
            #
            # players.id is database-local: the first run of this kept 5308270 on dev and
            # 5227015 on prod for the same person, inventing a dev/prod divergence in the
            # act of cleaning up. Any tie-break must be a property of the athlete, so that
            # both databases reach the same answer independently.
            keep = min(rows, key=lambda r: (len(str(r["espn_id"])), str(r["espn_id"])))
            empty = [r for r in rows if r["id"] != keep["id"]]
        elif len(empty) == len(rows) - 1:
            keep = next(r for r in rows if r not in empty)
        else:
            undecidable.append(
                (label, "more than one id carries data; folding needs its own decision"))
            continue
        duplicates.append((label, keep["espn_id"], [r["espn_id"] for r in empty]))
        if apply_changes:
            for row in empty:
                con.execute("DELETE FROM players WHERE id=?", (row["id"],))
                deleted += 1
    if apply_changes:
        con.commit()
    con.close()

    # Say the zero: each bucket prints even when empty, so "clean" is distinguishable
    # from "never ran".
    print("collisions examined: %d" % len(collisions))
    print("  duplicates (publisher describes both ids identically): %d" % len(duplicates))
    for label, keep, drop in duplicates:
        print("    %-30s keep %s, drop %s" % (label, keep, ", ".join(drop)))
    print("  two real people (a published field differs): %d" % len(distinct_people))
    for label in distinct_people:
        print("    %s" % label)
    print("  undecidable, left alone: %d" % len(undecidable))
    for label, why in undecidable:
        print("    %-30s %s" % (label, why))
    print("  deleted: %d%s" % (deleted, "" if apply_changes else " (audit only; pass --apply)"))
    return duplicates, distinct_people, undecidable


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="delete the unreferenced twin of a publisher-confirmed duplicate")
    parser.add_argument("--season", type=int)
    args = parser.parse_args(argv)
    audit(apply_changes=args.apply, season=args.season)
    return 0


if __name__ == "__main__":
    sys.exit(main())
