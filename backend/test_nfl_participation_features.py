"""Hand-computed checks for the participation coverage matchup (coverage_columns).

Fixture, season 2018, teams A and B.
Week 1, game g1 (home A, away B):
  A offense: MAN epa 1.0, MAN epa 0.0, ZONE epa -1.0
  B offense: MAN epa 0.5, ZONE epa 0.0, MAN sack epa -2.0 (a sack: never in a share)
Week 2, game g2 (home B, away A): plays of its own, which must never enter g2's column.

League to date before g2 (week 1 only): man 3, zone 2, labelled 5.
  L_man = 3/5, L_eM = 1.5/3 = 1/2, L_eZ = -1.0/2 = -1/2.
Offense, shrink K = 200:
  eM_A = (1.0 + 200*1/2) / (2 + 200) = 101/202 = 1/2
  eZ_A = (-1.0 + 200*(-1/2)) / (1 + 200) = -101/201
  eM_B = (0.5 + 200*1/2) / (1 + 200) = 100.5/201
  eZ_B = (0.0 + 200*(-1/2)) / (1 + 200) = -100/201
Defense, m = (man faced + 200*L_man) / (labelled faced + 200):
  m_A (faces B: man 1, labelled 2) = (1 + 120) / 202 = 121/202
  m_B (faces A: man 2, labelled 3) = (2 + 120) / 203 = 122/203
g2 home B, away A:
  home edge = (eM_B - eZ_B) * (m_A - L_man) = (401/402) * (121/202 - 3/5) = (401/402) * (-1/1010)
  away edge = (eM_A - eZ_A) * (m_B - L_man) = (403/402) * (122/203 - 3/5) = (403/402) * (1/1015)
  column    = home edge - away edge = -401/406020 - 403/408030
"""
from fractions import Fraction

import pytest

import nfl_feature_backtest as fb


def _play(season, week, posteam, defteam, cov, epa, sack=0):
    return {"season": season, "week": week, "posteam": posteam, "defteam": defteam,
            "sack": sack, "cov": cov, "epa": epa}


WEEK1 = [
    _play(2018, 1, "A", "B", "MAN_COVERAGE", 1.0),
    _play(2018, 1, "A", "B", "MAN_COVERAGE", 0.0),
    _play(2018, 1, "A", "B", "ZONE_COVERAGE", -1.0),
    _play(2018, 1, "B", "A", "MAN_COVERAGE", 0.5),
    _play(2018, 1, "B", "A", "ZONE_COVERAGE", 0.0),
    _play(2018, 1, "B", "A", "MAN_COVERAGE", -2.0, sack=1),
]
WEEK2 = [
    _play(2018, 2, "A", "B", "MAN_COVERAGE", 3.0),
    _play(2018, 2, "B", "A", "ZONE_COVERAGE", 2.0),
]
ROWS = [
    {"game_id": "g1", "season": 2018, "week": 1, "home": "A", "away": "B"},
    {"game_id": "g2", "season": 2018, "week": 2, "home": "B", "away": "A"},
]
HAND_G2 = float(Fraction(-401, 406020) - Fraction(403, 408030))


def test_hand_built_fixture_matches_hand_computed_column():
    cols, zeros = fb.coverage_columns(WEEK1 + WEEK2, ROWS)
    assert abs(cols["g2"][0] - HAND_G2) < 1e-12
    assert zeros == 1


def test_week_one_column_is_zero_and_counted():
    cols, zeros = fb.coverage_columns(WEEK1 + WEEK2, ROWS)
    assert cols["g1"] == [0.0]
    assert zeros == 1


def test_sack_never_enters_a_share():
    with_sack, _ = fb.coverage_columns(WEEK1 + WEEK2, ROWS)
    without, _ = fb.coverage_columns([p for p in WEEK1 if not p["sack"]] + WEEK2, ROWS)
    assert with_sack["g2"] == without["g2"]


def test_game_does_not_use_its_own_or_later_weeks():
    with_wk2, _ = fb.coverage_columns(WEEK1 + WEEK2, ROWS)
    wk2_inflated = [dict(p, epa=p["epa"] + 50.0) for p in WEEK2]
    changed, _ = fb.coverage_columns(WEEK1 + wk2_inflated, ROWS)
    assert changed["g2"] == with_wk2["g2"]
    assert abs(with_wk2["g2"][0] - HAND_G2) < 1e-12


def test_unlabelled_and_null_epa_plays_are_skipped():
    extra = [_play(2018, 1, "A", "B", "", 5.0),
             _play(2018, 1, "A", "B", "MAN_COVERAGE", None),
             _play(2018, 1, "B", "A", None, 4.0)]
    with_extra, _ = fb.coverage_columns(WEEK1 + extra + WEEK2, ROWS)
    assert abs(with_extra["g2"][0] - HAND_G2) < 1e-12


def test_week_two_without_labelled_history_raises():
    with pytest.raises(ValueError):
        fb.coverage_columns([], [{"game_id": "g9", "season": 2018, "week": 2, "home": "A", "away": "B"}])
