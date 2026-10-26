import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replay_evaluation as evaluation  # noqa: E402


def batch(mode, home, away, p_home, *, valid=100, requested=100, fairness='fair'):
    return {
        'forecast_frozen_at_utc': '2026-10-01T00:00:00Z',
        'simulation': {'context_mode': mode, 'requested_games': requested},
        'source': {'base_commit': 'a' * 40, 'producer_worktree_dirty': False},
        'data_sources': {'source_snapshot_sha256': 'b' * 64,
                         'observed_reference_sha256': 'c' * 64,
                         'input_availability': {'historical_replay_fairness': fairness}},
        'baseline_v1': {'source': 'immutable_locked_v1_projection', 'status': 'available',
                        'comparable_at_snapshot_cutoff': True,
                        'schedule_provenance': {'verified': True},
                        'projected_home_points': 20.0, 'projected_away_points': 17.0,
                        'home_win_probability': 0.6, 'run_id': 'v1-lock', 'locked_at': '2026-10-01T00:00:00Z'},
        'summary': {
            'requested_games': requested, 'valid_full_games': valid,
            'blocked_before_regulation_end': requested - valid,
            'tied_at_regulation_end': 0,
            'valid_full_game_distribution': {
                'sample_games': valid,
                'scores': {'home': {'mean': home}, 'away': {'mean': away}},
                'win_probability': {'home': p_home, 'away': 1 - p_home, 'tie': 0},
            },
            'regulation_end_reached_distribution': {
                'sample_games': requested,
                'scores': {'home': {'mean': home + 1}, 'away': {'mean': away + 1}},
            },
        },
    }


