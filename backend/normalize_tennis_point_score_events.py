#!/usr/bin/env python3
"""Normalize source point order and fill canonical after-scores.

Match Charting stores its rows in source-file order, which is not consistently
chronological. Its Pt field is the match point number, and Pts is recorded from
the server's perspective. Kalshi rows remain in captured sequence order.
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path


DB_DIR = Path(__file__).resolve().parent / "data" / "tennis_point_archives"
SOURCES = {
    "match_charting_project": {
        "db": "match_charting_project.db",
        "source": "match_charting_project",
        "dataset": "JeffSackmann/tennis_MatchChartingProject@1813a1309b7ed7ebf1c7e884b32bf675d00e4edf",
        "normalize_pts": True,
    },
    "kalshi": {
        "db": "kalshi.db",
        "source": "kalshi",
        "dataset": "Kalshi live tennis capture, 2026-10-03 through 2026-10-16 UTC",
        "normalize_pts": False,
    },
}


def _eligible_count(con, spec):
    source, dataset = spec["source"], spec["dataset"]
    order = "point_no,source_row_no" if spec["normalize_pts"] else "sequence_no"
    return con.execute(
        "WITH sequenced AS ("
        " SELECT point_no,score_before_json,"
        f" LEAD(point_no) OVER (PARTITION BY source_match_id ORDER BY {order}) AS next_no,"
        f" LEAD(score_before_json) OVER (PARTITION BY source_match_id ORDER BY {order}) AS next_score"
        " FROM tennis_point_events WHERE source=? AND source_dataset=? AND is_point=1"
        ") SELECT COUNT(*) FROM sequenced WHERE point_no IS NOT NULL "
        "AND next_no=point_no+1 AND next_score IS NOT NULL",
        (source, dataset),
    ).fetchone()[0]


def _normalize(db_path, spec, expected):
    con = sqlite3.connect(db_path, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    source, dataset = spec["source"], spec["dataset"]
    filled = expected
    try:
        con.execute("BEGIN IMMEDIATE")
        if spec["normalize_pts"]:
            con.execute(
                "CREATE TEMP TABLE normalized_mcp AS "
                "SELECT id,source_match_id,point_no,source_row_no, "
                "ROW_NUMBER() OVER (PARTITION BY source_match_id "
                "ORDER BY COALESCE(point_no,sequence_no),source_row_no) AS new_sequence_no, "
                "CASE WHEN point_server='1' AND instr(point_score,'-')>0 "
                "THEN substr(point_score,1,instr(point_score,'-')-1) "
                "WHEN point_server='2' AND instr(point_score,'-')>0 "
                "THEN substr(point_score,instr(point_score,'-')+1) END AS p1, "
                "CASE WHEN point_server='1' AND instr(point_score,'-')>0 "
                "THEN substr(point_score,instr(point_score,'-')+1) "
                "WHEN point_server='2' AND instr(point_score,'-')>0 "
                "THEN substr(point_score,1,instr(point_score,'-')-1) END AS p2, "
                "CASE WHEN json_extract(raw_json,'$.Set1') IS NOT NULL "
                "AND json_extract(raw_json,'$.Set2') IS NOT NULL THEN "
                "CAST(json_extract(raw_json,'$.Set1') AS INTEGER)+"
                "CAST(json_extract(raw_json,'$.Set2') AS INTEGER)+1 END AS set_no, "
                "CASE WHEN json_extract(raw_json,'$.Gm1') IS NOT NULL "
                "AND json_extract(raw_json,'$.Gm2') IS NOT NULL THEN "
                "CAST(json_extract(raw_json,'$.Gm1') AS INTEGER)+"
                "CAST(json_extract(raw_json,'$.Gm2') AS INTEGER)+1 END AS game_no "
                "FROM tennis_point_events WHERE source=? AND source_dataset=? AND is_point=1",
                (source, dataset),
            )
            con.execute("CREATE UNIQUE INDEX normalized_mcp_id ON normalized_mcp(id)")
            con.execute(
                "CREATE TEMP TABLE normalized_mcp_timeline AS "
                "SELECT id,point_no,new_sequence_no, "
                "CASE WHEN p1 IS NOT NULL AND p2 IS NOT NULL THEN "
                "json_object('set',CAST(set_no AS TEXT),'game',CAST(game_no AS TEXT),"
                "'player1',p1,'player2',p2) END AS before_score, "
                "LEAD(point_no) OVER (PARTITION BY source_match_id ORDER BY new_sequence_no) AS next_no, "
                "LEAD(CASE WHEN p1 IS NOT NULL AND p2 IS NOT NULL THEN "
                "json_object('set',CAST(set_no AS TEXT),'game',CAST(game_no AS TEXT),"
                "'player1',p1,'player2',p2) END) OVER "
                "(PARTITION BY source_match_id ORDER BY new_sequence_no) AS next_score "
                "FROM normalized_mcp"
            )
            con.execute("CREATE UNIQUE INDEX normalized_mcp_timeline_id ON normalized_mcp_timeline(id)")
            filled = con.execute(
                "SELECT COUNT(*) FROM normalized_mcp_timeline WHERE point_no IS NOT NULL "
                "AND next_no=point_no+1 AND next_score IS NOT NULL"
            ).fetchone()[0]
            if filled != expected:
                raise RuntimeError(f"Match Charting eligible transitions changed: {filled} != {expected}")
            con.execute(
                "UPDATE tennis_point_events SET "
                "sequence_no=(SELECT new_sequence_no FROM normalized_mcp_timeline n "
                "WHERE n.id=tennis_point_events.id), "
                "set_no=(SELECT CAST(set_no AS TEXT) FROM normalized_mcp n "
                "WHERE n.id=tennis_point_events.id), "
                "game_no=(SELECT CAST(game_no AS TEXT) FROM normalized_mcp n "
                "WHERE n.id=tennis_point_events.id), "
                "p1_score=(SELECT p1 FROM normalized_mcp n WHERE n.id=tennis_point_events.id), "
                "p2_score=(SELECT p2 FROM normalized_mcp n WHERE n.id=tennis_point_events.id), "
                "point_score=(SELECT CASE WHEN p1 IS NOT NULL AND p2 IS NOT NULL "
                "THEN p1||'-'||p2 END FROM normalized_mcp n WHERE n.id=tennis_point_events.id), "
                "score_before_json=(SELECT before_score FROM normalized_mcp_timeline n "
                "WHERE n.id=tennis_point_events.id), "
                "score_after_json=(SELECT CASE WHEN next_no=point_no+1 THEN next_score END "
                "FROM normalized_mcp_timeline n WHERE n.id=tennis_point_events.id), "
                "score_timing='source_before;server_receiver_to_players;after_from_next_consecutive_point' "
                "WHERE source=? AND source_dataset=? AND is_point=1",
                (source, dataset),
            )
            normalized_rows = con.execute("SELECT changes()").fetchone()[0]
            expected_rows = con.execute("SELECT COUNT(*) FROM normalized_mcp").fetchone()[0]
            if normalized_rows != expected_rows:
                raise RuntimeError(f"normalized {normalized_rows} Match Charting rows; expected {expected_rows}")
            mismatch = con.execute(
                "SELECT COUNT(*) FROM tennis_point_events e JOIN normalized_mcp_timeline n ON n.id=e.id "
                "WHERE e.source=? AND e.source_dataset=? AND n.next_no=n.point_no+1 "
                "AND n.next_score IS NOT NULL AND e.score_after_json<>n.next_score",
                (source, dataset),
            ).fetchone()[0]
            if mismatch:
                raise RuntimeError(f"{mismatch} Match Charting after-scores disagree with the next point")
            con.execute("DROP TABLE normalized_mcp_timeline")
            con.execute("DROP TABLE normalized_mcp")
        else:
            con.execute(
                "CREATE TEMP TABLE next_point_score AS "
                "SELECT id,point_no,"
                "LEAD(point_no) OVER (PARTITION BY source_match_id ORDER BY sequence_no) AS next_no,"
                "LEAD(score_before_json) OVER (PARTITION BY source_match_id ORDER BY sequence_no) AS next_score "
                "FROM tennis_point_events WHERE source=? AND source_dataset=? AND is_point=1",
                (source, dataset),
            )
            con.execute("CREATE UNIQUE INDEX next_point_score_id ON next_point_score(id)")
            con.execute(
                "UPDATE tennis_point_events SET "
                "score_after_json=(SELECT next_score FROM next_point_score n WHERE n.id=tennis_point_events.id), "
                "score_timing='source_before;after_from_next_consecutive_point' "
                "WHERE source=? AND source_dataset=? AND is_point=1 AND id IN ("
                " SELECT id FROM next_point_score WHERE point_no IS NOT NULL "
                " AND next_no=point_no+1 AND next_score IS NOT NULL)",
                (source, dataset),
            )
            updated = con.execute("SELECT changes()").fetchone()[0]
            if updated != expected:
                raise RuntimeError(f"updated {updated} after-scores; expected {expected}")
            mismatch = con.execute(
                "SELECT COUNT(*) FROM tennis_point_events e JOIN next_point_score n ON n.id=e.id "
                "WHERE e.source=? AND e.source_dataset=? AND n.next_no=n.point_no+1 "
                "AND n.next_score IS NOT NULL AND e.score_after_json<>n.next_score",
                (source, dataset),
            ).fetchone()[0]
            if mismatch:
                raise RuntimeError(f"{mismatch} after-scores do not match the following point state")
            con.execute("DROP TABLE next_point_score")
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()

    check = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=120)
    try:
        result = check.execute("PRAGMA quick_check").fetchone()[0]
        filled = check.execute(
            "SELECT COUNT(*) FROM tennis_point_events WHERE source=? AND source_dataset=? "
            "AND is_point=1 AND score_after_json IS NOT NULL",
            (source, dataset),
        ).fetchone()[0]
        if result != "ok" or filled < expected:
            raise RuntimeError(f"post-normalization verification failed: quick_check={result}, filled={filled}")
    finally:
        check.close()
    print(f"{source}: normalized score order; filled {filled:,} consecutive after-scores; quick_check=ok")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write normalized before/after score fields")
    args = parser.parse_args(argv)
    plans = {}
    for key, spec in SOURCES.items():
        path = DB_DIR / spec["db"]
        if not path.is_file():
            raise RuntimeError(f"database missing: {path}")
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            plans[key] = (path, spec, _eligible_count(con, spec))
        finally:
            con.close()
    for name, (path, _, count) in plans.items():
        print(f"{name}: {count:,} point rows have a following consecutive source point")
    if not args.apply:
        print("dry run only; pass --apply to write the derived after-scores")
        return 0
    required = sum(path.stat().st_size * 2 for path, _, _ in plans.values()) + 1024**3
    free = shutil.disk_usage(DB_DIR).free
    if free < required:
        raise RuntimeError(f"insufficient space: {free:,} free, require about {required:,} bytes")
    for path, spec, count in plans.values():
        _normalize(path, spec, count)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(f"normalize_tennis_point_score_events: {exc}", file=sys.stderr)
        sys.exit(1)
