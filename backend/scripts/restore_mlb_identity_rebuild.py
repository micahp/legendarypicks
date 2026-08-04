#!/usr/bin/env python3
"""Read back what an MLB identity rebuild archived, and put it back if asked.

The rebuild deletes players, game logs and aggregates. It does not lose them:
`_archive_rows` writes the ENTIRE row as `payload_json` before deleting it --
measured on a real run, 89 of 89 `player_stats` columns per row, nothing
dropped. That makes every archived row reconstructable.

But an archive nobody can read is a claim, not a backup, and "it's recoverable"
is exactly the sort of thing that stays true right up until someone tries. This
is the thing that tries.

  --list                    what runs exist, what each archived, when
  --show ENTITY             print rows for one entity type from a run
  --restore ENTITY          put them back

`--restore` refuses to overwrite: a row whose id is already present is reported
and skipped, never silently replaced. It restores into whatever `--db` names,
so a dry test against a copy costs one `cp`.

Usage:
  cd backend && venv/bin/python scripts/restore_mlb_identity_rebuild.py \\
      --db data/picks.db --list
  ... --db /tmp/copy.db --run mlb-rebuild-abc123 --restore player_stats
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

ARCHIVE = "player_identity_rebuild_archive"
ENTITIES = ("players", "player_stats", "player_game_logs")


class RestoreError(RuntimeError):
    """The archive cannot support what was asked of it."""


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def list_runs(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        f"""SELECT run_id, entity_type, disposition, COUNT(*) n,
                   MIN(archived_at) first_seen
            FROM {ARCHIVE}
            GROUP BY run_id, entity_type, disposition
            ORDER BY first_seen DESC, n DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def archived_rows(connection: sqlite3.Connection, *, run_id: str | None,
                  entity_type: str) -> list[dict]:
    query = f"SELECT payload_json FROM {ARCHIVE} WHERE entity_type=?"
    params: list = [entity_type]
    if run_id:
        query += " AND run_id=?"
        params.append(run_id)
    return [json.loads(r[0]) for r in
            connection.execute(query + " ORDER BY original_id", params)]


def restore(connection: sqlite3.Connection, *, run_id: str | None,
            entity_type: str, apply: bool) -> dict:
    if entity_type not in ENTITIES:
        raise RestoreError(f"unknown entity type {entity_type!r}")
    payloads = archived_rows(connection, run_id=run_id, entity_type=entity_type)
    if not payloads:
        raise RestoreError(
            f"nothing archived for {entity_type}"
            + (f" in run {run_id}" if run_id else "")
        )
    table_columns = set(_columns(connection, entity_type))
    missing = sorted(set(payloads[0]) - table_columns)
    if missing:
        # The schema moved since the archive was written. Restoring a subset
        # silently would put back a row that is quietly not the row that left.
        raise RestoreError(
            f"{entity_type} no longer has these archived columns: "
            + ", ".join(missing)
        )

    present = {
        int(r[0]) for r in connection.execute(f"SELECT id FROM {entity_type}")
    }
    restored = skipped = 0
    for payload in payloads:
        if int(payload["id"]) in present:
            skipped += 1
            continue
        if apply:
            columns = [c for c in payload if c in table_columns]
            connection.execute(
                f"INSERT INTO {entity_type} ({','.join(columns)}) "
                f"VALUES ({','.join('?' * len(columns))})",
                [payload[c] for c in columns],
            )
        restored += 1
    if apply:
        connection.commit()
    return {"entity_type": entity_type, "archived": len(payloads),
            "restorable": restored, "already_present_skipped": skipped,
            "applied": bool(apply)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--run", default=None, help="run_id; default all runs")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true")
    action.add_argument("--show", metavar="ENTITY")
    action.add_argument("--restore", metavar="ENTITY")
    parser.add_argument("--apply", action="store_true",
                        help="with --restore, actually write the rows")
    args = parser.parse_args(argv)

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    try:
        if args.list:
            rows = list_runs(connection)
            if not rows:
                print("no rebuild archive in this database")
                return 0
            for row in rows:
                print(f"  {row['first_seen'][:19]}  {row['run_id']}  "
                      f"{row['entity_type']:17} {row['n']:6}  "
                      f"{row['disposition']}")
            return 0
        if args.show:
            payloads = archived_rows(connection, run_id=args.run,
                                     entity_type=args.show)
            print(json.dumps(payloads[:20], indent=2, sort_keys=True))
            print(f"... {len(payloads)} rows total")
            return 0
        result = restore(connection, run_id=args.run,
                         entity_type=args.restore, apply=args.apply)
        print(json.dumps(result, indent=2, sort_keys=True))
        if not args.apply:
            print("\ndry run -- pass --apply to write them back")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RestoreError as exc:
        print(f"restore: {exc}", file=sys.stderr)
        sys.exit(2)
