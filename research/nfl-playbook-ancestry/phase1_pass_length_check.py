#!/usr/bin/env python3
"""Read-only comparison of the local raw pass_length field with dev nfl_pbp."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import duckdb


SEASONS = range(2022, 2026)


def play_key(game_id: str, play_id: object) -> tuple[str, int]:
    value = float(play_id)
    if not value.is_integer():
        raise RuntimeError(f"non-integer play_id for {game_id}: {play_id!r}")
    return game_id, int(value)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(db_path: Path, parquet_dir: Path) -> dict:
    db = db_path.resolve()
    if not db.is_file():
        raise SystemExit(f"dev database does not exist: {db}")
    sqlite_uri = f"file:{quote(str(db), safe='/')}?mode=ro"
    sql = sqlite3.connect(sqlite_uri, uri=True, timeout=30)
    sql.row_factory = sqlite3.Row
    sql.execute("PRAGMA query_only=ON")
    if sql.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise RuntimeError("SQLite did not enable query_only")
    sql.execute("BEGIN")
    parquet = duckdb.connect(":memory:")
    result = {}
    try:
        for season in SEASONS:
            path = (parquet_dir / f"play_by_play_{season}.parquet").resolve()
            if not path.is_file():
                raise SystemExit(f"raw parquet does not exist: {path}")
            raw_rows = parquet.execute(
                """SELECT game_id,play_id,pass_length FROM read_parquet(?)
                   WHERE season_type='REG' AND play_type='pass'""",
                [str(path)],
            ).fetchall()
            raw = {}
            counts = Counter()
            for game_id, play_id, pass_length in raw_rows:
                key = play_key(game_id, play_id)
                if key in raw:
                    raise RuntimeError(f"duplicate raw regular-season pass key: {key}")
                raw[key] = pass_length
                counts[pass_length] += 1

            db_rows = sql.execute(
                "SELECT game_id,play_id FROM nfl_pbp WHERE season=? AND play_type='pass'",
                (season,),
            ).fetchall()
            db_keys = {play_key(row["game_id"], row["play_id"]) for row in db_rows}
            if len(db_keys) != len(db_rows):
                raise RuntimeError(f"duplicate dev PBP pass key in {season}")
            raw_keys = set(raw)
            result[str(season)] = {
                "source_file": str(path),
                "source_sha256": sha256(path),
                "regular_season_raw_pass_rows": len(raw_rows),
                "dev_nfl_pbp_pass_rows": len(db_rows),
                "raw_only_keys": len(raw_keys - db_keys),
                "dev_only_keys": len(db_keys - raw_keys),
                "pass_length_rows_by_value": [
                    {"value": value, "rows": count}
                    for value, count in sorted(counts.items(), key=lambda item: (item[0] is not None, item[0] or ""))
                ],
            }
    finally:
        parquet.close()
        sql.close()
    return {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(db),
        "local_raw_directory": str(parquet_dir.resolve()),
        "join_rule": "Exact game_id and integer-valued play_id; regular-season pass rows only.",
        "interpretation": "pass_length short/deep is an observed depth bucket, not a route or named play concept; it is outside the dev nfl_pbp schema.",
        "seasons": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--parquet-dir", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(collect(args.db, args.parquet_dir), indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
