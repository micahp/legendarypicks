#!/usr/bin/env python3
"""nfl_shotgun_feature.py -- does the league's move away from under center change what frozen v1 should do?

Idea (Micah's friend, clarified by Micah 2026-10-13): this is NOT about whether a team uses
shotgun. It is about the era: the league moved from quarterbacks mostly taking snaps under center
to mostly shotgun, which changed how the game is played (shotgun share of plays: 28.8% in 2010,
55.1% in 2023, 50.3% in 2025, counted in nfl_pbp). A model with fixed weights fitted across that
shift may be wrong in both halves. The feature is therefore a property of the SEASON, not of a
team: the league shotgun share, used as an era variable.

This replaces the team-level shotgun definition committed in 0779c8a, which was never run.

Plumbing is `nfl_feature_backtest.py` unchanged: this file only registers features with its
`@feature` decorator and runs its `stack` and `report`. Every shared rule there applies (graded
set, 2011-2023 pooled, 2024, 2025, KEEP rule, 5,000 paired resamples, no parameter chosen by
looking at a result).

PRE-REGISTERED (written 2026-10-13 before the first run of this file)

era: the league shotgun share, the share of all offensive plays (pass or rush attempts) with
shotgun = 1, pooled over every team-game of the SAME season strictly before the game. Same
season, so it is known before kickoff and tracks the shift as it happens; the base rows start at
week 2, so it always has at least one week behind it. No break date is chosen. A step at an
invented year would be a parameter picked by looking at the data, so the era enters as a
continuous variable and the stack learns what it does. The harness fits on seasons 2010 to S-1,
so the training data contains the whole 28.8% to 55% transition.

era_shift: two stack columns, era (moves the home margin by a level: home field and scoring
environment changing with the era) and era x v1 projected margin (stretches or shrinks v1's margin
with the era: a favourite means more or less than it used to). Sigma as in the plain stack.

era_sigma: the baseline stack's margin, but sigma allowed to move with the era. sigma(game) =
sqrt(max(c0 + c1 x era, 25)), with c0, c1 from OLS of the training residuals squared on [1, era]
(sd floor 5 points). The era may change how spread out results are, which moves Brier without
moving the margin.

era_all: era_shift columns plus era_sigma together.

epa_plus_era: epa_units (the one own-data feature that met the keep rule, +0.0019 earlier) and the
two era_shift columns in one stack. Answers whether the era adds on top of it.

stacked_all (EXPLORATORY, not a keep test, never to be adopted from this run): every dev-harness
own-data feature that was not market-derived (epa_units, special_teams, venue_conditions,
pressure_matchup, sack_matchup, share_absence) plus the era_shift columns, in one stack. An upper
bound on what stacking everything could do; choosing the combination after seeing the singles
inflates it, and it is labelled so wherever it is quoted.

Limits stated up front: nfl_pbp starts in 2010, so the era variable cannot be tested before 2010
and the shotgun's earlier history is not in this data. Three seasons of the era's current plateau
(2023 to 2025) are the only evidence for how the variable behaves at its top.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_shotgun_feature.py --feature <name>
"""
from __future__ import annotations

import argparse
import bisect
import math
import sqlite3
import sys

import numpy as np

import nfl_feature_backtest as fb

SIGMA_FLOOR_VAR = 25.0


def _league_cumulative(con):
    """{season: (sorted [(week, game_id)], cumulative [(plays, shotgun_plays)])} from nfl_pbp."""
    per_season = {}
    q = ("SELECT season, week, game_id, posteam, SUM(pass_attempt = 1 OR rush_attempt = 1), "
         "SUM((pass_attempt = 1 OR rush_attempt = 1) AND shotgun = 1) FROM nfl_pbp "
         "WHERE season BETWEEN 2010 AND 2025 AND posteam IS NOT NULL "
         "GROUP BY season, week, game_id, posteam")
    for s, w, g, t, pl, sg in con.execute(q):
        per_season.setdefault(int(s), []).append((int(w), g, pl or 0, sg or 0))
    out = {}
    for s, recs in per_season.items():
        recs.sort()
        c = [(0, 0)]
        for r in recs:
            c.append((c[-1][0] + r[2], c[-1][1] + r[3]))
        out[s] = ([(r[0], r[1]) for r in recs], c)
    return out


def era_values(con, rows):
    """{game_id: league shotgun share before the game, same season}. Raises if there is none."""
    cum = _league_cumulative(con)
    out = {}
    for r in rows:
        keys, c = cum[int(r["season"])]
        plays, sg = c[bisect.bisect_left(keys, (int(r["week"]), ""))]
        if plays == 0:
            raise ValueError("no same-season league history before %s" % r["game_id"])
        out[r["game_id"]] = sg / float(plays)
    return out


def _shift_cols(rows, era):
    return {r["game_id"]: [era[r["game_id"]], era[r["game_id"]] * r["proj_margin"]] for r in rows}


def _sigma_by_era(era):
    def make(train, res):
        X = [[1.0, era[r["game_id"]]] for r in train]
        beta = fb.ols(X, np.asarray(res) ** 2)

        def sig(r):
            return math.sqrt(max(beta[0] + beta[1] * era[r["game_id"]], SIGMA_FLOOR_VAR))
        return sig
    return make


@fb.feature
def era_shift(con, rows):
    return fb._complete(rows, _shift_cols(rows, era_values(con, rows))), None


@fb.feature
def era_sigma(con, rows):
    return None, _sigma_by_era(era_values(con, rows))


@fb.feature
def era_all(con, rows):
    era = era_values(con, rows)
    return fb._complete(rows, _shift_cols(rows, era)), _sigma_by_era(era)


def _join(*parts):
    out = {}
    for p in parts:
        for k, v in p.items():
            out[k] = out.get(k, []) + list(v)
    return out


@fb.feature
def epa_plus_era(con, rows):
    a, _ = fb.epa_units(con, rows)
    return fb._complete(rows, _join(a, _shift_cols(rows, era_values(con, rows)))), None


@fb.feature
def stacked_all(con, rows):
    parts = [fb.epa_units(con, rows)[0], fb.special_teams(con, rows)[0],
             fb.venue_conditions(con, rows)[0], fb.pressure_matchup(con, rows)[0],
             fb.sack_matchup(con, rows)[0], fb.share_absence(con, rows)[0],
             _shift_cols(rows, era_values(con, rows))]
    return fb._complete(rows, _join(*parts)), None


NAMES = ["era_shift", "era_sigma", "era_all", "epa_plus_era", "stacked_all"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--feature", required=True, choices=NAMES)
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    rows = fb.base_rows(con)
    base = fb.stack(rows)
    cols, sigma_fn = fb.FEATURES[a.feature](con, rows)
    fb.report(rows, base, fb.stack(rows, cols, sigma_fn), a.feature)
    return 0


if __name__ == "__main__":
    sys.exit(main())
