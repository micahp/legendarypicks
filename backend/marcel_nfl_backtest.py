#!/usr/bin/env python3
"""marcel_nfl_backtest.py -- full Marcel for NFL per-game stats, graded against Marcel-lite and v2.

Marcel-lite (`analytics/projections.py`) uses only the current season, has no regression and no age, and
cannot project at all below three games. This is the full form: Marcel's 5/4/3 multi-season weighting,
regression to the position mean, and an aging multiplier.

  weighted value   per-game values from the target season's earlier weeks and the previous seasons, with the
                   current season on weight 5 and season k back on weight (5 - k). WINDOW sets how many
                   previous seasons enter, so the value of the third season is a measurable question.
  regression       the weighted mean is regressed toward the position mean with K pseudo-games, K fitted on
                   the fit seasons only.
  aging            multiplied by an age multiplier for the player's age in the target season, fitted on the
                   fit seasons only.

P(over) for Marcel is the share of games in the same window whose value beat the line: the direct analogue
of Marcel-lite's `prob_over`, over ~40 games instead of 3 or 4. No fitted distribution, deliberately, so the
comparison isolates "does more history fix the probability".

Two modes:
  MAE    walk-forward point accuracy over a full season (default). Compares full Marcel, Marcel-lite and the
         fit-quality baseline on identical player-games.
  props  Brier on settled sportsbook props, on the item set `grade_nfl_prop_probabilities.collect` builds, so
         the lines and the eligible player-games are identical to the v2 and baseline grades.

Read-only. Usage:
  LP_DB_PATH=... python3 marcel_nfl_backtest.py --season 2025 --window 3 --fit-seasons 2013 2014 ... 2021
  LP_DB_PATH=... python3 marcel_nfl_backtest.py --season 2026 --window 3 --props --fit-seasons ...
"""
import argparse
import csv
import json
import math
import os
import sqlite3
from collections import defaultdict

import grade_nfl_prop_probabilities as g
from analytics.projections import project_stat, prob_over

SKILL = ("QB", "RB", "FB", "WR", "TE")
GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}
CUR_W = 5.0                      # weight on the target season's earlier weeks
K_GRID = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
MARKET_KEY = {m: col for m, (_i, col) in list(g.RECEIVING.items()) + list(g.PASSING.items())}


def load_rows(con, seasons):
    """(pid, season, week, group, {key: value}) for REG skill-position games, plus position."""
    pos = {pid: p for pid, p in con.execute("SELECT id, position FROM players WHERE league='nfl'")}
    out = defaultdict(list)
    q = con.execute(
        "SELECT player_id, game_id, stats FROM player_game_logs WHERE league='nfl' "
        "AND season IN (%s) AND source='nflverse_weekly' AND (game_type='REG' OR game_type IS NULL)"
        % ",".join("?" * len(seasons)), list(seasons))
    for pid, gid, stats in q:
        p = pos.get(pid)
        if p not in SKILL:
            continue
        _s, week, _a, _h = gid.split("_")
        week = int(week)
        if week > 18:
            continue
        blob = json.loads(stats)
        vals = {k: float(v) for k, v in blob.items() if isinstance(v, (int, float))}
        out[pid].append((int(_s), week, GROUP[p], vals))
    for pid in out:
        out[pid].sort(key=lambda t: (t[0], t[1]))
    return out


def age_map(con):
    """pid -> birth year, via players.nfl_gsis_id."""
    return {pid: int(b[:4]) for pid, b in con.execute(
        "SELECT p.id, b.birth_date FROM players p JOIN nfl_player_birth_dates b ON b.gsis_id=p.nfl_gsis_id "
        "WHERE p.league='nfl' AND b.birth_date IS NOT NULL")}


def weighted_value(games, season, week, key, window):
    """Marcel weighted mean over the current season's earlier weeks and the previous `window` seasons."""
    tot = wt = 0.0
    for s, w, _grp, vals in games:
        if key not in vals:
            continue
        if s == season:
            if w >= week:
                continue
            k = CUR_W
        else:
            back = season - s
            if back < 1 or back > window:
                continue
            k = CUR_W - back
            if k <= 0:
                continue
        tot += k * vals[key]
        wt += k
    if wt <= 0:
        return None, 0.0
    return tot / wt, wt


def window_values(games, season, week, key, window):
    """Every value in the same window, for the empirical P(over) and the position mean."""
    out = []
    for s, w, _grp, vals in games:
        if key not in vals:
            continue
        if s == season:
            if w >= week:
                continue
        elif not (1 <= season - s <= window):
            continue
        out.append(vals[key])
    return out


