#!/usr/bin/env python3
"""nfl_feature_backtest.py -- one candidate feature at a time, stacked on frozen v1, judged
against a recalibrated v1 and against the de-vigged market. Read-only: the database is opened
with mode=ro and nothing is recorded. Plan: docs/PLAN-nfl-features-2026-10-11.md.

PRE-REGISTERED RULES (shared by every feature; written before any feature was run)
- Base: frozen v1 walk-forward rows (nfl_backtest.backtest_season, half_life 6, cap 14,
  cap_points off), seasons 2010-2025. Each row uses only earlier weeks of its season.
- Stack: for target season S, OLS of actual home margin on [1, v1 projected margin, feature
  columns], fitted on every base row of seasons 2010 to S-1 (ties included in the margin fit).
  sigma = sd (ddof 1) of that fit's residuals unless the feature defines its own sigma.
  p_home = Phi(margin / sigma). Baseline B is the same stack with no feature columns.
- Every feature column for a game is computed from data dated before that game's week.
- Graded set: games with an outcome (no tie), a moneyline and a spread. Groups: 2011-2023
  pooled (development; 2010 is training only), 2024 (confirmation), 2025 (second look only,
  it was v1's holdout).
- Intervals: nfl_metrics.bootstrap_mean_diff_ci, 5,000 resamples, its fixed seed.
- KEEP rule: the pooled 2011-2023 interval of Brier(feature) - Brier(B) lies entirely below
  zero, AND the 2024 and 2025 point differences are not above zero. Anything else is not kept.
  Margin MAE (feature - B) is reported the same way; a feature that changes only sigma cannot
  move it. The gap to the market (feature - market) is reported for every group.
- No parameter is chosen by looking at any result of this harness. Feature parameters are fixed
  in each feature's own docstring before it is run.

Usage: LP_DB_PATH=<dev db> venv/bin/python nfl_feature_backtest.py --feature <name>
       (--feature base prints B and frozen v1 only)
"""
from __future__ import annotations

import argparse
import bisect
import math
import os
import sqlite3
import sys

import numpy as np

import nfl_backtest as nb
import nfl_metrics as nm

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.dev.db")
FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "sigma": 13.295}
SEASONS = list(range(2010, 2026))
GROUPS = (("2011-2023", range(2011, 2024)), ("2024", (2024,)), ("2025", (2025,)))
REPS = 5000


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def base_rows(con):
    rows = []
    for s in SEASONS:
        rows += nb.backtest_season(con, s, FROZEN)
    return rows


def ols(X, y):
    beta, *_ = np.linalg.lstsq(np.asarray(X), np.asarray(y), rcond=None)
    return beta


def stack(rows, cols=None, sigma_fn=None):
    """Return game_id -> (proj_margin, p_home) for seasons 2011-2025.

    cols: game_id -> list of feature values (None = baseline B).
    sigma_fn(train_rows, residuals) -> function(row) -> sigma, or None for one sigma.
    """
    out = {}
    for s in SEASONS[1:]:
        train = [r for r in rows if r["season"] < s]
        test = [r for r in rows if r["season"] == s]

        def x(r):
            return [1.0, r["proj_margin"]] + (list(cols[r["game_id"]]) if cols else [])
        beta = ols([x(r) for r in train], [r["actual_margin"] for r in train])
        res = np.array([r["actual_margin"] for r in train]) - np.array([x(r) for r in train]) @ beta
        if sigma_fn is None:
            sd = float(np.std(res, ddof=1))
            sig = lambda r, sd=sd: sd
        else:
            sig = sigma_fn(train, res)
        for r in test:
            m = float(np.dot(x(r), beta))
            out[r["game_id"]] = (m, phi(m / sig(r)))
    return out


def graded(rows):
    return [r for r in rows if r["p_market"] is not None and r["outcome"] is not None
            and r["spread_line"] is not None and r["season"] >= 2011]


