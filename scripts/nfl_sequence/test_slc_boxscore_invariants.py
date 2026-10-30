"""Negative box-score mutations and the mandatory per-seed SLC accounting gate."""
import sys
import unittest
import copy
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import simulate_pregame_batch as batch  # noqa: E402
import slc_outputs as outputs  # noqa: E402
from test_slc_outputs import PROFILE, SNAPSHOT, game_record  # noqa: E402


def build(record, seed=17):
    outcome = {'seed': seed, 'status': 'complete', 'valid_full_game': True,
               'complete_game': True, 'tied_at_regulation_end': False}
    return outputs.build_boxscore(seed, outcome, record, SNAPSHOT, PROFILE)


class BoxscoreHardInvariants(unittest.TestCase):
    def test_batch_seed_outcome_preserves_paired_random_stream_provenance(self):
        record = game_record()
        stream_manifest = {'schema': 'lp.nfl.paired-random-streams.v1', 'root_sha256': 'e' * 64,
                           'snapshot_sha256': SNAPSHOT['snapshot_sha256']}
        record['paired_random_streams'] = stream_manifest
        with patch.object(batch.slc_engine, 'is_slc', return_value=False), \
                patch.object(batch.gs, 'play_game', return_value=record) as play_game, \
                patch.object(batch.gs, 'validate_game'), \
                patch.object(batch.slc_outputs, 'build_boxscore', return_value={
                    'reconciliation': {'status': 'passed'}}):
            outcome, _ = batch._simulate_seed(
                17, object(), SNAPSHOT, PROFILE, export_boxscores=False, paired_randomness=True)

        play_game.assert_called_once()
        self.assertTrue(play_game.call_args.kwargs['paired_randomness'])
        self.assertEqual(outcome['paired_random_streams'], stream_manifest)

    def test_ineligible_frozen_roster_player_cannot_receive_a_target(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['rosters']['home']['players'][1]['roster_eligible'] = False
        record = game_record()

        with patch.object(batch.slc_engine, 'is_slc', return_value=False), \
                patch.object(batch.gs, 'play_game', return_value=record), \
                patch.object(batch.gs, 'validate_game'):
            outcome, contribution = batch._simulate_seed(
                17, object(), snapshot, PROFILE, export_boxscores=False)

        self.assertEqual(outcome['status'], 'validation_error')
        self.assertFalse(outcome['valid_full_game'])
        self.assertIsNone(contribution)
        failure = outcome['assertion_failure']
        self.assertEqual(failure['failure_class'], 'ILLEGAL_STATE')
        self.assertEqual(failure['game_id'], snapshot['schedule']['game_id'])
        self.assertEqual(failure['seed'], 17)
        self.assertIsNone(failure['play_index'])
        self.assertEqual(failure['decision']['participant_id'], 'GA2')
        self.assertEqual(failure['source_artifact_hashes']['snapshot.snapshot_sha256'],
                         snapshot['snapshot_sha256'])

    def test_blocked_game_emits_unresolved_rule_evidence_and_never_contributes(self):
        record = game_record()
        record.update({
            'status': 'blocked', 'blocker': 'blocked_kick_outcome_unresolved',
            'valid_full_game': False, 'complete_game': False,
            'blocked_attempt': {
                'drive_index': 2, 'blocker': 'blocked_kick_outcome_unresolved',
                'state_at_drive_start': {'quarter': 2, 'clock': 300, 'offense': 'A', 'defense': 'B',
                                         'yl': 40, 'down': 4, 'togo': 6},
                'plays_before_block': [],
            },
        })
        with patch.object(batch.slc_engine, 'is_slc', return_value=False), \
                patch.object(batch.gs, 'play_game', return_value=record), \
                patch.object(batch.gs, 'validate_game'):
            outcome, contribution = batch._simulate_seed(17, object(), SNAPSHOT, PROFILE, export_boxscores=False)

        self.assertEqual(outcome['status'], 'blocked')
        self.assertFalse(outcome['valid_full_game'])
        self.assertIsNone(contribution)
        failure = outcome['unresolved_transition']
        self.assertEqual(failure['failure_class'], 'UNSUPPORTED_RULE')
        self.assertEqual(failure['status'], 'unresolved')
        self.assertEqual(failure['game_id'], SNAPSHOT['schedule']['game_id'])
        self.assertEqual(failure['seed'], 17)
        self.assertEqual(failure['state_before'], record['blocked_attempt']['state_at_drive_start'])
        self.assertEqual(failure['outcome']['blocker'], record['blocker'])
        self.assertEqual(failure['source_artifact_hashes']['snapshot.snapshot_sha256'],
                         SNAPSHOT['snapshot_sha256'])

    def test_mutation_completions_over_attempts_and_receptions_over_targets_fails(self):
        record = game_record()
        record['stats']['team']['A']['pass_comp'] = 2
        record['stats']['player'][0]['passing']['comp'] = 2
        record['stats']['player'][1]['receiving']['rec'] = 2

        box = build(record)
        self.assertEqual(box['reconciliation']['status'], 'failed')
        self.assertEqual(box['reconciliation']['failure_class'], 'STAT_ACCOUNTING')
        home = next(row for row in box['reconciliation']['teams'] if row['side'] == 'A')
        self.assertIn('completions_exceed_attempts', home['mismatches'])
        self.assertIn('receptions_exceed_targets', home['mismatches'])

    def test_mutation_turnover_and_game_points_mismatches_fail(self):
        record = game_record()
        record['stats']['team']['A']['points'] = 23
        record['stats']['team']['A']['interceptions'] = 1
        record['stats']['player'][0]['passing']['int'] = 1

        box = build(record)
        self.assertEqual(box['reconciliation']['status'], 'failed')
        self.assertEqual(box['reconciliation']['failure_class'], 'STAT_ACCOUNTING')
        home = next(row for row in box['reconciliation']['teams'] if row['side'] == 'A')
        self.assertIn('team_points_vs_game_points', home['mismatches'])
        self.assertEqual(home['mismatches']['turnovers'], {'players': 1, 'team': 0})

    def test_valid_complete_slc_seed_is_checked_even_without_boxscore_export(self):
        record = game_record()
        valid = {'seed': 17, 'status': 'complete', 'valid_full_game': True,
                 'complete_game': True, 'tied_at_regulation_end': False}
        with patch.object(batch.slc_engine, 'is_slc', return_value=True), \
                patch.object(batch.slc_engine, 'play', return_value=(record, [])), \
                patch.object(batch.gs, 'validate_game'), \
                patch.object(batch, '_record_outcome', return_value=valid.copy()), \
                patch.object(batch.slc_outputs, 'build_boxscore', return_value={
                    'reconciliation': {'status': 'passed'}}) as build_boxscore:
            outcome, contribution = batch._simulate_seed(17, object(), SNAPSHOT, PROFILE, export_boxscores=False)

        build_boxscore.assert_called_once()
        self.assertTrue(outcome['valid_full_game'])
        self.assertNotIn('boxscore', outcome)
        self.assertIsNotNone(contribution)

    def test_failed_per_seed_reconciliation_marks_seed_invalid_and_excludes_it(self):
        record = game_record()
        good = {'seed': 17, 'status': 'complete', 'valid_full_game': True,
                'complete_game': True, 'tied_at_regulation_end': False}
        failed = {'seed': 17, 'status': 'validation_error', 'valid_full_game': False,
                  'complete_game': False, 'tied_at_regulation_end': False}
        with patch.object(batch.slc_engine, 'is_slc', return_value=True), \
                patch.object(batch.slc_engine, 'play', return_value=(record, [])), \
                patch.object(batch.gs, 'validate_game'), \
                patch.object(batch, '_record_outcome', side_effect=[good, failed]), \
                patch.object(batch.slc_outputs, 'build_boxscore', return_value={
                    'reconciliation': {'status': 'failed', 'failure_class': 'STAT_ACCOUNTING'}}) as build_boxscore:
            outcome, contribution = batch._simulate_seed(17, object(), SNAPSHOT, PROFILE, export_boxscores=False)

        build_boxscore.assert_called_once()
        self.assertFalse(outcome['valid_full_game'])
        self.assertIn('STAT_ACCOUNTING', outcome['boxscore_error'])
        failure = outcome['assertion_failure']
        self.assertEqual(failure['failure_class'], 'STAT_ACCOUNTING')
        self.assertEqual(failure['game_id'], SNAPSHOT['schedule']['game_id'])
        self.assertEqual(failure['seed'], 17)
        self.assertIsNone(failure['play_index'])
        self.assertEqual(failure['state_before'], 'game_start')
        self.assertEqual(failure['decision'], 'boxscore_reconciliation')
        self.assertEqual(failure['state_after'], 'game_end')
        self.assertIn('STAT_ACCOUNTING', failure['violated_assertion'])
        self.assertEqual(failure['source_artifact_hashes']['snapshot.snapshot_sha256'],
                         SNAPSHOT['snapshot_sha256'])
        self.assertIsNone(contribution)

    def test_game_validator_failure_is_saved_with_class_and_play_evidence(self):
        record = game_record()
        decisions = [{'intent': 'dropback', 'event': 'pass_complete', 'artifact_sha256': 'a' * 64},
                     {'intent': 'run', 'event': 'punt', 'artifact_sha256': 'a' * 64}]
        with patch.object(batch.slc_engine, 'is_slc', return_value=True), \
                patch.object(batch.slc_engine, 'play', return_value=(record, decisions)), \
                patch.object(batch.gs, 'validate_game', side_effect=AssertionError(
                    'drive 1 play 1 has an illegal clock transition')):
            outcome, contribution = batch._simulate_seed(17, object(), SNAPSHOT, PROFILE, export_boxscores=False)

        self.assertEqual(outcome['status'], 'validation_error')
        self.assertIsNone(contribution)
        failure = outcome['assertion_failure']
        self.assertEqual(failure['failure_class'], 'ILLEGAL_STATE')
        self.assertEqual(failure['game_id'], SNAPSHOT['schedule']['game_id'])
        self.assertEqual(failure['seed'], 17)
        self.assertEqual(failure['play_index'], 1)
        self.assertEqual(failure['decision'], decisions[0])
        self.assertEqual(failure['state_before'], record['drives'][0]['plays'][0]['state_before'])
        self.assertEqual(failure['source_artifact_hashes']['snapshot.snapshot_sha256'], SNAPSHOT['snapshot_sha256'])


if __name__ == '__main__':
    unittest.main()
