import importlib.util
import json
import os
import sqlite3
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("replay_player_models", HERE / "replay-player-models.py")
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class ReplayTests(unittest.TestCase):
    def test_cutoff_excludes_served_week_and_future(self):
        rows = [
            {"game_id": "2026_02_A_B", "p_over": .4, "over": 1, "player_id": 1},
            {"game_id": "2026_09_A_B", "p_over": .4, "over": 1, "player_id": 1},
            {"game_id": "2026_10_A_B", "p_over": .4, "over": 1, "player_id": 1},
            {"game_id": "2026_11_A_B", "p_over": .4, "over": 0, "player_id": 2},
        ]
        self.assertTrue(replay.is_training_week(rows[0]["game_id"]))
        self.assertTrue(replay.is_training_week(rows[1]["game_id"]))
        self.assertFalse(replay.is_training_week(rows[2]["game_id"]))
        self.assertFalse(replay.is_training_week(rows[3]["game_id"]))
        self.assertEqual(2, sum(replay.is_training_week(r["game_id"]) for r in rows))

    def test_player_identity_join_matches_preserved_roster(self):
        db_path = Path(os.environ.get("LP_REPLAY_TEST_DB", "/root/legendarypicks/backend/data/picks.dev.db"))
        con = sqlite3.connect("file:%s?mode=ro" % db_path.resolve(), uri=True)
        roster = replay.roster_players(HERE / "evidence/full-depth-roster.json", con)
        self.assertGreater(len(roster), 0)
        self.assertEqual(len(roster), len({p["gsis"] for p in roster.values()}))
        self.assertTrue(all(p["team"] in ("WSH", "NYG") for p in roster.values()))
        con.close()

    def test_loaded_forecast_history_stops_at_week_nine(self):
        db_path = Path(os.environ.get("LP_REPLAY_TEST_DB", "/root/legendarypicks/backend/data/picks.dev.db"))
        con = sqlite3.connect("file:%s?mode=ro" % db_path.resolve(), uri=True)
        snapshot = json.loads((HERE / "evidence/finalized-snapshot.json").read_text())
        roster = replay.roster_players(HERE / "evidence/full-depth-roster.json", con)
        history = replay.make_history(con, HERE / "evidence/injuries_2026.parquet", roster, snapshot)
        self.assertLessEqual(history.max_target_history_week, 9)
        self.assertFalse(any(r.season == 2026 and r.week >= 10 for r in history.rows))
        self.assertTrue(history.status)
        con.close()

    def test_grading_uses_strict_over_threshold(self):
        draws = [(2,), (3,), (4,), (5,)]
        self.assertEqual(.5, replay.p_over(draws, 0, 3.5))
        self.assertEqual(.25, replay.p_over(draws, 0, 4.0))

    def test_calibration_fit_uses_only_pre_serve_weeks(self):
        rows = []
        for i in range(210):
            rows.append({"game_id": "2026_09_A_B", "player_id": i, "p_over": .6, "over": 1})
        rows.extend([
            {"game_id": "2026_10_A_B", "player_id": 211, "p_over": .01, "over": 0},
            {"game_id": "2026_11_A_B", "player_id": 212, "p_over": .99, "over": 1},
        ])
        fit = replay.fit_forward_platt(rows)
        self.assertEqual(210, fit[2])
        self.assertEqual(210, fit[3])

    def test_spec_b_draws_are_reproducible(self):
        seed1 = replay.model_seed(replay.GAME_ID, 1234, "rec")
        seed2 = replay.model_seed(replay.GAME_ID, 1234, "rec")
        self.assertEqual(seed1, seed2)
        first = replay.eng.simulate(5, .65, 10, .05, n=80, seed=seed1)
        second = replay.eng.simulate(5, .65, 10, .05, n=80, seed=seed2)
        self.assertEqual(first, second)

    def test_manifest_input_hashes_match_frozen_snapshot(self):
        snap = json.loads((HERE / "evidence/finalized-snapshot.json").read_text())
        self.assertEqual(snap["roster_snapshot_source"]["full_depth_roster_sha256"],
                         replay.sha256(HERE / "evidence/full-depth-roster.json"))
        injury = next(f for f in snap["capture"]["files"] if f["name"] == "injuries_2026.parquet")
        self.assertEqual(injury["sha256"], replay.sha256(HERE / "evidence/injuries_2026.parquet"))


if __name__ == "__main__":
    unittest.main()
