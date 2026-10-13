#!/usr/bin/env python3
"""nfl_elo_replica.py -- 538's NFL Elo rebuilt from scores, then used as evidence and as a feature.

Why: on identical 2010-2020 games 538 Elo scores Brier 0.2193 and frozen v1 0.2217 (benchmark_ladder_
2010_2020.py). We did not know how a rating this simple scores that low. Measured 2026-10-13 from the
`nfl_elo_538` table (its ratings are the pre-game ratings):
  - elo_prob1 = 1 / (1 + 10^(-(elo1 - elo2 + 65 x [not neutral]) / 400)), mean absolute difference 0.00000 over
    all 2,939 games 2010-2020, playoffs included.
  - post-game rating = pre + 20 x mult x (result - p), mult = ln(|margin| + 1) x 2.2 / (0.001 x winnerdiff + 2.2),
    winnerdiff = the winner's rating minus the loser's including the home 65; matches the next pre-game rating
    (same season) to under 0.01 on 99.75% of 8,036 transitions (mean abs error 0.0045; max 3.8).
  - a new season starts at 2/3 x last rating + 1/3 x 1505 (fit slope 0.6667, intercept 501.67, residual sd 0.000).
So the method is public and tiny. This file runs it forward from our own scores (nfl_schedule), so it extends past
2020, where the 538 file ends.

PRE-REGISTERED (written 2026-10-13 before any run of this file). Plumbing is nfl_feature_backtest.py unchanged
(`stack`, `report`, the shared KEEP rule and groups). No parameter is chosen by looking at a result except where
E4 says the choice is made only from earlier seasons.

Replica: start from the 538 file's pre-game rating of each team in its first 2010 game; every later game updates
with the constants above (K 20, home 65, neutral 0, mult as above; a tie uses the constant multiplier 1.525 with result 0.5. That constant is an E0 finding: the first
E0 run with mult 1 left a 3.8 Elo gap after the 2012 SF-STL tie, and the file's 11 ties (2002-2020) all imply
exactly 1.525; it is not a fitted parameter), ordered by game date
then game id; a team's first game of a new season first applies the 2/3 + 1/3 x 1505 carryover. All scored games are
used, playoffs included, as 538 did. Team code OAK is read as LV.

E0 replication: pre-game ratings of the replica against the file's elo1 and elo2, 2010-2020. Reported: mean absolute
difference, the share within 0.1 Elo, and the games that differ most, twice: with the schedule's neutral flag, and
with the file's own neutral flag (they disagree on 6 relocated home games, which 538 kept as home games). Not a model
result; it says whether we know 538's method.
E1 level: Brier of the replica's probabilities on the harness's graded set (2011-2023 pooled, 2024, 2025), beside
frozen v1 and the market, and on the identical 2010-2020 ladder games beside the file's elo_prob1.
E2 ablation (descriptive: explains 538's number, selects nothing): from the constants above change ONE at a time,
K in {10, 30, 40}, home in {0, 35, 95}, carryover in {0, 1/6, 1/2} (1/3 is 538), margin multiplier off (mult 1).
Reported as Brier on the 2011-2023 graded set and the change against the 538 constants.
E3 feature: `elo_diff` = home pre-game rating minus away pre-game rating plus 65 x [not neutral], as ONE column in
the harness stack on frozen v1 (same keep rule as every feature). `elo_plus_epa` adds epa_units as a second source.
E4 walk-forward tuning (a hail mary, out-of-sample by construction): grid K {10, 15, 20, 25, 30} x home {35, 50, 65,
80} x carryover {0, 1/6, 1/3, 1/2} x margin multiplier {on, off} = 160 configs. For each test season S from 2013 to
2025 pick the config with the lowest Brier on graded games of seasons 2011 to S-1, run it, score season S. Reported:
pooled Brier of the walk-forward pick against fixed 538 constants on the same seasons, and the pick for every season.
Limits: 538 chose its constants with this history in view, so the fixed-constants rung is flattering; the replica
needs the 2010 starting ratings from their file, which is why 2010 is a burn-in.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_elo_replica.py --run E0|E1|E2|E4
       LP_DB_PATH=<dev db> venv/bin/python nfl_elo_replica.py --feature elo_diff|elo_plus_epa   (E3)
"""
from __future__ import annotations

import argparse
import itertools
import math
import sqlite3
import statistics as stt
import sys

import nfl_feature_backtest as fb

CODE = {"OAK": "LV"}
BASE = {"K": 20.0, "hfa": 65.0, "carry": 1.0 / 3.0, "mov": True}
MEAN = 1505.0
TIE_MULT = 1.525


