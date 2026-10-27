from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import data
from kernel import Context, Token, Transition


def shift_fixture(*, missing_home_center=None, duplicate_home_center=False):
    rows = []
    roster = {}
    for side, team_id in (("home", "1"), ("away", "2")):
        positions = ["C", "L", "R", "D", "D", "G"]
        for index, position in enumerate(positions):
            player_id = f"{side}-{index}"
            roster[player_id] = (team_id, position)
            intervals = [(0, 1200)]
            if side == "home" and index == 0 and missing_home_center is not None:
                start, end = missing_home_center
                intervals = [(0, start), (end, 1200)]
            for start, end in intervals:
                if start == end:
                    continue
                rows.append({"gameId": "g", "period": 1,
                    "startTime": f"{start // 60:02d}:{start % 60:02d}",
                    "endTime": f"{end // 60:02d}:{end % 60:02d}",
                    "duration": f"{(end-start) // 60:02d}:{(end-start) % 60:02d}",
                    "playerId": player_id, "teamId": team_id})
    if duplicate_home_center:
        rows.append({"gameId": "g", "period": 1, "startTime": "00:05",
            "endTime": "00:10", "duration": "00:05",
            "playerId": "home-0", "teamId": "1"})
    return {"total": len(rows), "data": rows}, roster


def state5():
    return {"away_goalie": 1, "away_skaters": 5,
            "home_skaters": 5, "home_goalie": 1}


def event(event_type, second, *, side="home", details=None, score_before=None):
    return {"period_type": "REG", "period": 1, "time": second,
        "type": event_type, "side": side, "details": details or {},
        "score_before": score_before or {"home": 0, "away": 0},
        "event_state_attribution": {"eligible_for_conditional_fit": True,
                                     "state": state5()}}


class SequenceExtractionTests(unittest.TestCase):
    def test_shift_interval_sweep_finds_5v5_and_manpower_gap(self):
        shifts, roster = shift_fixture(missing_home_center=(10, 20))
        states, ambiguous, _ = data._state_by_second(
            shifts, "g", 1, {"1": "home", "2": "away"}, roster)
        self.assertEqual(states[:10], ["5v5"] * 10)
        self.assertEqual(states[10:20], ["non5v5"] * 10)
        self.assertEqual(states[20:30], ["5v5"] * 10)
        self.assertEqual(ambiguous, [])

    def test_duplicate_track_marks_clock_as_ambiguous(self):
        shifts, roster = shift_fixture(duplicate_home_center=True)
        states, ambiguous, _ = data._state_by_second(
            shifts, "g", 1, {"1": "home", "2": "away"}, roster)
        self.assertEqual(states[5:10], ["ambiguous"] * 5)
        self.assertEqual(ambiguous[0], 5)
        self.assertEqual(ambiguous[-1], 9)

    def test_zero_duration_shift_annotations_do_not_invalidate_period(self):
        shifts, roster = shift_fixture()
        shifts["data"].extend([
            {"gameId": "g", "period": 1, "startTime": "01:00",
             "endTime": "01:00", "duration": None, "typeCode": 505,
             "playerId": "home-0", "teamId": "1"},
            {"gameId": "g", "period": 1, "startTime": "05:00",
             "endTime": "", "duration": "00:00", "typeCode": 517,
             "playerId": "away-0", "teamId": "2"},
        ])
        shifts["total"] = len(shifts["data"])
        states, ambiguous, anomalies = data._state_by_second(
            shifts, "g", 1, {"1": "home", "2": "away"}, roster)
        self.assertEqual(states, ["5v5"] * data.PERIOD_SECONDS)
        self.assertEqual(ambiguous, [])
        self.assertEqual(anomalies["zero_duration_annotation"], 2)

    def test_positive_interval_without_duration_fails_closed(self):
        shifts, roster = shift_fixture()
        shifts["data"].append({
            "gameId": "g", "period": 1, "startTime": "01:00",
            "endTime": "01:05", "duration": None,
            "playerId": "home-0", "teamId": "1",
        })
        shifts["total"] = len(shifts["data"])
        states, ambiguous, anomalies = data._state_by_second(
            shifts, "g", 1, {"1": "home", "2": "away"}, roster)
        self.assertEqual(states, ["ambiguous"] * data.PERIOD_SECONDS)
        self.assertEqual(len(ambiguous), data.PERIOD_SECONDS)
        self.assertEqual(anomalies["unparseable_duration"], 1)

    def test_same_second_goal_faceoff_is_one_ordered_bundle(self):
        shifts, roster = shift_fixture()
        pbp = {"homeTeam": {"id": 1}, "awayTeam": {"id": 2},
            "rosterSpots": [
                {"playerId": player_id, "teamId": team_id}
                for player_id, (team_id, _) in roster.items()]}
        local = {"event_records": [
            event("goal", 20, side="home"),
            event("faceoff", 20, side="away",
                  details={"winningPlayerId": "away-0"},
                  score_before={"home": 1, "away": 0}),
        ]}
        bundles, excluded = data._make_bundles(local, pbp, "g", 2021, 1, set())
        self.assertEqual(excluded, {})
        self.assertEqual(len(bundles), 1)
        self.assertTrue(bundles[0].eligible)
        self.assertEqual([(token.family, token.owner) for token in bundles[0].mark],
                         [("goal", "home"), ("faceoff", "away")])
        self.assertEqual(bundles[0].context_after.score_diff, 1)
        self.assertTrue(bundles[0].context_after.possession_known)

    def test_penalty_bundle_is_excluded_and_not_relabelled_other(self):
        pbp = {"homeTeam": {"id": 1}, "awayTeam": {"id": 2}, "rosterSpots": []}
        local = {"event_records": [event("penalty", 20, details={"typeCode": "MIN"})]}
        bundles, excluded = data._make_bundles(local, pbp, "g", 2021, 1, set())
        self.assertFalse(bundles[0].eligible)
        self.assertEqual(bundles[0].reason, "penalty_bundle")
        self.assertEqual(bundles[0].mark, ())
        self.assertEqual(excluded["penalty_bundle"], 1)

    def test_gap_crossing_known_manpower_change_is_excluded(self):
        shifts, roster = shift_fixture(missing_home_center=(10, 20))
        pbp = {"homeTeam": {"id": 1}, "awayTeam": {"id": 2},
            "rosterSpots": [
                {"playerId": player_id, "teamId": team_id, "positionCode": position}
                for player_id, (team_id, position) in roster.items()]}
        local = {"event_records": [
            event("faceoff", 1, details={"winningPlayerId": "home-0"}),
            event("shot-on-goal", 25, side="away"),
        ]}
        period = data._period_data("g", 2021, 1, pbp, shifts, local)
        self.assertEqual(period.transitions, [])
        self.assertEqual(period.gap_excluded_counts["interval_not_5v5"], 1)

    def test_period_cache_round_trip_preserves_transition(self):
        period = data.PeriodData("2021020001", 2021, 2)
        period.transitions.append(Transition("2021020001", 2, 18,
            Context("faceoff", True, -1, 1), (Token("shot-on-goal", "away"),)))
        period.eligible_bundle_count = 2
        period.eligible_event_family_counts.update({"faceoff": 1, "shot-on-goal": 1})
        restored = data._period_from_dict(data._period_to_dict(period))
        self.assertEqual(restored.transitions, period.transitions)
        self.assertEqual(restored.eligible_bundle_count, 2)
        self.assertEqual(restored.eligible_event_family_counts,
                         period.eligible_event_family_counts)


if __name__ == "__main__":
    unittest.main()
