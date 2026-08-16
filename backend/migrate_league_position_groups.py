#!/usr/bin/env python3
"""Give NFL and NBA the same group-column split MLB already has.

`players.position` for NFL and NBA holds two levels of one vocabulary in the
same column: the group-level parent (NFL `RB`, NBA `F`) sits beside its own
child (NFL `FB`, NBA `PF`) on active rows, so `WHERE position='RB'` silently
misses every fullback and the audit's C/vocabulary[position] reports:

    two levels of one vocabulary in the same column: FB under RB
    two levels of one vocabulary in the same column: PF under F

MLB solved this exact problem (migrate_mlb_position_vocabulary.py, commit
da63c5a): `position` keeps the specific spot, `position_group` carries the
parent type the publisher publishes alongside it, and check C learns the
split is addressable via a populated group column.

This migration does the same for NFL and NBA, sourced from the committed
publisher vocabulary (data/position-vocabulary.json), not a hand-rolled list:

  NFL  position_group = parent of the leaf (FB -> RB, LB -> DEF, ...)
  NBA  position_group = parent of the leaf (PF -> F, SG -> G, ...)

The parent/child split already lives in the vocabulary file's `parent_id`
edges; this migration just materializes the group level for the rows that
carry a leaf whose parent is itself a published position. Leaf positions
whose parent is not a real position code (e.g. NFL `C` -> OL via a
non-position id) are left NULL -- there is no group to distinguish.

Purely additive: adds nothing to `position`, writes `position_group` only for
NFL/NBA, idempotent, backup-first (VACUUM INTO, never cp).

Usage:
  cd backend && venv/bin/python migrate_league_position_groups.py \
      --db /abs/path/picks.dev.db [--apply]

Dry run by default.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_schema import MigrationError, create_verified_backup  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
VOCABULARY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "position-vocabulary.json"
)

LEAGUES = ("nfl", "nba")


def _load_vocabulary() -> dict:
    with open(VOCABULARY_PATH) as f:
        data = json.load(f)
    return data["leagues"]


def _parent_code(positions: dict, code: str):
    """The published position code that is `code`'s parent, or None."""
    pos = positions.get(code)
    if not pos or pos.get("parent_id") is None:
        return None
    parent_id = pos["parent_id"]
    for other, other_pos in positions.items():
        if other_pos.get("id") == parent_id and other != code:
            return other
    return None


def _top_ancestor(positions: dict, code: str):
    """Walk to the top of the parent chain, returning its position code."""
    seen = set()
    while code in positions and code not in seen:
        seen.add(code)
        parent = _parent_code(positions, code)
        if parent is None:
            return code
        code = parent
    return code


def _group_map(league: str) -> dict[str, str]:
    """{leaf position -> group category} for every published position.

    The group is the top-level ancestor's NAME -- the same shape as MLB's
    `position_group` (primaryPosition.type: Pitcher/Infielder/Outfielder).
    NFL WR -> Offense, CB -> Defense, PK -> Special Teams; NBA PF -> Forward,
    SG -> Guard, C -> Center. A position whose top ancestor has no usable
    name (the NFL '-' Unknown / ATH / SETTER codes) is left unmapped.
    """
    positions = _load_vocabulary()[league]["positions"]
    mapping = {}
    for code, pos in positions.items():
        if not pos or not pos.get("name"):
            continue
        top = _top_ancestor(positions, code)
        top_pos = positions.get(top)
        if not top_pos or not top_pos.get("name"):
            continue
        if top in ("-", "ATH", "SETTER", "NA", "HEAD COACH"):
            continue
        name = top_pos["name"]
        # The NBA top-levels G/F/C have the same code as a leaf; their name is
        # the category, so a position whose top ancestor is itself maps to its
        # own name (C -> Center, F -> Forward, G -> Guard).
        mapping[code] = name
    return mapping


def migrate(db_path: str, *, apply: bool) -> int:
    connection = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in connection.execute("PRAGMA table_info(players)")}
        if "position_group" not in cols:
            print("ERROR: players.position_group does not exist -- run "
                  "migrate_mlb_position_vocabulary.py first", file=sys.stderr)
            return 1

        for league in LEAGUES:
            mapping = _group_map(league)
            current = {
                row[0]: row[1] for row in connection.execute(
                    "SELECT position, position_group FROM players "
                    "WHERE league=? AND position IS NOT NULL AND position_group IS NOT NULL",
                    (league,))
            }
            stale = {p for p, g in current.items() if g != mapping.get(p)}
            print(f"{league}: group map has {len(mapping)} leaf positions; "
                  f"{len(stale)} rows hold a stale group value")
            missing = connection.execute(
                "SELECT COUNT(*) FROM players WHERE league=? AND position IS NOT NULL "
                "AND TRIM(position)!='' AND position_group IS NULL", (league,)).fetchone()[0]
            print(f"  {missing} rows with a position but no position_group")
            if stale:
                print(f"  WARNING: {len(stale)} stale values would be corrected: "
                      f"{sorted(stale)[:8]}")

        if not apply:
            print("\ndry run -- pass --apply to write")
            return 0

        try:
            backup = create_verified_backup(db_path)
        except MigrationError as exc:
            print(f"ERROR: backup failed, nothing written: {exc}", file=sys.stderr)
            return 1
        print(f"backup: {backup} (quick_check=ok)")

        written = 0
        for league in LEAGUES:
            mapping = _group_map(league)
            for position, group in sorted(mapping.items()):
                cur = connection.execute(
                    "SELECT COUNT(*) FROM players WHERE league=? AND position=?",
                    (league, position)).fetchone()[0]
                if not cur:
                    continue
                connection.execute(
                    "UPDATE players SET position_group=? "
                    "WHERE league=? AND position=?",
                    (group, league, position))
                written += cur
        connection.commit()
        print(f"wrote position_group on {written} NFL/NBA rows")
        qc = connection.execute("PRAGMA quick_check").fetchone()[0]
        print(f"quick_check: {qc}")
        return 0 if qc == "ok" else 1
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print(f"database: {args.db}")
    return migrate(args.db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
