"""Tests for the reusable SLC family runner: plans and commands only, no simulation."""
import json
import tempfile
import unittest
from pathlib import Path

import slc_family_runner as fr

CFG = {
    "out_dir": "/tmp/unused", "db": __file__, "snapshot_dir": "/tmp/unused", "game_glob": "2026_10_*",
    "source_repo": "/tmp/unused",
    "models": [{"name": "v1", "ref": "origin/slc-v1", "extra_args": []},
               {"name": "v2", "ref": "origin/slc-v2", "extra_args": ["--slc-v2", "--rng-protocol", "v2"]}],
    "shared_args": ["--slc-profile", "v1_full_stack", "--progress-every", "250"],
    "blocker_fixes": ["run_scramble_backoff", "safety_free_kick_boundaries"],
    "seeds": {"start": 300001, "total": 1000, "chunk": 250},
    "concurrency": 4,
}


class Command(unittest.TestCase):
    def test_shared_blockers_and_model_extras_are_all_in_the_command(self):
        out = Path("/tmp/x.json")
        v1 = fr.build_command(CFG, CFG["models"][0], "snap.json", 300001, 250, out)
        v2 = fr.build_command(CFG, CFG["models"][1], "snap.json", 300001, 250, out)
        self.assertIn("--slc-profile", v1)
        self.assertNotIn("--slc-v2", v1)
        self.assertIn("--slc-v2", v2)
        self.assertEqual(2, v1.count("--slc-blocker-fix"))
        self.assertEqual(["--games", "250", "--seed-start", "300001"],
                         v1[v1.index("--games"):v1.index("--out")])
        self.assertEqual(["--slc-v2", "--rng-protocol", "v2"], v2[-3:])   # model extras come last


class Plan(unittest.TestCase):
    def test_one_job_per_game_model_and_chunk_and_seeds_add_up(self):
        games = [((("2026-11-19", "20:15")), "g1", Path("a")), (("2026-11-22", "13:00"), "g2", Path("b")),
                 (("2026-11-22", "13:00"), "g3", Path("c"))]
        jobs = fr.plan_jobs(CFG, games)
        self.assertEqual(3 * 2 * 4, len(jobs))
        per = {}
        for name, game, _path, _start, count in jobs:
            per[(name, game)] = per.get((name, game), 0) + count
        self.assertEqual({k: 1000 for k in per}, per)

    def test_only_filters_to_the_named_games(self):
        games = [((("2026-11-19", "20:15")), "g1", Path("a")), (("2026-11-22", "13:00"), "g2", Path("b"))]
        jobs = fr.plan_jobs(CFG, games, only=["g2"])
        self.assertEqual({"g2"}, {j[1] for j in jobs})

    def test_games_come_back_in_kickoff_order(self):
        with tempfile.TemporaryDirectory() as d:
            for name, when in (("2026_10_B_A", ("2026-11-22", "13:00")), ("2026_10_A_B", ("2026-11-19", "20:15"))):
                folder = Path(d) / name
                folder.mkdir()
                (folder / "prospective-1.json").write_text(json.dumps(
                    {"schedule": {"gameday": when[0], "gametime": when[1]}}))
            games = fr.games_in_kickoff_order(d, "2026_10_*")
            self.assertEqual(["2026_10_A_B", "2026_10_B_A"], [g[1] for g in games])


class Pins(unittest.TestCase):
    def test_a_changed_pinned_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            pinned = Path(d) / "kicker.json"
            pinned.write_text("{}")
            cfg = dict(CFG, db=str(pinned), pinned_files=[{"path": str(pinned), "sha256": "0" * 64}])
            with self.assertRaises(ValueError):
                fr.check_pins(cfg)
            cfg["pinned_files"] = [{"path": str(pinned), "sha256": fr.sha256(pinned)}]
            fr.check_pins(cfg)

    def test_config_missing_a_required_key_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            path.write_text(json.dumps({"out_dir": "x"}))
            with self.assertRaises(ValueError):
                fr.load_config(path)


if __name__ == "__main__":
    unittest.main()
