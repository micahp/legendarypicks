#!/usr/bin/env python3
"""Run the versioned NFL playoff-odds forecast from the local database only.

Writes team_ratings and playoff_odds for one run (read by /api/nfl/playoff-odds and /api/nfl/ratings).
It does NOT lock projections or grade them: locking is nfl_lock.lock_week and grading is
grade_nfl_locks.py, the one shared path, so this job cannot lock a week by accident.
Simulation is nfl_sim as on dev (played games keep their results; scores of simulated games are the
documented placeholder split), seeded by nfl_seeding's published tiebreak procedure.

The job fails before simulation if the schedule is stale. It never calls ESPN or mutates the
schedule ingest.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sqlite3
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import migrate_nfl_model_tables as migration
import nfl_lock
import nfl_sim
import nfl_standings
from check_nfl_schedule_scores import GRACE_HOURS, overdue_unscored

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.dev.db")
MODEL_VERSION = "nfl-playoff-odds-v1.2"
SIMULATIONS = 20_000
MIN_AVAILABLE_KIB = 1_572_864
MIN_SWAP_FREE_KIB = 262_144
MAX_LOAD_PER_CPU = 1.0


def selected_season(con, season=None):
    if season is not None:
        return int(season)
    row = con.execute("SELECT MAX(season) FROM nfl_schedule WHERE game_type='REG'").fetchone()
    if row is None or row[0] is None:
        raise ValueError("nfl_schedule has no regular-season rows")
    return int(row[0])


def selected_week(con, season, week=None):
    if week is not None:
        return int(week)
    row = con.execute(
        "SELECT MIN(week) FROM nfl_schedule WHERE season=? AND game_type='REG' "
        "AND (home_score IS NULL OR away_score IS NULL)", (season,)).fetchone()
    if row is None or row[0] is None:
        raise ValueError("season %d has no unscored regular-season games" % season)
    return int(row[0])


def assert_schedule_fresh(con, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    checked, overdue = overdue_unscored(con, now, GRACE_HOURS)
    if overdue:
        examples = ["%s wk%d %s at %s (%.1fh)" % (r[0], r[2], r[5], r[6], r[7])
                    for r in overdue[:8]]
        raise RuntimeError("schedule freshness failed: %d overdue unscored games of %d: %s" %
                           (len(overdue), checked, "; ".join(examples)))
    return checked


def resource_state():
    values = {}
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            name, _, rest = line.partition(":")
            if name in ("MemAvailable", "SwapFree", "SwapTotal"):
                values[name] = int(rest.strip().split()[0])
    if "MemAvailable" not in values or "SwapFree" not in values:
        raise RuntimeError("resource guard cannot read available memory and swap")
    load_1m, load_5m, load_15m = os.getloadavg()
    cpu_count = max(1, os.cpu_count() or 1)
    state = {"available_kib": values["MemAvailable"], "swap_free_kib": values["SwapFree"],
             "swap_total_kib": values.get("SwapTotal"), "load_1m": load_1m,
             "load_5m": load_5m, "load_15m": load_15m, "cpu_count": cpu_count}
    if (state["available_kib"] < MIN_AVAILABLE_KIB or
            state["swap_free_kib"] < MIN_SWAP_FREE_KIB or
            state["load_1m"] > cpu_count * MAX_LOAD_PER_CPU):
        raise RuntimeError("resource guard refused the simulation: %s" % state)
    return state


def _previous_odds(con, season, week):
    row = con.execute(
        "SELECT o.run_id,o.week FROM playoff_odds o JOIN model_runs r ON r.run_id=o.run_id "
        "WHERE o.league='nfl' AND o.season=? AND o.week<? AND r.model_version=? "
        "AND r.status='ok' ORDER BY o.week DESC,o.as_of DESC LIMIT 1",
        (season, week, MODEL_VERSION)).fetchone()
    if row is None:
        return None, {}
    rows = con.execute("SELECT team,p_playoffs FROM playoff_odds WHERE run_id=? AND league='nfl'",
                       (row[0],)).fetchall()
    return row[1], {team: float(prob) for team, prob in rows}


def store_outputs(con, run_id, season, week, as_of, inp, out):
    fit = inp["fit"]
    standings = nfl_standings.build(inp["tmap"], inp["played"])
    for team in sorted(fit.o):
        con.execute(
            "INSERT INTO team_ratings (run_id,league,season,week,team,\"off\",\"def\",overall,"
            "games,as_of) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, "nfl", season, week, team, fit.o[team], fit.d[team],
             fit.o[team] - fit.d[team], len(standings[team].results), as_of))

    previous = _previous_odds(con, season, week)
    seed_columns = ["p_seed_%d" % seed for seed in range(1, 8)]
    columns = ["run_id", "league", "season", "week", "team", "p_playoffs", "p_division",
               "p_bye"] + seed_columns + ["wins_mean", "wins_p10", "wins_p90", "d_playoffs", "as_of"]
    placeholders = ",".join("?" for _ in columns)
    for team, metrics in sorted(out["teams"].items()):
        old = previous[1].get(team)
        delta = None if old is None else metrics["p_playoffs"] - old
        values = [run_id, "nfl", season, week, team, metrics["p_playoffs"],
                  metrics["p_division"], metrics["p_bye"]]
        values.extend(metrics["p_seed_%d" % seed] for seed in range(1, 8))
        values.extend([metrics["wins_mean"], metrics["wins_p10"], metrics["wins_p90"], delta, as_of])
        con.execute("INSERT INTO playoff_odds (%s) VALUES (%s)" %
                    (",".join(columns), placeholders), values)
    con.commit()
    return previous


def run(con, season=None, week=None, n=SIMULATIONS, k=0.0, seed=None):
    migration.migrate(con)
    season = selected_season(con, season)
    week = selected_week(con, season, week)
    seed = random.SystemRandom().randrange(1, 2**31) if seed is None else int(seed)
    params = {"n": n, "k": k, "seed": seed, "simulation": "placeholder-split-40",
              "rating": dict(nfl_sim.FROZEN)}
    run_id = "nfl-weekly-%d-w%d-%s" % (season, week, uuid.uuid4().hex[:10])
    as_of = dt.datetime.now(dt.timezone.utc).isoformat()
    nfl_lock.start_run(con, run_id, season, week, MODEL_VERSION, params, model="nfl-playoff-odds")
    started = time.monotonic()
    try:
        checked = assert_schedule_fresh(con)
        inp = nfl_sim.inputs(con, season)
        if not inp["remaining"]:
            raise ValueError("no remaining regular-season games to simulate")
        resources = resource_state()
        result = nfl_sim.run(inp, n, k=k, seed=seed)
        conference_of = {team: conf for team, (conf, _) in inp["tmap"].items()}
        nfl_sim.sanity(result, conference_of)
        store_outputs(con, run_id, season, week, as_of, inp, result)
        elapsed = round(time.monotonic() - started, 3)
        result_params = dict(params)
        result_params["results"] = {
            "fit": {"mu": inp["fit"].mu, "h": inp["fit"].h,
                    "games": inp["fit"].n_games, "total_weight": inp["fit"].total_weight},
            "overdue_score_check_games": checked,
            "resources": resources,
            "coin_flips": result["coin_flips"],
            "elapsed_seconds": elapsed,
        }
        con.execute("UPDATE model_runs SET params_json=? WHERE run_id=?",
                    (json.dumps(result_params, sort_keys=True), run_id))
        nfl_lock.finish_run(con, run_id, "ok")
        print("OK run_id=%s season=%d week=%d model=%s simulations=%d runtime=%.3fs teams=%d "
              "coin_flips=%d" % (run_id, season, week, MODEL_VERSION, n, elapsed,
                                 len(result["teams"]), result["coin_flips"]))
        return {"run_id": run_id, "season": season, "week": week, "result": result,
                "elapsed_seconds": elapsed}
    except Exception as exc:
        con.rollback()
        nfl_lock.finish_run(con, run_id, "failed", str(exc))
        print("ALERT NFL model run %s failed: %s" % (run_id, exc), file=sys.stderr)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--n", type=int, default=SIMULATIONS)
    parser.add_argument("--k", type=float, default=0.0)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    if args.n <= 0:
        parser.error("--n must be > 0")
    if args.k < 0:
        parser.error("--k must be >= 0")
    con = sqlite3.connect(DB, timeout=30)
    try:
        run(con, args.season, args.week, args.n, args.k, args.seed)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
