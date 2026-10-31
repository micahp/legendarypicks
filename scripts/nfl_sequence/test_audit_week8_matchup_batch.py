"""Fixtures for immutable Week 8 batch and player-tail artifact auditing."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_week8_matchup_batch as audit  # noqa: E402


def _boxscore(seed, *, status='valid_complete', reconciliation='passed', carries=0):
    return {
        'schema': 'lp-nfl-slc-boxscore-json-1', 'game_id': '2026_08_TEST', 'seed': seed,
        'model_id': 'SLC_v1_full_stack', 'configuration_hash': 'cfg', 'status': status,
        'reconciliation': {'status': reconciliation},
        'players': [{
            'stable_player_id': 'rb-1', 'name': 'RB One', 'team': 'AAA', 'position': 'RB',
            'rushing': {'att': carries, 'yds': 100 if carries else 0},
            'receiving': {'tgt': 2, 'rec': 1, 'yds': 8},
            'passing': {'att': 0, 'comp': 0, 'yds': 0},
        }],
    }


def _outcome(seed, boxscore, *, valid=True, status='complete_regulation', blocker=None):
    return {
        'seed': seed, 'status': status, 'valid_full_game': valid,
        'complete_game': valid, 'regulation_end_reached': valid,
        'tied_at_regulation_end': False, 'blocker': blocker,
        'boxscore': boxscore,
    }


def _write_worker(root, outcomes, *, requested=2, game_id='2026_08_TEST'):
    directory = Path(root) / 'artifacts' / 'TEST' / 'parallel-6'
    directory.mkdir(parents=True)
    report = {
        'game_id': game_id,
        'simulation': {'requested_games': requested, 'seed_start': 1,
                       'seed_end_inclusive': requested, 'configuration_hash': 'cfg'},
        'boxscore_export': {'enabled': True},
        'summary': {'outcomes': outcomes},
    }
    (directory / 'worker-01.json').write_text(json.dumps(report), encoding='utf-8')
    header = {
        'schema': 'lp.nfl.seed-ledger.v1', 'game_id': game_id, 'seed_start': 1,
        'source_commit': 'a' * 40, 'source_snapshot_sha256': 'b' * 64,
        'playcall_artifact_sha256': 'c' * 64, 'boxscore_export': True,
        'slc_profile': {'configuration_hash': 'cfg'},
    }
    with (directory / 'worker-01.seeds.jsonl').open('w', encoding='utf-8') as handle:
        handle.write(json.dumps({'header': header}) + '\n')
        for outcome in outcomes:
            handle.write(json.dumps({'seed': outcome['seed'], 'outcome': outcome, 'players': {}}) + '\n')
    manifest = {'schema': 'lp-nfl-slc-boxscore-json-1', 'type': 'manifest',
                'game_id': game_id, 'model_id': 'SLC_v1_full_stack', 'configuration_hash': 'cfg'}
    with (directory / 'worker-01.boxscores.jsonl').open('w', encoding='utf-8') as handle:
        handle.write(json.dumps(manifest) + '\n')
        for outcome in outcomes:
            handle.write(json.dumps({'type': 'game', **outcome['boxscore']}) + '\n')


class Week8BatchAudit(unittest.TestCase):
    def test_complete_fixture_preserves_blocked_seed_and_reports_record_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            valid_box = _boxscore(1, carries=46)
            blocked_box = _boxscore(2, status='blocked')
            _write_worker(tmp, [
                _outcome(1, valid_box),
                _outcome(2, blocked_box, valid=False, status='blocked', blocker='thin_pool_cell'),
            ])
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=2, workers=1)
        game = report['matchups'][0]
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(game['accounted_seed_count'], 2)
        self.assertEqual(game['valid_full_games'], 1)
        self.assertEqual(game['reconciled_valid_full_games'], 1)
        self.assertEqual(game['blocked_before_regulation_end'], 1)
        self.assertEqual(game['blocker_counts'], {'thin_pool_cell': 1})
        usage = next(row for row in game['player_distributions'] if row['metric'] == 'rush_attempts')
        self.assertEqual(usage['maximum'], 46)
        self.assertEqual(usage['record_exceedance_seeds'], [1])
        self.assertEqual(game['unresolved_seed_outcomes'][0]['seed'], 2)

    def test_missing_seed_is_explicit_and_batch_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_worker(tmp, [_outcome(1, _boxscore(1))])
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=2, workers=1)
        game = report['matchups'][0]
        self.assertEqual(report['status'], 'incomplete_or_invalid')
        self.assertEqual(game['accounted_seed_count'], 1)
        self.assertTrue(any(row['code'] == 'SEED_COVERAGE_MISMATCH' for row in game['failures']))

    def test_valid_game_with_failed_reconciliation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_box = _boxscore(1, reconciliation='failed')
            _write_worker(tmp, [_outcome(1, bad_box)], requested=1)
            report = audit.audit_batch(Path(tmp), matchups=('TEST',), seed_count=1, workers=1)
        self.assertEqual(report['status'], 'incomplete_or_invalid')
        self.assertTrue(any(row['code'] == 'STAT_ACCOUNTING' for row in report['failures']))

    def test_shard_plan_matches_the_eight_matchup_launcher(self):
        self.assertEqual(audit.seed_partitions(1, 10000, 6), [
            (1, 1667), (1668, 1667), (3335, 1667),
            (5002, 1667), (6669, 1666), (8335, 1666),
        ])


if __name__ == '__main__':
    unittest.main()
