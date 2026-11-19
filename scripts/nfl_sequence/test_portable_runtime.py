"""Offline integration test: execute only code and state carried in a pack."""
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from portable_model_pack import write_pack
import simulate_portable_pack
from slc_model_registry import get_model


class PortableRuntime(unittest.TestCase):
    def test_bundled_engine_runs_with_db_and_tables_blocked(self):
        model = get_model("v1")
        reference = SimpleNamespace(
            pool={(1, 2, 3): [("run", {"play_id": "p1"}, 3, 10)]},
            kickoff_pool=[{"spot": 70}],
            kicks={"field_goal": [1], "field_goal_outcomes": {"short": (1, 1, 0)},
                   "extra_point": [1], "two_point": [1]},
            participants={("g", "p"): {}},
            missed_field_goal_pool={"short": [{"spot_adjustment_yards": 0}]},
            safety_kick_pool=[{"spot": 40}], overtime_pool=[{"winning_drive": True}],
            overtime_try_p_two={key: 0.05 for key in ("<=-9", "-8..-5", "-4..-1", "0", "1..4", "5..8", ">=9")},
            overtime_p_kick=0.0,
            blocked_kicks={"rates": {"punt_blocked": {"rate": 0.01},
                                      "field_goal_blocked_by_snap_bucket": {"short": {"rate": 0.01}}},
                           "records": {"punt": [], "field_goal": []}},
            model_inputs={"sha256": "f" * 64},
            contextual_sampler=SimpleNamespace(current_streak={"OLD": "W1"}, side_teams=None))
        snapshot = {"snapshot_sha256": "a" * 64, "as_of": "2026-11-18T22:00:00Z",
                    "verified": False, "verification_status": "incomplete_evidence",
                    "model_reference": {},
                    "schedule": {"game_id": "2026_11_IND_HOU", "season": 2026, "week": 11,
                                 "home_team": "IND", "away_team": "HOU"},
                    "rosters": {"home": {}, "away": {}}}
        engine_files = {
            "scripts/nfl_sequence/game_state.py": (
                "def play_game(seed, ref, pregame_snapshot=None):\n"
                "    assert ref.contextual_sampler.current_streak == {'NYG': 'W3', 'DAL': 'L2'}\n"
                "    return {'status': 'complete', 'blocker': None, 'valid_full_game': True,\n"
                "            'complete_game': True, 'regulation_end_reached': True,\n"
                "            'points': {'A': 10, 'B': 7}, 'stats': {'player': []},\n"
                "            'drives': [], 'kickoffs': [], 'boundaries': [], 'ledger': [],\n"
                "            'overtime': {'regulation_points': {'A': 7, 'B': 7}}, 'tied': False}\n"
                "def validate_game(record):\n    return None\n"
            ).encode(),
            "scripts/nfl_sequence/pregame_batch.py": (
                "def summarize_outcomes(rows, requested):\n"
                "    return {'valid_full_games': sum(row['valid_full_game'] for row in rows)}\n"
            ).encode(),
            "scripts/nfl_sequence/pregame_snapshot.py": (
                "import json\n"
                "def load_frozen_snapshot(path):\n"
                "    with open(path) as handle:\n        return json.load(handle)\n"
            ).encode(),
            "scripts/nfl_sequence/slc_engine.py": (
                "def is_slc(reference): return True\n"
                "def side_teams(snapshot): return {'A': snapshot['schedule']['home_team'], 'B': snapshot['schedule']['away_team']}\n"
                "def play(seed, reference, snapshot):\n"
                "    import game_state\n"
                "    return game_state.play_game(seed, reference, snapshot), []\n"
            ).encode(),
            "scripts/nfl_sequence/streak_splits.py": (
                "BUCKETS = ('L5+', 'L4', 'L3', 'L2', 'L1', 'NONE', 'W1', 'W2', 'W3', 'W4', 'W5+')\n"
            ).encode(),
            "scripts/nfl_sequence/nfl_team_codes.py": (
                "def to_pbp_team_code(team): return team\n"
            ).encode(),
        }
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            pack_path = root / "v1.slcpkg"
            pack = write_pack(pack_path, reference=reference, snapshot=snapshot,
                              model_id="v1", code_commit=model["code_commit"],
                              engine_files=engine_files,
                              config={"training_cutoff": {"eligible_before": [2026, 1]},
                                      "enabled_layers": ["current_streak_context"]})
            report_path, records_path = root / "run.json", root / "records.jsonl"
            runtime_snapshot = {**snapshot, "snapshot_sha256": "b" * 64,
                                "schedule": {"game_id": "2026_12_NYG_DAL", "season": 2026, "week": 12,
                                             "home_team": "NYG", "away_team": "DAL"},
                                "rosters": {"home": {"updated": True}, "away": {}},
                                "model_reference": {"current_streak_context": {
                                    "schema": "lp-slc-current-streak-context-1",
                                    "game_id": "2026_12_NYG_DAL",
                                    "cutoff_utc": "2026-11-18T22:00:00Z",
                                    "source_cutoff_utc": "2026-11-18T21:59:00Z",
                                    "teams": {"NYG": "W3", "DAL": "L2"},
                                    "source_sha256": "c" * 64,
                                }}}
            snapshot_path = root / "pregame.json"
            snapshot_path.write_text(json.dumps(runtime_snapshot))
            status = simulate_portable_pack.main([
                "--model", "v1", "--game", "2026_12_NYG_DAL",
                "--pack", str(pack_path), "--pack-sha256", pack["sha256"],
                "--snapshot", str(snapshot_path),
                "--games", "2", "--seed-start", "51", "--out", str(report_path),
                "--records-out", str(records_path),
            ])
            report = json.loads(report_path.read_text())
            rows = [json.loads(line) for line in records_path.read_text().splitlines()]
            self.assertEqual(status, 0)
            self.assertEqual(report["simulation"]["valid_full_games"], 2, {"report": report, "rows": rows})
            self.assertEqual(report["snapshot_sha256"], "b" * 64)
            self.assertEqual(report["game_id"], "2026_12_NYG_DAL")
            self.assertEqual(report["simulation"]["valid_full_games"], 2)
            self.assertEqual([row["seed"] for row in rows], [51, 52])
            self.assertEqual(rows[0]["record"]["points"], {"A": 10, "B": 7})
            self.assertEqual(report["regulation_end_diagnostics"]["games_tied_at_regulation_end"], 2)
            self.assertEqual(report["regulation_end_diagnostics"]["regulation_scores_by_seed"][0],
                             {"seed": 51, "home_points": 7, "away_points": 7})
            # Incomplete snapshot evidence does not invalidate completed game results.
            self.assertEqual(report["simulation"]["valid_full_games"], 2)
            with self.assertRaises(RuntimeError):
                sqlite3.connect(":memory:")
            with self.assertRaisesRegex(RuntimeError, "PORTABLE_RUNTIME_SOURCE_FILE_ACCESS"):
                open(root / "research.csv", "r")


if __name__ == "__main__":
    unittest.main()
