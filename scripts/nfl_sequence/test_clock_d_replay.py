"""Tests for the E3 clock replay's training-window guards."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clock_d as cd  # noqa: E402
from clock_d_replay import run_d, validate_training_window  # noqa: E402


class TrainingWindow(unittest.TestCase):
    def test_multiseason_training_window_can_precede_2025_evaluation(self):
        window = (2022, 2024, 1, 18)
        self.assertEqual(validate_training_window(window, (2025, 1)), window)

    def test_training_window_cannot_include_the_sealed_2026_season(self):
        with self.assertRaisesRegex(ValueError, '2022-2025'):
            validate_training_window((2022, 2026, 1, 18), (2027, 1))

    def test_training_must_precede_a_full_evaluation_window(self):
        with self.assertRaisesRegex(ValueError, 'end before the evaluation'):
            validate_training_window((2022, 2025, 1, 18), (2025, 1))

    def test_explicit_held_out_games_may_share_a_season_with_training(self):
        window = (2022, 2022, 1, 5)
        self.assertEqual(validate_training_window(window, (2022, 1), evaluation_games=('G1',)), window)

    def test_weeks_must_be_in_the_regular_season(self):
        with self.assertRaisesRegex(ValueError, 'weeks must be ordered'):
            validate_training_window((2022, 2022, 0, 5), (2025, 1))

    def test_replay_uses_the_simulated_clock_for_stop_class(self):
        model = cd.Model(
            pool={
                ('run', 'clock_runs', False): [25] * 50,
                ('run', 'oob_snap', False): [5] * 50,
            },
            pool_stop={},
            pool_all={},
            hazard={('clock_runs', 900): (0, 50), ('oob_snap', 900): (0, 50)},
            hazard_bucket={},
            flags={('G1', 2): (1, 0)},
            counts={},
        )
        plays = [
            {'row': {'game_id': 'G1', 'play_id': 1}, 'event': 'run', 'terminal': None,
             'qtr': 4, 'qsr': 320},
            {'row': {'game_id': 'G1', 'play_id': 2}, 'event': 'run', 'terminal': None,
             'qtr': 4, 'qsr': 320},
        ]

        result = run_d(plays, model, seed=7)

        self.assertEqual(result['draws'], [(0, 25, 'clock_runs'), (1, 5, 'oob_snap')])


if __name__ == '__main__':
    unittest.main()
