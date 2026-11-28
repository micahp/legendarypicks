"""Offline real-fork tests of bounded shared-reference execution."""
import os
import sys
import unittest
from types import SimpleNamespace

from simulate_portable_pack import _seed_results, _seed_result


@unittest.skipUnless(sys.platform == "linux", "Linux fork runtime")
class SharedWorkers(unittest.TestCase):
    def test_same_seed_records_one_inherited_reference_private_writes(self):
        import random
        import time
        ref = {"pool": [{"event": "run"}], "cache": []}
        parent = os.getpid()
        original_identity = id(ref["pool"])

        def run(seed):
            self.assertEqual(id(ref["pool"]), original_identity)
            self.assertEqual(ref["pool"][0]["event"], "run")
            ref["cache"].append(seed)
            time.sleep(0.02)
            return ({"seed": seed, "valid_full_game": True},
                    {"score": random.Random(seed).randrange(1000)},
                    {"pid": os.getpid(), "cache": list(ref["cache"])}, None)

        results = list(_seed_results(range(10, 20), run, workers=3))
        self.assertEqual([r[0]["seed"] for r in results], list(range(10, 20)))
        self.assertEqual(ref["cache"], [])
        self.assertTrue(all(r[2]["pid"] != parent for r in results))
        self.assertGreaterEqual(len({r[2]["pid"] for r in results}), 2)
        for pid in {r[2]["pid"] for r in results}:
            seen = [r[0]["seed"] for r in results if r[2]["pid"] == pid]
            last = [r[2]["cache"] for r in results if r[2]["pid"] == pid][-1]
            self.assertEqual(last, seen)
        self.assertEqual([r[1] for r in results],
                         [r[1] for r in _seed_results(range(10, 20), run, workers=1)])

    def test_first_seed_failure_does_not_launch_rest(self):
        def run(seed):
            return ({"seed": seed, "valid_full_game": False}, None, None, None)
        self.assertEqual([r[0]["seed"] for r in _seed_results(range(10), run, workers=3)], [0])

    def test_failure_drains_only_submitted_wave(self):
        def run(seed):
            return ({"seed": seed, "valid_full_game": seed != 2}, None, None, None)
        self.assertEqual([r[0]["seed"] for r in _seed_results(range(10), run, workers=3)], [0, 1, 2, 3])
        self.assertEqual([r[0]["seed"] for r in _seed_results(range(10), run, workers=1)], [0, 1, 2])
        self.assertEqual([r[0]["seed"] for r in _seed_results(range(10), run, workers=3, research=True)],
                         list(range(10)))

    def test_seed_result_contract_serial_and_fork(self):
        args = SimpleNamespace(with_player_lines=True, records_out=True, decisions_out=True,
                               experimental_profile=None, model="v1")
        ref = {"unchanged": [1]}
        snapshot = {"schedule": {}}
        def play(seed, reference, pregame_snapshot, paired_randomness=False):
            pregame_snapshot["seed"] = seed
            return {"status": "complete", "valid_full_game": True, "complete_game": True,
                    "regulation_end_reached": True, "points": {"A": seed, "B": 0},
                    "stats": {"player": [{"id": "player", "yards": seed}]}}
        gs = SimpleNamespace(play_game=play, validate_game=lambda record: None)
        rng = SimpleNamespace(scheme="v1", paired=False, seed_root=lambda snap: None)
        def run(seed):
            return _seed_result(seed, args, ref, snapshot, gs, None, rng)
        expected = list(_seed_results(range(10, 18), run, workers=1))
        actual = list(_seed_results(range(10, 18), run, workers=2))
        self.assertEqual(expected, actual)
        self.assertEqual(snapshot, {"schedule": {}})
        self.assertEqual(ref, {"unchanged": [1]})
        self.assertEqual(actual[0][1]["players"], [{"id": "player", "yards": 10}])


if __name__ == "__main__":
    unittest.main()
