#!/usr/bin/env python3
"""nfl_sim_backtest.py -- hot versus cold simulation, graded on who actually made the playoffs.

For each cutoff week w: simulate the rest of the season from games through w (backtest mode of
nfl_sim.inputs), and score each team's p_playoffs against whether it reached the playoffs. Playoff
teams are those in any WC or DIV game of that season (seed 1 appears in DIV as the bye team).

Spec 5.1: hot or cold, whichever grades better. The choice is made on 2024 (tuning). 2025 is
reported as a second look: version 1 has already been scored on 2025 (A3), so it is not a holdout.

Usage:
  LP_DB_PATH=<dev db> python3 nfl_sim_backtest.py --season 2024 --k 0.0 --n 2000 --out data/...json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

import nfl_sim as ns

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
CUTOFFS = list(range(5, 18))   # simulate from after week 5 up to after week 17


def playoff_teams(con, season):
    rows = con.execute("SELECT home_team, away_team FROM nfl_schedule WHERE season = ? "
                       "AND game_type IN ('WC','DIV','CON','SB')", (season,)).fetchall()
    return {t for r in rows for t in r}


def brier_for(p_by_team, playoff_set):
    """Mean squared error of p_playoffs over the teams given, against 0/1 membership."""
    if not p_by_team:
        raise ValueError("no teams")
    return sum((p - (1.0 if t in playoff_set else 0.0)) ** 2 for t, p in p_by_team.items()) / len(p_by_team)


def run_season(con, season, k, n, seed):
    actual = playoff_teams(con, season)
    if len(actual) != 14:
        raise SystemExit("expected 14 playoff teams in %d, found %d" % (season, len(actual)))
    rows = []
    for w in CUTOFFS:
        inp = ns.inputs(con, season, as_of_week=w)
        out = ns.run(inp, n, k=k, seed=seed + w)
        p = {t: v["p_playoffs"] for t, v in out["teams"].items()}
        rows.append({"through_week": w, "brier": brier_for(p, actual), "teams": len(p),
                     "coin_flips": out["coin_flips"]})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--k", type=float, required=True)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        rows = run_season(con, args.season, args.k, args.n, args.seed)
    finally:
        con.close()
    mean = sum(r["brier"] for r in rows) / len(rows)
    doc = {"season": args.season, "k": args.k, "n": args.n, "seed": args.seed,
           "weeks": rows, "mean_brier": mean}
    with open(args.out, "w") as fh:
        json.dump(doc, fh, indent=1)
    print("season %d k=%g n=%d mean brier over %d cutoffs: %.4f (flips %d)"
          % (args.season, args.k, args.n, len(rows), mean, sum(r["coin_flips"] for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
