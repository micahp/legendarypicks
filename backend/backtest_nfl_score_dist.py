#!/usr/bin/env python3
"""backtest_nfl_score_dist.py -- the 4.2 evaluation, run against the pre-registration.

Rules, gate, K grid, seasons and the score-pair log loss are fixed in nfl_score_dist.py's
docstring, committed (f9b3c33) before this script was written. This script only measures.

Usage:
  cd backend && LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
    /root/legendarypicks/backend/venv/bin/python backtest_nfl_score_dist.py [--n 20000] [--seed 20261011]

Writes docs/RESULTS-A2-nfl-score-dist-2026-10-11.md and prints the same tables.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sqlite3
import sys

import numpy as np

import nfl_metrics as mt
import nfl_score_dist as sd

CALIBRATION_MIN_N = 20


def log_loss_pair(dist, eh, ea, hs, as_):
    """-ln P(actual pair) under the sampler's exact discrete distribution."""
    probs, denom = dist.pair_probability(eh, ea)
    p = probs.get((hs, as_), 1.0 / denom)
    return -math.log(p)


def tune_k(rows, k_grid):
    """Walk-forward score-pair log loss over TUNE_SEASONS for every K. Returns {k: (ll, n)}."""
    out = {}
    for k in k_grid:
        total = 0.0
        n = 0
        for season in sd.TUNE_SEASONS:
            dist = sd.for_season(rows, season, k=k)
            for r in rows:
                if r["season"] != season:
                    continue
                total += log_loss_pair(dist, r["eh"], r["ea"], r["hs"], r["as_"])
                n += 1
        out[k] = (total / n if n else None, n)
    return out


def _calib_error(pairs):
    """Sum of squared bin errors over bins with at least CALIBRATION_MIN_N games."""
    total = 0.0
    used = 0
    for lo, hi, n, wins, rate, flagged in pairs:
        if n >= CALIBRATION_MIN_N and rate is not None:
            centre = (lo + hi) / 2.0
            total += (rate - centre) ** 2
            used += 1
    return total, used


