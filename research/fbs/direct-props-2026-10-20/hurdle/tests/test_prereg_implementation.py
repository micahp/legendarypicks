"""Unit and falsification tests for the preregistered passing hurdle.

Every leakage test asserts that the guard **fires** on an injected violation —
a check that never trips is not a check. Nothing here fits, tunes or scores a
model; the population test only derives membership, which is data derivation.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_DAY = os.path.dirname(_PKG)
if _DAY not in sys.path:
    sys.path.insert(0, _DAY)

from hurdle import cohort, leakage, model, prereg_gate, priors  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def frame(rows):
    """rows: (athlete_id, season, week, game_id, attempts) tuples."""
    df = pd.DataFrame(rows, columns=["athlete_id", "season", "week", "game_id", "pass_attempts"])
    df["position_abbreviation"] = "QB"
    return df.sort_values(["athlete_id", "season", "week", "game_id"]).reset_index(drop=True)


def five_qbs(season, totals, week=1):
    return [(100 + i, season, week, 9000 + season * 100 + i, t)
            for i, t in enumerate(totals)]


# ---------------------------------------------------------------------------
# 1. season-by-season, strictly chronological membership
# ---------------------------------------------------------------------------
def test_cut_season_is_target_season_minus_one():
    pg = frame(five_qbs(2018, [100, 200, 300, 400, 500])
               + five_qbs(2019, [100, 200, 300, 400, 500])
               + five_qbs(2020, [100, 200, 300, 400, 500]))
    m = cohort.classify(pg)
    for season in (2019, 2020):
        sub = m[m["season"] == season]
        assert set(sub["cut_season"].astype(int)) == {season - 1}
    leakage.assert_cut_precedes_target(m)


def test_threshold_is_recomputed_on_the_cut_season_not_reused():
    pg = frame(five_qbs(2018, [10, 20, 30, 40, 50])            # tight spread
               + five_qbs(2019, [100, 200, 300, 400, 500])     # wide spread
               + five_qbs(2020, [100, 200, 300, 400, 500]))
    vol = cohort.season_volume(pg, "pass_attempts", ("QB",))
    thr = cohort.season_thresholds(vol)
    assert thr[2018] != thr[2019]
    m = cohort.classify(pg)
    r2020 = m[m["season"] == 2020].iloc[0]
    assert r2020["cut_season"] == 2019
    assert r2020["cut_threshold"] == pytest.approx(thr[2019])
    assert r2020["cut_threshold"] != pytest.approx(thr[2018])
    leakage.assert_threshold_is_seasonal(m, thr)


def test_2018_rows_are_unclassifiable_and_never_members():
    pg = frame(five_qbs(2018, [100, 200, 300, 400, 500]))
    m = cohort.classify(pg)
    assert (m["membership_source"] == cohort.SOURCE_UNCLASSIFIABLE).all()
    assert not m["cohort_member"].any()
    assert m["cut_season"].isna().all()
    leakage.assert_unclassifiable_2018(m)


def test_no_carry_forward_across_seasons():
    """A high-volume 2018 QB is a 2019 member and a 2020 non-member once 2019 volume is low."""
    rows = []
    for aid, t in zip([1, 2, 3, 4, 5], [900, 100, 100, 100, 100]):      # athlete 1 dominates 2018
        rows.append((aid, 2018, 1, 8001 + aid, t))
    for aid, t in zip([1, 2, 3, 4, 5], [1, 900, 900, 900, 900]):        # athlete 1 collapses 2019
        rows.append((aid, 2019, 1, 8101 + aid, t))
        rows.append((aid, 2020, 1, 8201 + aid, 10))
    m = cohort.classify(frame(rows))
    a1_2019 = m[(m["athlete_id"] == 1) & (m["season"] == 2019)].iloc[0]
    a1_2020 = m[(m["athlete_id"] == 1) & (m["season"] == 2020)].iloc[0]
    assert a1_2019["membership_source"] == cohort.SOURCE_PRIOR
    assert bool(a1_2019["cohort_member"]) is True
    assert a1_2020["membership_source"] == cohort.SOURCE_PRIOR
    assert bool(a1_2020["cohort_member"]) is False


def test_strictly_trailing_fallback_crosses_the_threshold_mid_season():
    rows = [(1, 2018, 1, 8001, 10), (2, 2018, 1, 8002, 20),
            (3, 2018, 1, 8003, 30), (4, 2018, 1, 8004, 40)]
    rows += [(9, 2019, 1, 8101, 40), (9, 2019, 2, 8102, 40), (9, 2019, 3, 8103, 40)]
    pg = frame(rows)
    thr = cohort.season_thresholds(cohort.season_volume(pg, "pass_attempts", ("QB",)))[2018]
    m = cohort.classify(pg)
    got = m[(m["athlete_id"] == 9) & (m["season"] == 2019)].sort_values("week")
    assert (got["membership_source"] == cohort.SOURCE_TRAILING).all()
    assert list(got["trailing_volume"]) == [0.0, 40.0, 80.0]     # strictly before each game
    assert list(got["cohort_member"]) == [t >= thr for t in (0.0, 40.0, 80.0)]
    assert thr <= 40.0, "threshold should be crossed inside the season for this fixture"
    assert bool(got["cohort_member"].iloc[0]) is False


# ---------------------------------------------------------------------------
# 2. the two priors, two row sets
# ---------------------------------------------------------------------------
def membership_with_attempts(values):
    df = pd.DataFrame({
        "athlete_id": [7] * len(values),
        "season": [2019] * len(values),
        "week": list(range(1, len(values) + 1)),
        "game_id": [7000 + i for i in range(len(values))],
        "cut_season": [2018] * len(values),
        "cut_threshold": [10.0] * len(values),
        "membership_source": [cohort.SOURCE_PRIOR] * len(values),
        "cohort_member": [True] * len(values),
        "trailing_volume": [0.0] * len(values),
        "attempts": [float(v) for v in values],
    })
    return df


def test_participation_prior_counts_zero_attempts_in_the_denominator():
    m = membership_with_attempts([20, 0, 30, 0])
    p = priors.participation_prior(m, target_season=2020)
    assert p["n"] == 4
    assert p["s"] == 2
    assert p["zero_attempt_appearances"] == 2
    assert p["p_prior"] == pytest.approx(0.5)
    # positive-only estimation would report 1.0 — the failure mode this forbids
    assert p["p_prior"] != pytest.approx(1.0)


def test_conditional_volume_prior_uses_positive_attempts_only():
    m = membership_with_attempts([20, 0, 30, 0])
    v = priors.conditional_volume_rows(m, target_season=2020)
    assert len(v) == 2
    assert (v["attempts"] > 0).all()
    assert v["attempts"].mean() == pytest.approx(25.0)
    part = priors.participation_rows(m, target_season=2020)
    assert set(v.index).issubset(set(part.index))
    priors.assert_row_sets(m, target_season=2020)


def test_row_set_guard_rejects_a_zero_attempt_volume_prior():
    m = membership_with_attempts([20, 0, 30])
    bad = m.copy()
    bad.loc[bad.index[1], "attempts"] = 0.0
    with pytest.raises(AssertionError):
        leakage.assert_prior_row_sets(
            priors.participation_rows(bad, 2020),
            bad)                                   # includes the zero-attempt row


def test_priors_are_training_only():
    m = membership_with_attempts([20, 20])
    m.loc[m.index[-1], "season"] = 2021          # at/after the target season
    p = priors.participation_prior(m, target_season=2021)
    assert p["n"] == 1
    leakage.assert_no_target_season_in_fit([2019, 2020], 2021)
    with pytest.raises(leakage.LeakageError):
        leakage.assert_no_target_season_in_fit([2019, 2021], 2021)


# ---------------------------------------------------------------------------
# 3. the smoothed participation hurdle
# ---------------------------------------------------------------------------
def test_participation_probability_formula():
    assert model.participation_probability(3, 5, 0.4) == pytest.approx(3.4 / 6.0)
    assert model.participation_probability(0, 0, 0.25) == pytest.approx(0.25)
    assert model.participation_probability(5, 5, 0.5) == pytest.approx(5.5 / 6.0)


def test_participation_probability_rejects_impossible_inputs():
    with pytest.raises(ValueError):
        model.participation_probability(6, 5, 0.5)          # s > n
    with pytest.raises(ValueError):
        model.participation_probability(1, 6, 0.5)          # n > WINDOW
    with pytest.raises(ValueError):
        model.participation_probability(1, 5, 1.5)          # not a probability


def test_participation_counts_include_zero_attempt_appearances():
    pg = frame([(1, 2019, w, 7000 + w, a) for w, a in
                enumerate([10, 0, 5, 0, 0, 20], start=1)])
    s, n = model.participation_counts(pg)
    assert s.iloc[-1] == 2          # 10 and 5
    assert n.iloc[-1] == 5          # last five appearances, zeros counted


def test_trailing_positive_mean_excludes_zero_attempt_appearances():
    pg = frame([(1, 2019, w, 7000 + w, a) for w, a in
                enumerate([10, 0, 5, 0, 0, 20], start=1)])
    mu = model.trailing_positive_mean(pg)
    assert mu.iloc[-1] == pytest.approx(7.5)      # (10 + 5) / 2, not 15 / 5


# ---------------------------------------------------------------------------
# 4. zero-truncated conditional count
# ---------------------------------------------------------------------------
def test_ztnb_never_draws_zero():
    rng = np.random.default_rng(11)
    mu = np.array([0.5, 2.0, 15.0, 40.0])
    out = model.ztnb_samples(mu, r=1.0, n_draws=4000, rng=rng)
    assert (out > 0).all()
    assert out.shape == (4, 4000)


def test_ztnb_mean_matches_the_truncated_negative_binomial():
    rng = np.random.default_rng(12)
    mu, r = 9.0, 2.0                       # mu/(1-p0)=9.31, unlike mu+1=10: separable
    out = model.ztnb_samples(np.array([mu]), r=r, n_draws=200000, rng=rng)[0]
    p0 = (r / (r + mu)) ** r
    assert out.mean() == pytest.approx(mu / (1 - p0), rel=0.01)
    # falsification: a "+1 shift" would land near mu + 1, not mu / (1 - p0)
    assert abs(out.mean() - (mu + 1)) > 0.5


# ---------------------------------------------------------------------------
# 5. shared simulated attempts between the two markets
# ---------------------------------------------------------------------------
def test_attempts_are_shared_between_attempts_and_yards():
    rng = np.random.default_rng(13)
    mu = np.array([5.0, 20.0, 35.0])
    sim = model.simulate_passing(mu, r=1.0, p_H=np.array([0.2, 0.7, 0.95]),
                                 eff=np.array([7.0, 7.5, 8.0]), eff_sd=1.0,
                                 n_draws=500, rng=rng)
    att, yards, rate = sim["attempts"], sim["yards"], sim["rate"]
    assert np.array_equal(yards, att * rate)                  # one attempt draw, not two
    pos = att > 0
    assert np.allclose(yards[pos] / att[pos], rate[pos])
    assert np.array_equal(att[att > 0] % 1, np.zeros(int(pos.sum())))  # integer counts


def test_hurdle_produces_zero_mass_and_negative_yards_survive():
    rng = np.random.default_rng(14)
    sim = model.simulate_passing(np.array([25.0] * 2000), r=2.0,
                                 p_H=np.full(2000, 0.3), eff=np.full(2000, -0.5),
                                 eff_sd=2.0, n_draws=50, rng=rng)
    assert (sim["attempts"] == 0).any()          # zero-usage mass exists
    assert (sim["yards"] < 0).any()              # not clipped at zero
    assert sim["yards"].min() < 0


def test_sampling_is_deterministic_for_a_fixed_seed():
    a = model.simulate_passing(np.array([10.0, 20.0]), 1.0, np.array([0.5, 0.8]),
                               np.array([7.0, 7.0]), 1.0, 200,
                               np.random.default_rng(model.SEED))
    b = model.simulate_passing(np.array([10.0, 20.0]), 1.0, np.array([0.5, 0.8]),
                               np.array([7.0, 7.0]), 1.0, 200,
                               np.random.default_rng(model.SEED))
    assert np.array_equal(a["attempts"], b["attempts"])
    assert np.array_equal(a["yards"], b["yards"])


# ---------------------------------------------------------------------------
# 6. customised guards fire on injected violations
# ---------------------------------------------------------------------------
def test_leakage_guard_rejects_a_cut_from_the_target_season():
    pg = frame(five_qbs(2019, [100, 200, 300, 400, 500]) + five_qbs(2020, [1, 2, 3, 4, 5]))
    m = cohort.classify(pg)
    bad = m.copy()
    bad.loc[bad["season"] == 2020, "cut_season"] = 2020
    with pytest.raises(leakage.LeakageError):
        leakage.assert_cut_precedes_target(bad)


def test_leakage_guard_rejects_a_wrong_threshold():
    pg = frame(five_qbs(2018, [100, 200, 300, 400, 500]) + five_qbs(2019, [1, 2, 3, 4, 5]))
    m = cohort.classify(pg)
    thr = cohort.season_thresholds(cohort.season_volume(pg, "pass_attempts", ("QB",)))
    bad = m.copy()
    bad.loc[bad["season"] == 2019, "cut_threshold"] = 12345.0
    with pytest.raises(leakage.LeakageError):
        leakage.assert_threshold_is_seasonal(bad, thr)


def test_leakage_guard_rejects_a_classified_2018_row():
    pg = frame(five_qbs(2018, [100, 200, 300, 400, 500]))
    m = cohort.classify(pg)
    bad = m.copy()
    bad.loc[bad.index[0], "cohort_member"] = True
    with pytest.raises(leakage.LeakageError):
        leakage.assert_unclassifiable_2018(bad)


def test_leakage_guard_rejects_a_source_at_kickoff():
    with pytest.raises(leakage.LeakageError):
        leakage.assert_source_before_kickoff([1000.0], [1000.0])
    assert leakage.assert_source_before_kickoff([999.0], [1000.0]) is True


def test_leakage_guard_requires_provenance_columns():
    pg = frame(five_qbs(2019, [100, 200, 300, 400, 500]))
    m = cohort.classify(pg).drop(columns=["cut_threshold"])
    with pytest.raises(leakage.LeakageError):
        leakage.assert_provenance_present(m)


# ---------------------------------------------------------------------------
# 7. the signature gate
# ---------------------------------------------------------------------------
def test_gate_blocks_the_real_preregistration():
    st = prereg_gate.gate_status(prereg_gate.DEFAULT_PREREG)
    assert st["marker_present"] is True
    assert st["signed"] is False
    with pytest.raises(prereg_gate.PreregNotSigned):
        prereg_gate.assert_prereg_signed(prereg_gate.DEFAULT_PREREG)


def test_gate_accepts_only_a_real_signature(tmp_path):
    doc = tmp_path / "prereg.md"
    doc.write_text("# x\n\n## 10. Signature\n\n```\nAPPROVED BY MICAH: "
                   "______________________________   (date / initials)\n```\n")
    assert prereg_gate.signature_value(doc.read_text()) == ""
    with pytest.raises(prereg_gate.PreregNotSigned):
        prereg_gate.assert_prereg_signed(str(doc))

    doc.write_text(doc.read_text().replace(
        "APPROVED BY MICAH: ______________________________",
        "APPROVED BY MICAH: M. Price 2026-10-21"))
    assert prereg_gate.assert_prereg_signed(str(doc))["signed"] is True


# ---------------------------------------------------------------------------
# 8. immovable scoring rule and dispersion grids
# ---------------------------------------------------------------------------
def test_dispersion_grids_are_the_committed_ones():
    assert model.SPREAD_R_GRID == (0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
    assert model.SPREAD_ESD_MULT == (1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0, 4.0)
    assert model.WINDOW == 5
    assert model.EFF_WINDOW == 15


def test_committed_baseline_loader_rejects_a_thin_file(tmp_path):
    p = tmp_path / "pred.csv"
    pd.DataFrame({"athlete_id": [1], "season": [2025]}).to_csv(p, index=False)
    with pytest.raises(ValueError):
        model.load_committed_baselines(str(p))


def test_committed_baseline_loader_reads_the_real_file():
    path = os.path.join(_DAY, "predictions_pass_attempts.csv")
    if not os.path.exists(path):
        pytest.skip("committed predictions not present")
    df = model.load_committed_baselines(path)
    assert len(df) == 9059
    assert set(["crps_baseA", "crps_baseB"]).issubset(df.columns)
