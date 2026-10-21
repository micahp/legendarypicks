from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PHASE1 = HERE.parent / "nhl-v3-phase1-replay-2026-10-21"
PHASE2A = HERE.parent / "nhl-v3-phase2a-stochastic-2026-10-21"
sys.path.insert(0, str(PHASE1))
sys.path.insert(0, str(PHASE2A))
sys.path.insert(0, str(HERE))

import stochastic_model
import run_phase2b as phase2b
from prospective import PregameFeature, PregameSnapshot, SimulationRequest
from scoring_experiments import ExperimentParameters, use_context_location_builder
from stochastic_model import FittedParameters, GOAL_DIMENSIONS, LEVELS, state_key


def snapshot(game_id="phase2b-test"):
    start = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
    values = {
        "home_attack_sog_per_game": 28.0,
        "home_attack_sog_n": 10,
        "home_allowed_sog_per_game": 27.0,
        "home_allowed_sog_n": 10,
        "away_attack_sog_per_game": 27.0,
        "away_attack_sog_n": 10,
        "away_allowed_sog_per_game": 28.0,
        "away_allowed_sog_n": 10,
    }
    features = tuple(PregameFeature(
        key, value, start, "fixture", game_id, "0" * 64, "ACCEPT")
        for key, value in values.items())
    return PregameSnapshot(game_id, start, 1, 2, features)


def parameters():
    rate_width = 1 + sum(len(categories) - 1 for _, categories, _ in LEVELS)
    goal_width = 1 + sum(len(categories) - 1 for _, categories, _ in GOAL_DIMENSIONS)
    return FittedParameters(
        fit_seasons=(2018, 2019, 2020),
        poisson_coefficients=tuple([0.0] * rate_width),
        sog_logit_coefficients=tuple([0.0] * rate_width),
        block_logit_coefficients=tuple([0.0] * rate_width),
        goal_logit_coefficients=tuple([0.0] * goal_width),
        baseline_attempt_rate_per_minute=1.0,
        baseline_outcome_probabilities=(0.25, 0.25, 0.25, 0.25),
        penalty_rate_per_minute=0.002,
        shootout_goal_probability=0.35,
        sog_reference=27.5,
        rate_dimensions=LEVELS,
        goal_dimensions=GOAL_DIMENSIONS,
        location_pool=((89.0, 0.0, "WRIST", "EVEN"),),
        location_pools=(("EVEN", ((89.0, 0.0, "WRIST", "EVEN"),)),),
    )


class ScoringExperimentTests(unittest.TestCase):
    def test_conversion_offset_changes_goals_without_changing_on_target_probability(self):
        request_snapshot = snapshot()
        base = parameters()
        adjusted = ExperimentParameters.from_base(base, global_goal_logit_shift=0.6)
        args = dict(side="home", period="P1", strength="EVEN", score_difference=0,
                    remaining=1200, location_x=89.0, location_y=0.0,
                    shot_type="WRIST", conditional=True)
        base_probabilities = base.outcome_probabilities(request_snapshot, **args)
        adjusted_probabilities = adjusted.outcome_probabilities(request_snapshot, **args)
        self.assertAlmostEqual(sum(adjusted_probabilities), 1.0)
        self.assertAlmostEqual(sum(base_probabilities[2:]), sum(adjusted_probabilities[2:]))
        self.assertGreater(adjusted_probabilities[3], base_probabilities[3])
        self.assertLess(adjusted_probabilities[2], base_probabilities[2])

    def test_game_seed_reproduces_adjusted_scoring_events_and_accounting(self):
        base = parameters()
        adjusted = ExperimentParameters.from_base(base, global_goal_logit_shift=-0.3)
        request = SimulationRequest(snapshot(), 404)
        first = stochastic_model.simulate_game(request, adjusted)
        second = stochastic_model.simulate_game(request, adjusted)
        self.assertEqual(first, second)
        stochastic_model.validate_simulation(request, first)
        self.assertEqual(first.home_sog + first.away_sog,
                         sum(count for label, count in first.shot_outcomes
                             if label in {"SAVED", "GOAL"}))

    def test_state_builder_matches_phase2a_when_context_pools_are_empty(self):
        base = parameters()
        adjusted = ExperimentParameters.from_base(base)
        request = SimulationRequest(snapshot(), 7001)
        expected = stochastic_model.simulate_game(request, base)
        with use_context_location_builder():
            actual = stochastic_model.simulate_game(request, adjusted)
        self.assertEqual(expected, actual)

    def test_context_pool_uses_pregame_group_and_generated_score_state(self):
        base = parameters()
        request_snapshot = snapshot()
        key = state_key(request_snapshot, base, side="home", period="P1",
                        strength="EVEN", score_difference=0, remaining=1200)
        attack = key[6]
        location = (75.0, 3.0, "SNAP", "EVEN")
        adjusted = ExperimentParameters.from_base(
            base,
            state_location_pools={("EVEN", "P1", "TIED", "EARLY", attack): (location,)})
        selected = adjusted.sample_location_context(
            __import__("random").Random(13), "EVEN", period="P1",
            score_difference=0, remaining=1200, snapshot=request_snapshot, side="home")
        self.assertEqual(selected, location[:3])

    def test_future_feature_is_rejected_at_pregame_boundary(self):
        original = snapshot()
        future = PregameFeature("goal_conversion_logit_shift_home", 0.2,
                                datetime(2026, 10, 22, tzinfo=timezone.utc),
                                "fixture", original.game_id, "1" * 64, "ACCEPT")
        with self.assertRaises(ValueError):
            replace(original, features=original.features + (future,))

    def test_variant_checkpoint_is_reused_after_successful_validation(self):
        game = type("Game", (), {"definition": type("Definition", (), {
            "game_id": "cache-test"})()})()
        metrics = {"validated_simulations": 2, "score": 1.25}
        traces = {"cache-test": [{"goals": 1}, {"goals": 2}]}
        with TemporaryDirectory() as directory, patch.object(
                phase2b, "_run_simulation_variant", return_value=(metrics, traces)) as run:
            first = phase2b._run_cached_simulation_variant(
                Path(directory), "f" * 64, "cache test", [game], parameters(), 2, 11)
            second = phase2b._run_cached_simulation_variant(
                Path(directory), "f" * 64, "cache test", [game], parameters(), 2, 11)
        self.assertEqual(first, second)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