def load_games(con):
    """[(game_id, season, neutral, home, away, hs, as_)] scored games 2010 on, in order."""
    rows = con.execute(
        "SELECT game_id, season, gameday, location, home_team, away_team, home_score, away_score "
        "FROM nfl_schedule WHERE season >= 2010 AND home_score IS NOT NULL ORDER BY gameday, game_id").fetchall()
    return [(g, int(s), (loc or "").strip().lower() == "neutral", CODE.get(h, h), CODE.get(a, a), hs, as_)
            for g, s, d, loc, h, a, hs, as_ in rows]


def start_ratings(con):
    """The 538 file's pre-game rating of each team in its first 2010 game."""
    out = {}
    for t1, t2, e1, e2 in con.execute(
            "SELECT team1, team2, elo1, elo2 FROM nfl_elo_538 WHERE season = '2010' ORDER BY date, rowid"):
        out.setdefault(CODE.get(t1, t1), float(e1))
        out.setdefault(CODE.get(t2, t2), float(e2))
    return out


def run_elo(games, start, K=20.0, hfa=65.0, carry=1.0 / 3.0, mov=True, return_state=False):
    """{game_id: (pre_home, pre_away)} for every game, see the module docstring."""
    rating = dict(start)
    season_of = {t: 2010 for t in rating}
    out = {}
    for gid, season, neutral, h, a, hs, as_ in games:
        for t in (h, a):
            if t not in rating:
                raise ValueError("team %s has no 2010 starting rating (game %s)" % (t, gid))
            if season_of[t] != season:
                rating[t] = rating[t] * (1.0 - carry) + MEAN * carry
                season_of[t] = season
        eh, ea = rating[h], rating[a]
        out[gid] = (eh, ea)
        d = eh - ea + (0.0 if neutral else hfa)
        p = 1.0 / (10.0 ** (-d / 400.0) + 1.0)
        res = 1.0 if hs > as_ else (0.0 if hs < as_ else 0.5)
        m = abs(hs - as_)
        if not mov:
            mult = 1.0
        elif m == 0:
            mult = TIE_MULT  # measured from the 538 file: the same constant in all 11 ties (found by E0)
        else:
            wd = d if hs > as_ else -d
            mult = math.log(m + 1.0) * 2.2 / (wd * 0.001 + 2.2)
        delta = K * mult * (res - p)
        rating[h] += delta
        rating[a] -= delta
    if return_state:
        return out, rating, season_of
    return out


def prob(pre, neutral, hfa=65.0):
    return 1.0 / (10.0 ** (-(pre[0] - pre[1] + (0.0 if neutral else hfa)) / 400.0) + 1.0)


def _setup(con):
    games = load_games(con)
    neutral = {g[0]: g[2] for g in games}
    rows = fb.base_rows(con)
    graded = [r for r in fb.graded(rows)]
    return games, neutral, rows, graded


def _brier(rs, p_of):
    return stt.mean((p_of(r) - r["outcome"]) ** 2 for r in rs)


GROUPS = fb.GROUPS


def e0(con):
    games = load_games(con)
    day = {g: d for g, d in con.execute("SELECT game_id, gameday FROM nfl_schedule WHERE season BETWEEN 2010 AND 2020")}
    file_ = {}
    for date, t1, t2, e1, e2, neu in con.execute(
            "SELECT date, team1, team2, elo1, elo2, neutral FROM nfl_elo_538 "
            "WHERE CAST(season AS INTEGER) BETWEEN 2010 AND 2020"):
        file_[(date, CODE.get(t1, t1), CODE.get(t2, t2))] = (float(e1), float(e2), int(neu) == 1)
    file_neutral, lookup = {}, {}
    for g, season, neutral, h, a, hs, as_ in games:
        if season > 2020:
            continue
        k = (day[g], h, a)
        if k in file_:
            f = file_[k]
        elif (day[g], a, h) in file_:
            f = (file_[(day[g], a, h)][1], file_[(day[g], a, h)][0], file_[(day[g], a, h)][2])
        else:
            lookup[g] = None
            continue
        lookup[g] = f
        file_neutral[g] = f[2]
    games_file = [(g, s, file_neutral.get(g, n), h, a, hs, as_) for g, s, n, h, a, hs, as_ in games]
    for label, gm in (("schedule neutral flag", games), ("file neutral flag", games_file)):
        pre = run_elo(gm, start_ratings(con))
        diffs, worst, missing = [], [], 0
        for g, season, neutral, h, a, hs, as_ in games:
            if season > 2020:
                continue
            f = lookup[g]
            if f is None:
                missing += 1
                continue
            d = max(abs(pre[g][0] - f[0]), abs(pre[g][1] - f[1]))
            diffs.append(d)
            worst.append((d, g))
        worst.sort(reverse=True)
        print("E0 [%s] games %d (no file row: %d); mean abs diff %.4f; within 0.1 Elo %.4f; max %.2f"
              % (label, len(diffs), missing, stt.mean(diffs), sum(d < 0.1 for d in diffs) / len(diffs), max(diffs)))
        print("   largest:", [(round(d, 1), g) for d, g in worst[:5]])


