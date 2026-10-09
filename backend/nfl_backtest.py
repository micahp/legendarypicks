"""nfl_backtest.py -- walk-forward graded projections for one season (SPEC A, 6.1, A3 questions).

For each week w from 2 to the last scored week: fit on scored REG games of weeks < w only,
project every week-w game, and record the result next to the market numbers. Nothing from week
w or later reaches the fit. The leakage test lives in test_nfl_backtest.py.

Parameters (a dict, so every run can be written to model_runs verbatim):
  half_life     recency half-life in weeks (default 6)
  cap           margin winsorization for the 3rd observation (default 21; None = off)
  prior_games   pseudo-game weight of the prior (default 4)
  shrink        prior shrink toward zero, prior = (1 - shrink) * final rating (default 1/3)
  sigma         win-probability scale in points (default 13.4)
  cap_points    None (off) or a number: raw training scores clipped to league_mean +/- cap_points,
                league_mean taken from the training games only

Output rows: one dict per graded game, with None where the market number is missing.
"""
from __future__ import annotations

import nfl_ratings as nr
import nfl_ratings_data as nrd
from nfl_metrics import devig_home_prob

DEFAULTS = {"half_life": nr.DEFAULT_HALF_LIFE, "cap": nr.DEFAULT_CAP,
            "prior_games": nr.DEFAULT_PRIOR_GAMES, "shrink": nrd.DEFAULT_SHRINK,
            "sigma": 13.4, "cap_points": None}


def _params(overrides):
    p = dict(DEFAULTS)
    unknown = set(overrides) - set(DEFAULTS)
    if unknown:
        raise ValueError("unknown backtest parameters: %s" % sorted(unknown))
    p.update(overrides)
    if p["sigma"] <= 0:
        raise ValueError("sigma must be > 0")
    if p["cap_points"] is not None and p["cap_points"] <= 0:
        raise ValueError("cap_points must be > 0 or None")
    return p


def _schedule(con, season):
    return con.execute(
        "SELECT week, game_id, home_team, away_team, location, home_score, away_score, "
        "       spread_line, total_line, home_moneyline, away_moneyline "
        "FROM nfl_schedule WHERE season = ? AND game_type = 'REG' ORDER BY week, game_id",
        (season,)).fetchall()


def training_games(scored, before_week, cap_points=None):
    """Game objects for weeks < before_week, anchored at before_week - 1.

    scored: rows (week, home, away, home_score, away_score, location) for one season.
    cap_points clips each raw score to league_mean +/- cap_points; the mean is over training
    games only, so the cap never sees a week it is projecting.
    """
    rows = [r for r in scored if r[0] < before_week]
    if not rows:
        return []
    scores = [float(r[3]) for r in rows] + [float(r[4]) for r in rows]
    center = sum(scores) / len(scores)
    out = []
    for wk, h, a, hs, as_, loc in rows:
        hp, ap = float(hs), float(as_)
        if cap_points is not None:
            lo, hi = center - cap_points, center + cap_points
            hp, ap = max(lo, min(hi, hp)), max(lo, min(hi, ap))
        out.append(nr.Game(weeks_ago=float((before_week - 1) - wk), home=h, away=a,
                           home_pts=hp, away_pts=ap,
                           neutral=(loc or "").strip().lower() == "neutral"))
    return out


def prior_for(con, season, p):
    """Prior for `season` from season - 1's final fit under the same parameters. None if there is
    no earlier season loaded (the 2024 case; reported as such)."""
    try:
        return nrd.prior_for_season(con, season, shrink=p["shrink"], half_life=p["half_life"],
                                    cap=p["cap"], prior_games=p["prior_games"])
    except ValueError:
        return None


