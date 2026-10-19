#!/usr/bin/env python3
"""Check captured P(over) and job quantiles against the imported v2 API route."""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
import sqlite3
from functools import wraps
from pathlib import Path

import capture_nfl_props as capture


TOLERANCE = 1e-9
PARAM_FIELDS = ("mean", "median", "p10", "p90")


def memoize_exact_inputs(function):
    """Reuse the exact fixed-seed draw array when the serving route repeats inputs."""
    cache = {}
    stats = {"calls": 0, "unique_inputs": 0}

    @wraps(function)
    def call(*args, **kwargs):
        stats["calls"] += 1
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            stats["unique_inputs"] += 1
            cache[key] = function(*args, **kwargs)
        return cache[key]

    call.cache_stats = stats
    return call


class PersistentConnection:
    """Let FastAPI's closing() wrapper reuse one in-memory verification database."""

    def __init__(self, con):
        self.con = con

    def execute(self, *args, **kwargs):
        return self.con.execute(*args, **kwargs)

    def close(self):
        pass


def _row_values(entry, scenario, stat, values, season, week, as_of):
    mean, median, p10, p90 = values
    return ("capture-parity", "nfl", season, week, entry["game_id"], entry["player_id"], entry["team"],
            stat, mean, median, p10, p90, scenario, "v2", "lp", entry["p_plays"], as_of)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("artifact", type=Path)
    ap.add_argument("--db", type=Path, default=capture.DB_DEFAULT)
    args = ap.parse_args(argv)

    with gzip.open(args.artifact, "rt", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    if not records:
        raise SystemExit("empty forecast artifact")
    weeks = sorted({int(r["event"]["week"]) for r in records})
    season = int(records[0]["season"])
    con = capture.read_only_connection(args.db.resolve())
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    try:
        history = capture.engine.History.load(con, [season - 1, season])
        entries_by_key = {}
        for week in weeks:
            view = capture._BackfillScheduleView(con)
            entries, _summary = capture.projection_job.project_week(
                con=view, season=season, week=week, n_sims=1, hist=history
            )
            for entry in entries:
                key = (str(entry["game_id"]), int(entry["player_id"]))
                if key in entries_by_key:
                    raise RuntimeError(f"duplicate projected player-game {key}")
                entries_by_key[key] = entry

        mem.executescript("""
            CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT);
            CREATE TABLE player_projections (
                run_id TEXT, league TEXT, season INTEGER, week INTEGER, game_id TEXT, player_id INTEGER,
                team TEXT, stat TEXT, mean REAL, median REAL, p10 REAL, p90 REAL, scenario TEXT,
                model_version TEXT, source TEXT, p_plays REAL, as_of TEXT
            );
            CREATE TABLE nfl_prop_calibration (
                season INTEGER, week INTEGER, model_version TEXT, a REAL, b REAL,
                n_items INTEGER, n_player_games INTEGER, fitted_at_utc TEXT
            );
        """)
        player_ids = sorted({key[1] for key in entries_by_key})
        for start in range(0, len(player_ids), 400):
            chunk = player_ids[start:start + 400]
            marks = ",".join("?" for _ in chunk)
            for row in con.execute(f"SELECT id,name,team,league FROM players WHERE id IN ({marks})", chunk):
                mem.execute("INSERT INTO players VALUES (?,?,?,?)", tuple(row))

        as_of = "2026-10-19T00:00:00+00:00"
        for week in weeks:
            for row in con.execute(
                "SELECT season,week,model_version,a,b,n_items,n_player_games,fitted_at_utc "
                "FROM nfl_prop_calibration WHERE season=? AND week=?", (season, week)
            ):
                mem.execute("INSERT INTO nfl_prop_calibration VALUES (?,?,?,?,?,?,?,?)", tuple(row))
        for (game_id, player_id), entry in entries_by_key.items():
            week = int(game_id.split("_")[1])
            for scenario, stats in entry["scenarios"].items():
                for stat, values in stats.items():
                    mem.execute(
                        "INSERT INTO player_projections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        _row_values(entry, scenario, stat, values, season, week, as_of),
                    )
        mem.commit()

        from routers.players import nfl_projections as route

        route._db_pkg = lambda: PersistentConnection(mem)
        original_summarize = capture.engine.summarize
        tapped = []

        def tapped_summarize(draws, index, line=None):
            result = original_summarize(draws, index, line)
            if line is not None:
                tapped.append(float(result["p_over"]))
            return result

        capture.engine.summarize = tapped_summarize
        original_simulate = capture.engine.simulate
        original_simulate_qb = capture.engine.simulate_qb
        capture.engine.simulate = memoize_exact_inputs(original_simulate)
        capture.engine.simulate_qb = memoize_exact_inputs(original_simulate_qb)
        max_p_delta = 0.0
        max_quantile_delta = 0.0
        p_checks = quantile_checks = 0
        representative_lines = {}
        representative_quantiles = {}
        for record in records:
            representative_lines.setdefault(record["market"]["provider_market"], record)
            representative_quantiles.setdefault(record["market"]["stat"], record)

        for market, record in representative_lines.items():
            event_id, player_id, line = (record["event"]["id"], record["player"]["id"], float(record["line"]))
            entry = entries_by_key[(event_id, int(player_id))]
            before = len(tapped)
            payload = route.nfl_player_projection(
                int(player_id), week=int(record["event"]["week"]), season=season,
                market=market, line=line, model="v2",
            )
            if len(tapped) != before + 1:
                raise RuntimeError(f"route did not call the shared summarize function once for {market}")
            expected_raw = float(record["forecast_probability"]["p_over_raw"])
            max_p_delta = max(max_p_delta, abs(tapped[-1] - expected_raw))
            if abs(tapped[-1] - expected_raw) > TOLERANCE:
                raise AssertionError(f"P(over) mismatch {market}: {tapped[-1]} vs {expected_raw}")
            if payload["prob_over"]["p_over"] != record["forecast_probability"]["p_over_served_4dp"]:
                raise AssertionError(f"rounded route P(over) mismatch for {market}")
            p_checks += 1

        for stat, record in representative_quantiles.items():
            event_id, player_id = record["event"]["id"], record["player"]["id"]
            entry = entries_by_key[(event_id, int(player_id))]
            market, line = record["market"]["provider_market"], float(record["line"])
            payload = route.nfl_player_projection(
                int(player_id), week=int(event_id.split("_")[1]), season=season,
                market=market, line=line, model="v2",
            )
            expected = entry["scenarios"]["base"][stat]
            actual = payload["scenarios"]["base"][stat]
            for field, value in zip(PARAM_FIELDS, expected):
                delta = abs(float(actual[field]) - float(value))
                max_quantile_delta = max(max_quantile_delta, delta)
                if delta > TOLERANCE:
                    raise AssertionError(f"{field} mismatch {(event_id, player_id, stat)}: {actual[field]} vs {value}")
            quantile_checks += 1

        capture.engine.summarize = original_summarize
        simulate_stats = capture.engine.simulate.cache_stats
        qb_stats = capture.engine.simulate_qb.cache_stats
        capture.engine.simulate = original_simulate
        capture.engine.simulate_qb = original_simulate_qb

        map_deltas = []
        map_inputs = set()
        for record in records:
            calrow = record["forecast_probability"].get("calibration", {})
            if calrow.get("status") != "applied":
                continue
            map_inputs.add((float(calrow["a"]), float(calrow["b"]),
                            float(record["forecast_probability"]["p_over_raw"]),
                            float(record["forecast_probability"]["p_over_v2_platt"])))
        for a, b, raw, module_value in map_inputs:
            route_value = float(route._logistic(a, b, raw))
            map_deltas.append(abs(route_value - module_value))
        map_mismatches = sum(delta > TOLERANCE for delta in map_deltas)
        print(f"v2 route raw P(over): {p_checks} representative market inputs; max abs delta={max_p_delta:.12g}; tolerance={TOLERANCE}")
        print(f"v2 route stored summaries: {quantile_checks} representative stat inputs; max abs delta={max_quantile_delta:.12g}; tolerance={TOLERANCE}")
        print(f"exact fixed-seed simulation reuse: receiving {simulate_stats['calls']} calls/{simulate_stats['unique_inputs']} unique inputs; passing {qb_stats['calls']} calls/{qb_stats['unique_inputs']} unique inputs")
        print(f"v2-platt helper parity: {len(map_inputs)} unique parameter/probability inputs; route-vs-calibration max abs delta={max(map_deltas, default=0.0):.12g}; differences > tolerance={map_mismatches}")
        if max_p_delta > TOLERANCE or max_quantile_delta > TOLERANCE:
            return 1
        return 0
    finally:
        capture.engine.summarize = original_summarize if "original_summarize" in locals() else capture.engine.summarize
        if "original_simulate" in locals():
            capture.engine.simulate = original_simulate
            capture.engine.simulate_qb = original_simulate_qb
        mem.close()
        con.rollback()
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
