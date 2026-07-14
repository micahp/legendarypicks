#!/usr/bin/env python3
"""Safely promote the already-ingested UFC rankings from dev to production.

Only ``ufc_rankings`` is replaced. The source is validated before production is
opened, production is backed up, and the replacement is a single transaction.

Run from backend/: python3 migrate_ufc_rankings_to_prod.py
"""
import argparse
import datetime
import os
import sqlite3
import sys

from ingest_ufc_rankings import P4P_DIVISIONS, WEIGHT_DIVISIONS

DEFAULT_DEV = "data/picks.dev.db"
DEFAULT_PROD = "data/picks.db"
EXPECTED_COLUMNS = ["division", "rank", "fighter", "is_champion", "captured_at"]


def _columns(con, schema="main"):
    return [row[1] for row in con.execute(f"PRAGMA {schema}.table_info(ufc_rankings)")]


def _validate_rows(rows):
    if not rows:
        raise ValueError("dev ufc_rankings is empty")
    divisions = {row[0] for row in rows}
    missing_p4p = P4P_DIVISIONS - divisions
    missing_weights = WEIGHT_DIVISIONS - divisions
    if missing_p4p or missing_weights:
        raise ValueError(
            "dev UFC rankings are incomplete: "
            f"missing P4P={sorted(missing_p4p)}, divisions={sorted(missing_weights)}"
        )
    unexpected = divisions - P4P_DIVISIONS - WEIGHT_DIVISIONS
    if unexpected:
        raise ValueError(f"dev UFC rankings contain unexpected divisions: {sorted(unexpected)}")
    expected = P4P_DIVISIONS | WEIGHT_DIVISIONS
    populated = {
        division
        for division, rank, fighter, is_champion, _captured_at in rows
        if division in expected
        and not is_champion
        and isinstance(rank, int)
        and rank > 0
        and fighter
    }
    empty = expected - populated
    if empty:
        raise ValueError(
            "dev UFC rankings have no ranked non-champion rows for: "
            f"{sorted(empty)}"
        )


def promote(dev_path=DEFAULT_DEV, prod_path=DEFAULT_PROD):
    for path in (dev_path, prod_path):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"missing {path}")
    if os.path.realpath(dev_path) == os.path.realpath(prod_path):
        raise ValueError("dev and prod database paths must be different")

    with sqlite3.connect(dev_path) as dev:
        if _columns(dev) != EXPECTED_COLUMNS:
            raise ValueError(
                f"dev ufc_rankings schema mismatch: {_columns(dev)} != {EXPECTED_COLUMNS}"
            )
        rows = dev.execute(
            "SELECT division, rank, fighter, is_champion, captured_at "
            "FROM ufc_rankings ORDER BY division, rank"
        ).fetchall()
    _validate_rows(rows)

    with sqlite3.connect(prod_path) as prod:
        existing_columns = _columns(prod)
        if existing_columns and existing_columns != EXPECTED_COLUMNS:
            raise ValueError(
                f"prod ufc_rankings schema mismatch: {existing_columns} != {EXPECTED_COLUMNS}"
            )
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = f"{prod_path}.bak-premigrate-ufc-{timestamp}"
        with sqlite3.connect(backup_path) as backup:
            prod.backup(backup)
        try:
            with prod:
                prod.execute(
                    "CREATE TABLE IF NOT EXISTS ufc_rankings("
                    "division TEXT, rank INTEGER, fighter TEXT, "
                    "is_champion INTEGER, captured_at TEXT)"
                )
                prod.execute("DELETE FROM ufc_rankings")
                prod.executemany(
                    "INSERT INTO ufc_rankings "
                    "(division, rank, fighter, is_champion, captured_at) "
                    "VALUES (?,?,?,?,?)",
                    rows,
                )
                copied = prod.execute(
                    "SELECT division, rank, fighter, is_champion, captured_at "
                    "FROM ufc_rankings ORDER BY division, rank"
                ).fetchall()
                _validate_rows(copied)
                if len(copied) != len(rows):
                    raise RuntimeError(f"UFC row-count mismatch: dev={len(rows)}, prod={len(copied)}")
        except Exception:
            print(f"migration failed; untouched backup is at {backup_path}", file=sys.stderr)
            raise

    print(f"backed up prod -> {backup_path}")
    print(f"ufc_rankings: promoted {len(rows)} rows across 11 weight divisions")
    return backup_path, len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev", default=DEFAULT_DEV)
    parser.add_argument("--prod", default=DEFAULT_PROD)
    args = parser.parse_args()
    try:
        promote(args.dev, args.prod)
    except (FileNotFoundError, ValueError, RuntimeError, sqlite3.Error) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
