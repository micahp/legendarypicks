from __future__ import annotations

import collections
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_behavior import _find_penalty_overlaps


def state(code: str, clock: str, event_type: str = "faceoff") -> dict:
    away_goalie, away_skaters, home_skaters, home_goalie = map(int, code)
    return {
        "type": event_type, "period_type": "REG", "period": 1,
        "time": int(clock.split(":")[0]) * 60 + int(clock.split(":")[1]),
        "clock": clock, "event_id": 100 + int(clock.split(":")[1]),
        "code": {"away_goalie": away_goalie, "away_skaters": away_skaters,
                 "home_skaters": home_skaters, "home_goalie": home_goalie},
        "shift_positions_complete": True, "active_duplicate_player_ids": 0,
        "shift_lineup": {
            "home": {"skaters": home_skaters, "goalies": home_goalie, "unknown": 0},
            "away": {"skaters": away_skaters, "goalies": away_goalie, "unknown": 0},
        },
    }


def penalty(team_id: str, clock: str, event_id: int) -> dict:
    return {
        **state("1551", clock, "penalty"), "event_id": event_id,
        "penalty_team_id": team_id,
        "details": {"typeCode": "MIN", "duration": 2,
                    "committedByPlayerId": "unknown"},
    }


class PenaltyOverlapEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sides = {"H": "home", "A": "away"}
        self.stats = {"penalty_classes": collections.Counter(),
                      "penalty_overlap_examples": []}

    def test_faceoff_order_identifies_opposing_active_penalties(self):
        events = [
            state("1551", "05:00"),
            penalty("A", "05:10", 101),
            state("1451", "05:10"),  # away 4, home 5 after the first penalty
            penalty("H", "05:40", 102),
            state("1441", "05:40"),  # immediate restart is 4v4
        ]
        _find_penalty_overlaps(events, "game", self.sides, {}, self.stats)
        self.assertEqual(
            self.stats["penalty_classes"]["faceoff_delimited_5v4_to_4v4_overlap_candidates"], 1)
        example = self.stats["penalty_overlap_examples"][0]
        self.assertEqual(example["preceding_penalty_group"][0]["event_id"], 101)
        self.assertEqual(example["new_penalty_group"][0]["event_id"], 102)
        self.assertEqual(example["observed_state_before_new_penalty"]["situation_code"], "1451")
        self.assertEqual(example["observed_restart_after_new_penalty"]["situation_code"], "1441")

    def test_same_clock_opposing_calls_are_not_assumed_to_be_active_overlap(self):
        events = [
            state("1551", "05:00"),
            penalty("A", "05:10", 101),
            penalty("H", "05:10", 102),
            state("1551", "05:10"),
        ]
        _find_penalty_overlaps(events, "game", self.sides, {}, self.stats)
        self.assertEqual(self.stats["penalty_overlap_examples"], [])
        self.assertEqual(self.stats["penalty_classes"]["same_clock_opposing_record_pairs"], 1)

    def test_goal_before_restart_blocks_overlap_classification(self):
        events = [
            state("1551", "05:00"),
            penalty("A", "05:10", 101),
            state("1451", "05:10"),
            penalty("H", "05:40", 102),
            state("1441", "05:40", "goal"),
            state("1441", "05:40"),
        ]
        _find_penalty_overlaps(events, "game", self.sides, {}, self.stats)
        self.assertEqual(self.stats["penalty_overlap_examples"], [])


if __name__ == "__main__":
    unittest.main()
