"""nfl_epa_efficiency.py -- SPEC A section 9, version 2: the EPA layer.

EPA is published per play in the nflverse pbp release and copied into ``nfl_pbp`` by
``ingest_nfl_pbp_logs.py`` (posteam/home/away normalized to the ESPN vocabulary at ingest).
Nothing here computes EPA. This module only aggregates the published play-level values to
team-game totals, fits the version 1 rating structure (``nfl_ratings.py``) on those totals,
and blends the two projections, walk-forward, for the SPEC A 9 gate:

    margin = (1 - w) * margin_points + w * margin_epa

``margin_points`` is the frozen version 1 projection (SPEC A 4.1; frozen configuration from
d30ea75, applied by ``nfl_tune_2024.py``/``lock_nfl_week.py``). ``margin_epa`` comes from the
same rating structure fitted on team-game offensive EPA totals in place of points: EPA is in
points, so the blend needs no rescaling. The projected total stays the version 1 total; EPA
ratings carry no separate total signal in this version, and that is stated, not hidden.

Walk-forward, like the 6.1 backtest: for each week w both fits use only data from weeks < w
(the points fit from ``nfl_schedule`` scores, the EPA fit from ``nfl_pbp`` weeks). Nothing
from week w or later reaches either fit. The win-probability sigma is fitted from the blend's
own residuals (the A3 rule: sigma is never hard-coded), so the blend is also re-scaled before
Brier is computed.

Prior (SPEC A 4.1, same rule as points): a season's EPA prior is the previous season's final
EPA fit regressed toward zero by ``shrink``. 2024 has no prior in the backtest (2023 is not
ingested) and that is reported as ``prior_used = False``, exactly as version 1 does.

Gate (SPEC A 9): the blend must beat version 1 on the 6.1 backtest. Grid is run on 2024
only; 2025 is the holdout; the selection rule is ``nfl_tune_2024.py``'s (Brier to three
decimals ascending, ties to fewer non-default parameters). Version 1's own parameters are
frozen, not in the grid: v2 must beat v1 as configured.
"""
from __future__ import annotations

import nfl_backtest as nb
import nfl_metrics as nmt
import nfl_ratings as nr
import nfl_ratings_data as nrd

DEFAULTS = {
    # version 1, frozen (d30ea75): NOT in the v2 grid
    "half_life": nr.DEFAULT_HALF_LIFE,      # 6.0
    "cap": 14.0,                            # frozen margin cap
    "prior_games": nr.DEFAULT_PRIOR_GAMES,  # 4.0
    "shrink": nrd.DEFAULT_SHRINK,           # 1/3
    "cap_points": None,
    # the EPA fit
    "w_blend": 0.5,
    "epa_half_life": 6.0,
    "epa_cap": 14.0,        # EPA margin winsorization; None disables
    "epa_prior_games": 4.0,
}

EPANONDEFAULT = {"w_blend": 0.5, "epa_half_life": 6.0, "epa_cap": 14.0, "epa_prior_games": 4.0}


def _params(overrides):
    p = dict(DEFAULTS)
    unknown = set(overrides) - set(DEFAULTS)
    if unknown:
        raise ValueError("unknown epa-blend parameters: %s" % sorted(unknown))
    p.update(overrides)
    if not 0.0 <= p["w_blend"] <= 1.0:
        raise ValueError("w_blend must be in [0, 1]")
    if p["epa_half_life"] <= 0 or p["epa_prior_games"] <= 0:
        raise ValueError("epa_half_life and epa_prior_games must be > 0")
    return p


def _nondefault_count(cfg):
    return sum(1 for k, v in EPANONDEFAULT.items() if cfg[k] != v)


def scored_schedule(con, season):
    """(week, game_id, home, away, location, home_score, away_score, spread, total,
    home_ml, away_ml) for the season's scored REG games, week order. Same selection as
    nfl_backtest._schedule, kept here so this module owns its read path."""
    return con.execute(
        "SELECT week, game_id, home_team, away_team, location, home_score, away_score, "
        "       spread_line, total_line, home_moneyline, away_moneyline "
        "FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL "
        "ORDER BY week, game_id", (season,)).fetchall()