def e1(con):
    games, neutral, rows, graded = _setup(con)
    pre = run_elo(games, start_ratings(con))
    pe = lambda r: prob(pre[r["game_id"]], neutral[r["game_id"]])
    for name, seasons in GROUPS:
        g = [r for r in graded if r["season"] in seasons]
        print("E1 %-9s n=%4d Brier replica %.4f v1 %.4f market %.4f" % (
            name, len(g), _brier(g, pe), _brier(g, lambda r: r["p_model"]), _brier(g, lambda r: r["p_market"])))


def e2(con):
    games, neutral, rows, graded = _setup(con)
    start = start_ratings(con)
    g = [r for r in graded if 2011 <= r["season"] <= 2023]
    pre0 = run_elo(games, start)
    ref = _brier(g, lambda r: prob(pre0[r["game_id"]], neutral[r["game_id"]]))
    print("E2 538 constants, 2011-2023 n=%d: Brier %.4f; v1 %.4f; market %.4f" % (
        len(g), ref, _brier(g, lambda r: r["p_model"]), _brier(g, lambda r: r["p_market"])))
    variants = ([("K", k) for k in (10.0, 30.0, 40.0)] + [("hfa", h) for h in (0.0, 35.0, 95.0)]
                + [("carry", c) for c in (0.0, 1.0 / 6.0, 0.5)] + [("mov", False)])
    for key, val in variants:
        kw = dict(BASE)
        kw[key] = val
        pre = run_elo(games, start, **kw)
        b = _brier(g, lambda r: prob(pre[r["game_id"]], neutral[r["game_id"]], kw["hfa"]))
        print("E2 %-5s=%-8s Brier %.4f  vs 538 constants %+.4f" % (key, val if key == "mov" else "%.3f" % val, b, b - ref))


def e4(con):
    games, neutral, rows, graded = _setup(con)
    start = start_ratings(con)
    grid = list(itertools.product((10.0, 15.0, 20.0, 25.0, 30.0), (35.0, 50.0, 65.0, 80.0),
                                  (0.0, 1.0 / 6.0, 1.0 / 3.0, 0.5), (True, False)))
    pres = {c: run_elo(games, start, K=c[0], hfa=c[1], carry=c[2], mov=c[3]) for c in grid}

    def sse(c, seasons):
        pre = pres[c]
        rs = [r for r in graded if r["season"] in seasons]
        return stt.mean((prob(pre[r["game_id"]], neutral[r["game_id"]], c[1]) - r["outcome"]) ** 2 for r in rs)
    tot_w = tot_f = n = 0
    for S in range(2013, 2026):
        past = set(range(2011, S))
        best = min(grid, key=lambda c: sse(c, past))
        rs = [r for r in graded if r["season"] == S]
        bw = stt.mean((prob(pres[best][r["game_id"]], neutral[r["game_id"]], best[1]) - r["outcome"]) ** 2 for r in rs)
        bf = _brier(rs, lambda r: prob(pres[(20.0, 65.0, 1.0 / 3.0, True)][r["game_id"]], neutral[r["game_id"]]))
        tot_w += bw * len(rs); tot_f += bf * len(rs); n += len(rs)
        print("E4 %d pick K=%g hfa=%g carry=%.3f mov=%s | season Brier tuned %.4f fixed-538 %.4f"
              % (S, best[0], best[1], best[2], best[3], bw, bf))
    print("E4 pooled 2013-2025 n=%d: walk-forward tuned %.4f, fixed 538 constants %.4f, diff %+.4f"
          % (n, tot_w / n, tot_f / n, tot_w / n - tot_f / n))


@fb.feature
def elo_diff(con, rows):
    games = load_games(con)
    pre = run_elo(games, start_ratings(con))
    neutral = {g[0]: g[2] for g in games}
    cols = {r["game_id"]: [pre[r["game_id"]][0] - pre[r["game_id"]][1]
                           + (0.0 if neutral[r["game_id"]] else 65.0)] for r in rows}
    return fb._complete(rows, cols), None


@fb.feature
def elo_plus_epa(con, rows):
    a, _ = elo_diff(con, rows)
    b, _ = fb.epa_units(con, rows)
    return fb._complete(rows, {k: a[k] + b[k] for k in a}), None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", choices=["E0", "E1", "E2", "E4"])
    g.add_argument("--feature", choices=["elo_diff", "elo_plus_epa"])
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % fb.DB, uri=True)
    if a.run:
        {"E0": e0, "E1": e1, "E2": e2, "E4": e4}[a.run](con)
        return 0
    rows = fb.base_rows(con)
    base = fb.stack(rows)
    cols, sigma_fn = fb.FEATURES[a.feature](con, rows)
    fb.report(rows, base, fb.stack(rows, cols, sigma_fn), a.feature)
    return 0


if __name__ == "__main__":
    sys.exit(main())
