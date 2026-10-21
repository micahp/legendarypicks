"""The two priors of the passing hurdle, kept deliberately separate.

prereg rev4 §6.1 and §6.4:

  * **participation prior** `p_prior` = P(pass_attempts > 0 | pregame
    high-prior-volume QB cohort). Estimated over historical **cohort-eligible
    box-score appearances, positive and zero attempts alike** — a dressed
    quarterback with zero attempts contributes 0 to the numerator and 1 to the
    denominator. It must never be estimated from positive-attempt games alone.

  * **conditional volume prior** = positive pass-attempt counts among users.
    Estimated from **positive-attempt appearances only**; a zero-attempt
    appearance is not a draw from the conditional-on-usage count distribution.

Both are training-only (`season < target_season`), both follow the row-specific
membership of `cohort.classify` (each row classified by its own S-1 cut, 2018
unclassifiable and therefore absent from `cohort_member`), and both exclude rows
with no box-score record: an unknown is not a zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _training_rows(membership, target_season):
    """Cohort-eligible box-score appearances strictly before `target_season`."""
    m = membership[membership["cohort_member"]]
    return m[m["season"] < target_season]


def participation_rows(membership, target_season):
    """Rows entering the participation prior — zero-attempt ones included."""
    return _training_rows(membership, target_season)


def participation_prior(membership, target_season):
    """`P(attempts > 0 | cohort member)` over training appearances.

    Returns n (all cohort-eligible appearances), s (the positive ones), the rate,
    and the seasons/number of zero-attempt appearances that make up the
    denominator — so the split is auditable rather than implied.
    """
    rows = participation_rows(membership, target_season)
    n = int(len(rows))
    pos = int((rows["attempts"] > 0).sum())
    zeros = n - pos
    return {
        "n": n,
        "s": pos,
        "zero_attempt_appearances": zeros,
        "p_prior": float(pos / n) if n else float("nan"),
        "seasons": sorted(int(x) for x in rows["season"].unique()),
    }


def conditional_volume_rows(membership, target_season):
    """Rows entering the conditional volume prior — positive attempts only."""
    m = _training_rows(membership, target_season)
    return m[m["attempts"] > 0]


def conditional_volume_prior(membership, target_season):
    rows = conditional_volume_rows(membership, target_season)
    vals = rows["attempts"].to_numpy(dtype="float64")
    return {
        "n": int(len(vals)),
        "mean": float(vals.mean()) if len(vals) else float("nan"),
        "median": float(np.median(vals)) if len(vals) else float("nan"),
        "seasons": sorted(int(x) for x in rows["season"].unique()),
    }


def assert_row_sets(membership, target_season):
    """Falsification guard: the two priors must not be interchangeable.

    The volume prior's rows must be a subset of the participation prior's rows,
    and every volume-prior row must have a positive attempt count. A zero-attempt
    appearance inside the volume prior means the two estimands have been mixed.
    """
    part = participation_rows(membership, target_season)
    vol = conditional_volume_rows(membership, target_season)
    if not (vol["attempts"] > 0).all():
        raise AssertionError("volume prior contains a zero-attempt appearance")
    if len(vol) and not set(vol.index).issubset(set(part.index)):
        raise AssertionError("volume prior rows are not a subset of participation rows")
    return {"participation_rows": int(len(part)), "volume_rows": int(len(vol))}
