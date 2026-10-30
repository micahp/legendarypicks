"""Deterministic coordinate tests for paired-seed ablation streams."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paired_random_streams import PairedRandomStreams


class PairedRandomStreamTests(unittest.TestCase):
    def test_same_seed_snapshot_and_draw_coordinate_replay_exactly(self):
        left = PairedRandomStreams(73, 'a' * 64)
        right = PairedRandomStreams(73, 'a' * 64)
        self.assertEqual(left.manifest(), right.manifest())
        self.assertEqual(left.key('e1_playcall', 2, 19), right.key('e1_playcall', 2, 19))
        left_draws = left.rng('e1_playcall', 2, 19)
        right_draws = right.rng('e1_playcall', 2, 19)
        self.assertEqual([left_draws.random() for _ in range(4)], [right_draws.random() for _ in range(4)])

    def test_seed_snapshot_and_semantic_draw_site_are_part_of_the_key(self):
        baseline = PairedRandomStreams(73, 'a' * 64)
        self.assertNotEqual(baseline.key('e1_playcall', 2, 19), baseline.key('special_teams', 2, 19))
        self.assertNotEqual(baseline.key('e1_playcall', 2, 19), baseline.key('e1_playcall', 2, 20))
        self.assertNotEqual(baseline.key('e1_playcall', 2, 19),
                            PairedRandomStreams(74, 'a' * 64).key('e1_playcall', 2, 19))
        self.assertNotEqual(baseline.key('e1_playcall', 2, 19),
                            PairedRandomStreams(73, 'b' * 64).key('e1_playcall', 2, 19))

    def test_invalid_seed_and_missing_snapshot_hash_fail_closed(self):
        for seed, snapshot_hash in ((True, 'a' * 64), (1.5, 'a' * 64)):
            with self.subTest(seed=seed, snapshot_hash=snapshot_hash), self.assertRaises(TypeError):
                PairedRandomStreams(seed, snapshot_hash)
        for snapshot_hash in (None, 'not-a-hash', 'g' * 64):
            with self.subTest(snapshot_hash=snapshot_hash), self.assertRaises(ValueError):
                PairedRandomStreams(1, snapshot_hash)


if __name__ == '__main__':
    unittest.main()
