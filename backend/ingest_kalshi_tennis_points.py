#!/usr/bin/env python3
"""Load the trade desk's Kalshi tennis point rows into the dev DB (kalshi_tennis_points).

Source: prediction-market-trading/data/orderflow/KALSHI_POINTS_*.jsonl, one row per point the
poller wrote. Nothing is fetched from Kalshi here.

Rules:
  - DEV DB ONLY. The path must end in picks.dev.db; anything else exits.
  - A row's identity is (match_id, epoch_end, point_winner, p1_score, p2_score). The poller can
    write the same point twice; a repeat with identical content is skipped and counted. The same
    identity with DIFFERENT content is a conflict and aborts the whole load.
  - A malformed line aborts with its file and line number. Nothing partial is left behind.
  - --apply writes a backup of the dev DB first (SQLite backup API), then loads in one transaction.
  - Re-running is a no-op: every row is already present and identical.
"""
import argparse
import datetime as dt
import glob
import json
import pathlib
import sqlite3
import sys

# The worktree has no backend/data folder of its own, so the dev DB is named by absolute path.
DEV_DB = pathlib.Path("/root/legendarypicks/backend/data/picks.dev.db")
ORDERFLOW = pathlib.Path("/root/prediction-market-trading/data/orderflow")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kalshi_tennis_points (
  id           INTEGER PRIMARY KEY,
  match_id     TEXT NOT NULL,
  epoch_end    INTEGER NOT NULL,
  point_winner TEXT NOT NULL,
  p1_score     TEXT,
  p2_score     TEXT,
  tour         TEXT,
  tournament   TEXT,
  p1           TEXT,
  p2           TEXT,
  point_number TEXT,
  set_no       TEXT,
  game_no      TEXT,
  point_server TEXT,
  serve_number TEXT,
  epoch_start  INTEGER,
  source_file  TEXT NOT NULL,
  source_line  INTEGER NOT NULL,
  raw_json     TEXT NOT NULL,
  loaded_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_kalshi_tennis_points_match ON kalshi_tennis_points(match_id);
"""

INSERT = (
    "INSERT INTO kalshi_tennis_points (match_id, epoch_end, point_winner, p1_score, p2_score, tour,"
    " tournament, p1, p2, point_number, set_no, game_no, point_server, serve_number, epoch_start,"
    " source_file, source_line, raw_json, loaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def fail(message):
    sys.exit(f"refusing: {message}")


def read_rows(paths, loaded_at):
    """Every point row in the files, in file order. A bad line is a failure, not a skip."""
    rows = []
    for path in paths:
        with open(path) as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError as exc:
                    fail(f"{path.name}:{lineno} is not JSON ({exc})")
                try:
                    epoch_end = int(rec["EpochTimeEnd"])
                    match_id = str(rec["_match_id"])
                    winner = str(rec["PointWinner"])
                except (KeyError, TypeError, ValueError) as exc:
                    fail(f"{path.name}:{lineno} lacks a usable key ({exc!r})")
                p1_score = rec.get("P1Score")
                p2_score = rec.get("P2Score")
                key = (match_id, epoch_end, winner, "" if p1_score is None else str(p1_score),
                       "" if p2_score is None else str(p2_score))
                epoch_start = rec.get("EpochTimeStart")
                rows.append({
                    "key": key,
                    "file": path.name,
                    "line": lineno,
                    "raw": json.dumps(rec, sort_keys=True),
                    "values": (
                        match_id, epoch_end, winner,
                        None if p1_score is None else str(p1_score),
                        None if p2_score is None else str(p2_score),
                        rec.get("_tour"), rec.get("_tournament"), rec.get("_p1"), rec.get("_p2"),
                        None if rec.get("PointNumber") is None else str(rec.get("PointNumber")),
                        None if rec.get("SetNo") is None else str(rec.get("SetNo")),
                        None if rec.get("GameNo") is None else str(rec.get("GameNo")),
                        rec.get("PointServer"), rec.get("ServeNumber"),
                        None if epoch_start is None else int(epoch_start),
                        path.name, lineno, json.dumps(rec, sort_keys=True), loaded_at,
                    ),
                })
    return rows


def existing_rows(con):
    """identity -> (raw_json, where it came from), for the rows already in the table."""
    found = {}
    has_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'kalshi_tennis_points'"
    ).fetchone()
    if not has_table:
        return found
    for match_id, epoch_end, winner, p1, p2, raw in con.execute(
        "SELECT match_id, epoch_end, point_winner, COALESCE(p1_score, ''), COALESCE(p2_score, ''),"
        " raw_json FROM kalshi_tennis_points"
    ):
        found[(match_id, epoch_end, winner, p1, p2)] = (raw, "already in the dev DB")
    return found


def plan(rows, found):
    """Decide each row: insert, or skip as an identical repeat. A different repeat aborts."""
    seen = dict(found)
    stats = {}
    to_insert = []
    for r in rows:
        s = stats.setdefault(r["file"], {"read": 0, "inserted": 0, "identical": 0})
        s["read"] += 1
        prior = seen.get(r["key"])
        if prior is not None:
            if prior[0] == r["raw"]:
                s["identical"] += 1
                continue
            fail(f"conflict at {r['file']}:{r['line']}: same point as {prior[1]} with different content")
        seen[r["key"]] = (r["raw"], f"{r['file']}:{r['line']}")
        to_insert.append(r)
        s["inserted"] += 1
    for name, s in stats.items():
        if s["inserted"] + s["identical"] != s["read"]:
            fail(f"{name}: {s['read']} read, but {s['inserted']} inserted and {s['identical']} identical")
    return to_insert, stats


def backup(db):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = db.parent / f"backups-kalshi-points-{stamp[:8]}"
    folder.mkdir(exist_ok=True)
    target = folder / f"{db.name}.pre-kalshi-points-{stamp}.bak"
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(f"backup written: {target}")
    return target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEV_DB))
    ap.add_argument("--source", default=str(ORDERFLOW), help="folder holding KALSHI_POINTS_*.jsonl")
    ap.add_argument("--apply", action="store_true", help="write; without it this only plans")
    args = ap.parse_args()

    if not args.db.endswith("picks.dev.db"):
        fail("not the dev database")
    db = pathlib.Path(args.db)
    paths = [pathlib.Path(p) for p in sorted(glob.glob(f"{args.source}/KALSHI_POINTS_*.jsonl"))]
    if not paths:
        fail(f"no KALSHI_POINTS_*.jsonl files under {args.source}")

    loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = read_rows(paths, loaded_at)
    print(f"read {len(rows)} rows from {len(paths)} files")

    if not args.apply:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
        try:
            found = existing_rows(con)
        finally:
            con.close()
        to_insert, stats = plan(rows, found)
        for name, s in stats.items():
            print(f"  {name}: read {s['read']}, would insert {s['inserted']}, identical {s['identical']}")
        print(f"dry run: {len(to_insert)} rows would be inserted (pass --apply)")
        return 0

    backup(db)
    con = sqlite3.connect(db, timeout=60, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        # executescript would COMMIT first and end the transaction, so run each statement here.
        for stmt in [s for s in SCHEMA.split(";") if s.strip()]:
            con.execute(stmt)
        before = con.execute("SELECT COUNT(*) FROM kalshi_tennis_points").fetchone()[0]
        to_insert, stats = plan(rows, existing_rows(con))
        con.executemany(INSERT, [r["values"] for r in to_insert])
        after = con.execute("SELECT COUNT(*) FROM kalshi_tennis_points").fetchone()[0]
        if after != before + len(to_insert):
            raise RuntimeError(f"row count {after} != {before} + {len(to_insert)}")
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    for name, s in stats.items():
        print(f"  {name}: read {s['read']}, inserted {s['inserted']}, identical {s['identical']}")
    print(f"loaded {len(to_insert)} rows; table now has {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
