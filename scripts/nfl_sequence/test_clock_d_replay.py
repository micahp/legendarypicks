"""Tests for the E3 clock replay's training-window guards."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clock_d as cd  # noqa: E402
import e1_drive as e1  # noqa: E402
from clock_d_replay import index_event_runoffs, oob_stop_class_counts, run_a, run_d, validate_training_window  # noqa: E402


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

    def test_indexed_e1_pool_preserves_the_seeded_baseline_replay(self):
        row = {'down': 1, 'ydstogo': 10, 'yardline_100': 50}
        key = (1, e1.e0.ydstogo_bucket(10), e1.e0.yardline_bucket(50))
        pool = {key: [('run', row, 5, 0), ('pass_complete', row, 7, 0), ('run', row, 8, 0)]}
        plays = [{'row': row, 'event': 'run', 'qsr': 30}, {'row': row, 'event': 'pass_complete', 'qsr': 20}]

        self.assertEqual(run_a(plays, pool, seed=17), run_a(plays, index_event_runoffs(pool), seed=17))

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

    def test_oob_class_counts_keep_the_q2_two_minute_and_q4_five_minute_edges(self):
        quarters = {('G1', 2): [
            {'stop': 'oob_snap', 'qsr': 120, 'ended': False, 'event': 'run'},
            {'stop': 'oob_ready', 'qsr': 121, 'ended': False, 'event': 'pass_complete'},
        ], ('G2', 4): [
            {'stop': 'oob_snap', 'qsr': 299, 'ended': False, 'event': 'run'},
            {'stop': 'oob_ready', 'qsr': 300, 'ended': False, 'event': 'pass_complete'},
        ]}

        rows = oob_stop_class_counts(quarters)
        counts = {(row['quarter'], row['clock_bucket_upper_s'], row['policy_window'], row['stop_class']): row['examples']
                  for row in rows}

        self.assertEqual(counts[(2, 120, 'at_or_inside_two_minutes', 'oob_snap')], 1)
        self.assertEqual(counts[(2, 900, 'outside_two_minute_window', 'oob_ready')], 1)
        self.assertEqual(counts[(4, 900, 'inside_final_five_minutes', 'oob_snap')], 1)
        self.assertEqual(counts[(4, 900, 'outside_final_five_minutes', 'oob_ready')], 1)

    def test_q4_long_bucket_reports_exact_clock_windows_on_both_sides_of_300_seconds(self):
        quarters = {('G1', 4): [
            {'stop': 'oob_snap', 'qsr': 299, 'ended': False, 'event': 'pass_complete'},
            {'stop': 'oob_ready', 'qsr': 300, 'ended': False, 'event': 'pass_complete'},
        ]}

        rows = oob_stop_class_counts(quarters)
        by_cell = {(row['policy_window'], row['stop_class']): row for row in rows
                   if row['quarter'] == 4 and row['clock_bucket_upper_s'] == 900 and row['examples']}

        self.assertEqual(by_cell[('inside_final_five_minutes', 'oob_snap')]['clock_window'], '120<clock<300s')
        self.assertEqual(by_cell[('outside_final_five_minutes', 'oob_ready')]['clock_window'], '300-900s')

    def test_oob_runoff_never_uses_generic_clock_pool_when_class_support_is_thin(self):
        model = cd.Model(pool={}, pool_stop={}, pool_all={False: [25] * 50},
                         hazard={}, hazard_bucket={}, flags={}, counts={})

        for stop in ('oob_snap', 'oob_ready'):
            samples, source = model.runoffs('run', stop, False)
            self.assertIsNone(samples)
            self.assertIn('thin out-of-bounds runoff cell', source)

    def test_oob_runoff_may_back_off_to_the_same_stop_class(self):
        same_class = [7] * 50
        model = cd.Model(pool={}, pool_stop={('oob_snap', False): same_class},
                         pool_all={False: [25] * 50}, hazard={}, hazard_bucket={}, flags={}, counts={})

        samples, source = model.runoffs('run', 'oob_snap', False)

        self.assertIs(samples, same_class)
        self.assertEqual(source, 'stop and late')


if __name__ == '__main__':
    unittest.main()
