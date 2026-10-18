#!/usr/bin/env python3
"""nfl_team_quality.py -- pregame team ratings from nfl_pbp: EPA/play, and success rate.

Micah's definition, 2026-10-18: **consistency is the success rate**. There is no separate
SD-of-EPA feature. A team is consistent when its plays succeed, and success rate is the one measure
of that. So this module builds exactly two things per team-week, for offense and defense and split
pass/run:

  epa_<type>_<side>    weighted mean EPA per play. The existing input, kept as the control.
  succ_<type>_<side>   weighted mean of the published `success` flag -- the share of plays that
                       succeed. This is the candidate feature.

One place builds both so the control and the treatment in `nfl_success_rate_backtest.py` are
constructed identically and differ only in which features enter the game-level regression.

FILTER (stated because exclusions matter more than the formula):
  play_type IN ('pass','run')            -- drops kickoffs, punts, field goals, extra points, no_play
  epa IS NOT NULL
  coalesce(two_point_attempt, 0) = 0     -- a two-point try is a different play with a different baseline
  pass = pass_attempt = 1 OR qb_dropback = 1
  run  = NOT pass AND rush_attempt = 1   -- so every play lands in exactly one bucket, never both
Counts at each step are printed by `filters_report`, not asserted.

RATINGS, per team and week, from plays BEFORE that week only:
  weights             0.5 ** (weeks_ago / 6.0), the half-life the EPA model already uses
  window              the previous season plus the current season's plays before the target week; the
                      target week is never in its own window
  shrinkage           each mean is pulled toward its league prior with n_eff / (n_eff + K):
                        EPA  K = 150 play-equivalents (the EPA model's LAM)
                        success K = 300 play-equivalents (a binary carries less information per play;
                                  pre-registered, and the backtest re-runs at 150 and 600 as a
                                  sensitivity, not a search)
                      n_eff is Kish's effective sample size (sum w)^2 / sum w^2.
"""
from __future__ import annotations

import math
from collections import defaultdict

HALF_LIFE = 6.0
K_EPA = 150.0
K_SUCC = 300.0
BUCKETS = (("pass", "off"), ("pass", "def"), ("rush", "off"), ("rush", "def"))
MEASURES = ("epa", "succ")
FEATURES = tuple("%s_%s_%s" % (m, typ, side) for m in MEASURES for typ, side in BUCKETS)

SQL = ("SELECT season, week, posteam, defteam, pass_attempt, qb_dropback, rush_attempt, "
       "two_point_attempt, epa, success FROM nfl_pbp WHERE season BETWEEN ? AND ? "
       "AND play_type IN ('pass','run')")


def filters_report(con, first, last):
    """Play counts at each exclusion step, so the filter is auditable rather than asserted."""
    q = lambda sql: con.execute(sql, (first, last)).fetchone()[0]
    base = "FROM nfl_pbp WHERE season BETWEEN ? AND ?"
    keep = "play_type IN ('pass','run') AND epa IS NOT NULL AND COALESCE(two_point_attempt,0) = 0"
    out = {}
    out["all plays"] = q("SELECT COUNT(*) " + base)
    out["play_type pass/run"] = q("SELECT COUNT(*) " + base + " AND play_type IN ('pass','run')")
    out["  with epa"] = q("SELECT COUNT(*) " + base + " AND play_type IN ('pass','run') AND epa IS NOT NULL")
    out["  not two-point"] = q("SELECT COUNT(*) " + base + " AND " + keep)
    out["  classified pass"] = q("SELECT COUNT(*) " + base + " AND " + keep +
                                 " AND (pass_attempt = 1 OR qb_dropback = 1)")
    out["  classified run"] = q("SELECT COUNT(*) " + base + " AND " + keep +
                                " AND NOT (pass_attempt = 1 OR qb_dropback = 1) AND rush_attempt = 1")
    return out


def load_plays(con, first, last):
    """{(season, team, week, type, side): [n, sum(epa), sum(success)]}, unweighted.

    Weights depend on the target week, so they are applied in `_window_sums`, where the exact decay
    0.5 ** ((t_T - t) / 6) is computed per window row. That keeps every factor in a safe range.
    """
    agg = defaultdict(lambda: [0, 0.0, 0.0])
    rows = con.execute(SQL, (first, last))
    n_read = 0
    for season, week, posteam, defteam, pa, drop, rush, two_pt, epa, success in rows:
        if epa is None or two_pt:
            continue
        is_pass = bool(pa) or bool(drop)
        if not is_pass and not rush:
            continue
        if not posteam or not defteam:
            continue
        n_read += 1
        typ = "pass" if is_pass else "rush"
        s = 1.0 if success else 0.0
        for team, side in ((posteam, "off"), (defteam, "def")):
            a = agg[(season, team, week, typ, side)]
            a[0] += 1
            a[1] += epa
            a[2] += s
    return agg, n_read


class Ratings(object):
    """Pregame ratings for one target week, with the league priors they were shrunk toward."""

    def __init__(self, values, prior, n_eff):
        self.values = values
        self.prior = prior
        self.n_eff = n_eff

    def get(self, team, feature):
        return self.values.get((team, feature), self.prior.get(feature, 0.0))


def _window_sums(agg, window, target_t, team, typ, side):
    """Weighted sums for the window, weight = 0.5 ** ((target_t - t) / 6), 0.5 half-life."""
    cnt = w1 = wepa = ws = w2 = 0.0
    for (season, week) in window:
        a = agg.get((season, team, week, typ, side))
        if not a:
            continue
        w = 0.5 ** ((target_t - (season * 18 + week)) / HALF_LIFE)
        cnt += a[0]
        w1 += w * a[0]
        wepa += w * a[1]
        ws += w * a[2]
        w2 += w * w * a[0]
    return cnt, w1, wepa, ws, w2


def ratings_for(agg, season, week, k_succ=K_SUCC, k_epa=K_EPA, teams=None):
    """Ratings for every team for a target (season, week), from the prior season plus earlier weeks."""
    target_t = season * 18 + week
    window = [(season - 1, w) for w in range(1, 19)] + [(season, w) for w in range(1, week)]
    if teams is None:
        teams = sorted({t for (s, t, _w, _t, _sd) in agg if s in (season - 1, season)})
    sums, tot = {}, defaultdict(float)
    for team in teams:
        for typ, side in BUCKETS:
            got = _window_sums(agg, window, target_t, team, typ, side)
            sums[(team, typ, side)] = got
            for i, key in enumerate(("n", "w", "wepa", "ws", "w2")):
                tot[(typ, side, key)] += got[i]
    prior = {}
    for typ, side in BUCKETS:
        w = tot[(typ, side, "w")]
        prior["epa_%s_%s" % (typ, side)] = tot[(typ, side, "wepa")] / w if w else 0.0
        prior["succ_%s_%s" % (typ, side)] = tot[(typ, side, "ws")] / w if w else 0.5
    values, n_eff = {}, {}
    for (team, typ, side), (cnt, w1, wepa, ws, w2) in sums.items():
        neff = (w1 * w1 / w2) if w2 > 0 else 0.0
        for m, num, k in (("epa", wepa, k_epa), ("succ", ws, k_succ)):
            name = "%s_%s_%s" % (m, typ, side)
            pr = prior[name]
            raw = num / w1 if w1 > 0 else pr
            values[(team, name)] = (raw * neff + pr * k) / (neff + k)
            n_eff[(team, name)] = neff
    return Ratings(values, prior, n_eff)
