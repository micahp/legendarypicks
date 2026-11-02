import gzip
import hashlib
import unittest

from slc_realism_ranker import (
    DEFAULT_WEIGHTS,
    _interest,
    fit_reference_model,
    hard_gate,
    historical_neighbors,
    rank_candidates,
    replay_equivalence,
    select_marketing_scenarios,
    write_outputs,
)
from build_slc_realism_inputs import read_seed_rows
from run_week8_missing_matchup_10k import (_absolute_executable_path,
                                          _compress_worker_artifacts)
from validate_slc_seed_replays import (_load_scored_seed_features, _replay_evidence_mismatches,
                                       _trace_audit)
from tempfile import TemporaryDirectory
from pathlib import Path
import json


def candidate(seed, drives, score, *, status="success", valid=True, overtime=False, comeback=False):
    return {
        "seed": seed,
        "teams": ["DET", "MIN"],
        "status": status,
        "valid_full_game": valid,
        "score_only_overtime": overtime,
        "features": {
            "drives": {"drive_count": drives, "yardage": 30.0 + drives},
            "decisions": {"run_share": 0.45, "third_down_rate": 0.4},
            "workloads": {"qb_attempts": 34.0, "rb_carry_share": 0.62},
            "game": {"total_points": score, "margin": 3.0, "turnovers": 1.0},
        },
        "story": {"comeback": comeback, "margin": 3.0, "total_points": score, "defensive_score": score < 35},
        "replay_status": "passed",
    }


