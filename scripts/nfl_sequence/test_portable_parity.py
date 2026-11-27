import json
import tempfile
from pathlib import Path
import unittest

from compare_portable_parity import compare


RECORD = {
    "ledger": [{"play": {"event_type": "run", "outcome": {"yards_gained": 3}}}],
    "drives": [], "kickoffs": [], "boundaries": [], "points": {"A": 0, "B": 0},
    "stats": {"player": [{"player_id": "1", "rushing": {"yds": 3}}]},
    "status": "complete", "blocker": None, "complete_game": True,
    "valid_full_game": True, "regulation_end_reached": True, "tied": False, "overtime": None,
}


class PortableParity(unittest.TestCase):
    def _write(self, path, row):
        path.write_text(json.dumps(row) + "\n")

    def test_exact_seeded_game_records_pass(self):
        with tempfile.TemporaryDirectory() as dirname:
            left, right = Path(dirname) / "legacy.jsonl", Path(dirname) / "portable.jsonl"
            self._write(left, {"seed": 17, "record": RECORD})
            self._write(right, {"seed": 17, "record": RECORD})
            self.assertEqual(compare(left, right)["status"], "pass")

    def test_empty_or_matching_failed_cohorts_do_not_pass(self):
        with tempfile.TemporaryDirectory() as dirname:
            left, right = Path(dirname) / "legacy.jsonl", Path(dirname) / "portable.jsonl"
            for path in (left, right):
                path.write_text("")
            self.assertEqual(compare(left, right)["status"], "fail")
            for path in (left, right):
                self._write(path, {"seed": 17, "record": None, "error": "same failure"})
            self.assertEqual(compare(left, right)["status"], "fail")
            diagnostic = compare(left, right, allow_invalid_research=True)
            self.assertEqual(diagnostic["status"], "pass")
            self.assertEqual(diagnostic["comparison_class"], "diagnostic_only")

    def test_matching_truncated_cohort_fails_requested_seed_gate(self):
        with tempfile.TemporaryDirectory() as dirname:
            left, right = Path(dirname) / "legacy.jsonl", Path(dirname) / "portable.jsonl"
            for path in (left, right):
                self._write(path, {"seed": 17, "record": RECORD})
            self.assertEqual(compare(left, right, expected_seeds=100, seed_start=17)["status"], "fail")
            report = compare(left, right, expected_seeds=1, seed_start=17)
            self.assertEqual(report["status"], "pass")
            self.assertTrue(report["requested_cohort_verified"])

    def test_play_stats_score_and_completion_changes_fail(self):
        with tempfile.TemporaryDirectory() as dirname:
            left, right = Path(dirname) / "legacy.jsonl", Path(dirname) / "portable.jsonl"
            self._write(left, {"seed": 17, "record": RECORD})
            changed = json.loads(json.dumps(RECORD))
            changed["ledger"][0]["play"]["outcome"]["yards_gained"] = 4
            changed["stats"]["player"][0]["rushing"]["yds"] = 4
            changed["points"]["A"] = 7
            changed["complete_game"] = False
            self._write(right, {"seed": 17, "record": changed})
            report = compare(left, right, expected_seeds=1, seed_start=17)
            self.assertEqual(report["status"], "fail")
            self.assertFalse(report["requested_cohort_verified"])
            self.assertEqual({row["field"] for row in report["mismatches"]},
                             {"ledger", "stats", "points", "complete_game"})


if __name__ == "__main__":
    unittest.main()
