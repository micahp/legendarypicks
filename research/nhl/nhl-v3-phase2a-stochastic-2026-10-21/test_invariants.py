from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "nhl-v3-phase1-replay-2026-10-21"))
sys.path.insert(0, str(HERE))

from prospective import PregameFeature, PregameSnapshot, SimulationRequest  # noqa: E402
from run_phase2a import _accepted_team_goal, _event_elapsed  # noqa: E402
from stochastic_model import (FittedParameters, GOAL_DIMENSIONS, LEVELS,
                              SimulationInvariantError, game_time_level, simulate_game,
                              simulate_many,
                              validate_simulation)  # noqa: E402


def snapshot(game_id: str = "fixture-1") -> PregameSnapshot:
    start = datetime(2026, 10, 21, 18, tzinfo=timezone.utc)
    features = []
    values = {
        "home_attack_sog_per_game": 28.0, "home_attack_sog_n": 10,
        "home_allowed_sog_per_game": 27.0, "home_allowed_sog_n": 10,
        "away_attack_sog_per_game": 27.0, "away_attack_sog_n": 10,
        "away_allowed_sog_per_game": 28.0, "away_allowed_sog_n": 10,
    }
    for key, value in values.items():
        features.append(PregameFeature(key, value, start, "fixture", game_id,
                                       "0" * 64, "ACCEPT"))
    return PregameSnapshot(game_id, start, 1, 2, tuple(features))


def parameters(*, rare_goals: bool = False) -> FittedParameters:
    rate_width = 1 + sum(len(categories) - 1 for _, categories, _ in LEVELS)
    goal_width = 1 + sum(len(categories) - 1 for _, categories, _ in GOAL_DIMENSIONS)
    sog = [0.0] * rate_width
    block = [0.0] * rate_width
    goal = [0.0] * goal_width
    if rare_goals:
        goal[0] = -10.0
    return FittedParameters(
        fit_seasons=(2018, 2019, 2020),
        poisson_coefficients=tuple([0.0] * rate_width),
        sog_logit_coefficients=tuple(sog),
        block_logit_coefficients=tuple(block),
        goal_logit_coefficients=tuple(goal),
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


class SimulationInvariantTests(unittest.TestCase):
    def test_source_time_in_period_is_elapsed_time(self) -> None:
        event = SimpleNamespace(game_id="fixture-1", source_event_id="1", time_in_period="00:00")
        self.assertEqual(_event_elapsed(event, 1200), 0)
        event.time_in_period = "19:59"
        self.assertEqual(_event_elapsed(event, 1200), 1199)
        event.time_in_period = "04:59"
        self.assertEqual(_event_elapsed(event, 300), 299)

    def test_period_and_game_time_features_are_distinct(self) -> None:
        self.assertEqual(game_time_level("P1", 60), "EARLY")
        self.assertEqual(game_time_level("P3", 600), "MIDDLE")
        self.assertEqual(game_time_level("P3", 240), "LATE")
        self.assertEqual(game_time_level("OT", 240), "OVERTIME")

    def test_accepted_team_goal_advances_state_independent_of_shift_quality(self) -> None:
        event = SimpleNamespace(
            period_type="REG", event_type="goal",
            quality=SimpleNamespace(event="ACCEPT", team_count="ACCEPT"),
            shift_disposition="QUARANTINE")
        self.assertTrue(_accepted_team_goal(event, "home"))
        event.quality = SimpleNamespace(event="ACCEPT", team_count="QUARANTINE")
        self.assertFalse(_accepted_team_goal(event, "home"))
        self.assertFalse(_accepted_team_goal(event, None))

    def test_seed_reproduces_identical_event_stream(self) -> None:
        request = SimulationRequest(snapshot(), 404)
        fitted = parameters()
        self.assertEqual(simulate_game(request, fitted), simulate_game(request, fitted))

    def test_different_seeds_generate_different_events(self) -> None:
        fitted = parameters()
        first = simulate_game(SimulationRequest(snapshot(), 404), fitted)
        second = simulate_game(SimulationRequest(snapshot(), 405), fitted)
        self.assertNotEqual(first.events, second.events)

    def test_batch_is_seeded_and_returns_score_distribution_samples(self) -> None:
        fitted = parameters()
        first = simulate_many(snapshot(), fitted, 5, first_seed=500)
        repeated = simulate_many(snapshot(), fitted, 5, first_seed=500)
        self.assertEqual(first, repeated)
        self.assertEqual(len(first), 5)
        self.assertGreater(len({(game.home_final_goals, game.away_final_goals) for game in first}), 1)

    def test_events_reconcile_sog_goals_and_period_totals(self) -> None:
        request = SimulationRequest(snapshot(), 901)
        result = simulate_game(request, parameters())
        validate_simulation(request, result)
        self.assertEqual(result.home_sog + result.away_sog,
                         sum(count for _, count in result.shot_outcomes
                             if _ in {"SAVED", "GOAL"}))
        self.assertEqual(result.home_final_goals + result.away_final_goals,
                         result.home_reg_ot_goals + result.away_reg_ot_goals +
                         int(any(event.event_kind == "SHOOTOUT_GOAL" for event in result.events)))

    def test_corrupt_sog_flag_fails_closed(self) -> None:
        request = SimulationRequest(snapshot(), 901)
        result = simulate_game(request, parameters())
        changed = False
        events = []
        for event in result.events:
            attrs = dict(event.generated_attributes)
            if event.event_kind in {"SHOT_SAVED", "GOAL"} and not changed:
                attrs["counts_as_sog"] = 0
                event = replace(event, generated_attributes=tuple(sorted(attrs.items())))
                changed = True
            events.append(event)
        self.assertTrue(changed)
        with self.assertRaises(SimulationInvariantError):
            validate_simulation(request, replace(result, events=tuple(events)))

    def test_tied_regulation_uses_overtime_then_separate_shootout(self) -> None:
        fitted = parameters(rare_goals=True)
        seen_shootout = False
        for seed in range(80):
            request = SimulationRequest(snapshot(f"fixture-{seed}"), 10000 + seed)
            result = simulate_game(request, fitted)
            kinds = [event.event_kind for event in result.events]
            if "SHOOTOUT_ATTEMPT" in kinds:
                seen_shootout = True
                self.assertIn("OVERTIME_START", kinds)
                self.assertIn("OVERTIME_END", kinds)
                self.assertTrue(all(event.period_type != "SO" for event in result.events
                                    if event.event_kind in {"SHOT_ATTEMPT", "SHOT_SAVED", "GOAL"}))
                break
        self.assertTrue(seen_shootout, "fixture seeds did not exercise the shootout path")


if __name__ == "__main__":
    unittest.main()
