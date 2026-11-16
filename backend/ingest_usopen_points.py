#!/usr/bin/env python3
"""Load 2026 US Open point-by-point rows into the dev DB (usopen_points).

Two sources, kept apart by the `source` column:
  capture  the trade desk's usopen_points.py output, de-duplicated (84,173 rows, 572 matches);
  history  the official per-match history feed, one file per match (127 main-draw singles
           matches that the capture never saw).

Rules:
  - DEV DB ONLY. The path must end in picks.dev.db; anything else exits.
  - One transaction. A row that breaks the (source, match_id, point_id) uniqueness of a real
    point aborts the whole load, so nothing partial is left behind.
  - Non-point rows (blank PointID: arrivals, warm-ups, match end) are kept with is_point = 0
    and are not part of the uniqueness check.
  - Refuses to run if the table already has rows. Re-running needs a backup and a deliberate
    DELETE, not a silent second insert.
"""
import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEV_DB = HERE / "data" / "picks.dev.db"
CAPTURE = HERE.parent.parent / "prediction-market-trading" / "data" / "orderflow" / "USOPEN_POINTS_dedup_20260902_20260921.jsonl"
HISTORY_DIR = pathlib.Path("/tmp/claude-0/-root/95e95d67-12cc-44b0-8b87-6ab643c25e63/scratchpad/usopen-raw/history")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usopen_points (
  id            INTEGER PRIMARY KEY,
  source        TEXT NOT NULL,
  source_file   TEXT NOT NULL,
  match_id      TEXT NOT NULL,
  point_id      TEXT NOT NULL,
  is_point      INTEGER NOT NULL,
  point_number  TEXT,
  set_no        TEXT,
  game_no       TEXT,
  serve_number  TEXT,
  stage         TEXT,
  sentence      TEXT,
  point_winner  TEXT,
  point_server  TEXT,
  match_winner  TEXT,
  p1_score      TEXT,
  p2_score      TEXT,
  epoch_start   TEXT,
  epoch_end     TEXT,
  elapsed_time  TEXT,
  raw_json      TEXT NOT NULL,
  loaded_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_usopen_points_point
  ON usopen_points(source, match_id, point_id) WHERE is_point = 1;
CREATE INDEX IF NOT EXISTS ix_usopen_points_match ON usopen_points(match_id);
"""


def row_from(source, source_file, rec, loaded_at):
    pid = (rec.get("PointID") or "").strip()
    return (
        source,
        source_file,
        str(rec.get("MatchID") or ""),
        pid,
        1 if pid else 0,
        rec.get("PointNumber"),
        rec.get("SetNo"),
        rec.get("GameNo"),
        rec.get("ServeNumber"),
        rec.get("Stage"),
        rec.get("Sentence"),
        rec.get("PointWinner"),
        rec.get("PointServer"),
        rec.get("MatchWinner"),
        rec.get("P1Score"),
        rec.get("P2Score"),
        rec.get("EpochTimeStart"),
        rec.get("EpochTimeEnd"),
        rec.get("ElapsedTime"),
        json.dumps(rec, sort_keys=True),
        loaded_at,
    )


def collect():
    loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    with open(CAPTURE) as fh:
        for line in fh:
            if line.strip():
                rows.append(row_from("capture", CAPTURE.name, json.loads(line), loaded_at))
    for f in sorted(HISTORY_DIR.glob("*.json"), key=lambda p: int(p.stem)):
        for rec in json.loads(f.read_text()):
            rows.append(row_from("history", f.name, rec, loaded_at))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEV_DB))
    ap.add_argument("--apply", action="store_true", help="write; without it this only counts")
    args = ap.parse_args()

    if not args.db.endswith("picks.dev.db"):
        sys.exit("refusing: not the dev database")

    rows = collect()
    cap = sum(1 for r in rows if r[0] == "capture")
    his = sum(1 for r in rows if r[0] == "history")
    print(f"rows to load: {len(rows)} (capture {cap}, history {his})")
    print(f"real points: {sum(r[4] for r in rows)}, non-point rows: {sum(1 - r[4] for r in rows)}")
    matches = {r[2] for r in rows}
    print(f"distinct matches: {len(matches)}")
    if not args.apply:
        print("dry run: nothing written (pass --apply)")
        return 0

    con = sqlite3.connect(args.db, timeout=60)
    try:
        con.execute("BEGIN IMMEDIATE")
        for stmt in [s for s in SCHEMA.split(";") if s.strip()]:
            con.execute(stmt)
        existing = con.execute("SELECT COUNT(*) FROM usopen_points").fetchone()[0]
        if existing:
            con.rollback()
            sys.exit(f"refusing: usopen_points already has {existing} rows")
        con.executemany(
            "INSERT INTO usopen_points (source, source_file, match_id, point_id, is_point, point_number,"
            " set_no, game_no, serve_number, stage, sentence, point_winner, point_server, match_winner,"
            " p1_score, p2_score, epoch_start, epoch_end, elapsed_time, raw_json, loaded_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        loaded = con.execute("SELECT COUNT(*) FROM usopen_points").fetchone()[0]
        if loaded != len(rows):
            raise RuntimeError(f"row count {loaded} != {len(rows)}")
        dup = con.execute(
            "SELECT COUNT(*) FROM (SELECT source, match_id, point_id FROM usopen_points"
            " WHERE is_point = 1 GROUP BY 1,2,3 HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        if dup:
            raise RuntimeError(f"{dup} duplicate real points")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(f"loaded {loaded} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
