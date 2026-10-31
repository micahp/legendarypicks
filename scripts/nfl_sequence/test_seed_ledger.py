import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import simulate_pregame_batch as batch  # noqa: E402

HEADER = {'schema': 'lp-statistical-game-batch-1', 'game_id': 'g1', 'as_of': '2025-10-01T00:00:00Z',
          'source_snapshot_sha256': 'a', 'observed_reference_sha256': 'b', 'context_mode': 'unconditioned',
          'try_policy': 'unconditional', 'safety_kick_table': True, 'seed_start': 1}
OK_RECORD = {'status': 'complete', 'valid_full_game': True, 'complete_game': True, 'points': {'A': 24, 'B': 17},
             'stats': {'player': [{'player_id': 7, 'passing': {'att': 30, 'yds': 250}}]}}


class SeedLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'run.seeds.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def _fresh(self):
        finished, handle = batch._open_seed_ledger(self.path, HEADER, resume=False)
        return handle

    def test_existing_ledger_needs_resume_to_be_reused(self):
        self._fresh().close()
        with self.assertRaises(FileExistsError):
            batch._open_seed_ledger(self.path, HEADER, resume=False)

    def test_new_ledger_has_duplicate_counter_for_boxscore_summary(self):
        finished, handle = batch._open_seed_ledger(self.path, HEADER, resume=False)
        handle.close()
        self.assertIsInstance(finished, batch.FinishedSeeds)
        self.assertEqual(finished.duplicate_rows, 0)

    def test_resume_refuses_a_ledger_from_other_inputs(self):
        self._fresh().close()
        with self.assertRaises(ValueError):
            batch._open_seed_ledger(self.path, dict(HEADER, source_snapshot_sha256='different'), resume=True)

    def test_resume_keeps_the_last_row_for_a_seed(self):
        handle = self._fresh()
        handle.write(json.dumps({'seed': 1, 'outcome': {'seed': 1, 'status': 'simulation_error'},
                                 'players': None}) + '\n')
        handle.write(json.dumps({'seed': 1, 'outcome': {'seed': 1, 'status': 'complete'}, 'players': {}}) + '\n')
        handle.close()
        finished, handle = batch._open_seed_ledger(self.path, HEADER, resume=True)
        handle.close()
        self.assertEqual(finished[1]['outcome']['status'], 'complete')

    def test_resume_rejects_seed_values_that_alias_or_precede_the_requested_seed_range(self):
        for seed in (True, 1.0, 0):
            with self.subTest(seed=seed):
                handle = self._fresh()
                handle.write(json.dumps({'seed': seed, 'outcome': {'seed': seed, 'status': 'complete'},
                                         'players': {}}) + '\n')
                handle.close()
                before = self.path.read_text()
                with self.assertRaisesRegex(ValueError, 'invalid seed'):
                    batch._open_seed_ledger(self.path, HEADER, resume=True)
                self.assertEqual(self.path.read_text(), before)
                self.path.unlink()

    def test_resume_rejects_a_row_whose_outcome_seed_differs_from_its_ledger_seed(self):
        handle = self._fresh()
        handle.write(json.dumps({'seed': 1, 'outcome': {'seed': 2, 'status': 'complete'}, 'players': {}}) + '\n')
        handle.close()
        before = self.path.read_text()

        with self.assertRaisesRegex(ValueError, 'seed mismatch'):
            batch._open_seed_ledger(self.path, HEADER, resume=True)

        self.assertEqual(self.path.read_text(), before)

    def test_resume_rejects_rows_beyond_the_requested_seed_range(self):
        handle = self._fresh()
        handle.write(json.dumps({'seed': 2, 'outcome': {'seed': 2, 'status': 'complete'}, 'players': {}}) + '\n')
        handle.close()
        before = self.path.read_text()

        with self.assertRaisesRegex(ValueError, 'outside requested range \\[1, 2\\)'):
            batch._open_seed_ledger(self.path, HEADER, resume=True, seed_end=2)

        self.assertEqual(self.path.read_text(), before)

    def test_resume_rejects_seed_inside_range_but_outside_explicit_selection(self):
        handle = self._fresh()
        handle.write(json.dumps({'seed': 10, 'outcome': {'seed': 10, 'status': 'complete'},
                                 'players': {}}) + '\n')
        handle.close()
        before = self.path.read_text()

        with self.assertRaisesRegex(ValueError, 'not in the explicit seed selection'):
            batch._open_seed_ledger(self.path, HEADER, resume=True, seed_end=20,
                                     allowed_seeds={2, 19})

        self.assertEqual(self.path.read_text(), before)

    def test_partial_last_line_from_an_interrupted_run_is_dropped(self):
        handle = self._fresh()
        handle.write(json.dumps({'seed': 1, 'outcome': {'seed': 1, 'status': 'complete'}, 'players': None}) + '\n')
        handle.write('{"seed": 2, "outc')
        handle.close()
        finished, handle = batch._open_seed_ledger(self.path, HEADER, resume=True)
        handle.close()
        self.assertEqual(sorted(finished), [1])
        self.assertTrue(self.path.read_text().endswith('\n'))

    def test_simulated_valid_game_contributes_player_totals(self):
        with mock.patch.object(batch.gs, 'play_game', return_value=OK_RECORD), \
                mock.patch.object(batch.gs, 'validate_game'):
            outcome, contribution = batch._simulate_seed(1, None, {})
        self.assertEqual(outcome['status'], 'complete')
        self.assertEqual(contribution['7']['passing.att'], 30)
        self.assertEqual(contribution['7']['rushing.yds'], 0)

    def test_simulation_error_is_a_row_with_no_contribution(self):
        with mock.patch.object(batch.gs, 'play_game', side_effect=RuntimeError('boom')):
            outcome, contribution = batch._simulate_seed(3, None, {})
        self.assertEqual(outcome['status'], 'simulation_error')
        self.assertIn('boom', outcome['error'])
        self.assertIsNone(contribution)

    def test_finished_seed_is_reused_and_errored_seed_is_recomputed(self):
        finished = {
            1: {'seed': 1, 'outcome': {'seed': 1, 'status': 'complete'}, 'players': {}},
            2: {'seed': 2, 'outcome': {'seed': 2, 'status': 'simulation_error'}, 'players': None},
        }
        handle = self._fresh()
        with mock.patch.object(batch.gs, 'play_game', return_value=OK_RECORD) as play, \
                mock.patch.object(batch.gs, 'validate_game'):
            reused, _ = batch._seed_outcome(1, finished, handle, None, {})
            redone, contribution = batch._seed_outcome(2, finished, handle, None, {})
        handle.close()
        self.assertEqual(reused['status'], 'complete')
        self.assertEqual(redone['status'], 'complete')
        self.assertEqual(play.call_count, 1)
        self.assertEqual(contribution['7']['passing.yds'], 250)
        rows = [json.loads(line) for line in self.path.read_text().splitlines()[1:]]
        self.assertEqual([row['seed'] for row in rows], [2])


if __name__ == '__main__':
    unittest.main()