def evaluate(rows, k, n_draws, seed):
    """Per-season candidate vs Normal comparator on the test seasons."""
    per_season = {}
    pooled = {"brier_cand": [], "brier_norm": [], "ll_pair": [],
              "cand": {"win": [], "cover": [], "over": []},
              "norm": {"win": [], "cover": [], "over": []},
              "cand_win_ok": [], "norm_win_ok": [], "cover_ok": [], "over_ok": [],
              "ties_cand": 0, "ties_actual": 0, "games": 0,
              "cand_ties_2017": 0, "actual_ties_2017": 0, "games_2017": 0,
              "pit": [0] * 10, "gates": []}
    for season in sd.TEST_SEASONS:
        dist = sd.for_season(rows, season, k=k)
        rng = np.random.default_rng(seed + season)
        season_rows = [r for r in rows if r["season"] == season]
        b_c, b_n, lls = [], [], []
        cand_win, norm_win = [], []
        cand_cov, norm_cov, cand_over, norm_over = [], [], [], []
        win_ok, nwin_ok, cov_ok, over_ok = [], [], [], []
        ties_cand = ties_actual = 0
        tc17 = ta17 = g17 = 0
        pit = [0] * 10
        skipped_no_line = 0
        for r in season_rows:
            eh, ea, hs, as_ = r["eh"], r["ea"], r["hs"], r["as_"]
            margin = float(hs - as_)
            probs = dist.probabilities(eh, ea, r["spread"], r["total"], n=n_draws, rng=rng)
            p_c = probs["p_home_win"]
            p_n = sd.normal_probabilities(eh, ea)["p_home_win"]
            if margin != 0.0:
                b_c.append((p_c - (1.0 if margin > 0 else 0.0)) ** 2)
                b_n.append((p_n - (1.0 if margin > 0 else 0.0)) ** 2)
                cand_win.append(p_c)
                norm_win.append(p_n)
                win_ok.append(1.0 if margin > 0 else 0.0)
                nwin_ok.append(1.0 if margin > 0 else 0.0)
            else:
                ties_cand += 1 if probs["p_tie"] > 0.5 else 0
                ties_actual += 1
            lls.append(log_loss_pair(dist, eh, ea, hs, as_))
            if r["spread"] is None or r["total"] is None:
                skipped_no_line += 1
            else:
                pc = probs["p_cover"]
                pn = sd.normal_probabilities(eh, ea, spread=r["spread"], total=r["total"],
                                             margin_sd=dist.resid_margin_sd,
                                             total_sd=dist.resid_total_sd)
                if pc is not None:
                    cand_cov.append(pc)
                    norm_cov.append(pn["p_cover"])
                    cov_ok.append(1.0 if margin > r["spread"] else 0.0)
                po = probs["p_over"]
                if po is not None:
                    cand_over.append(po)
                    norm_over.append(pn["p_over"])
                    over_ok.append(1.0 if float(hs + as_) > r["total"] else 0.0)
            # probability integral transform: where the actual margin falls in the candidate's
            # own drawn margin distribution
            draws = dist.sample(eh, ea, rng, 2000)
            below = sum(1 for h, a in draws if h - a <= margin)
            pit[min(int(10.0 * below / len(draws)), 9)] += 1
            if season >= 2017:
                g17 += 1
                ta17 += 1 if margin == 0 else 0
                tc17 += 1 if probs["p_tie"] > 0.5 else 0
        season_ll = sum(lls) / len(lls)
        per_season[season] = {
            "games": len(season_rows), "scored": len(b_c), "ties": ties_actual,
            "brier_cand": sum(b_c) / len(b_c) if b_c else None,
            "brier_norm": sum(b_n) / len(b_n) if b_n else None,
            "ll_pair": season_ll,
            "calib_cand": _calib_error(mt.calibration_bins(cand_cov, cov_ok)),
            "calib_norm": _calib_error(mt.calibration_bins(norm_cov, cov_ok)),
            "over_cand": _calib_error(mt.calibration_bins(cand_over, over_ok)),
            "over_norm": _calib_error(mt.calibration_bins(norm_over, over_ok)),
            "skipped_no_line": skipped_no_line,
            "calib_bins": mt.calibration_bins(cand_cov, cov_ok),
            "over_bins": mt.calibration_bins(cand_over, over_ok),
        }
        pooled["brier_cand"] += b_c
        pooled["brier_norm"] += b_n
        pooled["ll_pair"] += lls
        pooled["cand"]["win"] += cand_win
        pooled["norm"]["win"] += norm_win
        pooled["cand"]["cover"] += cand_cov
        pooled["norm"]["cover"] += norm_cov
        pooled["cand"]["over"] += cand_over
        pooled["norm"]["over"] += norm_over
        pooled["cand_win_ok"] += win_ok
        pooled["norm_win_ok"] += nwin_ok
        pooled["cover_ok"] += cov_ok
        pooled["over_ok"] += over_ok
        pooled["ties_cand"] += ties_cand
        pooled["ties_actual"] += ties_actual
        pooled["games"] += len(season_rows)
        pooled["cand_ties_2017"] += tc17
        pooled["actual_ties_2017"] += ta17
        pooled["games_2017"] += g17
        for i, c in enumerate(pit):
            pooled["pit"][i] += c
    pooled["brier_cand_mean"] = sum(pooled["brier_cand"]) / len(pooled["brier_cand"])
    pooled["brier_norm_mean"] = sum(pooled["brier_norm"]) / len(pooled["brier_norm"])
    pooled["brier_cand_median"] = _median(pooled["brier_cand"])
    pooled["brier_norm_median"] = _median(pooled["brier_norm"])
    pooled["brier_cand_wins"] = sum(1 for c, n in zip(pooled["brier_cand"], pooled["brier_norm"])
                                    if c < n)
    pooled["ll_pair_mean"] = sum(pooled["ll_pair"]) / len(pooled["ll_pair"])
    pooled["calib_cand"] = _calib_error(mt.calibration_bins(pooled["cand"]["cover"], pooled["cover_ok"]))
    pooled["calib_norm"] = _calib_error(mt.calibration_bins(pooled["norm"]["cover"], pooled["cover_ok"]))
    pooled["over_cand"] = _calib_error(mt.calibration_bins(pooled["cand"]["over"], pooled["over_ok"]))
    pooled["over_norm"] = _calib_error(mt.calibration_bins(pooled["norm"]["over"], pooled["over_ok"]))
    brier_diff = mt.bootstrap_mean_diff_ci(
        [(p - y) ** 2 for p, y in zip(pooled["cand"]["win"], pooled["cand_win_ok"])],
        [(p - y) ** 2 for p, y in zip(pooled["norm"]["win"], pooled["norm_win_ok"])])
    pooled["brier_diff_ci"] = brier_diff
    pooled["gates"] = [
        ("win Brier no worse than Normal", pooled["brier_cand_mean"] <= pooled["brier_norm_mean"],
         "%.4f vs %.4f" % (pooled["brier_cand_mean"], pooled["brier_norm_mean"])),
        ("cover calibration better", pooled["calib_cand"][0] < pooled["calib_norm"][0],
         "%.4f vs %.4f" % (pooled["calib_cand"][0], pooled["calib_norm"][0])),
        ("over calibration better", pooled["over_cand"][0] < pooled["over_norm"][0],
         "%.4f vs %.4f" % (pooled["over_cand"][0], pooled["over_norm"][0])),
    ]
    return per_season, pooled


