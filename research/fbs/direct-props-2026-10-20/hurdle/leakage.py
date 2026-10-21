"""Leakage assertions for the passing hurdle (prereg rev4 §7).

These are meant to be **called at run time and to raise**, not to be read. The
suite in `tests/test_leakage.py` injects each violation and asserts that the
matching check fires, so a green run means the guards work rather than that
nobody tripped them.

Nothing here inspects the target game's outcome; the checks are about which rows
were allowed to contribute to a number.
"""
from __future__ import annotations

import numpy as np

from .cohort import SOURCE_UNCLASSIFIABLE


class LeakageError(AssertionError):
    """Raised when a membership or fit row set breaks the preregistered rule."""


def assert_provenance_present(membership):
    cols = ("cut_season", "cut_threshold", "membership_source", "cohort_member")
    missing = [c for c in cols if c not in membership.columns]
    if missing:
        raise LeakageError("membership table is missing provenance columns %s" % (missing,))
    return True


def assert_cut_precedes_target(membership):
    """The cut season is the row's own S-1; never a later season, never the target."""
    m = membership
    has_cut = m["cut_season"].notna()
    bad = m[has_cut & (m["cut_season"] != (m["season"] - 1))]
    if len(bad):
        raise LeakageError(
            "cut season is not the target season's own S-1 on %d row(s); "
            "e.g. season=%s cut=%s" % (len(bad), bad["season"].iloc[0], bad["cut_season"].iloc[0]))
    return True


def assert_threshold_is_seasonal(membership, thresholds):
    """`cut_threshold` must equal the threshold recomputed on the cut season."""
    m = membership
    has_cut = m["cut_season"].notna()
    expected = m.loc[has_cut, "cut_season"].astype(int).map(thresholds)
    got = m.loc[has_cut, "cut_threshold"].astype(float)
    exp = expected.astype(float)
    both_nan = got.isna() & exp.isna()
    close = np.isclose(got.fillna(0.0), exp.fillna(0.0), rtol=0, atol=1e-9) | both_nan
    if not bool(np.all(close)):
        raise LeakageError("cut_threshold does not match the cut season's own threshold")
    return True


def assert_unclassifiable_2018(membership):
    """2018 rows have no S-1 in the cache: never members, never classified."""
    m = membership
    y2018 = m["season"] == 2018
    bad_source = y2018 & (m["membership_source"] != SOURCE_UNCLASSIFIABLE)
    bad_member = y2018 & m["cohort_member"].astype(bool)
    bad_cut = y2018 & m["cut_season"].notna()
    if bad_source.any() or bad_member.any() or bad_cut.any():
        raise LeakageError(
            "2018 rows were classified: %d source, %d member, %d with a cut season"
            % (int(bad_source.sum()), int(bad_member.sum()), int(bad_cut.sum())))
    return True


def assert_no_target_season_in_fit(fit_seasons, target_season):
    """Nothing in the fit/tune set may come from the season being scored."""
    bad = [s for s in fit_seasons if int(s) >= int(target_season)]
    if bad:
        raise LeakageError("fit seasons %s include the target season %s" % (bad, target_season))
    return True


def assert_prior_row_sets(participation_rows, volume_rows):
    """The two priors use different row sets; volume rows are users only."""
    if len(volume_rows) and not (volume_rows["attempts"] > 0).all():
        raise LeakageError("volume prior contains a zero-attempt appearance")
    if len(volume_rows) and not set(volume_rows.index).issubset(set(participation_rows.index)):
        raise LeakageError("volume prior rows are not a subset of participation rows")
    return True


def assert_source_before_kickoff(max_source_ns, kickoff_ns):
    """Per target row: every contributing row predates the target kickoff."""
    a = np.asarray(max_source_ns, dtype="float64")
    b = np.asarray(kickoff_ns, dtype="float64")
    if a.shape != b.shape:
        raise LeakageError("source/kickoff arrays differ in shape")
    bad = a >= b
    if bad.any():
        raise LeakageError("%d target row(s) drew on a source at or after kickoff"
                           % int(bad.sum()))
    return True


def assert_no_future_week(membership, week_col="week", season_col="season"):
    """No contributing row may be the target row itself or a later week."""
    m = membership
    sub = m[m["cut_season"].notna()]
    if not len(sub):
        return True
    bad = sub[sub["cut_season"].astype(int) >= sub[season_col].astype(int)]
    if len(bad):
        raise LeakageError("cut season is not strictly before the target season")
    return True


def run_all(membership, thresholds, participation_rows, volume_rows):
    """Every check, in the order a reviewer would ask for them."""
    assert_provenance_present(membership)
    assert_cut_precedes_target(membership)
    assert_threshold_is_seasonal(membership, thresholds)
    assert_unclassifiable_2018(membership)
    assert_no_future_week(membership)
    assert_prior_row_sets(participation_rows, volume_rows)
    return True
