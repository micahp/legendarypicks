#!/usr/bin/env python3
"""nfl_era_scores.py -- slowly moving era variables built from SCORES only, so they can use history back to 1920.

Why (Micah, 2026-10-13): the move away from under center is not the only thing that changed in the game, and play
data only starts in 2010 (nfl_pbp). Scores go back to 1920 (nfl_elo_538, 16,810 games, ends 2020) and nfl_schedule
covers 2010 on. By decade, non-neutral games: mean total points 38.3 (1970s), 42.3 (2000s), 45.4 (2010s); margin sd
about 18 (1940s) falling to about 14.6 (2010s); home win rate 57% with 60.2% in the 1990s and 49.8% in the 2020 season.
These variables capture such drift without naming its cause or choosing a break year.

Plumbing is `nfl_feature_backtest.py` unchanged (`stack`, `report`, the shared KEEP rule and groups). This file only
registers features with its `@feature` decorator. Every shared rule there applies.

PRE-REGISTERED (written 2026-10-13 before the first run of this file)

History: seasons 1920 to 2020 from `nfl_elo_538` (team1 is the home team; neutral games dropped), seasons 2021 on from
`nfl_schedule` (REG and POST, scored, location not Neutral). A game's features use only SEASONS BEFORE ITS OWN SEASON,
pooled over the window, so nothing from the season being scored enters. Windows are fixed here and not tuned: recent
= the previous 3 seasons for scoring and spread, the previous 5 for home field; long run = the previous 25 seasons.
2020 (played mostly without fans) is in the windows as data; it is not removed.

hfa_drift: one column, the mean home margin over the previous 5 seasons minus the mean over the previous 25.
scoring_scale: one column, (mean total points per game over the previous 3 seasons / over the previous 25 - 1) x v1
projected margin. Higher scoring means a given favourite wins by more points, so v1's margins may be too small or too
large in the current environment.
spread_sigma: no margin column; sigma varies with era: sigma(game) = sqrt(max(c0 + c1 x d, 25)) where d = the sd of
margin over the previous 3 seasons minus the sd over the previous 25, and c0, c1 come from OLS of the training
residuals squared on [1, d] (sd floor 5 points).
era_scores_all: hfa_drift and scoring_scale columns together with spread_sigma.

Limits stated up front: each variable is constant within a season, so the stack has only 13 to 15 distinct values to
learn from and a coefficient on it is weakly identified; a gain from it is more likely to be an overfit than a
coefficient measured on a game-level feature. It is reported with the same intervals and the same keep rule, which
needs the 2024 and 2025 point differences not above zero too.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_era_scores.py --feature hfa_drift|scoring_scale|spread_sigma|era_scores_all
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys

import numpy as np

import nfl_feature_backtest as fb

SIGMA_FLOOR_VAR = 25.0


def season_sums(con):
    """{season: (n, sum_margin, sum_total, sum_margin_sq)} over non-neutral scored games."""
    acc = {}

    def add(season, hs, as_):
        n, sm, st_, sq = acc.get(season, (0, 0.0, 0.0, 0.0))
        m = hs - as_
        acc[season] = (n + 1, sm + m, st_ + hs + as_, sq + m * m)
    for season, neu, s1, s2 in con.execute("SELECT season, neutral, score1, score2 FROM nfl_elo_538"):
        if int(neu) != 1:
            add(int(season), float(s1), float(s2))
    for season, loc, hs, as_ in con.execute(
            "SELECT season, location, home_score, away_score FROM nfl_schedule "
            "WHERE season >= 2021 AND home_score IS NOT NULL"):
        if (loc or "").strip().lower() != "neutral":
            add(int(season), float(hs), float(as_))
    return acc


def window(acc, season, years):
    """Pooled (mean margin, mean total, sd margin) over the `years` seasons before `season`."""
    n = sm = st_ = sq = 0
    for y in range(season - years, season):
        if y in acc:
            a = acc[y]
            n += a[0]; sm += a[1]; st_ += a[2]; sq += a[3]
    if n < 100:
        raise ValueError("fewer than 100 games in the %d seasons before %d" % (years, season))
    mean = sm / n
    return mean, st_ / n, math.sqrt(max(sq / n - mean * mean, 0.0))


def era_by_season(con):
    acc = season_sums(con)
    out = {}
    for s in fb.SEASONS:
        hfa5, _, _ = window(acc, s, 5)
        hfa25, tot25, sd25 = window(acc, s, 25)
        _, tot3, sd3 = window(acc, s, 3)
        out[s] = {"hfa_drift": hfa5 - hfa25, "scoring": tot3 / tot25 - 1.0, "sd_drift": sd3 - sd25}
    return out


def _cols(rows, era, keys):
    out = {}
    for r in rows:
        e = era[int(r["season"])]
        col = []
        if "hfa_drift" in keys:
            col.append(e["hfa_drift"])
        if "scoring_scale" in keys:
            col.append(e["scoring"] * r["proj_margin"])
        out[r["game_id"]] = col
    return out


def _sigma(era):
    def make(train, res):
        X = [[1.0, era[int(r["season"])]["sd_drift"]] for r in train]
        beta = fb.ols(X, np.asarray(res) ** 2)

        def sig(r):
            return math.sqrt(max(beta[0] + beta[1] * era[int(r["season"])]["sd_drift"], SIGMA_FLOOR_VAR))
        return sig
    return make


@fb.feature
def hfa_drift(con, rows):
    return fb._complete(rows, _cols(rows, era_by_season(con), ("hfa_drift",))), None


@fb.feature
def scoring_scale(con, rows):
    return fb._complete(rows, _cols(rows, era_by_season(con), ("scoring_scale",))), None


@fb.feature
def spread_sigma(con, rows):
    return None, _sigma(era_by_season(con))


@fb.feature
def era_scores_all(con, rows):
    era = era_by_season(con)
    return fb._complete(rows, _cols(rows, era, ("hfa_drift", "scoring_scale"))), _sigma(era)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--feature", required=True, choices=["hfa_drift", "scoring_scale", "spread_sigma", "era_scores_all"])
    ap.add_argument("--print-era", action="store_true", help="print the per-season variables and exit")
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    if a.print_era:
        for s, e in era_by_season(con).items():
            print(s, {k: round(v, 4) for k, v in e.items()})
        return 0
    rows = fb.base_rows(con)
    base = fb.stack(rows)
    cols, sigma_fn = fb.FEATURES[a.feature](con, rows)
    fb.report(rows, base, fb.stack(rows, cols, sigma_fn), a.feature)
    return 0


if __name__ == "__main__":
    sys.exit(main())
