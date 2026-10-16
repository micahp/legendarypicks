#!/usr/bin/env python3
"""Copy the existing US Open and Kalshi point captures into separate canonical databases.

The existing dev database is opened read-only. Each source is written to its own
SQLite file using the same schema as the historical archive databases.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from ingest_historical_tennis_point_events import (
    ARCHIVE_DIR,
    EVENT_INSERT,
    EVENT_SCHEMA,
    MATCH_INSERT,
    MATCH_SCHEMA,
    SOURCE_SCHEMA,
    _event_type,
    _flag,
    _score_json,
)


HERE = Path(__file__).resolve().parent
SOURCE_DB = HERE / "data" / "picks.dev.db"
MIN_HEADROOM_BYTES = 512 * 1024**2
BATCH_SIZE = 5_000

SOURCES = {
    "usopen": {
        "table": "usopen_points",
        "dataset": "US Open 2026 captured feed and official history",
        "source_url": "https://www.usopen.org/",
    },
    "kalshi": {
        "table": "kalshi_tennis_points",
        "dataset": "Kalshi live tennis capture, 2026-10-03 through 2026-10-16 UTC",
        "source_url": "Kalshi live-data endpoint; captured by the trade desk",
    },
}


def _iso_epoch(value):
    if value in (None, ""):
        return None
    try:
        return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _clean(value):
    value = str(value or "").strip()
    return value or None


def _tour_category(value):
    label = str(value or "").strip()
    folded = label.casefold()
    if "women" in folded or folded == "wta":
        tour = "wta"
        gender = "women"
    elif "men" in folded or folded == "atp":
        tour = "atp"
        gender = "men"
    else:
        return "unknown", "unknown"
    if "mixed" in folded:
        return "mixed", "mixed doubles"
    if "double" in folded:
        return tour, f"{gender}'s doubles"
    return tour, f"{gender}'s singles"


def _point_score_json(row, raw, *, timing):
    p1 = row["p1_score"] if "p1_score" in row.keys() else None
    p2 = row["p2_score"] if "p2_score" in row.keys() else None
    return _score_json(
        set_no=(row["set_no"] if "set_no" in row.keys() else raw.get("SetNo")),
        game_no=(row["game_no"] if "game_no" in row.keys() else raw.get("GameNo")),
        p1=p1,
        p2=p2,
    )


def _prepare_source(con, source):
    spec = SOURCES[source]
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (spec["table"],)
    ).fetchone()
    if not exists:
        raise RuntimeError(f"source table {spec['table']} is missing from {SOURCE_DB}")
    point_predicate = "is_point=1" if source == "usopen" else "point_winner IN ('1','2')"
    total, points, raw_bytes = con.execute(
        f"SELECT COUNT(*),SUM(CASE WHEN {point_predicate} THEN 1 ELSE 0 END),"
        f"SUM(length(raw_json)) FROM {spec['table']}"
    ).fetchone()
    matches = con.execute(f"SELECT COUNT(DISTINCT match_id) FROM {spec['table']}").fetchone()[0]
    if not total or not matches:
        raise RuntimeError(f"source table {spec['table']} is empty")
    return {"rows": total, "points": points or 0, "raw_bytes": raw_bytes or 0, "matches": matches}


def _source_rows(con, source):
    table = SOURCES[source]["table"]
    con.row_factory = sqlite3.Row
    if source == "usopen":
        sql = f"SELECT * FROM {table} ORDER BY match_id, CAST(COALESCE(NULLIF(epoch_start,''),NULLIF(epoch_end,''),'0') AS INTEGER), id"
    else:
        sql = f"SELECT * FROM {table} ORDER BY match_id, epoch_end, id"
    return con.execute(sql)


def _match_meta(source, match_id, raw, row, timestamp):
    if source == "usopen":
        event = _clean(raw.get("_event")) or "unknown"
        tour, category = _tour_category(event)
        p1, p2 = _clean(raw.get("_p1")), _clean(raw.get("_p2"))
        round_name = _clean(raw.get("_round"))
        tournament = "US Open"
        match_date = dt.datetime.fromtimestamp(int(timestamp), tz=dt.timezone.utc).date().isoformat() if timestamp else None
        source_file = row["source_file"]
        raw_match = {key: raw.get(key) for key in ("MatchID", "_match_id", "_p1", "_p2", "_event", "_round") if raw.get(key) is not None}
        year = 2026
    else:
        tour = str(row["tour"] or "").strip().casefold()
        tour = tour if tour in {"atp", "wta"} else "unknown"
        gender = "women" if tour == "wta" else "men" if tour == "atp" else "unknown"
        category = f"{gender}'s singles" if gender != "unknown" else "unknown"
        p1, p2 = _clean(row["p1"]), _clean(row["p2"])
        round_name = None
        tournament = _clean(row["tournament"])
        match_date = dt.datetime.fromtimestamp(int(timestamp), tz=dt.timezone.utc).date().isoformat() if timestamp else None
        source_file = row["source_file"]
        raw_match = {key: raw.get(key) for key in ("MatchID", "_match_id", "_p1", "_p2", "_tour", "_tournament") if raw.get(key) is not None}
        year = int(match_date[:4]) if match_date else None
    if not raw_match:
        raw_match = {"match_id": match_id, "player1": p1, "player2": p2}
    dataset = SOURCES[source]["dataset"]
    return (
        source, dataset, match_id, tour, category, year, match_date, tournament,
        f"{year}-{tournament.casefold().replace(' ', '-') if tournament else 'unknown'}",
        round_name, None, p1, p2, None, None, None, None, None, None,
        source_file, "not assessed", json.dumps(raw_match, ensure_ascii=False, sort_keys=True),
        dt.datetime.now(dt.timezone.utc).isoformat(),
    )


def _event_row(source, dataset, row, sequence_no, previous_scores, player_names, loaded_at):
    raw = json.loads(row["raw_json"])
    match_id = str(row["match_id"])
    if source == "usopen":
        point_id = str(row["point_id"] or f"row:{row['id']}")
        is_point = int(row["is_point"] == 1)
        point_no = int(row["point_number"]) if str(row["point_number"] or "").isdigit() else None
        set_no, game_no = row["set_no"], row["game_no"]
        winner, server = _clean(row["point_winner"]), _clean(row["point_server"])
        serve = row["serve_number"]
        start, end = row["epoch_start"], row["epoch_end"]
        ts_precision = "source_unix_second"
        ace = _flag(raw, ("Ace",))
        double_fault = _flag(raw, ("DoubleFault",))
        rally_winner = _flag(raw, ("Winner",))
        unforced_error = _flag(raw, ("UnforcedError",))
        score_timing = "source_after"
        after = _point_score_json(row, raw, timing="after")
        prior = previous_scores.get(match_id)
        if is_point and prior and prior["set_no"] == set_no and prior["game_no"] == game_no:
            before = prior["score"]
        elif is_point:
            before = _score_json(set_no=set_no, game_no=game_no, p1="0", p2="0")
        else:
            before = None
        if is_point and after:
            previous_scores[match_id] = {"set_no": set_no, "game_no": game_no, "score": after}
        rally = raw.get("RallyCount")
        speed = raw.get("Speed_KMH")
        first = second = None
        filename, row_no = row["source_file"], row["id"]
    else:
        point_id = str(row["point_number"] or f"row:{row['id']}")
        winner, server = _clean(row["point_winner"]), _clean(row["point_server"])
        is_point = int(winner in {"1", "2"})
        point_no = int(row["point_number"]) if str(row["point_number"] or "").isdigit() else None
        set_no, game_no = row["set_no"], row["game_no"]
        serve = row["serve_number"]
        start, end = row["epoch_start"], row["epoch_end"]
        ts_precision = "poll_observed_up_to_4s_late"
        ace = _flag(raw, ("Ace",))
        double_fault = _flag(raw, ("DoubleFault",))
        rally_winner = _flag(raw, ("Winner",))
        unforced_error = _flag(raw, ("UnforcedError",))
        score_timing = "source_before"
        before = _point_score_json(row, raw, timing="before")
        after = None
        rally = raw.get("RallyCount")
        speed = raw.get("Speed_KMH")
        first = second = None
        filename, row_no = row["source_file"], row["source_line"]
    event_type = _event_type(is_point, ace, double_fault, rally_winner, unforced_error, raw)
    p1_name, p2_name = player_names
    winner_name = p1_name if winner == "1" else p2_name if winner == "2" else None
    server_name = p1_name if server == "1" else p2_name if server == "2" else None
    return (
        source, dataset, match_id, filename, row_no, point_id, sequence_no, is_point,
        point_no, set_no, game_no, event_type,
        None,
        str(row["p1_score"]) if row["p1_score"] is not None else None,
        str(row["p2_score"]) if row["p2_score"] is not None else None,
        before, after, score_timing, _iso_epoch(start), _iso_epoch(end), ts_precision,
        winner, winner_name, server, server_name, serve,
        ace, double_fault, rally_winner, unforced_error,
        int(rally) if str(rally or "").isdigit() else None,
        float(speed) if str(speed or "").replace(".", "", 1).isdigit() else None,
        first, second, json.dumps(raw, ensure_ascii=False, sort_keys=True), loaded_at,
    )


def _load(source, stats):
    spec = SOURCES[source]
    target = ARCHIVE_DIR / f"{source}.db"
    if target.exists() and target.stat().st_size:
        raise RuntimeError(f"refusing to overwrite existing canonical database: {target}")
    read = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True, timeout=120)
    read.row_factory = sqlite3.Row
    write = sqlite3.connect(target, timeout=120)
    write.execute("PRAGMA foreign_keys=ON")
    loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
    dataset = spec["dataset"]
    try:
        write.execute("BEGIN IMMEDIATE")
        write.execute(SOURCE_SCHEMA)
        write.execute(MATCH_SCHEMA)
        write.execute(EVENT_SCHEMA)
        match_values = {}
        match_times = {}
        for row in _source_rows(read, source):
            match_id = str(row["match_id"])
            raw = json.loads(row["raw_json"])
            ts = row["epoch_start"] if row["epoch_start"] is not None else row["epoch_end"]
            if source == "kalshi" and ts is None:
                ts = row["epoch_end"]
            if match_id not in match_values:
                match_values[match_id] = _match_meta(source, match_id, raw, row, ts)
                match_times[match_id] = ts
            elif source == "usopen":
                current = match_values[match_id]
                p1, p2 = _clean(raw.get("_p1")), _clean(raw.get("_p2"))
                if p1 and current[11] and p1 != current[11]:
                    raise RuntimeError(f"US Open player 1 changed for match {match_id}: {current[11]} / {p1}")
                if p2 and current[12] and p2 != current[12]:
                    raise RuntimeError(f"US Open player 2 changed for match {match_id}: {current[12]} / {p2}")
                if not current[11] or not current[12]:
                    match_values[match_id] = _match_meta(source, match_id, raw, row, ts)
        write.executemany(MATCH_INSERT, match_values.values())
        write.execute(
            "INSERT INTO tennis_point_sources VALUES (?,?,?,?,?,?,?,?,?,?)",
            (source, dataset, spec["source_url"], None, "not assessed", None, loaded_at,
             stats["matches"], stats["rows"], stats["points"]),
        )
        sequences = collections.Counter()
        previous_scores = {}
        batch = []
        for row in _source_rows(read, source):
            match_id = str(row["match_id"])
            sequences[match_id] += 1
            names = (match_values[match_id][11], match_values[match_id][12])
            batch.append(_event_row(source, dataset, row, sequences[match_id], previous_scores, names, loaded_at))
            if len(batch) >= BATCH_SIZE:
                write.executemany(EVENT_INSERT, batch)
                batch.clear()
        if batch:
            write.executemany(EVENT_INSERT, batch)
        write.execute(
            "CREATE UNIQUE INDEX ux_tennis_point_events_source_row "
            "ON tennis_point_events(source,source_dataset,source_file,source_row_no)"
        )
        write.execute(
            "CREATE INDEX ix_tennis_point_events_match_point "
            "ON tennis_point_events(source,source_dataset,source_match_id,is_point,sequence_no)"
        )
        write.execute(
            "CREATE INDEX ix_tennis_point_events_double_fault "
            "ON tennis_point_events(source,source_dataset,source_match_id) "
            "WHERE is_point=1 AND is_double_fault=1"
        )
        write.execute(
            "CREATE INDEX ix_tennis_point_matches_tournament "
            "ON tennis_point_matches(tour,match_year,tournament_key)"
        )
        write.commit()
    except BaseException:
        write.rollback()
        raise
    finally:
        read.close()
        write.close()
    verify = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        quick = verify.execute("PRAGMA quick_check").fetchone()[0]
        got = verify.execute("SELECT COUNT(*),SUM(is_point) FROM tennis_point_events").fetchone()
        matches = verify.execute("SELECT COUNT(*) FROM tennis_point_matches").fetchone()[0]
        missing_raw = verify.execute(
            "SELECT COUNT(*) FROM tennis_point_events WHERE raw_json IS NULL"
        ).fetchone()[0]
        if quick != "ok" or got != (stats["rows"], stats["points"]) or matches != stats["matches"] or missing_raw:
            raise RuntimeError(
                f"verification failed for {target}: quick_check={quick}, events={got}, "
                f"matches={matches}, missing_raw={missing_raw}"
            )
    finally:
        verify.close()
    print(
        f"loaded {source}: {target} ({target.stat().st_size:,} bytes), "
        f"matches={stats['matches']:,}, rows={stats['rows']:,}, "
        f"points={stats['points']:,}, quick_check=ok",
        flush=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["all", *SOURCES], default="all")
    parser.add_argument("--apply", action="store_true", help="create the standalone canonical databases")
    args = parser.parse_args(argv)
    if not SOURCE_DB.is_file():
        raise RuntimeError(f"read-only source database not found: {SOURCE_DB}")
    sources = list(SOURCES) if args.source == "all" else [args.source]
    read = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True, timeout=120)
    try:
        plans = {source: _prepare_source(read, source) for source in sources}
    finally:
        read.close()
    for source, stats in plans.items():
        print(f"{source}: {stats['matches']:,} matches, {stats['rows']:,} source rows, "
              f"{stats['points']:,} points, raw JSON={stats['raw_bytes']:,} bytes")
    if not args.apply:
        print(f"dry run only; no changes (pass --apply to create databases under {ARCHIVE_DIR})")
        return 0
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    required = sum(item["raw_bytes"] * 2 for item in plans.values()) + MIN_HEADROOM_BYTES
    free = shutil.disk_usage(ARCHIVE_DIR).free
    if free < required:
        raise RuntimeError(f"insufficient space: {free:,} free, conservatively require {required:,} bytes")
    for source, stats in plans.items():
        _load(source, stats)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(f"ingest_canonical_live_tennis_points: {exc}", file=sys.stderr)
        sys.exit(1)