def report(rows, base, feat, label):
    print("feature: %s" % label)
    for name, seasons in GROUPS:
        g = [r for r in graded(rows) if r["season"] in seasons]
        y = [r["outcome"] for r in g]
        bb = [(base[r["game_id"]][1] - o) ** 2 for r, o in zip(g, y)]
        bf = [(feat[r["game_id"]][1] - o) ** 2 for r, o in zip(g, y)]
        bk = [(r["p_market"] - o) ** 2 for r, o in zip(g, y)]
        bv = [(r["p_model"] - o) ** 2 for r, o in zip(g, y)]
        eb = [abs(base[r["game_id"]][0] - r["actual_margin"]) for r in g]
        ef = [abs(feat[r["game_id"]][0] - r["actual_margin"]) for r in g]
        es = [abs(float(r["spread_line"]) - r["actual_margin"]) for r in g]
        d_fb = nm.bootstrap_mean_diff_ci(bf, bb, reps=REPS)
        d_fk = nm.bootstrap_mean_diff_ci(bf, bk, reps=REPS)
        d_bk = nm.bootstrap_mean_diff_ci(bb, bk, reps=REPS)
        m_fb = nm.bootstrap_mean_diff_ci(ef, eb, reps=REPS)
        n = len(g)
        print("  %-9s n=%4d Brier v1 %.4f B %.4f F %.4f mkt %.4f | F-B %+.4f [%+.4f,%+.4f] | "
              "F-mkt %+.4f [%+.4f,%+.4f] | B-mkt %+.4f [%+.4f,%+.4f]"
              % (name, n, sum(bv) / n, sum(bb) / n, sum(bf) / n, sum(bk) / n,
                 *d_fb, *d_fk, *d_bk))
        print("  %-9s        margin MAE B %.3f F %.3f spread %.3f | F-B %+.3f [%+.3f,%+.3f]"
              % ("", sum(eb) / n, sum(ef) / n, sum(es) / n, *m_fb))


FEATURES = {}


def feature(fn):
    FEATURES[fn.__name__] = fn
    return fn