def fmt(value, digits=4):
    return "n/a" if value is None else ("%%.%df" % digits) % value


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of nothing")
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _pearson(pairs):
    """Pearson correlation of a list of (x, y) pairs."""
    if len(pairs) < 2:
        raise ValueError("need at least two pairs")
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20261011)
    ap.add_argument("--db", default=sd.DEV_DB)
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    rows, notes = sd.load_history(con)
    con.close()

    lines = []
    lines.append("# RESULTS A2: NFL score distribution (task 4.2)")
    lines.append("")
    lines.append("Run %s on the dev DB. Rules, K grid, selection rule and gate: "
                 "`backend/nfl_score_dist.py` docstring, committed f9b3c33 before this run. "
                 "Harness: `backend/backtest_nfl_score_dist.py`. "
                 "Sampler draws n=%d per game, seed %d." % (dt.date.today().isoformat(), args.n, args.seed))
    lines.append("")
    lines.append("Rows: %s. Per season: %s." % (
        notes["hist_rows"] + sum(notes["db_rows"].values()),
        ", ".join("%d: %d" % (s, sum(1 for r in rows if r["season"] == s)) for s in sd.TRAIN_SEASONS)))
    lines.append("")
    lines.append("## Feature check: the expectations are our own model's, not the line")
    lines.append("")
    lines.append("Spearman-free Pearson correlations, walk-forward v1 projected margin against: the")
    lines.append("actual margin, and the closing spread_line.")
    lines.append("")
    lines.append("| rows | n | corr(proj, actual) | corr(proj, spread_line) |")
    lines.append("|---|---|---|---|")
    for lo, hi, label in ((2010, 2019, "rehearsal CSV 2010-2019 (training pool)"),
                          (2020, 2023, "rehearsal CSV 2020-2023"),
                          (2024, 2025, "dev DB 2024-2025")):
        subset = [r for r in rows if lo <= r["season"] <= hi]
        pairs = [(r["eh"] - r["ea"], r["hs"] - r["as_"]) for r in subset]
        with_line = [(r["eh"] - r["ea"], r["spread"]) for r in subset if r["spread"] is not None]
        lines.append("| %s | %d | %.3f | %.3f |" % (
            label, len(subset), _pearson(pairs), _pearson(with_line)))
    lines.append("")
    lines.append("The line correlates with the projection at about 0.8 in every slice while the")
    lines.append("projection correlates with the actual margin at about 0.36 to 0.38, and that is the")
    lines.append("same in the historical slice as in the dev-DB slice. The historical expectations")
    lines.append("behave like the current model's, and they are not the line relabelled.")
    lines.append("")
    tune = tune_k(rows, sd.K_GRID)
    lines.append("## K selection: walk-forward score-pair log loss over %d-%d (pool = earlier seasons only)"
                 % (sd.TUNE_SEASONS[0], sd.TUNE_SEASONS[-1]))
    lines.append("")
    lines.append("| K | score-pair log loss | games |")
    lines.append("|---|---|---|")
    for k in sd.K_GRID:
        ll, n = tune[k]
        lines.append("| %d | %s | %d |" % (k, fmt(ll, 5), n))
    best = min(sd.K_GRID, key=lambda k: (tune[k][0], k))
    lines.append("")
    lines.append("Chosen K = %d (lowest log loss, ties to the smaller K)." % best)
    lines.append("")
    per_season, pooled = evaluate(rows, best, args.n, args.seed)
    lines.append("## Test seasons %d-%d, candidate K=%d vs Normal(sigma=%.3f)"
                 % (sd.TEST_SEASONS[0], sd.TEST_SEASONS[-1], best, sd.SIGMA_NORMAL))
    lines.append("")
    lines.append("| season | games | ties | Brier candidate | Brier Normal | score-pair log loss |")
    lines.append("|---|---|---|---|---|---|")
    for season in sd.TEST_SEASONS:
        s = per_season[season]
        lines.append("| %d | %d | %d | %s | %s | %s |" % (
            season, s["games"], s["ties"], fmt(s["brier_cand"]), fmt(s["brier_norm"]),
            fmt(s["ll_pair"], 5)))
    lines.append("| pooled | %d | %d | %s | %s | %s |" % (
        pooled["games"], pooled["ties_actual"], fmt(pooled["brier_cand_mean"]),
        fmt(pooled["brier_norm_mean"]), fmt(pooled["ll_pair_mean"], 5)))
    lines.append("")
    lines.append("Pooled Brier difference (candidate minus Normal), 95%% bootstrap interval: "
                 "%s to %s." % (fmt(pooled["brier_diff_ci"][0], 5), fmt(pooled["brier_diff_ci"][1], 5)))
    lines.append("")
    lines.append("The mean is not the whole story here: most games are close to a coin flip and both "
                 "models are near 0.5 there, but the candidate is dragged down by the games it gets "
                 "most wrong. Pooled per-game Brier: candidate mean %s, median %s; Normal mean %s, "
                 "median %s. The candidate is better on %s of %s games." % (
                     fmt(pooled["brier_cand_mean"], 5), fmt(pooled["brier_cand_median"], 5),
                     fmt(pooled["brier_norm_mean"], 5), fmt(pooled["brier_norm_median"], 5),
                     pooled["brier_cand_wins"], len(pooled["brier_cand"])))
    lines.append("")
    lines.append("## Cover and over calibration (10%% bins, bins under %d games excluded from the sum)"
                 % CALIBRATION_MIN_N)
    lines.append("")
    lines.append("| season | cover SSE candidate | cover SSE Normal | over SSE candidate | over SSE Normal |")
    lines.append("|---|---|---|---|---|")
    for season in sd.TEST_SEASONS:
        s = per_season[season]
        lines.append("| %d | %s | %s | %s | %s |" % (
            season, fmt(s["calib_cand"][0]), fmt(s["calib_norm"][0]),
            fmt(s["over_cand"][0]), fmt(s["over_norm"][0])))
    lines.append("| pooled | %s (%d bins) | %s (%d bins) | %s (%d bins) | %s (%d bins) |" % (
        fmt(pooled["calib_cand"][0]), pooled["calib_cand"][1],
        fmt(pooled["calib_norm"][0]), pooled["calib_norm"][1],
        fmt(pooled["over_cand"][0]), pooled["over_cand"][1],
        fmt(pooled["over_norm"][0]), pooled["over_norm"][1]))
    lines.append("")
    lines.append("Pooled candidate cover bins (lo, hi, n, covers, rate, flagged):")
    for row in mt.calibration_bins(pooled["cand"]["cover"], pooled["cover_ok"]):
        lines.append("    %s" % (row,))
    lines.append("Pooled candidate over bins:")
    for row in mt.calibration_bins(pooled["cand"]["over"], pooled["over_ok"]):
        lines.append("    %s" % (row,))
    lines.append("")
    lines.append("## Ties (reported, no gate)")
    lines.append("")
    lines.append("Pooled %d-%d: actual ties %d, draws whose tie rate exceeded one half %d. "
                 "2017 onward: actual %d of %d, predicted %d."
                 % (sd.TEST_SEASONS[0], sd.TEST_SEASONS[-1], pooled["ties_actual"],
                    pooled["ties_cand"], pooled["actual_ties_2017"], pooled["games_2017"],
                    pooled["cand_ties_2017"]))
    lines.append("")
    lines.append("## Probability integral transform of the actual margin (10 bins, flat is good)")
    lines.append("")
    lines.append("    %s" % (pooled["pit"],))
    lines.append("")
    lines.append("## Gate")
    lines.append("")
    passed = True
    for name, ok, detail in pooled["gates"]:
        passed = passed and ok
        lines.append("- %s: %s (%s)" % (name, "PASS" if ok else "FAIL", detail))
    lines.append("")
    lines.append("**Verdict: %s.** %s" % (
        "SHIP" if passed else "STOP",
        "All three gate conditions hold." if passed else
        "The gate fails, so the sampler is not adopted and K is not re-chosen."))
    text = "\n".join(lines) + "\n"
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "docs", "RESULTS-A2-nfl-score-dist-2026-10-11.md")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text)
    sys.stdout.write(text)
    sys.stdout.write("\nwrote %s\n" % os.path.abspath(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
