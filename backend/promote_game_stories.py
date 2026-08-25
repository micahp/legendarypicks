#!/usr/bin/env python3
"""Promote one league's generated game stories between explicit databases.

Stories are keyed by the publisher-stable ``(league, game_id)`` pair, so this
copy never depends on database-local integer ids. The source is always opened
read-only. A target row is inserted when absent and updated only when the
source ``generated_at`` is newer; equal timestamps with different content are
refused as an unresolved conflict.

Dry-run is the default. Both paths must be absolute, existing, distinct files.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing


REQUIRED_COLUMNS = (
    "league",
    "game_id",
    "story",
    "generated_at",
    "has_form",
    "has_stakes",
    "form_suppressed",
)


class StoryPromotionError(RuntimeError):
    pass


def _validate_path(path: str, label: str) -> str:
    if not os.path.isabs(path):
        raise StoryPromotionError(f"--{label} must be an absolute path")
    if not os.path.isfile(path):
        raise StoryPromotionError(f"--{label} must name an existing file")
    return os.path.realpath(path)


def _connect(path: str, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    return connection


def _validate_schema(connection: sqlite3.Connection, label: str) -> None:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(game_story)")
    }
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise StoryPromotionError(
            f"{label} game_story is missing required columns: {', '.join(missing)}"
        )


def _record(row: sqlite3.Row) -> dict:
    return {column: row[column] for column in REQUIRED_COLUMNS}


def plan(
    source: sqlite3.Connection, target: sqlite3.Connection, league: str
) -> dict:
    _validate_schema(source, "source")
    _validate_schema(target, "target")
    source_rows = [
        _record(row)
        for row in source.execute(
            f"SELECT {','.join(REQUIRED_COLUMNS)} FROM game_story "
            "WHERE league=? ORDER BY game_id",
            (league,),
        )
    ]
    invalid = [
        row
        for row in source_rows
        if not str(row["game_id"] or "").strip()
        or not str(row["story"] or "").strip()
        or not str(row["generated_at"] or "").strip()
    ]
    if invalid:
        raise StoryPromotionError(
            f"source has {len(invalid)} blank game_id, story, or generated_at rows"
        )

    target_rows = {
        str(row["game_id"]): _record(row)
        for row in target.execute(
            f"SELECT {','.join(REQUIRED_COLUMNS)} FROM game_story WHERE league=?",
            (league,),
        )
    }
    inserts, updates, unchanged, target_newer, conflicts = [], [], 0, 0, []
    for row in source_rows:
        held = target_rows.get(str(row["game_id"]))
        if held is None:
            inserts.append(row)
            continue
        if row == held:
            unchanged += 1
            continue
        source_time = str(row["generated_at"])
        target_time = str(held["generated_at"] or "")
        if source_time > target_time:
            updates.append(row)
        elif source_time < target_time:
            target_newer += 1
        else:
            conflicts.append(str(row["game_id"]))
    if conflicts:
        raise StoryPromotionError(
            "equal-timestamp story conflicts for game ids: " + ", ".join(conflicts[:10])
        )
    return {
        "league": league,
        "source_rows": len(source_rows),
        "target_rows_before": len(target_rows),
        "insert": inserts,
        "update": updates,
        "unchanged": unchanged,
        "target_newer": target_newer,
    }


def apply(target: sqlite3.Connection, computed: dict) -> int:
    rows = computed["insert"] + computed["update"]
    target.execute("PRAGMA foreign_keys=ON")
    target.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            target.execute(
                f"""INSERT INTO game_story({','.join(REQUIRED_COLUMNS)})
                    VALUES({','.join('?' for _ in REQUIRED_COLUMNS)})
                    ON CONFLICT(league, game_id) DO UPDATE SET
                      story=excluded.story,
                      generated_at=excluded.generated_at,
                      has_form=excluded.has_form,
                      has_stakes=excluded.has_stakes,
                      form_suppressed=excluded.form_suppressed""",
                [row[column] for column in REQUIRED_COLUMNS],
            )
        for row in rows:
            held = target.execute(
                f"SELECT {','.join(REQUIRED_COLUMNS)} FROM game_story "
                "WHERE league=? AND game_id=?",
                (row["league"], row["game_id"]),
            ).fetchone()
            if held is None or _record(held) != row:
                raise StoryPromotionError(
                    f"post-write verification failed for game {row['game_id']}"
                )
        target.commit()
    except Exception:
        target.rollback()
        raise
    return len(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--league", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    source_path = _validate_path(args.source, "source")
    target_path = _validate_path(args.target, "target")
    if source_path == target_path:
        raise StoryPromotionError("--source and --target must be distinct files")
    league = str(args.league or "").strip().lower()
    if not league:
        raise StoryPromotionError("--league must not be blank")

    with closing(_connect(source_path, readonly=True)) as source, closing(
        _connect(target_path, readonly=not args.apply)
    ) as target:
        source.execute("BEGIN")
        computed = plan(source, target, league)
        print(
            f"league={league} source_rows={computed['source_rows']} "
            f"target_rows_before={computed['target_rows_before']}"
        )
        print(
            f"insert={len(computed['insert'])} update={len(computed['update'])} "
            f"unchanged={computed['unchanged']} target_newer={computed['target_newer']}"
        )
        if not args.apply:
            print("dry_run=ok (pass --apply to promote)")
            return 0
        written = apply(target, computed)
        after = target.execute(
            "SELECT COUNT(*) FROM game_story WHERE league=?", (league,)
        ).fetchone()[0]
        print(f"written={written} target_rows_after={after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