def _sched(con, season):
    return con.execute(
        "SELECT game_id, week, home_team, away_team, location, spread_line, home_rest, "
        "away_rest, roof, wind FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "ORDER BY week, game_id", (season,)).fetchall()


@feature
def market_prior(con, rows):
    """PRE-REGISTERED (before its first run): a market-implied team rating.

    For a game in week w of season S: fit r_t (one number per team) and a home term h by
    weighted ridge on the closing spread_line of every REG game of season S in weeks < w:
        spread = r_home - r_away + h (h = 0 at neutral sites)
    weight 0.5 ** ((w - 1 - week) / 6), ridge 2.0 on each r_t toward 0, h unpenalised.
    Column: r_home - r_away + h (h = 0 at neutral sites). Parameters 6 and 2.0 are fixed here,
    not tuned. This rating is derived from the market. A gain here measures information the
    market has that v1 lacks; it is not an independent forecast and must be labelled so.
    """
    cols = {}
    for s in SEASONS:
        g = _sched(con, s)
        teams = sorted({x[2] for x in g} | {x[3] for x in g})
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        for w in sorted({x[1] for x in g}):
            past = [x for x in g if x[1] < w and x[5] is not None]
            if not past:
                continue
            A = np.zeros((n + 1, n + 1))
            b = np.zeros(n + 1)
            for gid, wk, h, a, loc, sp, *_ in past:
                v = np.zeros(n + 1)
                v[idx[h]] += 1.0
                v[idx[a]] -= 1.0
                v[n] = 0.0 if (loc or "").strip().lower() == "neutral" else 1.0
                wt = 0.5 ** ((w - 1 - wk) / 6.0)
                A += wt * np.outer(v, v)
                b += wt * float(sp) * v
            A[np.arange(n), np.arange(n)] += 2.0
            sol = np.linalg.solve(A, b)
            for gid, wk, h, a, loc, *_ in (x for x in g if x[1] == w):
                hh = 0.0 if (loc or "").strip().lower() == "neutral" else sol[n]
                cols[gid] = [sol[idx[h]] - sol[idx[a]] + hh]
    return _complete(rows, cols), None


@feature
def epa_units(con, rows):
    """PRE-REGISTERED (before its first run): opponent-adjusted EPA by unit (v2).

    nfl_epa_model as frozen in RESULTS-A9 (half_life 12, lam 450, shrink 1/3): pass and rush
    offense and defense ratings from plays of weeks < w of the season, prior = season S-1's
    final fit shrunk (none for 2010). Column: the raw EPA-points margin
    predictor(home, away) - predictor(away, home) from nfl_epa_backtest.walk_forward. Its scale
    and home term are left to the stack, so v2's own a, b, h calibration is not used.

    AMENDMENT (after the first run crashed, before any result was seen): a team with no plays
    yet in the season (2017 TB and MIA, whose week 1 game was moved) has no pace or pass rate,
    and v2's predictor fails. For such a team, pace and pass rate come from its prior (season
    S-1 final fit); with no prior, from the mean over teams that have them. Ratings are untouched.
    """
    import nfl_epa_backtest as eb
    import nfl_epa_model as em
    cols = {}
    prev = None
    for s in SEASONS:
        plays = eb.season_plays(con, s)
        teams = eb.teams_of(con, s)
        prior = eb.final_prior(prev[0], prev[1], 12.0, 450.0) if prev else None
        g = eb.sched(con, s)
        for w in sorted({x[0] for x in g}):
            past = [p for p in plays if p[0] < w]
            if not past:
                continue
            r = em.fit(past, teams, prior=prior, half_life=12.0, lam=450.0)
            have = [t for t in teams if r.plays_pg[t] is not None]
            for t in teams:
                if r.plays_pg[t] is None:
                    if prior is not None and prior.plays_pg.get(t) is not None:
                        r.plays_pg[t], r.pass_rate[t] = prior.plays_pg[t], prior.pass_rate[t]
                    else:
                        r.plays_pg[t] = sum(r.plays_pg[u] for u in have) / len(have)
                        r.pass_rate[t] = sum(r.pass_rate[u] for u in have) / len(have)
            for x in (x for x in g if x[0] == w):
                cols[x[1]] = [em.predictor(r, x[2], x[3]) - em.predictor(r, x[3], x[2])]
        prev = (plays, teams)
    return _complete(rows, cols), None


PRIOR_K = 400.0  # plays of shrinkage: a team's season-S-1 EPA mean counts n / (n + K) of its gap


def shrunk_ratings(off, dfn, k=PRIOR_K):
    """off, dfn: team -> (mean EPA per play, plays). Returns team -> offense - defense rating.

    Each unit's mean is pulled toward the league mean of the teams in it by n / (n + k). Offense
    is the EPA the team's offense gains per play; defense is the EPA it allows, so a rating is
    higher when the team's offense is better or its defense is better. Teams in one dict but not
    the other are not rated.
    """
    m_off = sum(v for v, _ in off.values()) / len(off)
    m_def = sum(v for v, _ in dfn.values()) / len(dfn)
    out = {}
    for t in off.keys() & dfn.keys():
        o, n_o = off[t]
        d, n_d = dfn[t]
        out[t] = (m_off + (o - m_off) * n_o / (n_o + k)) - (m_def + (d - m_def) * n_d / (n_d + k))
    return out


@feature
def preseason_prior(con, rows):
    """PRE-REGISTERED (before its first run): an independent preseason rating from published
    play-by-play only, with no market input.

    For season S, the rating of team t is last season's (S-1, regular season) EPA per play,
    offense minus defense, each shrunk toward the league mean by n / (n + 400) plays (shrunk_ratings).
    Column: rating(home) - rating(away) for every REG game of S, in every week. The stack takes its
    scale; the column carries no home term. Only the play-by-play columns epa, posteam, defteam and
    play_type (pass or run) are read.

    A team with no plays in S-1 gets rating 0, the league average, and the count is printed. This
    happens to every 2010 game, since play-by-play starts in 2010 and 2010 has no S-1. Those games
    carry column 0 and the count reports them. Nothing else is tuned: 400 is fixed here.

    NOT in this version (each would be its own pre-registered feature): QB change, coach change
    (both from nfl_schedule's starters and coaches) and returning starters (snap counts, needs the
    pfr to gsis crosswalk). The epa_units feature already carries S-1 information through v2's
    prior; this one is a simpler, published-only version of that and is judged on its own.
    """
    cols = {}
    missing = 0
    for s in SEASONS:
        prev = {}
        for side, col in (("off", "posteam"), ("def", "defteam")):
            prev[side] = {
                t: (float(m), int(n)) for t, m, n in con.execute(
                    "SELECT %s, AVG(epa), COUNT(*) FROM nfl_pbp WHERE season = ? "
                    "AND play_type IN ('pass', 'run') AND epa IS NOT NULL AND %s IS NOT NULL "
                    "GROUP BY %s" % (col, col, col), (s - 1,))}
        ratings = shrunk_ratings(prev["off"], prev["def"]) if prev["off"] and prev["def"] else {}
        for gid, h, a in con.execute(
                "SELECT game_id, home_team, away_team FROM nfl_schedule "
                "WHERE season = ? AND game_type = 'REG'", (s,)):
            rh, ra = ratings.get(h), ratings.get(a)
            if rh is None or ra is None:
                missing += 1
            cols[gid] = [(rh or 0.0) - (ra or 0.0)]
    if missing:
        print("preseason_prior: %d scheduled games had a team with no S-1 plays (rated 0)" % missing)
    return _complete(rows, cols), None


TO_K = 8.0  # games of shrinkage for the season-to-date turnover and penalty features (fixed here)


def _team_week_events(con, season):
    """team -> week -> [giveaways, takeaways, penalties committed] from the stored REG plays.

    A giveaway is a fumble lost or an interception by the offense (posteam); a takeaway is the same
    play counted for the defense (defteam). A penalty is charged to penalty_team.
    """
    out = {}

    def add(team, week, i):
        if team is None:
            return
        out.setdefault(team, {}).setdefault(week, [0, 0, 0])[i] += 1
    for week, pos, dfn, pen_team, lost, intc in con.execute(
            "SELECT week, posteam, defteam, penalty_team, fumble_lost, interception "
            "FROM nfl_pbp WHERE season = ?", (season,)):
        if (lost == 1 or intc == 1):
            add(pos, week, 0)
            add(dfn, week, 1)
        if pen_team is not None:
            add(pen_team, week, 2)
    return out


def _to_date(con, season, w, team_week):
    """team -> (games to date, giveaways, takeaways, penalties) over weeks < w."""
    games = {}
    for week, h, a in con.execute(
            "SELECT week, home_team, away_team FROM nfl_schedule "
            "WHERE season = ? AND game_type = 'REG'", (season,)):
        for t in (h, a):
            if week < w:
                games[t] = games.get(t, 0) + 1
    res = {}
    for t, n in games.items():
        g = tk = tp = 0
        for week, (gv, tkw, pn) in team_week.get(t, {}).items():
            if week < w:
                g += gv
                tk += tkw
                tp += pn
        res[t] = (n, g, tk, tp)
    return res


@feature
def turnover_margin(con, rows):
    """PRE-REGISTERED (before its first run): season-to-date turnover margin, shrunk.

    For a game in week w of season S, a team's rating is its takeaways minus giveaways per game,
    counted over weeks < w of S (fumbles lost and interceptions from the stored plays), times
    n / (n + 8), where n is its games to date. Column: rating(home) - rating(away). Teams with no
    games yet rate 0. Zero-sum by construction, so the league mean is 0. The feature tests luck:
    turnovers are thought to carry over weakly, so a small coefficient is the expected outcome.
    """
    cols = {}
    for s in SEASONS:
        tw = _team_week_events(con, s)
        for gid, w, h, a in con.execute(
                "SELECT game_id, week, home_team, away_team FROM nfl_schedule "
                "WHERE season = ? AND game_type = 'REG'", (s,)):
            d = _to_date(con, s, w, tw)
            cols[gid] = [_turnover_rating(d.get(h)) - _turnover_rating(d.get(a))]
    return _complete(rows, cols), None


def _turnover_rating(v):
    if v is None or v[0] == 0:
        return 0.0
    n, g, tk, _ = v
    return (n / (n + TO_K)) * (tk - g) / n


@feature
def penalty_rate(con, rows):
    """PRE-REGISTERED (before its first run): season-to-date penalties committed, shrunk.

    Column: -(penalties per game of home - of away), counted over weeks < w of S (penalty = 1 is
    charged to penalty_team). Each team's rate is shrunk toward the league average to date by
    n / (n + 8). Negative sign: more penalties is worse, so a positive coefficient is the expected
    direction. Teams with no games yet count as the league average (their term is 0).
    """
    cols = {}
    for s in SEASONS:
        tw = _team_week_events(con, s)
        for gid, w, h, a in con.execute(
                "SELECT game_id, week, home_team, away_team FROM nfl_schedule "
                "WHERE season = ? AND game_type = 'REG'", (s,)):
            d = _to_date(con, s, w, tw)
            cols[gid] = [-(_penalty_rating(d, h) - _penalty_rating(d, a))]
    return _complete(rows, cols), None


def _penalty_rating(d, team):
    played = [(n, pn) for n, _, _, pn in d.values() if n > 0]
    if not played:
        return 0.0
    league = sum(pn / n for n, pn in played) / len(played)
    v = d.get(team)
    if v is None or v[0] == 0:
        return league
    n, _, _, pn = v
    return league + (n / (n + TO_K)) * (pn / n - league)


# ---- FTN blitz, PRE-REGISTERED 2026-10-12, before any run of ftn_keep_test ----
# FTN charting exists for 2022 to 2025 only, so the walk-forward stack cannot grade it. Instead:
#   variant A: fit on 2022-2023, grade 2024-2025 (two graded seasons)
#   variant B: fit on 2022,      grade 2023-2025 (three graded seasons)
# Each variant fixes its coefficients on the fitting seasons and applies them unchanged to the
# graded seasons, so no graded game is used to fit. Base B is refit the same way (proj_margin only),
# so the comparison is paired on the same games.
# Feature: each team's season-to-date blitzers per dropback on the defense (FTN n_blitzers over
# dropbacks, weeks < w), shrunk toward the league rate by n / (n + 8) games. Column: rating(home) -
# rating(away). Teams with no games to date are at the league rate.
# Keep rule (pooled interval only, no per-season rule): the pooled graded-season F-B interval is
# entirely below zero. Each variant is judged on its own. Per-season numbers are printed as
# diagnostics and are not part of the rule.
FTN_BLITZ_K = 8.0
FTN_VARIANTS = {"A (fit 2022-23, grade 2024-25)": ((2022, 2023), (2024, 2025)),
                "B (fit 2022, grade 2023-25)": ((2022,), (2023, 2024, 2025))}


def _ftn_defense_week(con, season):
    """defteam -> week -> (dropbacks, blitzers) on FTN-charted dropbacks."""
    out = {}
    for week, team, n, blitz in con.execute(
            "SELECT p.week, p.defteam, COUNT(*), SUM(f.n_blitzers) FROM nfl_hist_ftn_charting f "
            "JOIN nfl_pbp p ON p.game_id = f.nflverse_game_id AND p.play_id = f.nflverse_play_id "
            "WHERE f.season = ? AND p.qb_dropback = 1 AND f.n_blitzers IS NOT NULL "
            "GROUP BY p.week, p.defteam", (season,)):
        out.setdefault(team, {})[week] = (n, blitz)
    return out


def _ftn_rate_to_date(con, season, w, week_map):
    """team -> (games to date, blitz rate to date) for weeks < w; league rate over all teams."""
    games = {}
    teams = set()
    for week, h, a in con.execute(
            "SELECT week, home_team, away_team FROM nfl_schedule "
            "WHERE season = ? AND game_type = 'REG'", (season,)):
        teams.update((h, a))
        if week < w:
            games[h] = games.get(h, 0) + 1
            games[a] = games.get(a, 0) + 1
    raw = {}
    for t, weeks in week_map.items():
        n = sum(d for wk, (d, _) in weeks.items() if wk < w)
        b = sum(bl for wk, (_, bl) in weeks.items() if wk < w)
        if n:
            raw[t] = (n, b)
    total_n = sum(n for n, _ in raw.values())
    league = sum(b for _, b in raw.values()) / total_n if total_n else 0.0
    out = {}
    for t in teams:
        g = games.get(t, 0)
        if t in raw and g:
            n, b = raw[t]
            out[t] = league + (g / (g + FTN_BLITZ_K)) * (b / n - league)
        else:
            out[t] = league
    return out


def ftn_blitz_columns(con, seasons):
    """game_id -> [home rating - away rating] for every REG game of the given seasons."""
    cols = {}
    for s in seasons:
        week_map = _ftn_defense_week(con, s)
        for gid, w, h, a in con.execute(
                "SELECT game_id, week, home_team, away_team FROM nfl_schedule "
                "WHERE season = ? AND game_type = 'REG'", (s,)):
            r = _ftn_rate_to_date(con, s, w, week_map)
            cols[gid] = [r[h] - r[a]]
    return cols


def ftn_keep_test(con):
    """Runs both pre-registered variants. Prints pooled point and interval, and per-season diagnostics."""
    rows = [r for r in base_rows(con) if r["season"] >= 2022]
    cols = ftn_blitz_columns(con, range(2022, 2026))
    g = [r for r in graded(rows)]
    for label, (fit, grade) in FTN_VARIANTS.items():
        tr = [r for r in g if r["season"] in fit]
        te = [r for r in g if r["season"] in grade]
        xb = lambda r: [1.0, r["proj_margin"]]
        xf = lambda r: [1.0, r["proj_margin"], cols[r["game_id"]][0]]
        bb_ = ols([xb(r) for r in tr], [r["actual_margin"] for r in tr])
        bf_ = ols([xf(r) for r in tr], [r["actual_margin"] for r in tr])
        sd_b = float(np.std([r["actual_margin"] - np.dot(xb(r), bb_) for r in tr], ddof=1))
        sd_f = float(np.std([r["actual_margin"] - np.dot(xf(r), bf_) for r in tr], ddof=1))
        lb = [(phi(float(np.dot(xb(r), bb_)) / sd_b) - r["outcome"]) ** 2 for r in te]
        lf = [(phi(float(np.dot(xf(r), bf_)) / sd_f) - r["outcome"]) ** 2 for r in te]
        d, lo, hi = nm.bootstrap_mean_diff_ci(lf, lb, reps=REPS)
        verdict = "KEEP" if hi < 0 else "NOT KEPT"
        print("FTN blitz, variant %s: n=%d F-B %+.4f [%+.4f,%+.4f]  -> %s"
              % (label, len(te), d, lo, hi, verdict))
        for s in grade:
            idx = [i for i, r in enumerate(te) if r["season"] == s]
            dd = [lf[i] - lb[i] for i in idx]
            print("   diagnostic %d n=%d F-B %+.4f" % (s, len(idx), sum(dd) / len(dd)))
        print("   fitted coef on feature %+.4f (base proj_margin %+.3f)" % (bf_[2], bf_[1]))
    return None


@feature
def rating_uncertainty(con, rows):
    """PRE-REGISTERED (before its first run): sigma grows with rating uncertainty.

    No feature column. sigma is the sd (ddof 1) of the stack's training residuals within the
    game's week bucket: weeks 2-4, 5-8, 9 and later. Early ratings rest on fewer games, so their
    margin errors should be wider. Margin MAE cannot change by construction.
    """
    def bucket(w):
        return 0 if w <= 4 else (1 if w <= 8 else 2)

    def sigma_fn(train, res):
        sds = {}
        for k in (0, 1, 2):
            v = [e for r, e in zip(train, res) if bucket(r["week"]) == k]
            sds[k] = float(np.std(v, ddof=1))
        return lambda r: sds[bucket(r["week"])]
    return None, sigma_fn


@feature
def special_teams(con, rows):
    """PRE-REGISTERED (before its first run): net special-teams EPA per game.

    Plays: nfl_pbp play_type in (kickoff, punt, field_goal, extra_point) with epa, posteam and
    defteam present. Per team-game: net = sum(epa where team is posteam) - sum(epa where team is
    defteam). Rating before week w: (sum_k wt_k * net_k + 4 * prior) / (sum_k wt_k + 4) over
    the team's games of weeks < w, wt = 0.5 ** ((w - 1 - week) / 6); prior = (2/3) * the
    team's mean net per game in season S-1 (0 for 2010 or a team with no S-1 games).
    Column: rating_home - rating_away. Parameters fixed here, not tuned.
    """
    cols = {}
    prior = {}
    for s in SEASONS:
        net = {}
        for gid, wk, pt, dt_, e in con.execute(
                "SELECT game_id, week, posteam, defteam, epa FROM nfl_pbp WHERE season = ? "
                "AND play_type IN ('kickoff','punt','field_goal','extra_point') "
                "AND epa IS NOT NULL AND posteam IS NOT NULL AND defteam IS NOT NULL", (s,)):
            for t, sgn in ((pt, 1.0), (dt_, -1.0)):
                rec = net.setdefault((gid, t), [wk, 0.0])
                rec[1] += sgn * e
        g = _sched(con, s)
        for w in sorted({x[1] for x in g}):
            num, den = {}, {}
            for (gid, t), (wk, v) in net.items():
                if wk < w:
                    wt = 0.5 ** ((w - 1 - wk) / 6.0)
                    num[t] = num.get(t, 0.0) + wt * v
                    den[t] = den.get(t, 0.0) + wt

            def rating(t):
                return (num.get(t, 0.0) + 4.0 * prior.get(t, 0.0)) / (den.get(t, 0.0) + 4.0)
            for x in (x for x in g if x[1] == w):
                cols[x[0]] = [rating(x[2]) - rating(x[3])]
        tot, cnt = {}, {}
        for (gid, t), (wk, v) in net.items():
            tot[t] = tot.get(t, 0.0) + v
            cnt[t] = cnt.get(t, 0) + 1
        prior = {t: (2.0 / 3.0) * tot[t] / cnt[t] for t in tot}
    return _complete(rows, cols), None


@feature
def venue_conditions(con, rows):
    """PRE-REGISTERED (before its first run): rest and wind.

    Columns: (1) home_rest - away_rest, clipped to [-7, 7]; (2) v1 projected margin times a
    high-wind flag, flag = 1 when roof is 'outdoors' or 'open' and recorded wind >= 15 mph.
    Domes and closed roofs have no wind by design (flag 0). An outdoor game with no recorded
    wind (2021: 11, 2022: 91, 2023: 41 REG games, nflverse's own gaps) gets flag 0: no wind
    value is invented, the term is simply absent. Both are published before kickoff (rest from
    the schedule; wind is the game-time reading, a small look-ahead the forecast would replace
    with a forecast wind).
    """
    v1 = {r["game_id"]: r["proj_margin"] for r in rows}
    cols = {}
    for s in SEASONS:
        for gid, wk, h, a, loc, sp, hr, ar, roof, wind in _sched(con, s):
            if gid not in v1:
                continue
            rest = 0.0 if hr is None or ar is None else max(-7.0, min(7.0, float(hr - ar)))
            windy = 1.0 if (roof in ("outdoors", "open") and wind is not None
                            and wind >= 15) else 0.0
            cols[gid] = [rest, v1[gid] * windy]
    return _complete(rows, cols), None


# ---- stats research, 2026-10-12: pressure, sacks and touch shares (RESULTS-nfl-stability-stats-2026-10-12.md)
PRESS_K = 200.0     # dropback shrink weight, the same as QBE's 200-dropback shrink
PRESS_WIN = 8       # team games in the window, the same as QBE's last 8 team games
SHARE_WIN = 4       # team games in the window, the same as AVAIL's last 4 REG games


def _offense_records(con):
    """One record per team-game with plays, 2010-2025, sorted by (season, week, game_id).

    record = {"key": (season, week, game_id), "team", "plays", "db" (dropbacks), "hit" (QB hits
    on dropbacks), "sack", "touches": {gsis_id: targets + carries}}. Plays are pass or rush
    attempts. Built from nfl_pbp by the team that had the ball.
    """
    recs = {}
    for s, w, g, t, pl, db, hit, sk in con.execute(
            "SELECT season, week, game_id, posteam, SUM(pass_attempt = 1 OR rush_attempt = 1), "
            "SUM(qb_dropback = 1), SUM(qb_dropback = 1 AND qb_hit = 1), SUM(sack = 1) "
            "FROM nfl_pbp WHERE season BETWEEN 2010 AND 2025 AND posteam IS NOT NULL "
            "GROUP BY season, week, game_id, posteam"):
        recs[(g, t)] = {"key": (int(s), int(w), g), "team": t, "plays": pl or 0, "db": db or 0,
                        "hit": hit or 0, "sack": sk or 0, "touches": {}}
    for sql in ("SELECT game_id, posteam, receiver_player_id, COUNT(*) FROM nfl_pbp "
                "WHERE season BETWEEN 2010 AND 2025 AND pass_attempt = 1 "
                "AND receiver_player_id IS NOT NULL AND posteam IS NOT NULL "
                "GROUP BY game_id, posteam, receiver_player_id",
                "SELECT game_id, posteam, rusher_player_id, COUNT(*) FROM nfl_pbp "
                "WHERE season BETWEEN 2010 AND 2025 AND rush_attempt = 1 "
                "AND rusher_player_id IS NOT NULL AND posteam IS NOT NULL "
                "GROUP BY game_id, posteam, rusher_player_id"):
        for g, t, p, n in con.execute(sql):
            recs[(g, t)]["touches"][p] = recs[(g, t)]["touches"].get(p, 0) + n
    return recs


class _Index:
    """Team-game lookups in pbp order. Windows are the team's games strictly before a cutoff."""

    def __init__(self, recs):
        self.recs = recs
        self.team_keys = {}
        self.opp = {}
        games = {}
        for (g, t), r in recs.items():
            self.team_keys.setdefault(t, []).append(r["key"])
            games.setdefault(g, []).append(t)
        for t in self.team_keys:
            self.team_keys[t].sort()
        for g, ts in games.items():
            if len(ts) == 2:
                self.opp[(g, ts[0])], self.opp[(g, ts[1])] = ts[1], ts[0]
        self.all_recs = sorted(recs.values(), key=lambda r: r["key"])
        self.all_keys = [r["key"] for r in self.all_recs]
        self.cum = [[0, 0, 0]]
        for r in self.all_recs:
            c = self.cum[-1]
            self.cum.append([c[0] + r["db"], c[1] + r["hit"], c[2] + r["sack"]])

    def window(self, team, cutoff, n):
        keys = self.team_keys.get(team, [])
        i = bisect.bisect_left(keys, cutoff)
        return [self.recs[(k[2], team)] for k in keys[max(0, i - n):i]]

    def league_before(self, cutoff):
        """(dropbacks, hits, sacks) pooled over every team-game strictly before the cutoff."""
        return self.cum[bisect.bisect_left(self.all_keys, cutoff)]


def _matchup(con, rows, metric):
    """Expected offensive rate by matchup, home minus away, per dropback. metric: hit or sack."""
    idx = _Index(_offense_records(con))
    cols, missing = {}, 0
    for r in rows:
        s, w = int(r["season"]), int(r["week"])
        cutoff = (s, w, "")
        ldb, lhit, lsk = idx.league_before(cutoff)
        if ldb == 0:
            cols[r["game_id"]] = [0.0]
            missing += 1
            continue
        lg = (lhit if metric == "hit" else lsk) / float(ldb)

        def rate(team, own):
            db = m = 0
            for x in idx.window(team, cutoff, PRESS_WIN):
                if own:
                    d = x
                else:
                    d = idx.recs[(x["key"][2], idx.opp[(x["key"][2], team)])]
                db += d["db"]; m += d[metric]
            return (m + PRESS_K * lg) / (db + PRESS_K)
        h, a = r["home"], r["away"]
        exp_h = rate(h, True) + rate(a, False) - lg
        exp_a = rate(a, True) + rate(h, False) - lg
        cols[r["game_id"]] = [exp_h - exp_a]
    print("%s checks: base rows with no league history before the game (column 0) %d" % (metric, missing))
    return cols


@feature
def pressure_matchup(con, rows):
    """PRE-REGISTERED (before its first run): expected QB-hit rate by matchup.

    Per dropback. Team offense rate = (hits on its dropbacks in its last 8 team games + 200 x
    league rate) / (its dropbacks in those games + 200). Team defense rate the same, using the
    opponents' dropbacks and hits in those games. League rate = pooled over every team-game
    before the game (any season). Expected home offense rate = home offense + away defense -
    league; expected away offense = away offense + home defense - league. Column = expected home
    minus expected away. Expected sign: negative (more pressure on the home QB, lower home margin).
    The window crosses season boundaries. Week 1 of 2010 has no league history: column 0, counted.
    """
    return _complete(rows, _matchup(con, rows, "hit")), None


@feature
def sack_matchup(con, rows):
    """PRE-REGISTERED (before its first run): expected sack rate by matchup. Same rules as
    pressure_matchup with sacks (sacks on dropbacks) in place of QB hits. Expected sign negative.
    """
    return _complete(rows, _matchup(con, rows, "sack")), None


@feature
def share_absence(con, rows):
    """PRE-REGISTERED (before its first run): touch share lost to listed absences.

    Listed: nfl_hist_injuries REG rows with report_status Out or Doubtful and position not QB, the
    same listing as AVAIL. A listed player's touch share = (his targets + carries over the team's
    last 4 team games before the game) / (the team's pass and rush attempts over those games).
    gsis_id is used directly: nfl_pbp and nfl_hist_injuries share it. Team load = sum of listed
    players' shares. Column: load home - load away. Expected sign: negative. A listed player with
    no touches in the window contributes 0. Counted: listings with no touches anywhere in pbp.
    """
    idx = _Index(_offense_records(con))
    listed = {}
    never = 0
    seen = set()
    for r in idx.recs.values():
        seen.update(r["touches"].keys())
    for s, w, t, g in con.execute(
            "SELECT season, week, team, gsis_id FROM nfl_hist_injuries WHERE game_type = 'REG' "
            "AND report_status IN ('Out', 'Doubtful') AND COALESCE(position, '') != 'QB' "
            "AND gsis_id IS NOT NULL"):
        if g not in seen:
            never += 1
            continue
        listed.setdefault((int(s), int(w), t), []).append(g)
    cols = {}
    for r in rows:
        cutoff = (int(r["season"]), int(r["week"]), "")
        load = {}
        for t in (r["home"], r["away"]):
            win = idx.window(t, cutoff, SHARE_WIN)
            plays = sum(x["plays"] for x in win)
            lo = 0.0
            if plays:
                for p in listed.get((cutoff[0], cutoff[1], t), []):
                    lo += sum(x["touches"].get(p, 0) for x in win) / float(plays)
            load[t] = lo
        cols[r["game_id"]] = [load[r["home"]] - load[r["away"]]]
    print("share_absence checks: listings with no pbp touches anywhere %d" % never)
    return _complete(rows, cols), None


@feature
def kept_combined(con, rows):
    """PRE-REGISTERED (after the five single-feature runs, before this run): the two features
    that met the keep rule, market_prior and epa_units, as two stack columns together. Same
    rules; it answers how much of the market gap the kept features close jointly.
    """
    a, _ = market_prior(con, rows)
    b, _ = epa_units(con, rows)
    return {k: a[k] + b[k] for k in a}, None


def _complete(rows, cols):
    """Every base row must have its column; a missing one is a bug, never a zero."""
    miss = [r["game_id"] for r in rows if r["game_id"] not in cols]
    if miss:
        raise ValueError("feature missing for %d base rows, e.g. %s" % (len(miss), miss[:3]))
    return cols


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--feature", required=True, choices=["base", "ftn_keep"] + sorted(FEATURES))
    a = ap.parse_args(argv)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    if a.feature == "ftn_keep":
        ftn_keep_test(con)
        return 0
    rows = base_rows(con)
    base = stack(rows)
    if a.feature == "base":
        report(rows, base, base, "base (F = B)")
        return 0
    cols, sigma_fn = FEATURES[a.feature](con, rows)
    report(rows, base, stack(rows, cols, sigma_fn), a.feature)
    return 0


if __name__ == "__main__":
    sys.exit(main())
