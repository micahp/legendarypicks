"""Pregame cohort membership for the FBS passing hurdle (prereg rev4 §2.1-§2.2).

Membership is a property of the **target row's season**, never of a run:

  * a row in season S is classified by season S-1 full-season volume, with the
    top-quartile threshold recomputed on S-1 alone;
  * an athlete with no volume in S-1 falls back to strictly-trailing volume
    within S before that game, measured against the same S-1 threshold;
  * 2018 rows have no S-1 (the Phase-5 cache starts at 2018), so they are
    **unclassifiable**: never classified, never given a 2018 threshold.

Every row carries its provenance (`cut_season`, `cut_threshold`,
`membership_source`) so a reviewer can reconstruct the cut without reading this
module. No parameter is estimated here; membership is derived, not fitted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

QUANTILE = 0.75
MIN_SEASON = 2018          # first season present in the Phase-5 cache
MIN_ATHLETES = 4           # below this a season's threshold is undefined

SOURCE_PRIOR = "prior_season_volume"
SOURCE_TRAILING = "strictly_trailing"
SOURCE_UNCLASSIFIABLE = "unclassifiable"

# Which athletes take the prior-season branch rather than the trailing fallback.
#   "season_appearance"  athlete has a row in the cut season at all (preregistered
#                        population: reproduces COHORT.md's 1,175 rows / 106
#                        athletes, matching cohort_analysis.py's isin(vol.index))
#   "positive_volume"    athlete recorded positive volume in the cut season
#                        (literal reading of "no prior-season volume"; gives
#                        1,219 rows / 118 athletes on 2025 and is NOT the
#                        registered population)
PRIOR_BASIS_APPEARANCE = "season_appearance"
PRIOR_BASIS_POSITIVE = "positive_volume"
DEFAULT_PRIOR_BASIS = PRIOR_BASIS_APPEARANCE

ATHLETE_KEY = "athlete_id"


def season_volume(pg, col, positions, seasons=None):
    """Season total of `col` per (season, athlete), position-restricted."""
    d = pg[pg.position_abbreviation.isin(list(positions))]
    if seasons is not None:
        d = d[d.season.isin(list(seasons))]
    return d.groupby(["season", ATHLETE_KEY])[col].sum()


def season_thresholds(vol, quantile=QUANTILE, min_athletes=MIN_ATHLETES):
    """Top-quartile threshold per season, recomputed on that season alone.

    A season with fewer than `min_athletes` athletes recording volume gets
    +inf: nobody qualifies by prior-season volume and every row falls to the
    strictly-trailing fallback. Same convention as `cohort_analysis.py`.
    """
    out = {}
    for season, s in vol.groupby(level=0):
        active = s[s > 0]
        out[int(season)] = (float(active.quantile(quantile))
                            if len(active) >= min_athletes else float("inf"))
    return out


def trailing_within_season(pg, col, athlete_key=ATHLETE_KEY):
    """Cumulative `col` within (athlete, season) strictly before each row."""
    order = [athlete_key, "season", "week", "game_id"]
    d = pg.sort_values(order)
    vals = d[col].fillna(0.0)
    before = d.groupby([athlete_key, "season"])[col].cumsum() - vals
    return before.reindex(pg.index)


def classify(pg, col="pass_attempts", positions=("QB",),
             athlete_key=ATHLETE_KEY, volume_frame=None,
             prior_basis=DEFAULT_PRIOR_BASIS):
    """Return the membership table for every row of `pg`.

    `pg` is the population being classified: the strictly-trailing fallback is
    computed from **its** rows, because trailing volume is a property of the
    appearances in that population (this is what `cohort_analysis.py` did over
    the scored rows).

    `volume_frame` supplies the prior-season volume used for the cut, and
    defaults to `pg`. Pass the full history when `pg` is a single-season
    population — otherwise the cut season is absent from the frame and every row
    is (correctly) unclassifiable.

    `prior_basis` selects who takes the prior-season branch instead of the
    trailing fallback; see PRIOR_BASIS_* above. The default reproduces the
    preregistered population.

    Columns: athlete_id, season, week, game_id, cut_season, cut_threshold,
    membership_source, cohort_member, trailing_volume, attempts.
    """
    if not pg.index.is_unique:
        raise ValueError("classify() needs a unique index; call reset_index(drop=True) first")
    if prior_basis not in (PRIOR_BASIS_APPEARANCE, PRIOR_BASIS_POSITIVE):
        raise ValueError("unknown prior_basis %r" % (prior_basis,))

    src = pg if volume_frame is None else volume_frame
    vol = season_volume(src, col, positions)
    thr = season_thresholds(vol)

    season = pg["season"].to_numpy()
    cut = season - 1
    athletes = pg[athlete_key].to_numpy()

    thr_by_season = pd.Series(thr, dtype="float64")
    cut_threshold = thr_by_season.reindex(cut).to_numpy(dtype="float64")
    available = thr_by_season.reindex(cut).notna().to_numpy()

    idx = pd.MultiIndex.from_arrays([cut, athletes])
    prior_vol = pd.Series(vol.reindex(idx).to_numpy(dtype="float64"),
                          index=pg.index)
    present_in_cut = prior_vol.notna().to_numpy()
    prior_value = prior_vol.fillna(0.0).to_numpy(dtype="float64")
    if prior_basis == PRIOR_BASIS_APPEARANCE:
        has_prior = present_in_cut & available
    else:
        has_prior = (prior_value > 0) & available

    trail = trailing_within_season(pg, col, athlete_key).to_numpy(dtype="float64")

    member = np.where(has_prior,
                      prior_value >= cut_threshold,
                      trail >= cut_threshold)
    member = np.where(available, member, False)

    source = np.where(~available, SOURCE_UNCLASSIFIABLE,
                      np.where(has_prior, SOURCE_PRIOR, SOURCE_TRAILING))

    out = pd.DataFrame({
        athlete_key: athletes,
        "season": season,
        "week": pg["week"].to_numpy(),
        "game_id": pg["game_id"].to_numpy(),
        "cut_season": pd.array([int(c) if a else None for c, a in zip(cut, available)],
                               dtype="Int64"),
        "cut_threshold": np.where(available, cut_threshold, np.nan),
        "membership_source": source,
        "cohort_member": member.astype(bool),
        "trailing_volume": trail,
        "attempts": pg[col].fillna(0.0).to_numpy(dtype="float64"),
    }, index=pg.index)
    return out
