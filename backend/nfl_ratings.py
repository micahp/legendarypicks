"""nfl_ratings.py -- the version 1 team-rating fit (SPEC A, section 4.1). Pure: no database.

Model, per team t: offense o_t and defense d_t, in points versus an average team. Shared:
league average `mu` and home-field `h`. For a game with home H and away A (not neutral):

    pts_H = mu + o_H - d_A + h/2
    pts_A = mu + o_A - d_H - h/2
    margin = pts_H - pts_A = (o_H - d_A) - (o_A - d_H) + h

Each game gives three weighted observations:
  1. home points       (raw score)
  2. away points       (raw score)
  3. margin            (home minus away, winsorized to +/-cap; this is the blowout dampener)

Recency: each game's weight is 0.5 ** (weeks_ago / half_life).
Prior: each team's o and d get a pseudo-observation at its prior value, with weight
`prior_games`. A team with no games therefore sits at its prior exactly.
`mu` and `h` are unpenalised and fitted.

Solved by weighted least squares (numpy lstsq on sqrt-weighted rows). Identifiability: the
points model is invariant to (o + c, mu - c) and to (d - c, mu - c); the prior penalty removes
both, so `prior_games` must be > 0.

Interpretation of the one-sided margin observation: only the home-minus-away difference is
capped. Raw points are used as scored, so a 50-point blowout still moves the points rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_HALF_LIFE = 6.0
DEFAULT_CAP = 21.0
DEFAULT_PRIOR_GAMES = 4.0


@dataclass(frozen=True)
class Game:
    weeks_ago: float        # >= 0; the current week minus the game's week
    home: str
    away: str
    home_pts: float
    away_pts: float
    neutral: bool = False


@dataclass
class Fit:
    o: dict = field(default_factory=dict)
    d: dict = field(default_factory=dict)
    mu: float = 0.0
    h: float = 0.0
    n_games: int = 0
    total_weight: float = 0.0


def fit(games, teams, *, half_life=DEFAULT_HALF_LIFE, cap=DEFAULT_CAP,
        prior=None, prior_games=DEFAULT_PRIOR_GAMES):
    """Fit ratings for `teams` from `games`.

    prior: optional dict team -> (o, d) prior ratings (already shrunk by the caller).
    cap: winsorize the margin observation at +/-cap; None disables it.
    """
    if prior_games <= 0:
        raise ValueError("prior_games must be > 0: without it mu and the ratings are not identified")
    if half_life <= 0:
        raise ValueError("half_life must be > 0")
    teams = list(teams)
    index = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    n_params = 2 * T + 2          # o_0..o_{T-1}, d_0..d_{T-1}, mu, h
    MU, H = 2 * T, 2 * T + 1

    rows, ys, ws = [], [], []
    total_w = 0.0
    for g in games:
        if g.home not in index or g.away not in index:
            raise KeyError("game references a team not in `teams`: %s/%s" % (g.home, g.away))
        if g.weeks_ago < 0:
            raise ValueError("weeks_ago must be >= 0, got %r" % (g.weeks_ago,))
        w = 0.5 ** (g.weeks_ago / half_life)
        total_w += w
        hi, ai = index[g.home], index[g.away]
        h_home = 0.0 if g.neutral else 0.5
        h_away = 0.0 if g.neutral else -0.5
        margin = g.home_pts - g.away_pts
        if cap is not None:
            margin = max(-cap, min(cap, margin))

        r = np.zeros(n_params)            # home points
        r[hi] += 1.0; r[T + ai] -= 1.0; r[MU] += 1.0; r[H] += h_home
        rows.append(r); ys.append(g.home_pts); ws.append(w)

        r = np.zeros(n_params)            # away points
        r[ai] += 1.0; r[T + hi] -= 1.0; r[MU] += 1.0; r[H] += h_away
        rows.append(r); ys.append(g.away_pts); ws.append(w)

        r = np.zeros(n_params)            # margin
        r[hi] += 1.0; r[T + ai] -= 1.0; r[ai] -= 1.0; r[T + hi] += 1.0
        r[H] += 0.0 if g.neutral else 1.0
        rows.append(r); ys.append(margin); ws.append(w)

    prior = prior or {}
    for t in teams:
        po, pd = prior.get(t, (0.0, 0.0))
        r = np.zeros(n_params); r[index[t]] = 1.0
        rows.append(r); ys.append(po); ws.append(prior_games)
        r = np.zeros(n_params); r[T + index[t]] = 1.0
        rows.append(r); ys.append(pd); ws.append(prior_games)

    X = np.vstack(rows)
    y = np.asarray(ys, dtype=float)
    sw = np.sqrt(np.asarray(ws, dtype=float))
    beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)

    return Fit(
        o={t: float(beta[index[t]]) for t in teams},
        d={t: float(beta[T + index[t]]) for t in teams},
        mu=float(beta[MU]),
        h=float(beta[H]),
        n_games=len(games),
        total_weight=float(total_w),
    )


def expected_points(f: Fit, home: str, away: str, neutral: bool = False):
    """(pts_home, pts_away) implied by a fit."""
    h = 0.0 if neutral else f.h
    pts_home = f.mu + f.o[home] - f.d[away] + h / 2.0
    pts_away = f.mu + f.o[away] - f.d[home] - h / 2.0
    return pts_home, pts_away