def team_game_epa_rows(con, season, before_week=None):
    """Team-game EPA totals from the published play-level EPA.

    One row per played game:
        (week, game_id, home, away, home_epa, away_epa, home_plays, away_plays)

    Plays counted: pass_attempt = 1 or rush_attempt = 1 (dropbacks and carries). Plays with
    a null published EPA (kicks and similar) are excluded from the sums; the exclusion is a
    fact about the publisher's own null, not a filter of this module. Games with zero counted
    plays on either side are reported in the return as zero-EPA rows, never dropped, and the
    caller decides. Nothing from week ``before_week`` or later is read.
    """
    sql = (
        "SELECT week, game_id, home_team, away_team, "
        "  SUM(CASE WHEN posteam = home_team THEN epa ELSE 0 END), "
        "  SUM(CASE WHEN posteam = away_team THEN epa ELSE 0 END), "
        "  SUM(CASE WHEN posteam = home_team THEN 1 ELSE 0 END), "
        "  SUM(CASE WHEN posteam = away_team THEN 1 ELSE 0 END) "
        "FROM nfl_pbp WHERE season = ? AND epa IS NOT NULL AND posteam IS NOT NULL "
        "AND (pass_attempt = 1 OR rush_attempt = 1)"
    )
    args = [season]
    if before_week is not None:
        sql += " AND week < ?"
        args.append(before_week)
    sql += " GROUP BY week, game_id ORDER BY week, game_id"
    rows = []
    for week, gid, home, away, he, ae, hp, ap in con.execute(sql, args):
        if home is None or away is None:
            raise ValueError("pbp game %s has no home/away team" % gid)
        if not hp or not ap:
            # A played game with zero counted dropbacks/carries is a data problem,
            # not a rating. Refuse rather than rate it from nothing.
            raise ValueError("game %s has a side with 0 pass/rush plays" % gid)
        rows.append((week, gid, home, away, float(he), float(ae), int(hp), int(ap)))
    return rows


def epa_games(rows, before_week=None):
    """nfl_ratings.Game list for the EPA fit: offensive EPA totals in place of points.

    ``weeks_ago`` is anchored the same way as the points fit (``nfl_backtest.training_games``):
    the last played week before ``before_week`` carries weight 1.
    """
    if before_week is not None:
        rows = [r for r in rows if r[0] < before_week]
    if not rows:
        return []
    anchor = max(r[0] for r in rows)
    return [nr.Game(weeks_ago=float(anchor - r[0]), home=r[2], away=r[3],
                    home_pts=r[4], away_pts=r[5], neutral=False) for r in rows]


def epa_season_fit(con, season, teams=None, **fit_kwargs):
    """Final EPA fit of a whole season (for building the next season's prior)."""
    games = epa_games(team_game_epa_rows(con, season))
    if not games:
        raise ValueError("no EPA rows for season %d" % season)
    teams = teams or nrd.teams_in_season(con, season)
    return nr.fit(games, teams, **fit_kwargs)


def epa_prior_for_season(con, season, shrink=1.0 / 3.0, **fit_kwargs):
    """Prior for `season` from season - 1's final EPA fit, regressed toward zero."""
    fe = epa_season_fit(con, season - 1, **fit_kwargs)
    return nrd.prior_from_fit(fe, shrink=shrink)


def backtest_season_blend(con, season, overrides=None):
    """Graded walk-forward rows for one season: version 1 margin blended with the EPA margin.

    Output rows match nfl_backtest.backtest_season's (same keys), so nfl_backtest.summarize
    grades both versions identically. Extra keys: epa_margin, v1_margin, plays used.
    """
    p = _params(overrides or {})
    sched = scored_schedule(con, season)
    if not sched:
        raise ValueError("no scored REG games for season %d" % season)
    scored = [(r[0], r[2], r[3], r[5], r[6], r[4]) for r in sched]
    epa_rows = team_game_epa_rows(con, season)
    covered = {r[1] for r in epa_rows}
    v1_prior = None
    try:
        v1_prior = nrd.prior_for_season(con, season, shrink=p["shrink"], half_life=p["half_life"],
                                        cap=p["cap"], prior_games=p["prior_games"])
    except ValueError:
        pass  # no earlier season loaded (2024): reported per row as prior_used False
    try:
        epa_prior = epa_prior_for_season(con, season, shrink=p["shrink"],
                                         half_life=p["epa_half_life"], cap=p["epa_cap"],
                                         prior_games=p["epa_prior_games"])
    except ValueError:
        epa_prior = None
    teams = nrd.teams_in_season(con, season)
    out = []
    for w in sorted({r[0] for r in sched}):
        if w < 2:
            continue
        train = nb.training_games(scored, w, p["cap_points"])
        if not train:
            continue
        f = nr.fit(train, teams, prior=v1_prior, half_life=p["half_life"], cap=p["cap"],
                   prior_games=p["prior_games"])
        e_games = epa_games(epa_rows, before_week=w)
        if not e_games:
            raise ValueError("no EPA games before week %d of %d" % (w, season))
        fe = nr.fit(e_games, teams, prior=epa_prior, half_life=p["epa_half_life"],
                    cap=p["epa_cap"], prior_games=p["epa_prior_games"])
        for wk, gid, h, a, loc, hs, as_, spread, total, hml, aml in (
                r for r in sched if r[0] == w):
            if gid not in covered:
                # Refuse: a scored game without pbp EPA would silently fall back to v1
                # and the gate would grade a mix we cannot see.
                raise ValueError("no published EPA for scored game %s" % gid)
            neutral = (loc or "").strip().lower() == "neutral"
            ph, pa = nr.expected_points(f, h, a, neutral)
            v1_margin = ph - pa
            he, ae = nr.expected_points(fe, h, a, neutral)
            epa_margin = he - ae
            margin = (1.0 - p["w_blend"]) * v1_margin + p["w_blend"] * epa_margin
            out.append({
                "season": season, "week": wk, "game_id": gid, "home": h, "away": a,
                "neutral": neutral, "proj_margin": margin, "proj_total": ph + pa,
                "v1_margin": v1_margin, "epa_margin": epa_margin,
                "p_model": nr.win_probability(margin, 13.4),  # rescaled by sigma() before Brier
                "actual_margin": float(hs) - float(as_),
                "actual_total": float(hs) + float(as_),
                "outcome": 1 if float(hs) > float(as_) else (0 if float(hs) < float(as_) else None),
                "spread_line": spread, "total_line": total,
                "prior_used": v1_prior is not None, "fit_games": len(train),
                "epa_games": len(e_games),
            })
            row = out[-1]
            # the market comparison, same definition as nfl_backtest.backtest_season
            if hml is not None and aml is not None:
                row["p_market"] = nmt.devig_home_prob(hml, aml)
            else:
                row["p_market"] = None
    return out


