#!/usr/bin/env python3
"""grade_nfl_game_distributions.py -- score the stored NFL distribution against the market line.

For every stored distribution whose game is final, from the stored parameters only (no refit, no
sampling):

  winner   P(home wins) = P(margin > 0). Market probability = the de-vigged two-way moneyline
           (same multiplicative devig the player props use). Ties have no outcome and are excluded
           from Brier and log loss, counted separately.
  spread   P(home covers) = P(margin > line). The line is the one the lock stored
           (`line_snapshot_id`), falling back to the schedule's spread when the lock predates
           snapshots. The market's *probability* for a spread is NOT stored anywhere in this database
           -- only the line -- so the spread is graded against the constant base rate and the line is
           used to settle; the market column is reported as absent rather than invented.
  total    P(total over) = P(total > line), same line provenance and same market-price caveat.

Pushes (only possible on a whole-number line) are excluded per market and counted.

Reported per market: n, pushes, Brier and log loss for ours, the constant base rate and (winner only)
the market; 10-bin reliability and the Murphy decomposition; the paired differences against the
constant and against the market, clustered by week (games in one week share ratings and parameters).

Read-only. Usage: LP_DB_PATH=... python3 grade_nfl_game_distributions.py --season 2025 [--csv out.csv]
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sqlite3
from collections import defaultdict

import numpy as np

EPS = 1e-9
BINS = 10


def devig(home_ml, away_ml):
    def implied(odds):
        return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)
    if home_ml is None or away_ml is None:
        return None
    h, a = implied(home_ml), implied(away_ml)
    return h / (h + a)


def p_over(mean, sd, line):
    if sd is None or sd <= 0:
        return 1.0 if mean > line else 0.0
    z = (mean - line) / sd
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def logloss(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def murphy(rows, key):
    bins = defaultdict(list)
    for r in rows:
        bins[min(int(r[key] * BINS), BINS - 1)].append(r)
    n = len(rows)
    obs = sum(r["y"] for r in rows) / n
    rel = res = 0.0
    for cell in bins.values():
        nb = len(cell)
        pb = sum(r[key] for r in cell) / nb
        ob = sum(r["y"] for r in cell) / nb
        rel += nb * (pb - ob) ** 2
        res += nb * (ob - obs) ** 2
    return rel / n, res / n


def cluster_bootstrap(rows, ka, kb, reps=2000, seed=20261018):
    """Mean paired difference (a - b), clustered by week."""
    by_week = defaultdict(list)
    for r in rows:
        by_week[(r.get("season"), r["week"])].append(r[ka] - r[kb])
    weeks = list(by_week)
    allv = np.array([x for w in weeks for x in by_week[w]])
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(reps):
        pick = rng.choice(len(weeks), size=len(weeks), replace=True)
        means.append(np.concatenate([by_week[weeks[i]] for i in pick]).mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(allv.mean()), float(lo), float(hi), len(allv), len(weeks)


def enrich(con, dist_rows):
    """Attach schedule outcome, lines and the devigged market probability to each distribution row."""
    con.row_factory = sqlite3.Row
    ids = [r["game_id"] for r in dist_rows]
    info = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in con.execute(
                "SELECT game_id, week, home_score, away_score, spread_line, total_line, home_moneyline, "
                "away_moneyline FROM nfl_schedule WHERE game_type='REG' AND home_score IS NOT NULL "
                "AND away_score IS NOT NULL AND game_id IN (%s)" % ",".join("?" * len(chunk)), chunk):
            info[r["game_id"]] = r
    rows = []
    for d in dist_rows:
        s = info.get(d["game_id"])
        if s is None:
            continue
        spread, total = d.get("spread_line"), d.get("total_line")
        line_id = d.get("line_snapshot_id")
        if line_id is not None:
            snap = con.execute("SELECT spread_line, total_line FROM nfl_line_snapshots WHERE snapshot_id=?",
                               (line_id,)).fetchone()
            if snap:
                spread, total = snap["spread_line"], snap["total_line"]
        if spread is None:
            spread = s["spread_line"]
        if total is None:
            total = s["total_line"]
        rows.append({"game_id": d["game_id"], "season": d["season"], "week": s["week"],
                     "margin_mean": d["margin_mean"], "margin_sd": d["margin_sd"],
                     "total_mean": d["total_mean"], "total_sd": d["total_sd"],
                     "actual_margin": s["home_score"] - s["away_score"],
                     "actual_total": s["home_score"] + s["away_score"],
                     "spread": spread, "total": total,
                     "market_p": devig(s["home_moneyline"], s["away_moneyline"])})
    return rows


def load(con, seasons):
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM nfl_game_distributions WHERE season IN (%s) ORDER BY season, week, game_id"
        % ",".join("?" * len(seasons)), list(seasons))]
    return enrich(con, rows)


def market_rows(rows, line_key, actual_key, p_key, mean_key):
    """One scored row per game for a spread or total, drops pushes and missing lines."""
    out, pushes = [], 0
    for r in rows:
        line = r[line_key]
        if line is None:
            continue
        actual = r[actual_key]
        if actual == line:
            pushes += 1
            continue
        out.append({"season": r["season"], "week": r["week"],
                    "y": 1.0 if actual > line else 0.0, "p": r[p_key],
                    "disagree": r[mean_key] - line, "resid": actual - line})
    return out, pushes


def corr(a, b):
    n = len(a)
    if n < 3:
        return float("nan")
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) if va and vb else float("nan")


def report(name, rows, market_key=None):
    n = len(rows)
    if not n:
        print("  %s: no items" % name)
        return
    base = sum(r["y"] for r in rows) / n
    ours = sum((r["p"] - r["y"]) ** 2 for r in rows) / n
    ll = sum(logloss(r["p"], r["y"]) for r in rows) / n
    const_b = sum((base - r["y"]) ** 2 for r in rows) / n
    const_ll = sum(logloss(base, r["y"]) for r in rows) / n
    rel, res = murphy(rows, "p")
    print("  %-7s n %4d  base rate %.3f  Brier ours %.4f  constant %.4f  logloss ours %.4f  constant %.4f"
          % (name, n, base, ours, const_b, ll, const_ll))
    print("          reliability %.4f  resolution %.4f" % (rel, res))
    if name in ("spread", "total"):
        bins = defaultdict(list)
        for r in rows:
            bins[min(int(r["p"] * BINS), BINS - 1)].append(r)
        print("          bin  n     pred   obs")
        for b in sorted(bins):
            cell = bins[b]
            print("          %.1f %4d  %.3f  %.3f" % (b / 10.0, len(cell),
                  sum(r["p"] for r in cell) / len(cell), sum(r["y"] for r in cell) / len(cell)))
    bs_ours, bs_lo, bs_hi, nn, gg = cluster_bootstrap(
        [dict(r, b_ours=(r["p"] - r["y"]) ** 2, b_const=(base - r["y"]) ** 2) for r in rows],
        "b_ours", "b_const")
    print("          Brier ours - constant %+.5f [%+.5f, %+.5f] (n=%d, %d weeks)%s"
          % (bs_ours, bs_lo, bs_hi, nn, gg, "" if bs_lo * bs_hi > 0 else "  spans zero"))
    if market_key and any(r.get(market_key) is not None for r in rows):
        mr = [r for r in rows if r.get(market_key) is not None]
        mkt = sum((r[market_key] - r["y"]) ** 2 for r in mr) / len(mr)
        mll = sum(logloss(r[market_key], r["y"]) for r in mr) / len(mr)
        mrel, mres = murphy([dict(r, pm=r[market_key]) for r in mr], "pm")
        print("          market n %4d  Brier %.4f  logloss %.4f  reliability %.4f  resolution %.4f"
              % (len(mr), mkt, mll, mrel, mres))
        dm, mlo, mhi, mn, mg = cluster_bootstrap(
            [dict(r, b_ours=(r["p"] - r["y"]) ** 2, b_mkt=(r[market_key] - r["y"]) ** 2) for r in mr],
            "b_ours", "b_mkt")
        print("          Brier ours - market %+.5f [%+.5f, %+.5f] (n=%d, %d weeks)%s"
              % (dm, mlo, mhi, mn, mg, "" if mlo * mhi > 0 else "  spans zero"))
    else:
        print("          market: absent (no two-sided price stored for this market)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, nargs="+", default=None)
    ap.add_argument("--backtest-seasons", type=int, nargs="+", default=None,
                    help="build the distributions walk-forward in memory instead of reading the lock table")
    ap.add_argument("--csv")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    if a.backtest_seasons:
        import nfl_game_distribution as gd
        built = gd.build(con, set(a.backtest_seasons), min(a.backtest_seasons) - 13)
        rows = enrich(con, built)
        seasons_used = a.backtest_seasons
    else:
        if not a.season:
            raise SystemExit("--season or --backtest-seasons is required")
        rows = load(con, a.season)
        seasons_used = a.season
    for r in rows:
        r["p_win"] = p_over(r["margin_mean"], r["margin_sd"], 0.0)
        r["p_cover"] = p_over(r["margin_mean"], r["margin_sd"], r["spread"]) if r["spread"] is not None else None
        r["p_over"] = p_over(r["total_mean"], r["total_sd"], r["total"]) if r["total"] is not None else None
    print("populations: %d distributions with a final game, seasons %s, weeks %s"
          % (len(rows), sorted(set(seasons_used)), sorted({r["week"] for r in rows})))
    print("method: gaussian margin x gaussian total, independent; estimated by the stored parameters only")

    # winner: ties excluded
    win = []
    ties = 0
    for r in rows:
        if r["actual_margin"] == 0:
            ties += 1
            continue
        win.append({"season": r["season"], "week": r["week"],
                    "y": 1.0 if r["actual_margin"] > 0 else 0.0,
                    "p": r["p_win"], "market": r["market_p"]})
    print("\nwinner (ties excluded: %d)" % ties)
    report("winner", win, market_key="market")

    spreads, push_s = market_rows(rows, "spread", "actual_margin", "p_cover", "margin_mean")
    print("\nspread (pushes excluded: %d; line = the lock's snapshot, else the schedule's closing line)" % push_s)
    report("spread", spreads)
    print("          corr(model margin - line, actual margin - line) %+.3f  "
          "(negative means the model's disagreement with the line is anti-informative)"
          % corr([r["disagree"] for r in spreads], [r["resid"] for r in spreads]))

    totals, push_t = market_rows(rows, "total", "actual_total", "p_over", "total_mean")
    print("\ntotal (pushes excluded: %d)" % push_t)
    report("total", totals)
    print("          corr(model total - line, actual total - line) %+.3f" % corr(
        [r["disagree"] for r in totals], [r["resid"] for r in totals]))

    # distribution coverage of the stated 80% band
    for key, sd, actual in (("margin", "margin_sd", "actual_margin"), ("total", "total_sd", "actual_total")):
        inside = below = above = 0
        for r in rows:
            mean = r["%s_mean" % key]
            z = 1.2815515655446004 * r[sd]
            if r[actual] < mean - z:
                below += 1
            elif r[actual] > mean + z:
                above += 1
            else:
                inside += 1
        n = inside + below + above
        print("  p10-p90 band, %-6s inside %.1f%%  below %.1f%%  above %.1f%%  (nominal 80 / 10 / 10)"
              % (key, 100.0 * inside / n, 100.0 * below / n, 100.0 * above / n))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
