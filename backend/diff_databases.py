#!/usr/bin/env python3
"""What does PROD hold that DEV does not, and vice versa?

Every gate in this repo runs against whichever database you point it at, so a
green run proves nothing about the other one. On 2026-08-05 that cost five
separate defects, each of them correct in code and absent from production:

  * NFL `rush_td`/`rec_td` -- v0.7.3's headline feature, 0 rows in prod through
    three releases while dev had it
  * NBA season stats 2026 -- dev had 576 rows, prod served 2023
  * MLB `position_group` / `pitcher_role` -- dev migrated, prod had no column
  * NBA 2025 -- never ingested to prod
  * NHL season keys -- `migrate_nhl_season_keys.py` ran on dev 2026-08-02; prod
    still held 48,017 rows at nhle.com's raw `20252026`, so a season-scoped
    join returned 0 for NHL and 6k-52k for every other league

None of them raised. Both databases answered 200 throughout, and the audit was
green against dev. The only thing that distinguishes them is a diff nobody ran.

This is that diff. It reports three things and exits non-zero on any of them:

  1. SCHEMA   -- a table or column one side has and the other does not
  2. SEASONS  -- a (league, season) present on one side and missing on the other
  3. VOLUME   -- a row count differing by more than --tolerance (default 5%)

Divergence is not automatically wrong: dev is often deliberately ahead. The
point is that it should be a decision someone made, not a discovery weeks later.

Usage:
  cd backend && venv/bin/python diff_databases.py
  venv/bin/python diff_databases.py --prod data/picks.db --dev data/picks.dev.db
  venv/bin/python diff_databases.py --quiet      # only differences
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROD = os.path.join(HERE, "data", "picks.db")
DEFAULT_DEV = os.path.join(HERE, "data", "picks.dev.db")

# Tables whose divergence is expected and uninteresting: caches, scratch and
# anything a background timer rewrites on its own schedule.
SKIP = {"sqlite_sequence", "sqlite_stat1"}


def _open(path):
    if not os.path.exists(path):
        raise SystemExit(f"diff_databases: no such database: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _tables(con):
    return {
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
    } - SKIP


def _columns(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}


def _count(con, table):
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except sqlite3.Error:
        return None


def _seasons(con, table):
    """(league, season) pairs, or None if the table is not season-scoped."""
    cols = _columns(con, table)
    if not {"league", "season"} <= cols:
        return None
    return {
        (str(r[0]), str(r[1])) for r in con.execute(
            f'SELECT DISTINCT league, season FROM "{table}"')
        if r[0] is not None and r[1] is not None
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prod", default=DEFAULT_PROD)
    ap.add_argument("--dev", default=DEFAULT_DEV)
    ap.add_argument("--tolerance", type=float, default=0.05,
                    help="row-count difference to ignore, as a fraction (default 0.05)")
    ap.add_argument("--quiet", action="store_true",
                    help="print only differences")
    args = ap.parse_args(argv)

    prod, dev = _open(args.prod), _open(args.dev)
    findings: list[str] = []

    # 1. SCHEMA ---------------------------------------------------------------
    pt, dt = _tables(prod), _tables(dev)
    for name in sorted(dt - pt):
        findings.append(f"SCHEMA   table {name!r} exists in DEV, missing from PROD")
    for name in sorted(pt - dt):
        findings.append(f"SCHEMA   table {name!r} exists in PROD, missing from DEV")

    shared = sorted(pt & dt)
    for table in shared:
        pc, dc = _columns(prod, table), _columns(dev, table)
        for col in sorted(dc - pc):
            findings.append(f"SCHEMA   {table}.{col} exists in DEV, missing from PROD")
        for col in sorted(pc - dc):
            findings.append(f"SCHEMA   {table}.{col} exists in PROD, missing from DEV")

    # 2. SEASONS --------------------------------------------------------------
    # The highest-signal check: a season present on one side and absent on the
    # other is what "the ingest ran on dev" looks like from the outside.
    for table in shared:
        ps, ds = _seasons(prod, table), _seasons(dev, table)
        if ps is None or ds is None:
            continue
        for league, season in sorted(ds - ps):
            findings.append(
                f"SEASONS  {table}: ({league}, {season}) in DEV, missing from PROD")
        for league, season in sorted(ps - ds):
            findings.append(
                f"SEASONS  {table}: ({league}, {season}) in PROD, missing from DEV")

    # 3. VOLUME ---------------------------------------------------------------
    for table in shared:
        pn, dn = _count(prod, table), _count(dev, table)
        if pn is None or dn is None or pn == dn:
            continue
        denominator = max(pn, dn) or 1
        drift = abs(pn - dn) / denominator
        if drift > args.tolerance:
            findings.append(
                f"VOLUME   {table}: prod={pn} dev={dn} "
                f"({drift * 100:.0f}% apart)")

    if not args.quiet:
        print(f"prod: {args.prod}")
        print(f"dev : {args.dev}")
        print(f"tables: {len(pt)} prod / {len(dt)} dev, {len(shared)} shared")
        print()

    if not findings:
        print("no divergence: schema, seasons and row counts agree")
        return 0

    for line in findings:
        print(line)
    print()
    print(f"{len(findings)} difference(s). Divergence is not automatically wrong -- "
          "dev is often deliberately ahead. It should be a decision, not a discovery.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