class ReplayEvaluation(unittest.TestCase):
    def test_batch_extractors_retain_coverage_and_require_cutoff_safe_v1(self):
        extracted = evaluation.forecast_from_batch(batch('both', 24.0, 17.0, 0.65, valid=80))
        self.assertEqual(extracted['home_points'], 24.0)
        self.assertEqual(extracted['valid_games'], 80)
        self.assertEqual(extracted['requested_games'], 100)
        self.assertEqual(extracted['home_win_probability'], 0.65)
        baseline = batch('unconditioned', 20, 17, .6)['baseline_v1']
        self.assertEqual(evaluation.forecast_from_v1(baseline)['home_points'], 20.0)
        baseline['status'] = 'exploratory_later_lock'
        self.assertIsNone(evaluation.forecast_from_v1(baseline))

    def test_replay_record_will_not_attach_actuals_before_forecasts_freeze(self):
        runs = {'S0': batch('unconditioned', 20, 17, .6), 'S1': batch('both', 21, 18, .62)}
        with self.assertRaisesRegex(ValueError, 'only after forecasts are frozen'):
            evaluation.replay_record('G1', {'home_points': 20, 'away_points': 17}, runs)
        record = evaluation.replay_record('G1', {'home_points': 20, 'away_points': 17,
                                                  'source': 'test actuals', 'source_sha256': 'd' * 64,
                                                  'attached_at_utc': '2026-10-02T00:00:00Z',
                                                  'attached_after_forecasts_frozen': True}, runs)
        self.assertEqual(record['comparison_status'], 'fair')
        self.assertEqual(record['forecasts']['v1']['run_id'], 'v1-lock')

    def test_actual_attachment_timestamp_must_follow_every_forecast(self):
        runs = {'S0': batch('unconditioned', 20, 17, .6), 'S1': batch('both', 21, 18, .62)}
        actual = {'home_points': 20, 'away_points': 17, 'source': 'test actuals', 'source_sha256': 'd' * 64,
                  'attached_at_utc': '2026-10-01T00:00:00Z', 'attached_after_forecasts_frozen': True}
        with self.assertRaisesRegex(ValueError, 'must be later than the frozen forecasts'):
            evaluation.replay_record('G1', actual, runs)

    def test_metrics_keep_fair_exploratory_and_excluded_games_separate(self):
        rows = []
        for index, status in enumerate(('fair', 'fair', 'exploratory', 'excluded')):
            s0 = evaluation.forecast_from_batch(batch('unconditioned', 20 + index, 17, .6))
            s1 = evaluation.forecast_from_batch(batch('both', 19 + index, 18, .4))
            v1 = {'home_points': 20.0, 'away_points': 17.0, 'home_win_probability': .6}
            rows.append({'game_id': f'G{index}', 'comparison_status': status,
                         'actual': {'home_points': 21, 'away_points': 17},
                         'forecasts': {'S0': s0, 'S1': s1, 'v1': v1},
                         'exclusion_reason': 'unsafe_schedule_version'})
        report = evaluation.evaluate_replays(rows, bootstrap_resamples=100, seed=7)
        self.assertEqual(report['fair_game_count'], 2)
        self.assertEqual(report['exploratory_game_count'], 1)
        self.assertEqual(report['excluded_games'], [{'game_id': 'G3', 'reason': 'unsafe_schedule_version'}])
        fair_s0 = report['fair']['models']['S0']
        self.assertEqual(fair_s0['games'], 2)
        self.assertEqual(fair_s0['valid_seed_coverage']['valid'], 200)
        self.assertEqual(fair_s0['valid_seed_coverage']['requested'], 200)
        self.assertEqual(fair_s0['team_score_mae'], 0.25)
        self.assertEqual(fair_s0['winner_games'], 2)
        self.assertIsNotNone(fair_s0['winner_brier'])
        self.assertIn('team_score_mae', fair_s0['bootstrap_ci95_by_game'])
        self.assertEqual(report['fair']['common_game_ids'], ['G0', 'G1'])
        self.assertEqual(report['fair']['paired_models']['v1']['games'], 2)

    def test_fair_provenance_requires_clean_code_asof_inputs_and_v1_lock(self):
        payload = batch('both', 24, 17, .6)
        payload['data_sources']['input_availability']['historical_replay_fairness'] = 'chronological_filter_only'
        result = evaluation.classify_provenance(payload)
        self.assertEqual(result['status'], 'exploratory')
        self.assertIn('historical_input_availability_unverified', result['reasons'])

    def test_duplicate_game_ids_and_invalid_probabilities_are_rejected(self):
        row = {'game_id': 'G1', 'comparison_status': 'fair', 'actual': {'home_points': 20, 'away_points': 17},
               'forecasts': {'S0': {'home_points': 20, 'away_points': 17, 'home_win_probability': 1.2}}}
        with self.assertRaisesRegex(ValueError, 'between 0 and 1'):
            evaluation.evaluate_replays([row])
        row['forecasts']['S0']['home_win_probability'] = .6
        with self.assertRaisesRegex(ValueError, 'unique game ids'):
            evaluation.evaluate_replays([row, row], bootstrap_resamples=0)

    def test_zero_valid_games_still_count_toward_seed_coverage_and_are_not_scored(self):
        payload = batch('unconditioned', 20, 17, .6, valid=0, requested=20)
        payload['summary']['valid_full_game_distribution'] = {
            'sample_games': 0, 'scores': None, 'win_probability': None,
        }
        forecast = evaluation.forecast_from_batch(payload)
        self.assertIsNone(forecast['home_points'])
        self.assertEqual(forecast['requested_games'], 20)
        row = {'game_id': 'G0', 'comparison_status': 'fair',
               'actual': {'home_points': 20, 'away_points': 17},
               'forecasts': {'S0': forecast,
                             'S1': {'home_points': 22, 'away_points': 18, 'home_win_probability': .7,
                                    'valid_games': 18, 'requested_games': 20},
                             'v1': {'home_points': 20, 'away_points': 17, 'home_win_probability': .6}}}
        report = evaluation.evaluate_replays([row], bootstrap_resamples=0)
        s0 = report['fair']['models']['S0']
        self.assertEqual(s0['valid_seed_coverage'], {'valid': 0, 'requested': 20,
                                                       'rate': 0.0, 'wilson_ci95': [0.0, 0.161125]})
        self.assertEqual(s0['games'], 0)
        self.assertEqual(s0['no_valid_score_forecast_game_ids'], ['G0'])
        self.assertEqual(report['fair']['common_game_ids'], [])

    def test_report_builder_accepts_only_versioned_input_bundles_and_pins_hashes(self):
        actual = {'home_points': 20, 'away_points': 17, 'source': 'official results',
                  'source_sha256': 'd' * 64, 'attached_at_utc': '2026-10-02T00:00:00Z',
                  'attached_after_forecasts_frozen': True}
        bundle = {'schema': 'gridiron.lp-historical-replay-inputs', 'version': 1,
                  'replays': [{'game_id': 'G1', 'actual': actual,
                               'batches': {'S0': batch('unconditioned', 20, 17, .6),
                                           'S1': batch('both', 21, 18, .62)}}]}
        report = evaluation.build_replay_report(bundle, bootstrap_resamples=0, seed=9,
                                                 input_sha256='a' * 64, evaluator_sha256='b' * 64)
        self.assertEqual(report['fair_game_count'], 1)
        self.assertEqual(report['experiment']['input_manifest_sha256'], 'a' * 64)
        self.assertEqual(report['experiment']['evaluator_source_sha256'], 'b' * 64)
        bundle['version'] = 2
        with self.assertRaisesRegex(ValueError, 'schema/version'):
            evaluation.build_replay_report(bundle, bootstrap_resamples=0)


if __name__ == '__main__':
    unittest.main()
