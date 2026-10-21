"""Integration check: the implementation must reproduce the preregistered population.

The prereg fixes the 2025 evaluation set at **1,175 rows / 106 athletes** for
passing attempts (produced by `cohort_analysis.py` at 9b3ab91e). If this test
fails, the model would be scoring a different population than the one that was
approved, no matter how good the code looks — so it fails loudly rather than
warning.

Read-only against the Phase-5 cache and the committed predictions file. Skips if
either is absent (fresh clone without the cache).
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_DAY = os.path.dirname(_PKG)
if _DAY not in sys.path:
    sys.path.insert(0, _DAY)

from hurdle import cohort, run_hurdle_passing as runner  # noqa: E402

CACHE = "/root/lp-fbs-archive/research/fbs/phase5/cache/player_games.parquet"
PREDICTIONS = os.path.join(_DAY, "predictions_pass_attempts.csv")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(CACHE) and os.path.exists(PREDICTIONS)),
    reason="Phase-5 cache or committed predictions not present")


@pytest.fixture(scope="module")
def fitted():
    return runner.readiness(runner.rdp.DEFAULT_CACHE, runner.prereg_gate.DEFAULT_PREREG,
                            PREDICTIONS)


def test_population_matches_the_preregistration(fitted):
    assert fitted["scored_2025_rows"] == 9059
    assert fitted["scored_2025_members"] == 1175, (
        "2025 cohort has %d rows, prereg registers 1,175" % fitted["scored_2025_members"])
    assert fitted["scored_2025_athletes"] == 106
    assert fitted["prereg_population_match"]["matches"] is True


def test_2018_is_unclassifiable_on_real_data(fitted):
    s2018 = fitted["by_season"][2018]
    assert s2018["unclassifiable"] == s2018["rows"]
    assert s2018["members"] == 0
    assert s2018["cut_season"] is None


def test_every_later_season_uses_its_own_prior_cut(fitted):
    for season, row in fitted["by_season"].items():
        if season == 2018:
            continue
        assert row["cut_season"] == season - 1, (season, row["cut_season"])


def test_thresholds_are_seasonal_and_recomputed(fitted):
    th = fitted["thresholds"]
    assert len(set(th.values())) > 1, "thresholds were reused across seasons"
    assert th[2024] == pytest.approx(132.25)          # the committed cut


def test_prior_rowsets_are_nested(fitted):
    part = fitted["participation_prior_rowset"]
    vol = fitted["conditional_volume_prior_rowset"]
    assert vol["n"] <= part["n"]
    assert part["s"] == vol["n"]          # positive appearances in both
    assert part["value_reported"] is False


def test_gate_still_blocks_fitting(fitted):
    assert fitted["prereg"]["signed"] is False