def fit(rows, ages, fit_seasons, window, key, use_aging=True, k_override=None):
    """Fit the position means, the regression K and the aging multipliers on the fit seasons only."""
    pos_sum, pos_n = defaultdict(float), defaultdict(int)
    by_age = defaultdict(lambda: [0.0, 0])
    pooled = [0.0, 0]
    for pid, games in rows.items():
        for s, w, grp, vals in games:
            if s not in fit_seasons or key not in vals:
                continue
            pos_sum[grp] += vals[key]
            pos_n[grp] += 1
            pooled[0] += vals[key]
            pooled[1] += 1
            by = ages.get(pid)
            if by is None:
                continue
            a = s - by
            by_age[(grp, a)][0] += vals[key]
            by_age[(grp, a)][1] += 1
    pos_mean = {k: pos_sum[k] / pos_n[k] for k in pos_n}
    overall = pooled[0] / pooled[1] if pooled[1] else 0.0
    mult = {}
    for (grp, a), (t, n) in by_age.items():
        m = pos_mean.get(grp, overall)
        mult[(grp, a)] = (t / n) / m if m else 1.0
    # smooth: only keep an age cell with enough games, else fall back to the pooled age curve
    pooled_age = defaultdict(lambda: [0.0, 0])
    for (grp, a), (t, n) in by_age.items():
        pooled_age[a][0] += t
        pooled_age[a][1] += n
    for a, (t, n) in pooled_age.items():
        pooled_age[a] = (t / n) / overall if overall else 1.0
    for k, v in list(mult.items()):
        if by_age[k][1] < 30:
            mult[k] = pooled_age[k[1]]
    if not use_aging:
        mult, pooled_age = {}, {}
    if k_override is not None:
        return {"pos_mean": pos_mean, "overall": overall, "mult": mult, "pooled_age": pooled_age,
                "K": k_override, "fit_mae": None, "fit_n": 0}
    # fit K by MAE of the regressed point on the fit seasons. The weighted mean does not depend on K, so it is
    # computed once per player-game and reused across the grid.
    cache = []
    for pid, games in rows.items():
        for s, w, grp, vals in games:
            if s not in fit_seasons or key not in vals or w < 2:
                continue
            mean, wt = weighted_value(games, s, w, key, window)
            if mean is None or wt < 1:
                continue
            cache.append((mean, wt, pos_mean.get(grp, overall), vals[key]))
    best, best_k = None, 0.0
    for K in K_GRID:
        err = 0.0
        for mean, wt, m, actual in cache:
            err += abs((mean * wt + K * m) / (wt + K) - actual)
        if cache and (best is None or err / len(cache) < best):
            best, best_k = err / len(cache), K
    return {"pos_mean": pos_mean, "overall": overall, "mult": mult, "pooled_age": pooled_age, "K": best_k,
            "fit_mae": best, "fit_n": len(cache)}


def predict(games, season, week, key, window, model, ages, pid):
    mean, wt = weighted_value(games, season, week, key, window)
    if mean is None:
        return None
    grp = None
    for s, w, grp_, _v in games:
        if s == season and w < week:
            grp = grp_
            break
    grp = grp or "WR"
    m = model["pos_mean"].get(grp, model["overall"])
    point = (mean * wt + model["K"] * m) / (wt + model["K"])
    by = ages.get(pid)
    if by is not None and model["mult"]:
        a = season - by
        point *= model["mult"].get((grp, a), model["pooled_age"].get(a, 1.0))
    return point


def grade_mae(con, rows, ages, season, window, fit_seasons, stats, use_aging=True, k_override=None):
    print("\n== MAE, season %d, walk-forward, window %d, aging %s, K %s ==" % (
        season, window, "on" if use_aging else "off",
        "fitted" if k_override is None else k_override))
    print("  %-10s %6s %8s %8s %8s %8s" % ("stat", "n", "marcel", "marcel-lite", "pos-mean", "best K"))
    for key in stats:
        model = fit(rows, ages, fit_seasons, window, key, use_aging, k_override)
        err_m = err_l = err_b = 0.0
        n = 0
        for pid, games in rows.items():
            for s, w, grp, vals in games:
                if s != season or key not in vals or w < 2:
                    continue
                pred = predict(games, s, w, key, window, model, ages, pid)
                if pred is None:
                    continue
                prior = [v[key] for ss, ww, _g, v in games if ss == s and ww < w and key in v]
                lite = project_stat(prior)
                if lite is None:
                    continue                      # the live route serves nothing here
                err_m += abs(pred - vals[key])
                err_l += abs(lite["projection"] - vals[key])
                # the position-mean-only baseline, i.e. what regression alone gives
                err_b += abs(model["pos_mean"].get(grp, model["overall"]) - vals[key])
                n += 1
        if n:
            print("  %-10s %6d %8.3f %8.3f %8.3f %8.1f" % (
                key, n, err_m / n, err_l / n, err_b / n, model["K"]))


