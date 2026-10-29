import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import run_slc_archival_comparison as comparison  # noqa: E402
import slc_config  # noqa: E402


class ArchivalComparisonContract(unittest.TestCase):
    def test_primary_population_is_exactly_the_28_locked_week5_to_week7_games(self):
        matrix = REPO / 'docs/research/slc-week1-7-readiness-2026-10-29/readiness_matrix.csv'
        candidates, classes = comparison._primary_candidates(matrix)
        self.assertEqual(classes, {'cutoff-valid': 28, 'exploratory reconstruction': 51, 'refused': 28})
        self.assertEqual(len(candidates), 28)
        self.assertEqual({row['week'] for row in candidates}, {'5', '6', '7'})
        self.assertTrue(all(row['readiness_class'] == 'cutoff-valid' for row in candidates))
        self.assertTrue(all(row['cutoff_basis'] == 'recorded LP lock' for row in candidates))

    def test_smoke_gate_compares_every_profile_layer_including_disabled_fixed_shares(self):
        expected = comparison._required_full_stack_layers()
        self.assertEqual(set(expected), set(slc_config.ENGINE_LAYER_KEYS))
        self.assertEqual(len(comparison.RUNTIME_FIELDS), len(slc_config.ENGINE_LAYER_KEYS) - 1)
        self.assertFalse(expected['fixed_player_target_carry_shares'])
        self.assertTrue(all(expected[name] for name in comparison.RUNTIME_FIELDS))

    def test_full_stack_arms_reuse_shared_frame_cache(self):
        cache = Path('/tmp/shared-playcall-frame.npz')
        args = SimpleNamespace(
            readiness_matrix=Path('/matrix.csv'), archive_manifest=Path('/archive.json'),
            archive_root=Path('/archive'), slc_profile='v1_full_stack', games=2, seed_start=1,
            db=Path('/db.sqlite'), frame_cache=cache, resume=False, artifact=Path('/artifact.json'),
        )
        row = {'game_id': '2026_05_AAA_BBB'}
        slc_command, _ = comparison._command_for(args, Path('/phase'), row, 'SLC_v1_full_stack', Path('/snap.json'))
        s0_command, _ = comparison._command_for(args, Path('/phase'), row, 'S0', Path('/snap.json'))
        self.assertEqual(slc_command.count(str(cache)), 2)
        self.assertIn('--playcall-point-splits-cache', slc_command)
        self.assertIn('--playcall-streak-cache', slc_command)
        self.assertNotIn(str(cache), s0_command)

    def test_interrupt_stops_child_and_records_checkpoint(self):
        class Child:
            def __init__(self):
                self.stdout = io.StringIO('')
                self.return_code = None
                self.terminated = False

            def poll(self):
                return self.return_code

            def terminate(self):
                self.terminated = True
                self.return_code = -15

            def wait(self, timeout=None):
                return self.return_code

        child = Child()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(comparison.subprocess, 'Popen', return_value=child), \
                    mock.patch.object(comparison.queue.Queue, 'get', side_effect=KeyboardInterrupt):
                code, _elapsed = comparison._run_command(
                    ['fake'], log_path=root / 'child.log', label='test', progress_path=root / 'progress.jsonl')
            events = [json.loads(line) for line in (root / 'progress.jsonl').read_text().splitlines()]
        self.assertEqual(code, 130)
        self.assertTrue(child.terminated)
        self.assertEqual(events[-1]['event'], 'command_interrupted')


if __name__ == '__main__':
    unittest.main()
