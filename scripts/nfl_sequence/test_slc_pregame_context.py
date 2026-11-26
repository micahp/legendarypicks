import json
import tempfile
import unittest
from pathlib import Path

from slc_pregame_context import (
    freeze_current_streak_context,
    freeze_current_streak_model_inputs,
    current_streaks_for_snapshot,
)


class StreakContext(unittest.TestCase):
    class TeamCodes:
        @staticmethod
        def to_pbp_team_code(team):
            return {"JAC": "JAX"}.get(team, team)

        @staticmethod
        def to_nflverse_team_code(team):
            return {"JAC": "JAX", "JAX": "JAX"}.get(team, team)

    class StreakSplits:
        BUCKETS = ("L5+", "L4", "L3", "L2", "L1", "NONE", "W1", "W2", "W3", "W4", "W5+")

        @staticmethod
        def bucket_from_text(value):
            return value if value in StreakContext.StreakSplits.BUCKETS else None

    def test_freezes_separate_per_game_streaks_and_reads_the_new_game_values(self):
        snapshot = {
            "as_of": "2026-11-19T00:00:00Z",
            "schedule": {"game_id": "game-two", "home_team": "NYG", "away_team": "JAC"},
            "model_reference": {},
        }
        payload = {"game_id": "game-two", "cutoff_utc": snapshot["as_of"],
                   "teams": {"NYG": {"streak": "W3"}, "JAX": {"streak": "L2"},
                             "ARI": {"streak": "not-a-bucket"}}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "streaks.json"
            path.write_text(json.dumps(payload))
            self.freeze(path, snapshot)
            model_inputs = freeze_current_streak_model_inputs(path, snapshot, self.StreakSplits, self.TeamCodes)
        self.assertEqual(current_streaks_for_snapshot(snapshot, self.TeamCodes, self.StreakSplits, model_inputs),
                         {"NYG": "W3", "JAX": "L2", "ARI": None})

    def test_rejects_streaks_from_another_game(self):
        snapshot = {
            "as_of": "2026-11-19T00:00:00Z",
            "schedule": {"game_id": "game-two", "home_team": "NYG", "away_team": "DAL"},
        }
        payload = {"game_id": "game-one", "cutoff_utc": snapshot["as_of"],
                   "teams": {"NYG": {"streak": "W3"}, "DAL": {"streak": "L2"}}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "streaks.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "CURRENT_STREAK_GAME_ID_MISMATCH"):
                self.freeze(path, snapshot)

    def test_model_input_must_be_frozen_and_hash_validated(self):
        snapshot = {
            "as_of": "2026-11-19T00:00:00Z",
            "schedule": {"game_id": "game-two", "home_team": "NYG", "away_team": "DAL"},
            "model_reference": {"current_streak_context": {
                "schema": "lp-slc-current-streak-context-1", "game_id": "game-two",
                "cutoff_utc": "2026-11-19T00:00:00Z", "source_cutoff_utc": "2026-11-19T00:00:00Z",
                "source_sha256": "a" * 64}},
        }
        with self.assertRaisesRegex(ValueError, "RUNTIME_CURRENT_STREAK_MODEL_INPUT_MISSING"):
            current_streaks_for_snapshot(snapshot, self.TeamCodes, self.StreakSplits)
        with self.assertRaisesRegex(ValueError, "RUNTIME_CURRENT_STREAK_MODEL_INPUT_HASH_MISMATCH"):
            current_streaks_for_snapshot(snapshot, self.TeamCodes, self.StreakSplits, {
                "schema": "lp-slc-runtime-model-inputs-1", "current_streak": {},
                "source_sha256": "a" * 64, "sha256": "b" * 64,
            })

    def test_accepts_cutoff_pinned_team_wide_streak_artifact(self):
        snapshot = {
            "as_of": "2026-11-19T00:02:00Z",
            "schedule": {"game_id": "game-two", "home_team": "NYG", "away_team": "JAC"},
        }
        payload = {"as_of_utc": "2026-11-19T00:00:00Z",
                   "teams": {"NYG": {"streak": "W3"}, "JAX": {"streak": "L2"}}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "streaks.json"
            path.write_text(json.dumps(payload))
            self.freeze(path, snapshot)
            model_inputs = freeze_current_streak_model_inputs(path, snapshot, self.StreakSplits, self.TeamCodes)
        context = snapshot["model_reference"]["current_streak_context"]
        self.assertEqual(context["source_cutoff_utc"], "2026-11-19T00:00:00Z")
        self.assertEqual(current_streaks_for_snapshot(snapshot, self.TeamCodes, self.StreakSplits, model_inputs),
                         {"NYG": "W3", "JAX": "L2"})

    def freeze(self, path, snapshot):
        freeze_current_streak_context(path, snapshot, self.StreakSplits, self.TeamCodes)


if __name__ == "__main__":
    unittest.main()