def sigma_of(rows):
    """Residual sigma of the blend, fitted from the rows' own residuals (the A3 rule)."""
    import statistics
    resid = [r["actual_margin"] - r["proj_margin"] for r in rows]
    if not resid:
        raise ValueError("no residuals to fit sigma from")
    return statistics.pstdev(resid)


def with_sigma(rows):
    """Rows with p_model recomputed at the blend's own residual sigma (projections unchanged)."""
    import nfl_ratings as _nr
    s = sigma_of(rows)
    out = []
    for r in rows:
        q = dict(r)
        q["p_model"] = _nr.win_probability(r["proj_margin"], s)
        q["sigma"] = s
        out.append(q)
    return out


def evaluate(con, season, overrides=None, reps=0):
    """One graded configuration: blend rows with own sigma, plus the v1 baseline rows with
    the same walk-forward machinery at the frozen configuration, both summarized by
    nfl_backtest.summarize. Returns a dict with both summaries and the raw rows."""
    rows = with_sigma(backtest_season_blend(con, season, overrides))
    cfg = _params(overrides or {})
    v1_rows = nb.backtest_season(con, season, {
        "half_life": cfg["half_life"], "cap": cfg["cap"], "prior_games": cfg["prior_games"],
        "shrink": cfg["shrink"], "cap_points": cfg["cap_points"],
    })
    v1_sigma = sigma_of(v1_rows)
    v1_rows = [dict(r, p_model=nr.win_probability(r["proj_margin"], v1_sigma),
                    sigma=v1_sigma) for r in v1_rows]
    return {
        "season": season,
        "config": {k: cfg[k] for k in ("w_blend", "epa_half_life", "epa_cap", "epa_prior_games")},
        "nondefault": _nondefault_count(cfg),
        "sigma": round(sigma_of(rows), 3),
        "blend": nb.summarize(rows, reps=reps) if reps else _cheap(rows),
        "v1": nb.summarize(v1_rows, reps=reps) if reps else _cheap(v1_rows),
    }


def _cheap(rows):
    """Brier / log loss / margin MAE without bootstrap (used inside the grid, where 10k
    bootstrap replicates per configuration would dominate runtime). Same definitions as
    nfl_backtest.summarize, so a flagged cell can be re-run through summarize to confirm."""
    import nfl_metrics as mt
    graded = [r for r in rows if r["outcome"] is not None]
    if not graded:
        raise ValueError("no graded games")
    y = [r["outcome"] for r in graded]
    pm = [r["p_model"] for r in graded]
    return {
        "n": len(graded), "ties": len(rows) - len(graded),
        "brier": {"model": mt.brier(pm, y)},
        "log_loss": {"model": mt.log_loss(pm, y)},
        "margin_mae": {"model": mt.mae([r["proj_margin"] for r in rows if r["spread_line"] is not None],
                                       [r["actual_margin"] for r in rows if r["spread_line"] is not None])},
    }
