"""Focused tests for strict event identity, shift alignment, and label gating."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
DAY = HERE.parent
sys.path.insert(0, str(DAY))

import audit_event_detail as detail  # noqa: E402


def make_play(kind, *, details=None, period=1, clock="05:00", situation="1551"):
    row = {"typeDescKey": kind, "periodDescriptor": {"number": period, "periodType": "REG"},
           "timeInPeriod": clock, "details": details or {}}
    if situation is not None:
        row["situationCode"] = situation
    return row


def test_shot_fields_are_measured_separately_and_goal_scorer_is_not_lost():
    plays = [
        make_play("shot-on-goal", details={"shootingPlayerId": 8470001, "xCoord": 11, "yCoord": -5,
                                           "shotType": "wrist", "goalieInNetId": 8470002}),
        make_play("goal", details={"scoringPlayerId": 8470003, "xCoord": 1, "yCoord": 2,
                                   "shotType": "slap", "goalieInNetId": 8470002}),
        make_play("blocked-shot", details={"shootingPlayerId": 8470004, "xCoord": 1,
                                           "yCoord": 2, "goalieInNetId": None}),
        make_play("missed-shot", details={"shootingPlayerId": 8470005, "xCoord": 1}),
    ]
    got = detail.field_counts(plays)
    assert got["shot_events"] == 4
    assert got["shooter_id_direct"] == 3
    assert got["shooter_id_goal_scorer_only"] == 1
    assert got["shot_player_id_attributed"] == 4
    assert got["location_xy"] == 3
    assert got["shot_type"] == 2
    assert got["blocked_shot_events"] == 1
    assert got["blocked_shot_type"] == 0
    assert got["unblocked_shot_events"] == 3
    assert got["unblocked_shot_type"] == 2


def test_goal_player_id_uses_credited_scorer_only_when_shooter_is_absent():
    goal = make_play("goal", details={"scoringPlayerId": 8470001})
    assert detail.shot_player_id(goal) == 8470001
    goal["details"]["shootingPlayerId"] = 8470002
    assert detail.shot_player_id(goal) == 8470002
    assert detail.shot_player_id(make_play("shot-on-goal", details={"scoringPlayerId": 8470001})) is None


def test_clock_and_period_reject_invalid_source_values():
    assert detail.clock_seconds("19:59") == 1199
    assert detail.clock_seconds("20:60") is None
    assert detail.clock_seconds("-1:00") is None
    assert detail.period_parts(make_play("shot-on-goal")) == (1, "REG")
    assert detail.period_parts({"periodDescriptor": {"number": 0, "periodType": "REG"}})[0] is None


def test_shift_player_join_uses_numeric_id_and_marks_boundaries():
    intervals = [(1, 60, 120, 8470001, "10")]
    assert detail.player_shift_status(intervals, 1, 80, 8470001, 10) == "ON_ICE"
    assert detail.player_shift_status(intervals, 1, 59, 8470001, 10) == "BOUNDARY_AMBIGUOUS"
    assert detail.player_shift_status(intervals, 1, 20, 8470001, 10) == "OFF_ICE"
    assert detail.player_shift_status(intervals, 1, 80, 8470001, 20) == "OFF_ICE"


def test_situation_code_reconstructs_even_strength_and_empty_net():
    intervals = []
    for team, goalies, skaters in (("20", [8470001], range(8470010, 8470015)),
                                    ("10", [8470002], range(8470020, 8470025))):
        for pid in [*goalies, *skaters]:
            intervals.append((1, 0, 1200, pid, team))
    goalie_ids = {8470001, 8470002}
    assert detail.situation_shift_status(intervals, 1, 300, "1551", 10, 20, goalie_ids) == "MATCH"

    pulled = [(1, 0, 1200, pid, "20") for pid in range(8470100, 8470106)]
    pulled += [(1, 0, 1200, 8470002, "10")]
    pulled += [(1, 0, 1200, pid, "10") for pid in range(8470020, 8470025)]
    assert detail.situation_shift_status(pulled, 1, 300, "0651", 10, 20,
                                         {8470001, 8470002}) == "MATCH"


def test_only_researchable_grading_labels_are_eligible():
    def label(status, eligible, value):
        return SimpleNamespace(quality_status=status, eligible_grading=eligible, accepted_value=value)

    assert detail.label_is_eligible(label("VERIFIED", True, 3))
    assert detail.label_is_eligible(label("ADJUDICATED", True, 0))
    assert not detail.label_is_eligible(label("QUARANTINED", False, None))
    assert not detail.label_is_eligible(label("NOT_APPLICABLE", False, None))
    assert not detail.label_is_eligible(label("VERIFIED", False, 3))


def test_zero_toi_backup_is_not_a_played_goalie(tmp_path, monkeypatch):
    (tmp_path / "official_goalie_outcomes.csv").write_text(
        "game_id,player_id,appeared,toi_seconds\n"
        "2018020001,8470001,1,1200\n"
        "2018020001,8470002,0,0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(detail, "OFFICIAL_GOALIES", tmp_path / "official_goalie_outcomes.csv")
    assert detail.load_official_goalies() == {"2018020001": {8470001}}


def test_missing_goalie_id_is_classified_by_the_defending_side():
    empty_net_goal = make_play("goal", details={"eventOwnerTeamId": 10}, situation="0651")
    assert detail.expected_goalie_presence(empty_net_goal, home_id=10, away_id=20) is False
    ordinary_sog = make_play("shot-on-goal", details={"eventOwnerTeamId": 10}, situation="1551")
    assert detail.expected_goalie_presence(ordinary_sog, home_id=10, away_id=20) is True
    assert detail.expected_goalie_presence(make_play("goal", details={"eventOwnerTeamId": 10},
                                                     situation=None), 10, 20) is None


def test_source_hash_check_fails_loudly_on_changed_input(tmp_path):
    changed = tmp_path / "changed.csv"
    changed.write_text("different\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        detail.pinned_hash("canonical_frame_sha256", changed)

