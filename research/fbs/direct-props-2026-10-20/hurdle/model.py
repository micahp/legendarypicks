"""The preregistered passing-hurdle structure (prereg rev4 §6.1-§6.3, §6.6).

Stage 1  participation   H = (pass_attempts > 0), p_H = (s + p_prior) / (n + 1)
Stage 2  conditional     attempts | H = 1  ~ zero-truncated negative binomial
Stage 3  efficiency      yards/attempt ~ Normal(eff, eff_sd), independent of the
                         count given pregame information
Mixture  P(Y) = (1 - p_H) * delta_0 + p_H * P(Y | H = 1)

The **sampled attempts array is shared** between the attempts market and the
yards market, so the two projections are coherent by construction rather than by
post-hoc reconciliation. Zero and negative passing yards survive a positive
attempt count: nothing here clips them.

`WINDOW`, `EFF_WINDOW`, `SPREAD_R_GRID` and `SPREAD_ESD_MULT` are imported from
the committed `run_direct_props.py`, which is the single source of truth for them.
They are **immutable for this experiment** and are exposed here as read-only
tuples; nothing in this module tunes them.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

import run_direct_props as rdp  # noqa: E402  (committed conventions, no fit)

WINDOW = int(rdp.WINDOW)                       # 5, participation + conditional count
EFF_WINDOW = int(rdp.EFF_WINDOW)               # 15, passing-yards efficiency
SPREAD_R_GRID = tuple(rdp.SPREAD_R_GRID)       # immutable
SPREAD_ESD_MULT = tuple(rdp.SPREAD_ESD_MULT)   # immutable
BOOT_N = int(rdp.BOOT_N)
SEED = int(rdp.SEED)

DEFAULT_R = 1.0        # untuned default, used ONLY by the simple hurdle baseline
DEFAULT_EFF_SD = 1.0   # untuned default, same restriction


# ---------------------------------------------------------------------------
# strictly-chronological trailing features
# ---------------------------------------------------------------------------
def _athlete_positions(df, athlete_key):
    """Contiguous positional index blocks per athlete on a (athlete, season, week,
    game) sorted frame."""
    order = [athlete_key, "season", "week", "game_id"]
    d = df.sort_values(order)
    return d, d.groupby(athlete_key).indices


def participation_counts(df, col="pass_attempts", athlete_key="athlete_id", k=WINDOW):
    """`s` and `n` for the smoothed hurdle.

    `s` = positive-attempt appearances among the athlete's last `k` box-score
    appearances strictly before the target game.
    `n` = the number of those appearances, `n <= k`; zero-attempt appearances are
    appearances and **do** count in `n`.
    """
    d, blocks = _athlete_positions(df, athlete_key)
    vals = d[col].fillna(0.0).to_numpy(dtype="float64")
    ind = (vals > 0).astype("float64")
    s = np.zeros(len(d), dtype="float64")
    n = np.zeros(len(d), dtype="float64")
    for pos in blocks.values():
        pos = np.sort(pos)
        prior = ind[pos][:-1]                       # strictly before each row
        rows = pos[1:]
        for j, stop in enumerate(range(len(prior))):
            lo = max(0, stop + 1 - k)
            win = prior[lo:stop + 1]
            s[rows[j]] = float(win.sum())
            n[rows[j]] = float(len(win))
    return _back_to_index(d, s, df), _back_to_index(d, n, df)


def trailing_positive_mean(df, col="pass_attempts", athlete_key="athlete_id", k=WINDOW):
    """Mean over the athlete's last `k` **positive** appearances, strictly before
    each row. Zero-attempt appearances are excluded here (they are not draws from
    the conditional-on-usage count distribution)."""
    d, blocks = _athlete_positions(df, athlete_key)
    vals = d[col].fillna(0.0).to_numpy(dtype="float64")
    out = np.full(len(d), np.nan)
    for pos in blocks.values():
        pos = np.sort(pos)
        v = vals[pos]
        pos_mask = v > 0
        pos_rows = pos[pos_mask]
        if len(pos_rows) == 0:
            continue
        pre = np.concatenate([[0.0], np.cumsum(v[pos_mask])])
        cnt = np.searchsorted(pos_rows, pos, side="left")   # positives strictly before
        lo = np.maximum(cnt - k, 0)
        num = pre[cnt] - pre[lo]
        den = cnt - lo
        with np.errstate(invalid="ignore", divide="ignore"):
            out[pos] = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
    return _back_to_index(d, out, df)


def _back_to_index(sorted_df, values, original):
    return pd.Series(values, index=sorted_df.index).reindex(original.index)


# ---------------------------------------------------------------------------
# stage 1: participation
# ---------------------------------------------------------------------------
def participation_probability(s, n, p_prior):
    """`p_H = (s + p_prior) / (n + 1)` — prereg §6.1, verbatim."""
    s = np.asarray(s, dtype="float64")
    n = np.asarray(n, dtype="float64")
    p = float(p_prior)
    if not (0.0 <= p <= 1.0):
        raise ValueError("p_prior must be a probability, got %r" % (p,))
    if np.any(s > n + 1e-9):
        raise ValueError("s (positive appearances) exceeds n (appearances)")
    if np.any(n > WINDOW + 1e-9):
        raise ValueError("n exceeds the registered WINDOW of %d" % WINDOW)
    return (s + p) / (n + 1.0)


# ---------------------------------------------------------------------------
# stage 2: zero-truncated negative binomial
# ---------------------------------------------------------------------------
def ztnb_samples(mu, r, n_draws, rng, max_iter=2000):
    """Draws from a negative binomial **truncated at zero**.

    A zero attempt count cannot occur conditionally on H = 1, so zeros are
    redrawn rather than relabelled. The redraw is exact (rejection sampling),
    never a +1 shift.
    """
    mu = np.clip(np.asarray(mu, dtype="float64").ravel(), 1e-9, None)
    rr = float(r)
    if rr <= 0:
        raise ValueError("dispersion r must be positive")
    p = rr / (rr + mu)
    out = rng.negative_binomial(rr, p[:, None], size=(len(mu), int(n_draws))).astype("float64")
    for _ in range(max_iter):
        zero = out == 0
        if not zero.any():
            return out
        rows, cols = np.nonzero(zero)
        out[rows, cols] = rng.negative_binomial(rr, p[rows])
    raise RuntimeError("zero-truncated NB did not converge; check mu/r %r" % ((mu.min(), rr),))


# ---------------------------------------------------------------------------
# stage 3 + mixture: shared attempts across the two passing markets
# ---------------------------------------------------------------------------
def simulate_passing(mu_att, r, p_H, eff, eff_sd, n_draws, rng):
    """Simulate attempts once and reuse them for yards.

    Returns a dict with `attempts` (n x draws, zeros allowed by the hurdle),
    `rate` (draws of yards/attempt) and `yards = attempts * rate`. The attempts
    array is the **same object** the attempts market scores, so a row cannot have
    two different attempt counts in the two markets.
    """
    n = len(np.asarray(mu_att).ravel())
    draws = ztnb_samples(mu_att, r, n_draws, rng)
    H = rng.random((n, int(n_draws))) < np.asarray(p_H, dtype="float64").reshape(-1, 1)
    attempts = np.where(H, draws, 0.0)
    rate = rng.normal(np.asarray(eff, dtype="float64").reshape(-1, 1), float(eff_sd),
                      size=attempts.shape)
    yards = attempts * rate          # not clipped: negative yards stay possible
    return {"attempts": attempts, "rate": rate, "yards": yards}


def mixture_moments(p_H, mu_cond):
    """Analytic P(usage) and unconditional mean, for coherence checks."""
    p = np.asarray(p_H, dtype="float64")
    mu = np.asarray(mu_cond, dtype="float64")
    return {"p_usage": p, "unconditional_mean": p * mu}


# ---------------------------------------------------------------------------
# baseline comparators (reported, never decisive)
# ---------------------------------------------------------------------------
def simple_hurdle_participation(s, n):
    """Untuned empirical rate s/n; no smoothing prior. For the simple hurdle
    baseline only — not the registered model."""
    s = np.asarray(s, dtype="float64")
    n = np.asarray(n, dtype="float64")
    return np.where(n > 0, s / np.where(n > 0, n, 1.0), 0.0)


def fixed_spread_samples(mu, spread, n_draws, rng):
    """Fixed-spread comparator distribution (the committed baseA convention)."""
    mu = np.asarray(mu, dtype="float64").reshape(-1, 1)
    return np.clip(rng.normal(mu, float(spread), size=(len(mu), int(n_draws))), 0.0, None)


def load_committed_baselines(predictions_csv):
    """Per-row committed baseA/baseB CRPS for the same game-player-market rows."""
    need = ("athlete_id", "season", "week", "game_id", "observed",
            "crps_model", "crps_baseA", "crps_baseB")
    df = pd.read_csv(predictions_csv)
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError("%s is missing columns %s" % (predictions_csv, missing))
    return df


# ---------------------------------------------------------------------------
# scoring (committed conventions, reused verbatim)
# ---------------------------------------------------------------------------
crps_from_samples = rdp.crps_from_samples
cluster_ci = rdp.cluster_ci
score_block = rdp.score_block
