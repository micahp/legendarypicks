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