class RealismRankerTests(unittest.TestCase):
    def setUp(self):
        self.historical = [
            {"game_id": f"g-{year}-{i}", "season": year, "teams": ["DET", "MIN"], "features": {
                "drives": {"drive_count": 10 + i % 3, "yardage": 28.0 + i},
                "decisions": {"run_share": 0.42 + 0.01 * (i % 4), "third_down_rate": 0.35 + 0.02 * (i % 3)},
                "workloads": {"qb_attempts": 32.0 + i % 5, "rb_carry_share": 0.55 + 0.02 * (i % 4)},
                "game": {"total_points": 42.0 + i % 8, "margin": float(i % 11), "turnovers": float(i % 3)},
            }}
            for year in range(2022, 2026) for i in range(12)
        ]

    def test_ranking_is_deterministic_and_exposes_weighted_contributions(self):
        rows = [candidate(8, 11, 44), candidate(3, 11, 44), candidate(5, 18, 64)]
        ranked = rank_candidates(rows, self.historical, k=5, use_numpy=False)
        again = rank_candidates(rows, self.historical, k=5, use_numpy=False)
        parallel = rank_candidates(rows * 4, self.historical, k=5, workers=2, use_numpy=False)
        serial = rank_candidates(rows * 4, self.historical, k=5, use_numpy=False)
        vectorized = rank_candidates(rows * 4, self.historical, k=5, use_numpy=True)
        serial_model = fit_reference_model(self.historical, k=5)
        parallel_model = fit_reference_model(self.historical, k=5, workers=2)
        self.assertEqual([r["seed"] for r in ranked], [r["seed"] for r in again])
        self.assertEqual([(r["seed"], r["realism_score"], r["score_contributions"]) for r in parallel],
                         [(r["seed"], r["realism_score"], r["score_contributions"]) for r in serial])
        self.assertEqual([(r["seed"], r["realism_score"], r["score_contributions"]) for r in vectorized],
                         [(r["seed"], r["realism_score"], r["score_contributions"]) for r in serial])
        self.assertEqual(serial_model["calibration"], parallel_model["calibration"])
        self.assertEqual(serial_model["validation"], parallel_model["validation"])
        self.assertEqual([(-r["realism_score"], r["seed"]) for r in ranked],
                         sorted((-r["realism_score"], r["seed"]) for r in ranked))
        self.assertAlmostEqual(sum(ranked[0]["score_contributions"].values()), ranked[0]["realism_score"])
        self.assertEqual(set(ranked[0]["component_scores"]), set(DEFAULT_WEIGHTS))

    def test_score_only_overtime_is_scored_but_not_renderable(self):
        gate = hard_gate(candidate(1, 10, 45, overtime=True))
        self.assertTrue(gate["scoreable"])
        self.assertFalse(gate["renderable"])
        self.assertIn("score_only_overtime", gate["render_reasons"])

    def test_invalid_game_and_failed_reconciliation_are_hard_gates(self):
        row = candidate(2, 10, 40, valid=False)
        row["reconciliation"] = {"matches": False}
        gate = hard_gate(row)
        self.assertFalse(gate["scoreable"])
        self.assertFalse(gate["renderable"])
        self.assertIn("invalid_full_game", gate["reasons"])
        self.assertIn("boxscore_reconciliation_failed", gate["reasons"])

    def test_historical_neighbors_exclude_the_held_out_season(self):
        row = self.historical[0]
        neighbors = historical_neighbors(row, self.historical, "drives", season_exclude=2022, k=4)
        self.assertTrue(neighbors)
        self.assertTrue(all(item["season"] != 2022 for item, _distance in neighbors))

    def test_replay_equivalence_checks_all_archived_evidence_groups(self):
        original = {"score": {"DET": 24, "MIN": 21}, "teams": {"DET": {"yards": 300}},
                    "players": {"qb": {"attempts": 35}}, "drives": [{"terminal": "punt"}],
                    "quarters": {"DET": [3, 7, 7, 7]}}
        self.assertEqual(replay_equivalence(original, original), [])
        replay = {**original, "drives": [{"terminal": "touchdown"}]}
        self.assertTrue(any("drives" in mismatch for mismatch in replay_equivalence(original, replay)))

    def test_replay_validation_compares_direct_score_drive_and_quarter_evidence(self):
        boxscore = {
            "home_team": "DET", "away_team": "MIN", "status": "valid_complete",
            "points_by_period": {"DET": {"Q1": 3, "Q2": 7, "Q3": 0, "Q4": 0, "OT": 0},
                                 "MIN": {"Q1": 0, "Q2": 0, "Q3": 7, "Q4": 0, "OT": 0}},
            "teams": [{"team": "DET", "side": "A", "stats": {"points": 10}},
                      {"team": "MIN", "side": "B", "stats": {"points": 7}}],
            "players": [{"stable_player_id": "gsis-1", "rushing": {"attempts": 1}}],
            "quarter_scoring_complete": True,
            "reconciliation": {"status": "passed"},
            "quarter_by_quarter": {"periods": ["Q1", "Q2", "Q3", "Q4", "OT"],
                                   "drive_summaries": [{"drive_index": 1, "terminal": "punt"}],
                                   "team_stats": {"DET": {"Q1": {"points": 3}}}},
        }
        record = {"points": {"A": 10, "B": 7}, "valid_full_game": True}
        self.assertEqual(_replay_evidence_mismatches(boxscore, boxscore, record), [])

        wrong_score = {**record, "points": {"A": 13, "B": 7}}
        self.assertIn("score", _replay_evidence_mismatches(boxscore, boxscore, wrong_score))
        changed_drive = json.loads(json.dumps(boxscore))
        changed_drive["quarter_by_quarter"]["drive_summaries"][0]["terminal"] = "touchdown"
        self.assertIn("drives", _replay_evidence_mismatches(boxscore, changed_drive, record))
        self.assertIn("quarters", _replay_evidence_mismatches(boxscore, changed_drive, record))

    def test_marketing_selection_keeps_interest_separate_and_avoids_duplicate_seeds(self):
        rows = [candidate(i, 10, 40 + i % 4, comeback=(i == 3)) for i in range(1, 8)]
        rows[2]["story"].update({"comeback": True, "margin": 2, "total_points": 46, "defensive_score": False})
        rows[4]["story"].update({"margin": 2, "total_points": 45, "defensive_score": False})
        rows[5]["story"].update({"margin": 14, "total_points": 28, "defensive_score": True})
        rows[6]["story"]["plausible_star"] = True
        selected = select_marketing_scenarios(rows, limit=5)
        seeds = [row["seed"] for row in selected if row.get("seed") is not None]
        self.assertEqual(len(seeds), len(set(seeds)))
        self.assertTrue(all("visual_interest_score" in row for row in selected))
        self.assertEqual({row["selection"] for row in selected},
                         {"most_representative", "close_finish", "comeback", "defensive_game", "star_showcase"})
        sample = candidate(99, 10, 48, comeback=True)
        before = _interest(sample)
        sample["realism_score"] = 100.0
        self.assertEqual(_interest(sample), before, "visual interest must not change the realism score")

    def test_marketing_output_uses_versioned_seed_library_schema(self):
        with TemporaryDirectory() as directory:
            write_outputs([candidate(8, 11, 44)], Path(directory), top_n=1, marketing_n=1)
            document = json.loads((Path(directory) / "marketing-seeds.json").read_text())
            self.assertEqual(document["schema"], "lp.nfl.slc-marketing-seeds.v1")
            self.assertEqual(len(document["seeds"]), 1)
            self.assertEqual(document["seeds"][0]["seed"], 8)

    def test_seed_identity_rejects_duplicates_and_gaps(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "worker-01.seeds.jsonl"
            path.write_text("\n".join(json.dumps({"seed": seed, "outcome": {"seed": seed}})
                                      for seed in (1, 1)) + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                read_seed_rows([path], expected_count=2)

    def test_replay_trace_rejects_record_seed_identity_mismatch(self):
        findings = _trace_audit({"seed": 8, "result": {"seed": 9, "drives": []}})
        self.assertIn("trace_record_seed_mismatch", findings)

    def test_replay_validator_restores_stage_a_scores_for_every_seed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            features = root / "seed-features.jsonl"
            rankings = root / "seed-realism-rankings.csv"
            records = [candidate(seed, 10, 40) for seed in (4, 9)]
            features.write_text("".join(json.dumps(row) + "\n" for row in records))
            rankings.write_text(
                "seed,realism_score,replay_status,score_drives,score_decisions,score_workloads,score_game,"
                "distance_drives,distance_decisions,distance_workloads,distance_game\n"
                "4,72.5,not_tested,22.5,20,15,15,1,2,3,4\n"
                "9,63,not_tested,18,17,14,14,5,6,7,8\n"
            )
            loaded = _load_scored_seed_features(features, rankings)
            self.assertEqual([row["seed"] for row in loaded], [4, 9])
            self.assertEqual(loaded[0]["realism_score"], 72.5)
            self.assertEqual(loaded[0]["score_contributions"], {
                "drives": 22.5, "decisions": 20.0, "workloads": 15.0, "game": 15.0,
            })
            self.assertEqual(loaded[0]["group_distances"], {
                "drives": 1.0, "decisions": 2.0, "workloads": 3.0, "game": 4.0,
            })
            self.assertEqual(len(loaded), 2)

    def test_worker_artifacts_are_gzip_stored_only_after_hash_verified_roundtrip(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = b'{"seed":1,"events":' + (b'"ordinary football play",' * 2000) + b'null}\n'
            raw_path = root / "worker-01.json"
            raw_path.write_bytes(original)
            manifest = _compress_worker_artifacts(root)
            stored_path = root / "worker-01.json.gz"
            self.assertFalse(raw_path.exists())
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]["raw_bytes"], len(original))
            self.assertLess(manifest[0]["stored_bytes"], len(original))
            self.assertEqual(manifest[0]["raw_sha256"], hashlib.sha256(original).hexdigest())
            with gzip.open(stored_path, "rb") as handle:
                self.assertEqual(handle.read(), original)

    def test_runner_keeps_virtualenv_python_symlink_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "python-base"
            target.write_text("interpreter")
            venv_python = root / "venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.symlink_to(target)
            self.assertEqual(_absolute_executable_path(venv_python), venv_python)



if __name__ == "__main__":
    unittest.main()