def grade_props(con, rows, ages, season, window, fit_seasons, csv_path=None):
    items, skipped = g.collect(con, season)
    final_weeks = {w for (w,) in con.execute(
        "SELECT DISTINCT week FROM nfl_schedule WHERE season=? AND game_type='REG' AND home_score IS NOT NULL",
        (season,))}
    models = {k: fit(rows, ages, fit_seasons, window, k) for k in set(MARKET_KEY.values())}
    graded, miss = [], {"no_marcel": 0, "no_prior": 0}
    for gid, pid, market, book, line, p_mkt, book_hit in items:
        week = int(gid.split("_")[1])
        if week < 2 or week not in final_weeks:
            continue
        key = MARKET_KEY[market]
        games = rows.get(pid)
        if not games:
            miss["no_marcel"] += 1
            continue
        vals = window_values(games, season, week, key, window)
        if len(vals) < 3:
            miss["no_prior"] += 1
            continue
        actual = next((v[key] for s, w, _g, v in games if s == season and w == week and key in v), None)
        if actual is None:
            miss["no_marcel"] += 1
            continue
        point = predict(games, season, week, key, window, models[key], ages, pid)
        graded.append({"over": 1 if actual > line else 0, "p_marcel": prob_over(vals, line)["p_over"],
                       "p_market": p_mkt, "n_games": len(vals), "market": market, "book": book,
                       "line": line, "point": point if point is not None else 0.0, "actual": actual,
                       "game_id": gid, "player_id": pid, "week": week})
    n = len(graded)
    if not n:
        print("props: no items")
        return
    pg = len({(r["game_id"], r["player_id"]) for r in graded})
    print("\n== props, season %d, window %d: %d items on %d player-games ==" % (season, window, n, pg))
    print("  (excluded: %s, plus %s)" % (skipped, miss))
    print("  %-14s %8s %8s %8s %8s" % ("market", "n", "marcel", "market", "mean games"))
    for m in ["all"] + sorted({r["market"] for r in graded}):
        sub = graded if m == "all" else [r for r in graded if r["market"] == m]
        b_m = sum((r["p_marcel"] - r["over"]) ** 2 for r in sub) / len(sub)
        b_k = sum((r["p_market"] - r["over"]) ** 2 for r in sub) / len(sub)
        print("  %-14s %8d %8.4f %8.4f %8.1f" % (
            m, len(sub), b_m, b_k, sum(r["n_games"] for r in sub) / len(sub)))
    print("  weeks covered: %s" % sorted({r["week"] for r in graded}))
    print("  (constant 0.5 scores 0.2500)")
    if csv_path:
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(graded[0]))
            w.writeheader()
            w.writerows(graded)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--window", type=int, default=3)
    ap.add_argument("--fit-seasons", type=int, nargs="+", required=True)
    ap.add_argument("--props", action="store_true")
    ap.add_argument("--no-aging", action="store_true")
    ap.add_argument("--k-override", type=float)
    ap.add_argument("--csv")
    ap.add_argument("--stats", nargs="+", default=["rec_yds", "rec", "tgt", "pass_yds", "att", "cmp"])
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    seasons = sorted(set(a.fit_seasons) | {a.season} | {a.season - k for k in range(1, a.window + 1)})
    rows = load_rows(con, seasons)
    ages = age_map(con)
    print("loaded %d players over seasons %s; %d have a birth year" % (
        len(rows), seasons, sum(1 for p in rows if p in ages)))
    if a.props:
        grade_props(con, rows, ages, a.season, a.window, set(a.fit_seasons), a.csv)
    else:
        grade_mae(con, rows, ages, a.season, a.window, set(a.fit_seasons), a.stats,
                  use_aging=not a.no_aging, k_override=a.k_override)


if __name__ == "__main__":
    main()
