"""Offline integration test: execute only code and state carried in a pack."""
import json
import os
import subprocess
import sys
import hashlib
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from portable_model_pack import write_pack
import simulate_portable_pack
from slc_model_registry import get_model


def _run_main_isolated(argv, probe_file=None):
    """Run simulate_portable_pack.main in a fresh interpreter. The runtime guard it installs is process-wide, so each run
    gets its own process. Returns 0. Raises with the child's stderr when it fails.

    With probe_file, the child also checks that the guard refuses a database connection and a source-file read."""
    probe = ""
    if probe_file is not None:
        probe = ("import sqlite3\n"
                 "try:\n    sqlite3.connect(':memory:')\nexcept RuntimeError:\n    pass\n"
                 "else:\n    sys.exit(3)\n"
                 "try:\n    open(sys.argv[2], 'r')\nexcept RuntimeError as exc:\n"
                 "    assert 'PORTABLE_RUNTIME_SOURCE_FILE_ACCESS' in str(exc)\n"
                 "else:\n    sys.exit(4)\n")
    code = ("import json, sys\n"
            "import simulate_portable_pack as m\n"
            "status = m.main(json.loads(sys.argv[1]))\n" + probe + "sys.exit(status)\n")
    here = str(Path(__file__).resolve().parent)
    extra = [str(probe_file)] if probe_file is not None else []
    result = subprocess.run([sys.executable, "-c", code, json.dumps(argv)] + extra, cwd=here,
                            env={**os.environ, "PYTHONPATH": here}, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"exit {result.returncode}: {result.stderr[-1200:]}")
    return 0


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
            contextual_sampler=SimpleNamespace(current_streak={"OLD": "W1"}, side_teams=None,
                                               optional_input_sha256={}))
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
                "    with open(path) as handle:\n        payload=json.load(handle)\n"
                "    return payload.get('pregame_snapshot', payload)\n"
            ).encode(),
            "scripts/nfl_sequence/slc_engine.py": (
                "def is_slc(reference): return True\n"
                "def side_teams(snapshot): return {'A': snapshot['schedule']['home_team'], 'B': snapshot['schedule']['away_team']}\n"
                "def describe(reference): return {'artifact_sha256': 'a'*64, 'enabled_layers': {}, 'layer_artifact_sha256': {}}\n"
                "def play(seed, reference, snapshot, paired_randomness=False, rng_plan=None):\n"
                "    assert paired_randomness == rng_plan.paired\n"
                "    import game_state\n"
                "    return game_state.play_game(seed, reference, snapshot), []\n"
            ).encode(),
            "scripts/nfl_sequence/rng_protocol.py": (
                "class Plan:\n"
                "    def __init__(self, scheme, pregame): self.scheme=scheme; self.pregame=pregame; self.paired=(scheme=='v2'); self.root=('d'*64 if self.paired else None)\n"
                "    def seed_root(self, snapshot): return self.root\n"
                "    def manifest(self): return {'scheme':self.scheme, 'pregame_state_sha256':self.pregame, **({'stream_root_sha256':self.root} if self.root else {})}\n"
                "V1='v1'\n"
                "def plan(scheme, pregame_state_sha256, ref, description): return Plan(scheme, pregame_state_sha256)\n"
            ).encode(),
            "scripts/nfl_sequence/streak_splits.py": (
                "BUCKETS = ('L5+', 'L4', 'L3', 'L2', 'L1', 'NONE', 'W1', 'W2', 'W3', 'W4', 'W5+')\n"
            ).encode(),
            "scripts/nfl_sequence/nfl_team_codes.py": (
                "def to_pbp_team_code(team): return team\n"
                "def to_nflverse_team_code(team): return team\n"
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
            model_inputs = {"schema": "lp-slc-runtime-model-inputs-1",
                            "current_streak": {"NYG": "W3", "DAL": "L2"},
                            "source_sha256": "c" * 64}
            model_inputs["sha256"] = hashlib.sha256(json.dumps(
                model_inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")).hexdigest()
            snapshot_path.write_text(json.dumps({"pregame_snapshot": runtime_snapshot,
                                                 "runtime_model_inputs": model_inputs}))
            status = _run_main_isolated([
                "--model", "v1", "--game", "2026_12_NYG_DAL",
                "--pack", str(pack_path), "--pack-sha256", pack["sha256"],
                "--snapshot", str(snapshot_path),
                "--games", "2", "--seed-start", "51", "--out", str(report_path),
                "--records-out", str(records_path),
            ], probe_file=root / "research.csv")
            report = json.loads(report_path.read_text())
            rows = [json.loads(line) for line in records_path.read_text().splitlines()]
            self.assertEqual(status, 0)
            self.assertEqual(report["simulation"]["valid_full_games"], 2, {"report": report, "rows": rows})
            self.assertEqual(report["snapshot_sha256"], "b" * 64)
            self.assertEqual(report["rng_protocol"], {"scheme": "v1", "pregame_state_sha256": "b" * 64})
            self.assertEqual(report["game_id"], "2026_12_NYG_DAL")
            self.assertEqual(report["simulation"]["valid_full_games"], 2)
            self.assertEqual([row["seed"] for row in rows], [51, 52])
            self.assertEqual(rows[0]["record"]["points"], {"A": 10, "B": 7})
            self.assertEqual(report["regulation_end_diagnostics"]["games_tied_at_regulation_end"], 2)
            self.assertEqual(report["regulation_end_diagnostics"]["regulation_scores_by_seed"][0],
                             {"seed": 51, "home_points": 7, "away_points": 7})
            # Incomplete snapshot evidence does not invalidate completed game results.
            self.assertEqual(report["simulation"]["valid_full_games"], 2)

            v2_report_path = root / "v2-run.json"
            v2_status = _run_main_isolated([
                "--model", "v1", "--game", "2026_12_NYG_DAL",
                "--pack", str(pack_path), "--pack-sha256", pack["sha256"],
                "--snapshot", str(snapshot_path), "--games", "1", "--seed-start", "71",
                "--rng-protocol", "v2", "--expected-stream-root-sha256", "d" * 64,
                "--out", str(v2_report_path),
            ])
            self.assertEqual(v2_status, 0)
            self.assertEqual(json.loads(v2_report_path.read_text())["rng_protocol"],
                             {"scheme": "v2", "pregame_state_sha256": "b" * 64,
                              "stream_root_sha256": "d" * 64})
            with self.assertRaisesRegex(Exception, "EXPECTED_STREAM_ROOT_MISMATCH"):
                _run_main_isolated([
                    "--model", "v1", "--game", "2026_12_NYG_DAL",
                    "--pack", str(pack_path), "--pack-sha256", pack["sha256"],
                    "--snapshot", str(snapshot_path), "--games", "1", "--seed-start", "71",
                    "--rng-protocol", "v2", "--expected-stream-root-sha256", "e" * 64,
                    "--out", str(root / "wrong-root.json"),
                ])

    def test_completed_overtime_tie_counts_as_valid_full_game(self):
        rows = [
            {"seed": 1, "valid_full_game": True, "complete_game": True,
             "tied_at_regulation_end": False, "home_points": 24, "away_points": 17},
            {"seed": 2, "valid_full_game": True, "complete_game": True,
             "tied_at_regulation_end": True, "home_points": 27, "away_points": 24},
            {"seed": 3, "valid_full_game": False, "complete_game": False,
             "tied_at_regulation_end": True, "home_points": 14, "away_points": 14},
        ]
        summary = {"valid_full_games": 1, "valid_full_game_coverage": 1 / 3,
                   "valid_full_game_distribution": {"sample_games": 1}}
        aggregation = SimpleNamespace(
            _round=lambda value: round(float(value), 4),
            _distribution=lambda outcomes: {"sample_games": len(outcomes)},
        )

        corrected = simulate_portable_pack._include_completed_overtime(
            summary, rows, 3, aggregation)

        self.assertEqual(corrected["valid_full_games"], 2)
        self.assertEqual(corrected["valid_full_game_coverage"], 0.6667)
        self.assertEqual(corrected["valid_full_game_distribution"]["sample_games"], 2)


if __name__ == "__main__":
    unittest.main()