def backtest_season(con, season, overrides=None):
    """Graded walk-forward rows for one season, weeks 2 to the last scored week."""
    p = _params(overrides or {})
    sched = [r for r in _schedule(con, season) if r[5] is not None and r[6] is not None]
    if not sched:
        raise ValueError("no scored REG games for season %d" % season)
    scored = [(r[0], r[2], r[3], r[5], r[6], r[4]) for r in sched]
    prior = prior_for(con, season, p)
    teams = nrd.teams_in_season(con, season)
    out = []
    for w in sorted({r[0] for r in sched}):
        if w < 2:
            continue
        train = training_games(scored, w, p["cap_points"])
        if not train:
            continue
        f = nr.fit(train, teams, prior=prior, half_life=p["half_life"], cap=p["cap"],
                   prior_games=p["prior_games"])
        for wk, gid, h, a, loc, hs, as_, spread, total_line, hml, aml in (
                (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10])
                for r in sched if r[0] == w):
            neutral = (loc or "").strip().lower() == "neutral"
            ph, pa = nr.expected_points(f, h, a, neutral)
            margin = float(hs) - float(as_)
            p_mkt = devig_home_prob(hml, aml) if (hml is not None and aml is not None) else None
            out.append({
                "season": season, "week": w, "game_id": gid, "home": h, "away": a,
                "neutral": neutral, "proj_margin": ph - pa, "proj_total": ph + pa,
                "p_model": nr.win_probability(ph - pa, p["sigma"]), "p_market": p_mkt,
                "actual_margin": margin, "actual_total": float(hs) + float(as_),
                "outcome": 1 if margin > 0 else (0 if margin < 0 else None),
                "spread_line": spread, "total_line": total_line,
                "prior_used": prior is not None, "fit_games": len(train),
            })
    return out


def summarize(rows, reps=10000):
    """Scores for the SPEC A 6.1 questions, from graded rows. Ties are excluded and counted.

    Brier and log loss against 50/50 and a constant 57% home win, plus the market where a
    moneyline exists. Differences come with paired bootstrap intervals. Margin and total MAE
    against the lines. ATS record. Calibration bins for the model.
    """
    import nfl_metrics as mt
    graded = [r for r in rows if r["outcome"] is not None]
    ties = len(rows) - len(graded)
    if not graded:
        raise ValueError("no graded games")
    y = [r["outcome"] for r in graded]
    pm = [r["p_model"] for r in graded]
    base = {"coin": [0.5] * len(y), "home57": [0.57] * len(y)}

    def loss_vec(probs):
        return [(p - o) ** 2 for p, o in zip(probs, y)]

    out = {"n": len(graded), "ties": ties,
           "brier": {"model": mt.brier(pm, y), **{k: mt.brier(v, y) for k, v in base.items()}},
           "log_loss": {"model": mt.log_loss(pm, y),
                        **{k: mt.log_loss(v, y) for k, v in base.items()}},
           "brier_diff_ci": {}}
    for k, v in base.items():
        point, lo, hi = mt.bootstrap_mean_diff_ci(loss_vec(pm), loss_vec(v), reps=reps)
        out["brier_diff_ci"][k] = {"model_minus_base": point, "lo": lo, "hi": hi}
    with_mkt = [r for r in graded if r["p_market"] is not None]
    if with_mkt:
        ym = [r["outcome"] for r in with_mkt]
        pmm = [r["p_model"] for r in with_mkt]
        pk = [r["p_market"] for r in with_mkt]
        out["market"] = {"n": len(with_mkt), "brier_model": mt.brier(pmm, ym),
                         "brier_market": mt.brier(pk, ym),
                         "log_loss_model": mt.log_loss(pmm, ym),
                         "log_loss_market": mt.log_loss(pk, ym)}
        point, lo, hi = mt.bootstrap_mean_diff_ci(
            [(p - o) ** 2 for p, o in zip(pmm, ym)], [(p - o) ** 2 for p, o in zip(pk, ym)],
            reps=reps)
        out["market"]["brier_diff_ci"] = {"model_minus_market": point, "lo": lo, "hi": hi}
    lined = [r for r in graded if r["spread_line"] is not None]
    if lined:
        out["margin_mae"] = {"model": mt.mae([r["proj_margin"] for r in lined],
                                             [r["actual_margin"] for r in lined]),
                             "spread": mt.mae([float(r["spread_line"]) for r in lined],
                                              [r["actual_margin"] for r in lined]),
                             "n": len(lined)}
        out["ats"] = mt.ats_record([r["actual_margin"] for r in lined],
                                   [float(r["spread_line"]) for r in lined])
    tl = [r for r in graded if r["total_line"] is not None]
    if tl:
        out["total_mae"] = {"model": mt.mae([r["proj_total"] for r in tl],
                                            [r["actual_total"] for r in tl]),
                            "line": mt.mae([float(r["total_line"]) for r in tl],
                                           [r["actual_total"] for r in tl]),
                            "n": len(tl)}
    out["calibration"] = mt.calibration_bins(pm, y)
    return out
