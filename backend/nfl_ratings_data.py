"""nfl_ratings_data.py -- reads nfl_schedule into nfl_ratings.Game lists and builds priors.

Decisions (SPEC A, 4.1, recorded here so they are reviewable):
- Regular-season games only (game_type == 'REG'). Playoff games are not used to rate teams in
  version 1: they are fewer, often neutral, and selected on the outcome they would rate.
- Only games with both scores are used. Unscored games are counted and returned, never
  silently treated as zero or as ties.
- weeks_ago = anchor_week - week. The anchor defaults to the last REG week that has a score
  for the season, so a fit made mid-season weights the latest played week as 0.
- The prior for season S+1 is the season-S final rating regressed toward zero by `shrink`
  (spec: one third). prior = (1 - shrink) * rating, for both o and d.
"""
from __future__ import annotations

import nfl_ratings as nr

DEFAULT_SHRINK = 1.0 / 3.0


def teams_in_season(con, season):
    rows = con.execute(
        "SELECT home_team FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "UNION SELECT away_team FROM nfl_schedule WHERE season = ? AND game_type = 'REG'",
        (season, season)).fetchall()
    return sorted({r[0] for r in rows if r[0]})


def load_games(con, season, anchor_week=None):
    """Return (games, unscored_count, anchor_week) for the season's scored REG games."""
    scored = con.execute(
        "SELECT week, home_team, away_team, home_score, away_score, location "
        "FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL "
        "ORDER BY week, game_id", (season,)).fetchall()
    unscored = con.execute(
        "SELECT COUNT(*) FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "AND (home_score IS NULL OR away_score IS NULL)", (season,)).fetchone()[0]
    if not scored:
        return [], unscored, None
    if anchor_week is None:
        anchor_week = max(r[0] for r in scored)
    games = []
    for week, home, away, hs, as_, loc in scored:
        if week > anchor_week:
            continue
        games.append(nr.Game(
            weeks_ago=float(anchor_week - week), home=home, away=away,
            home_pts=float(hs), away_pts=float(as_),
            neutral=(loc or "").strip().lower() == "neutral"))
    return games, unscored, anchor_week


def season_fit(con, season, anchor_week=None, **fit_kwargs):
    """Fit one season on its own games, with no prior unless the caller passes one."""
    games, unscored, anchor = load_games(con, season, anchor_week)
    if not games:
        raise ValueError("no scored REG games for season %d" % season)
    f = nr.fit(games, teams_in_season(con, season), **fit_kwargs)
    return f, {"unscored": unscored, "anchor_week": anchor, "games": len(games)}


def prior_from_fit(f, shrink=DEFAULT_SHRINK):
    """Map team -> (o, d) prior for the next season: (1 - shrink) * final rating."""
    if not 0.0 <= shrink < 1.0:
        raise ValueError("shrink must be in [0, 1)")
    keep = 1.0 - shrink
    return {t: (keep * f.o[t], keep * f.d[t]) for t in f.o}


def _scored_rows(con, season):
    return con.execute(
        "SELECT week, home_team, away_team, home_score, away_score, location "
        "FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL "
        "ORDER BY week, game_id", (season,)).fetchall()


def walk_forward(con, season, prior=None, first_week=2, **fit_kwargs):
    """Out-of-sample margin residuals for one season (spec 6.1 style).

    For each week w from first_week: fit on the scored REG games of weeks < w (anchored at
    w - 1), project the week-w games, and record actual minus projected home margin.
    Returns a list of dicts: season, week, home, away, neutral, projected, actual, residual.
    """
    rows = _scored_rows(con, season)
    if not rows:
        raise ValueError("no scored REG games for season %d" % season)
    teams = teams_in_season(con, season)
    out = []
    for w in range(first_week, max(r[0] for r in rows) + 1):
        train = [nr.Game(weeks_ago=float((w - 1) - wk), home=h, away=a, home_pts=float(hs),
                         away_pts=float(as_), neutral=(loc or "").strip().lower() == "neutral")
                 for wk, h, a, hs, as_, loc in rows if wk < w]
        if not train:
            continue
        f = nr.fit(train, teams, prior=prior, **fit_kwargs)
        for wk, h, a, hs, as_, loc in rows:
            if wk != w:
                continue
            neutral = (loc or "").strip().lower() == "neutral"
            ph, pa = nr.expected_points(f, h, a, neutral)
            projected = ph - pa
            actual = float(hs) - float(as_)
            out.append({"season": season, "week": w, "home": h, "away": a, "neutral": neutral,
                        "projected": projected, "actual": actual,
                        "residual": actual - projected})
    return out


def fit_for_week(con, season, week, prior=None, **fit_kwargs):
    """The fit a lock for (season, week) uses: scored REG games of weeks < week only.

    Anchored at week - 1, so the most recent played week carries weight 1. Returns
    (fit, games_used). Raises if no game before `week` has a score.
    """
    rows = _scored_rows(con, season)
    train = [nr.Game(weeks_ago=float((week - 1) - wk), home=h, away=a, home_pts=float(hs),
                     away_pts=float(as_), neutral=(loc or "").strip().lower() == "neutral")
             for wk, h, a, hs, as_, loc in rows if wk < week]
    if not train:
        raise ValueError("no scored REG games before week %d of %d" % (week, season))
    return nr.fit(train, teams_in_season(con, season), prior=prior, **fit_kwargs), len(train)


def prior_for_season(con, season, shrink=DEFAULT_SHRINK, **fit_kwargs):
    """Prior for `season` built from the final fit of season - 1."""
    f, _ = season_fit(con, season - 1, **fit_kwargs)
    return prior_from_fit(f, shrink=shrink)
