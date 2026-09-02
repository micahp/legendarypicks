#!/usr/bin/env python3
"""spine_merge.py -- one generic repair for a person recorded twice, any league.

Why generic. There are five one-off dedupers in this directory, each written for one
league during one incident, and every one of them silently orphans rows. Measured
2026-08-24 against the real schema:

  14 tables carry a player_id column
  5  of them declare a FOREIGN KEY, so 9 are unenforced and nothing raises
  dedupe_nfl.py           touches 3   (misses all EIGHT nfl_* tables)
  dedupe_mlb.py           touches 5
  merge_mls_prop_players.py touches 1

A hardcoded table list is wrong the day someone adds a table, and wrong quietly, because
an orphaned player_id is not an error anywhere -- the row just stops joining. So this
DISCOVERS the referencing columns from the schema every run: the foreign keys plus the
`*player_id` naming convention the unenforced tables follow. If a future table follows
neither, it will be missed, so `referencing_columns` is asserted against a known count in
the tests and that assertion is the thing that fails when the schema grows.

What it repairs. One league, one name, one row carrying a publisher id and one without.
That is a person recorded twice: the resolved row, and the row a name-keyed ingest minted
before anyone had an id for them. Prod held 547 such groups before any of today's work,
536 of them NFL.

What it refuses:
  - a name held by two rows that BOTH carry ids (two real players do share a name; NFL
    has 442 such groups and NCAAF 171, and they are the spine working)
  - a name held by more than one id-less row, or more than one id-carrying row, because
    which merges into which is then a guess
  - anything where the surviving row is not uniquely determined

Plan first, apply second, in one transaction, like every other ingest here.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))


def referencing_columns(con) -> List[Tuple[str, str]]:
    """Every (table, column) that holds a players.id, discovered from the schema.

    Two signals, unioned, because neither is sufficient: only 5 of the 14 tables declare
    the foreign key, and `nfl_adp` carries `espn_player_id` alongside `player_id`, which
    is NOT a players.id and must not be rewritten.
    """
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    found = []
    for table in tables:
        if table == "players":
            continue
        cols = {r[1] for r in con.execute("PRAGMA table_info('{}')".format(table))}
        by_fk = {r[3] for r in con.execute("PRAGMA foreign_key_list('{}')".format(table))
                 if r[2] == "players"}
        for col in sorted(cols):
            # `espn_player_id` holds a PUBLISHER's id, not ours. Rewriting it would
            # corrupt the very identity this repair exists to consolidate.
            if col in by_fk or (col == "player_id"):
                found.append((table, col))
    return sorted(found)


@dataclass
class Merge:
    league: str
    name: str
    keep_id: int
    drop_id: int
    keep_espn_id: str
    moved: Dict[str, int] = field(default_factory=dict)


@dataclass
class MergePlan:
    merges: List[Merge] = field(default_factory=list)
    refused: List[Tuple[str, str, str]] = field(default_factory=list)
    columns: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def mutations(self) -> int:
        return len(self.merges)


def build_plan(con, league: Optional[str] = None, limit: Optional[int] = None) -> MergePlan:
    con.row_factory = sqlite3.Row
    plan = MergePlan(columns=referencing_columns(con))

    where = "WHERE league = ?" if league else ""
    args: Sequence = (league,) if league else ()
    groups = con.execute(
        "SELECT league, name, COUNT(*) n FROM players {} GROUP BY league, name "
        "HAVING n > 1".format(where), args).fetchall()

    for group in groups:
        rows = con.execute(
            "SELECT id, name, espn_id FROM players WHERE league=? AND name=? ORDER BY id",
            (group["league"], group["name"])).fetchall()
        with_id = [r for r in rows if (r["espn_id"] or "").strip()]
        without = [r for r in rows if not (r["espn_id"] or "").strip()]

        if not without:
            continue  # distinct publisher ids: two real people, the spine working
        if not with_id:
            plan.refused.append((group["league"], group["name"],
                                 "every row is unresolved; nothing to merge into"))
            continue
        if len(with_id) > 1:
            plan.refused.append((group["league"], group["name"],
                                 "{} rows carry ids; which one survives is a guess".format(
                                     len(with_id))))
            continue
        if len(without) > 1:
            plan.refused.append((group["league"], group["name"],
                                 "{} id-less rows; which merges in is a guess".format(
                                     len(without))))
            continue

        keep, drop = with_id[0], without[0]
        moved = {}
        for table, col in plan.columns:
            n = con.execute("SELECT COUNT(*) FROM {} WHERE {}=?".format(table, col),
                            (drop["id"],)).fetchone()[0]
            if n:
                moved[table] = n
        plan.merges.append(Merge(group["league"], group["name"], keep["id"], drop["id"],
                                 keep["espn_id"], moved))
        if limit and len(plan.merges) >= limit:
            break
    return plan


def render(plan: MergePlan, emit=print, show: int = 12) -> None:
    emit("  discovered {} player_id columns across the schema".format(len(plan.columns)))
    emit("  {} merges planned, {} refused".format(len(plan.merges), len(plan.refused)))
    by_league: Dict[str, int] = {}
    for m in plan.merges:
        by_league[m.league] = by_league.get(m.league, 0) + 1
    for lg, n in sorted(by_league.items(), key=lambda kv: -kv[1]):
        emit("    {:<7} {}".format(lg, n))
    for m in plan.merges[:show]:
        detail = ", ".join("{} x{}".format(t, n) for t, n in sorted(m.moved.items())) or "no rows"
        emit("    MERGE {:<6} {!r}: drop {} into {} (espn {}) moving {}".format(
            m.league, m.name, m.drop_id, m.keep_id, m.keep_espn_id, detail))
    for league, name, why in plan.refused[:show]:
        emit("    REFUSE {:<6} {!r}: {}".format(league, name, why))


def apply_plan(con, plan: MergePlan) -> Dict[str, int]:
    """Repoint every reference, then delete the now-unreferenced row."""
    counts = {"merged": 0, "rows_moved": 0, "aliases": 0}
    for m in plan.merges:
        for table, col in plan.columns:
            cur = con.execute(
                "UPDATE OR IGNORE {} SET {}=? WHERE {}=?".format(table, col, col),
                (m.keep_id, m.drop_id))
            counts["rows_moved"] += cur.rowcount
        # A UNIQUE constraint can leave a row behind that UPDATE OR IGNORE skipped; it
        # would become an orphan pointing at a deleted player, so drop those explicitly.
        for table, col in plan.columns:
            con.execute("DELETE FROM {} WHERE {}=?".format(table, col), (m.drop_id,))
        cur = con.execute(
            "DELETE FROM players WHERE id=? AND league=? AND NULLIF(espn_id,'') IS NULL",
            (m.drop_id, m.league))
        counts["merged"] += cur.rowcount
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # LP_DB_PATH is how every other tool on this box is pointed at a database,
    # and this one ignored it and defaulted to PROD. So
    # `LP_DB_PATH=data/picks.dev.db spine_merge.py --apply` read as a dev
    # rehearsal and would have merged rows in prod. A destructive tool must
    # never resolve to prod through the same variable the operator used to say
    # "not prod"; --db stays as the explicit override.
    ap.add_argument("--db", default=(os.environ.get("LP_DB_PATH")
                                     or os.path.join(HERE, "data", "picks.db")))
    ap.add_argument("--league")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--apply", action="store_true", help="without this it only reports")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.db):
        print("spine_merge: no database at {}".format(args.db), file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    try:
        plan = build_plan(con, args.league, args.limit)
        # Absolute, and printed before anything is written. A relative path
        # resolves against the cwd, so "data/picks.dev.db" in a log does not
        # identify a database -- and telling two environments apart by how good
        # their data looks is how a frozen snapshot passed for dev once already.
        print("db: {}".format(os.path.abspath(args.db)))
        render(plan)
        if not args.apply:
            print("  dry run; pass --apply to write")
            return 0
        if not plan.mutations:
            return 0
        with con:
            counts = apply_plan(con, plan)
        print("  applied: {merged} rows merged, {rows_moved} references moved".format(**counts))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
