"""nfl_epa_model.py -- SPEC A section 9, version 2: per-play EPA ratings, pure (no points blend).

Published nflverse EPA per play (nfl_pbp.epa, pass_attempt = 1 or rush_attempt = 1) is rated with
a weighted ridge, separately for pass and rush plays:

    epa_play = c_type + off[posteam, type] - def[defteam, type]

Weights: 0.5 ** (weeks_ago / HALF_LIFE). Prior: the previous season's final ratings shrunk one
third toward zero, entering as a ridge pull of strength LAM (play-weight units). Nothing is tuned
for the first lock: HALF_LIFE 6 (v1's frozen value) and LAM 150 (about four games of plays) are
the spec defaults, so the first lock cannot have spent any holdout.

EPA to points (the one choice the spec does not give; stated, not hidden). For team A against B:

    plays_A  = weighted mean offensive plays per game of A
    pass_A   = weighted pass rate of A
    pred_A   = plays_A * (pass_A * (offpass_A - defpass_B) + (1 - pass_A) * (offrush_A - defrush_B))
    points_A = a + b * pred_A + (h / 2 if A is home else -h / 2 for the other side), h = 0 neutral

a, b, h are fitted by least squares on walk-forward predictions (each game predicted from games
before its week only) of the CALIBRATION season, both sides as observations. Sigma is the sd of
that fit's margin residuals. Expected scores and total therefore come from EPA alone.
"""
from __future__ import annotations

import math

import numpy as np

HALF_LIFE = 6.0
LAM = 150.0
SHRINK = 1.0 / 3.0


def plays(con, season, before_week=None):
    sql = ("SELECT week, game_id, posteam, defteam, home_team, pass_attempt, epa FROM nfl_pbp "
           "WHERE season = ? AND epa IS NOT NULL AND posteam IS NOT NULL AND defteam IS NOT NULL "
           "AND (pass_attempt = 1 OR rush_attempt = 1)")
    args = [season]
    if before_week is not None:
        sql += " AND week < ?"
        args.append(before_week)
    return con.execute(sql, args).fetchall()


class Ratings:
    def __init__(self, teams, const, off, dfn, plays_pg, pass_rate):
        self.teams, self.const, self.off, self.dfn = teams, const, off, dfn
        self.plays_pg, self.pass_rate = plays_pg, pass_rate


def fit(rows, teams, prior=None, half_life=HALF_LIFE, lam=LAM):
    """rows: plays() tuples. prior: Ratings or None. Returns Ratings."""
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    anchor = max(r[0] for r in rows)
    w = np.array([0.5 ** ((anchor - r[0]) / half_life) for r in rows])
    pos = np.array([idx[r[2]] for r in rows])
    dfn_i = np.array([idx[r[3]] for r in rows])
    is_pass = np.array([1 if r[5] == 1 else 0 for r in rows])
    y = np.array([r[6] for r in rows])
    const, off, dfn = {}, {}, {}
    for typ, mask in (("pass", is_pass == 1), ("rush", is_pass == 0)):
        X = np.zeros((int(mask.sum()), 2 * n + 1))
        X[:, 0] = 1.0
        X[np.arange(X.shape[0]), 1 + pos[mask]] = 1.0
        X[np.arange(X.shape[0]), 1 + n + dfn_i[mask]] = -1.0
        ww, yy = w[mask], y[mask]
        A = X.T @ (X * ww[:, None])
        b = X.T @ (ww * yy)
        p0 = np.zeros(2 * n + 1)
        if prior is not None:
            p0[1:1 + n] = [prior.off[typ][t] for t in teams]
            p0[1 + n:] = [prior.dfn[typ][t] for t in teams]
        pen = np.full(2 * n + 1, lam)
        pen[0] = 0.0
        A = A + np.diag(pen)
        b = b + pen * p0
        sol = np.linalg.solve(A, b)
        const[typ] = float(sol[0])
        off[typ] = {t: float(sol[1 + idx[t]]) for t in teams}
        dfn[typ] = {t: float(sol[1 + n + idx[t]]) for t in teams}
    # pace and pass rate: weighted per team-game
    tg = {}
    for (wk, gid, pt, dt_, ht, pa, e), wi in zip(rows, w):
        key = (gid, pt)
        rec = tg.setdefault(key, [wk, 0, 0])
        rec[1] += 1
        rec[2] += 1 if pa == 1 else 0
    num = {t: 0.0 for t in teams}
    den = {t: 0.0 for t in teams}
    pn = {t: 0.0 for t in teams}
    for (gid, t), (wk, cnt, pc) in tg.items():
        wi = 0.5 ** ((anchor - wk) / half_life)
        num[t] += wi * cnt
        den[t] += wi
        pn[t] += wi * pc
    plays_pg = {t: (num[t] / den[t]) if den[t] else None for t in teams}
    pass_rate = {t: (pn[t] / num[t]) if num[t] else None for t in teams}
    return Ratings(teams, const, off, dfn, plays_pg, pass_rate)


def shrink(r, s=SHRINK):
    """Prior from a season's final fit: ratings regressed toward zero."""
    k = 1.0 - s
    off = {typ: {t: v * k for t, v in d.items()} for typ, d in r.off.items()}
    dfn = {typ: {t: v * k for t, v in d.items()} for typ, d in r.dfn.items()}
    return Ratings(r.teams, r.const, off, dfn, r.plays_pg, r.pass_rate)


def predictor(r, a, b):
    """EPA-points predictor for team a (offense) against b (defense)."""
    pg = r.plays_pg[a]
    pr = r.pass_rate[a]
    return pg * (pr * (r.off["pass"][a] - r.dfn["pass"][b])
                 + (1.0 - pr) * (r.off["rush"][a] - r.dfn["rush"][b]))


def calibrate(obs):
    """obs: [(pred_off, home_flag(+1 home, -1 away, 0 neutral), points)]. Returns (a, b, h)."""
    X = np.array([[1.0, p, s * 0.5] for p, s, _ in obs])
    y = np.array([pts for _, _, pts in obs])
    sol, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(sol[0]), float(sol[1]), float(sol[2])


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
