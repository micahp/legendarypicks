"""Unit and falsification tests for the event-data coverage audit.

Synthetic payloads only — no network, no cache dependency. Each contradiction
test asserts that the audit **flags** an injected disagreement, so a clean audit
run means the checks work rather than that nothing was checked.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DAY = HERE.parent
sys.path.insert(0, str(DAY))

import audit_event_coverage as audit  # noqa: E402

GID = "2018020001"


# ---------------------------------------------------------------------------
# payload builders
# ---------------------------------------------------------------------------
def play(period, t, type_key, details=None, situation="1551"):
    p = {"eventId": 1, "periodDescriptor": {"number": period, "periodType": "REG"},
         "timeInPeriod": t, "typeDescKey": type_key, "details": details or {}}
    if situation:
        p["situationCode"] = situation
    return p


def pbp_payload(plays, home_id=10, away_id=20, roster=(1, 2, 3, 4)):
    return {
        "id": GID, "gameType": 2, "gameState": "OFF",
        "homeTeam": {"id": home_id}, "awayTeam": {"id": away_id},
        "plays": plays,
        "rosterSpots": [{"playerId": p} for p in roster],
    }


def shift_payload(rows):
    return {"data": [{"typeCode": 517, "playerId": pid, "period": per, "teamId": team,
                      "startTime": st, "endTime": en, "duration": dur, "gameId": GID}
                     for pid, per, team, st, en, dur in rows], "total": len(rows)}


def write_cache(tmp_path, pbp=None, shifts=None):
    root = tmp_path / "raw"
    (root / "pbp").mkdir(parents=True, exist_ok=True)
    (root / "shifts").mkdir(parents=True, exist_ok=True)
    if pbp is not None:
        (root / "pbp" / f"{GID}.json.gz").write_bytes(gzip.compress(json.dumps(pbp).encode()))
    if shifts is not None:
        (root / "shifts" / f"{GID}.json.gz").write_bytes(gzip.compress(json.dumps(shifts).encode()))
    return root


LABEL_SIDE = {"team_sog": "4", "canonical_score": "2", "score": "2"}
LABEL_SIDE_AWAY = {"team_sog": "1", "canonical_score": "0", "score": "0"}
SKATERS = {1: {"toi_seconds": "600", "appeared": "1"}, 2: {"toi_seconds": "600", "appeared": "1"},
           3: {"toi_seconds": "600", "appeared": "1"}, 4: {"toi_seconds": "600", "appeared": "1"}}
GOALIES: dict = {}
SAMPLE_ROW = {"season": "2018", "game_date": "2018-10-03"}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    root = write_cache(
        tmp_path,
        pbp=pbp_payload([
            play(1, "00:24", "shot-on-goal", {"xCoord": 36, "yCoord": 29, "shotType": "snap",
                                              "eventOwnerTeamId": 10}),
            play(1, "05:00", "shot-on-goal", {"xCoord": -20, "yCoord": 10, "eventOwnerTeamId": 20}),
            play(1, "11:44", "goal", {"xCoord": 50, "yCoord": -25, "shotType": "wrist",
                                      "scoringPlayerId": 1, "eventOwnerTeamId": 10}),
            play(2, "03:00", "goal", {"xCoord": 10, "yCoord": 5, "shotType": "tip",
                                      "scoringPlayerId": 2, "eventOwnerTeamId": 10}),
            play(1, "02:05", "penalty", {"duration": 2, "descKey": "tripping",
                                         "committedByPlayerId": 20, "eventOwnerTeamId": 20}),
            play(3, "19:00", "shot-on-goal", {"xCoord": 0, "yCoord": 0, "shotType": "slap",
                                              "eventOwnerTeamId": 10}),
        ]),
        shifts=shift_payload([
            (1, 1, 10, "00:00", "10:00", "10:00"),
            (2, 1, 10, "00:00", "10:00", "10:00"),
            (3, 1, 10, "10:00", "20:00", "10:00"),
            (4, 1, 10, "10:00", "20:00", "10:00"),
        ]),
    )
    monkeypatch.setattr(audit, "CACHE", root)
    return root


def run(gid=GID, sides=None, skaters=None, goalies=None):
    sides = sides if sides is not None else {
        gid: {"home": dict(LABEL_SIDE), "away": dict(LABEL_SIDE_AWAY)}}
    skaters = skaters if skaters is not None else {gid: SKATERS}
    goalies = goalies if goalies is not None else {gid: GOALIES}
    return audit.audit_game(gid, SAMPLE_ROW, sides, skaters, goalies)


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------
def test_strength_class_parsing():
    assert audit.strength_class("1551") == "EV_5v5"
    assert audit.strength_class("1541") == "PP_away_5v4"
    assert audit.strength_class("1451") == "PP_home_5v4"
    assert audit.strength_class("1331") == "EV_3v3"
    assert audit.strength_class("0651") == "EN_away_pulled"
    assert audit.strength_class("1560") == "EN_home_pulled"


def test_strength_class_rejects_garbage():
    for bad in (None, "", "155", "15x1", "15511", 1551):
        assert audit.strength_class(bad) is None


def test_mmss():
    assert audit.mmss("01:41") == 101
    assert audit.mmss("20:00") == 1200
    assert audit.mmss("bad") is None
    assert audit.mmss(None) is None


# ---------------------------------------------------------------------------
# metrics on a well-formed game
# ---------------------------------------------------------------------------
def test_clean_game_metrics(wired):
    m, issues = run()
    assert m["events"] == 6
    assert m["shot_events"] == 5           # 3 shot-on-goal + 2 goals
    assert m["shot_events_with_xy"] == 5
    assert m["shot_events_with_type"] == 4    # the away shot has no shotType: a real gap
    assert m["blocked_shot_events"] == 0
    assert m["unblocked_shot_events"] == 5
    assert m["unblocked_with_type"] == 4
    assert m["goals_in_pbp"] == 2
    assert m["goals_by_period"] == json.dumps({"1": 1, "2": 1})
    assert m["penalty_events"] == 1
    assert m["penalties_with_duration"] == 1
    assert m["shift_players"] == 4
    assert m["toi_compared"] == 4
    assert m["toi_within_30s"] == 4
    assert m["roster_ids_not_in_official"] == 0
    # the synthetic game is internally consistent, so nothing is flagged
    assert issues == []


def test_feed_sog_matches_labels_when_counts_agree(wired):
    m, issues = run(sides={GID: {"home": {"team_sog": "4", "canonical_score": "2"},
                                 "away": {"team_sog": "1", "canonical_score": "0"}}})
    assert not [i for i in issues if i["issue"] == "SOG_FEED_VS_OFFICIAL"]
    assert not [i for i in issues if i["issue"] == "GOALS_FEED_VS_OFFICIAL"]


# ---------------------------------------------------------------------------
# falsification: injected contradictions must be flagged
# ---------------------------------------------------------------------------
def test_sog_disagreement_is_flagged(wired):
    _, issues = run(sides={GID: {"home": {"team_sog": "99", "canonical_score": "2"},
                                 "away": {"team_sog": "30", "canonical_score": "2"}}})
    hits = [i for i in issues if i["issue"] == "SOG_FEED_VS_OFFICIAL"]
    assert hits and "home" in hits[0]["detail"]


def test_goal_disagreement_is_flagged(wired):
    _, issues = run(sides={GID: {"home": {"team_sog": "2", "canonical_score": "5"},
                                 "away": {"team_sog": "1", "canonical_score": "2"}}})
    assert [i for i in issues if i["issue"] == "GOALS_FEED_VS_OFFICIAL"]


def test_unknown_roster_id_is_flagged(tmp_path, monkeypatch):
    root = write_cache(tmp_path, pbp=pbp_payload(
        [play(1, "00:24", "shot-on-goal", {"xCoord": 1, "yCoord": 1, "shotType": "snap",
                                          "eventOwnerTeamId": 10})],
        roster=(1, 2, 3, 4, 999)))
    monkeypatch.setattr(audit, "CACHE", root)
    _, issues = run()
    assert [i for i in issues if i["issue"] == "ROSTER_ID_NOT_IN_LABELS"]


def test_scorer_missing_from_roster_is_flagged(tmp_path, monkeypatch):
    root = write_cache(tmp_path, pbp=pbp_payload(
        [play(1, "11:44", "goal", {"xCoord": 50, "yCoord": -25, "shotType": "wrist",
                                   "scoringPlayerId": 777, "eventOwnerTeamId": 10})],
        roster=(1, 2, 3, 4)))
    monkeypatch.setattr(audit, "CACHE", root)
    _, issues = run()
    assert [i for i in issues if i["issue"] == "SCORER_NOT_IN_ROSTER"]


def test_shift_toi_contradiction_is_flagged(tmp_path, monkeypatch):
    root = write_cache(tmp_path, pbp=pbp_payload(
        [play(1, "00:24", "shot-on-goal", {"xCoord": 1, "yCoord": 1, "shotType": "snap",
                                          "eventOwnerTeamId": 10})]),
        shifts=shift_payload([(1, 1, 10, "00:00", "20:00", "20:00")]))
    monkeypatch.setattr(audit, "CACHE", root)
    m, issues = run(skaters={GID: {1: {"toi_seconds": "600", "appeared": "1"}}})
    assert m["toi_over_60s"] == 1
    assert [i for i in issues if i["issue"] == "TOI_SHIFT_VS_OFFICIAL"]


def test_missing_shifts_is_flagged(tmp_path, monkeypatch):
    root = write_cache(tmp_path, pbp=pbp_payload(
        [play(1, "00:24", "shot-on-goal", {"xCoord": 1, "yCoord": 1, "shotType": "snap",
                                          "eventOwnerTeamId": 10})]))
    monkeypatch.setattr(audit, "CACHE", root)
    m, issues = run()
    assert m["shifts"] is False
    assert [i for i in issues if i["issue"] == "SHIFTS_MISSING"]


def test_missing_pbp_is_flagged(tmp_path, monkeypatch):
    root = write_cache(tmp_path, pbp=None, shifts=shift_payload([(1, 1, 10, "0:00", "1:00", "1:00")]))
    monkeypatch.setattr(audit, "CACHE", root)
    m, issues = run()
    assert m["pbp"] is False
    assert [i for i in issues if i["issue"] == "PBP_MISSING"]


def test_out_of_box_coordinates_are_counted(tmp_path, monkeypatch):
    root = write_cache(tmp_path, pbp=pbp_payload(
        [play(1, "00:24", "shot-on-goal", {"xCoord": 500, "yCoord": 999, "shotType": "snap",
                                          "eventOwnerTeamId": 10})]),
        shifts=shift_payload([]))
    monkeypatch.setattr(audit, "CACHE", root)
    m, _ = run()
    assert m["shot_xy_out_of_box"] == 1


def test_shift_overlap_is_flagged(tmp_path, monkeypatch):
    rows = [(pid, 1, 10, "00:00", "10:00", "10:00") for pid in range(1, 9)]
    root = write_cache(tmp_path, pbp=pbp_payload(
        [play(1, "00:24", "shot-on-goal", {"xCoord": 1, "yCoord": 1, "shotType": "snap",
                                          "eventOwnerTeamId": 10})]),
        shifts=shift_payload(rows))
    monkeypatch.setattr(audit, "CACHE", root)
    m, issues = run(skaters={GID: {pid: {"toi_seconds": "600", "appeared": "1"} for pid in range(1, 9)}})
    assert m["max_concurrent_shift_players_all_teams"] == 8
    assert not [i for i in issues if i["issue"] == "SHIFT_OVERLAP"]   # 8 <= 12: legal
    # falsification: 13 simultaneous shifts is impossible hockey and must be flagged
    rows13 = [(pid, 1, 10, "00:00", "10:00", "10:00") for pid in range(1, 14)]
    root13 = write_cache(tmp_path / "over", pbp=pbp_payload(
        [play(1, "00:24", "shot-on-goal", {"xCoord": 1, "yCoord": 1, "shotType": "snap",
                                          "eventOwnerTeamId": 10})]),
        shifts=shift_payload(rows13))
    monkeypatch.setattr(audit, "CACHE", root13)
    m2, issues2 = run(skaters={GID: {pid: {"toi_seconds": "600", "appeared": "1"}
                                    for pid in range(1, 14)}})
    assert m2["max_concurrent_shift_players_all_teams"] == 13
    assert [i for i in issues2 if i["issue"] == "SHIFT_OVERLAP"]


# ---------------------------------------------------------------------------
# shootout convention and duplicated shift charts
# ---------------------------------------------------------------------------
def test_shootout_goal_counts_reconcile_with_the_winner_bonus(tmp_path, monkeypatch):
    """A SO game: feed has the SO conversion as a goal event, official score credits +1."""
    plays = [
        play(1, "10:00", "goal", {"xCoord": 10, "yCoord": 5, "shotType": "wrist",
                                  "scoringPlayerId": 1, "eventOwnerTeamId": 10}),
        play(2, "10:00", "goal", {"xCoord": 10, "yCoord": -5, "shotType": "wrist",
                                  "scoringPlayerId": 2, "eventOwnerTeamId": 10}),
        play(5, "00:10", "goal", {"xCoord": 5, "yCoord": 0, "shotType": "wrist",
                                  "scoringPlayerId": 1, "eventOwnerTeamId": 10, "situation": "1651"}),
    ]
    # a shootout goal must be in a period marked SO so the audit can exclude it
    plays[-1]["periodDescriptor"] = {"number": 5, "periodType": "SO"}
    root = write_cache(tmp_path, pbp=pbp_payload(plays), shifts=shift_payload([]))
    monkeypatch.setattr(audit, "CACHE", root)
    m, issues = run(sides={GID: {"home": {"team_sog": "2", "canonical_score": "3"},
                                 "away": {"team_sog": "1", "canonical_score": "0"}}})
    assert m["has_shootout"] is True
    assert m["shootout_goals_in_feed"] == 1
    assert m["goals_home_pbp_reg"] == 2 and m["goals_home_pbp_adj"] == 3
    assert not [i for i in issues if i["issue"] == "GOALS_FEED_VS_OFFICIAL"]
    assert [i for i in issues if i["issue"] == "SHOOTOUT_GOAL_BONUS_APPLIED"]


def test_goals_disagree_when_the_bonus_is_not_enough(tmp_path, monkeypatch):
    plays = [play(1, "10:00", "goal", {"xCoord": 10, "yCoord": 5, "shotType": "wrist",
                                      "scoringPlayerId": 1, "eventOwnerTeamId": 10})]
    root = write_cache(tmp_path, pbp=pbp_payload(plays), shifts=shift_payload([]))
    monkeypatch.setattr(audit, "CACHE", root)
    _, issues = run(sides={GID: {"home": {"team_sog": "1", "canonical_score": "4"},
                                 "away": {"team_sog": "1", "canonical_score": "1"}}})
    assert [i for i in issues if i["issue"] == "GOALS_FEED_VS_OFFICIAL"]


def test_duplicate_shift_chart_is_detected(tmp_path, monkeypatch):
    """Every shift listed twice: median shift/official TOI ratio ~2.0."""
    rows = [(pid, 1, 10, "00:00", "10:00", "10:00") for pid in (1, 2)] * 2
    root = write_cache(tmp_path, pbp=pbp_payload(
        [play(1, "00:24", "shot-on-goal", {"xCoord": 1, "yCoord": 1, "shotType": "snap",
                                          "eventOwnerTeamId": 10})]),
        shifts=shift_payload(rows))
    monkeypatch.setattr(audit, "CACHE", root)
    m, issues = run(skaters={GID: {1: {"toi_seconds": "600", "appeared": "1"},
                                   2: {"toi_seconds": "600", "appeared": "1"}}})
    assert m["shift_toi_ratio_median"] == pytest.approx(2.0, abs=0.05)
    assert m["shift_chart_duplicated"] is True
    assert [i for i in issues if i["issue"] == "DUPLICATE_SHIFT_CHART"]
