"""Tests for historical NFL injuries without inventing a source publication date."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import recover_nfl_injury_weeks as mod


def sample(status="Questionable", modified=None):
    return {"season": 2026, "week": 2, "team": "NYG",
            "gsis_id": "00-9990001", "full_name": "Example Player",
            "position": "WR", "report_status": status,
            "practice_status": "Limited Participation in Practice",
            "report_primary_injury": "Ankle", "date_modified": modified}


class InjuryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.kickoff = datetime(2026, 9, 20, 17, tzinfo=timezone.utc)
        self.games = {(2, "NYG"): {"kickoff": self.kickoff,
                                    "game_id": "2026_02_WAS_NYG"}}

    def test_missing_source_time_is_not_fabricated(self):
        result, counts = mod.recover([sample()], "sourcehash", self.games)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_modified_at_utc"], "")
        self.assertEqual(result[0]["earliest_captured_at_utc"], "")
        self.assertEqual(result[0]["evidence_class"],
                         "historical_weekly_report_undated")
        self.assertEqual(counts["historical_weekly_report_undated"], 1)

    def test_historical_source_modified_without_capture_is_not_verified_lock(self):
        result, _ = mod.recover([sample(modified="2026-09-19T16:00:00Z")],
                                "hash", self.games)
        self.assertEqual(result[0]["evidence_class"],
                         "source_modified_before_kickoff_not_observed")

    def test_after_kickoff_source_modified_is_flagged(self):
        result, _ = mod.recover([sample(modified="2026-09-21T00:00:00Z")],
                                "hash", self.games)
        self.assertEqual(result[0]["evidence_class"],
                         "source_modified_after_kickoff")

    def test_naive_source_date_cannot_be_assumed_utc(self):
        self.assertIsNone(mod.utc_timestamp("2026-09-19 20:00:00"))
        self.assertIsNone(mod.utc_timestamp("bogus"))

    def test_captured_pre_kickoff_matching_report_is_verified(self):
        cap = {"sha256": "pinned", "path": "/archive/sep19.parquet",
               "observed": datetime(2026, 9, 19, 16, tzinfo=timezone.utc),
               "rows": [sample()]}
        result, _ = mod.recover([sample()], "sourcehash", self.games, [cap])
        self.assertEqual(result[0]["evidence_class"], "pre_kickoff_archived_capture")
        self.assertEqual(result[0]["capture_sha256"], "pinned")
        self.assertEqual(result[0]["earliest_captured_at_utc"],
                         "2026-09-19T16:00:00Z")

    def test_after_kickoff_capture_cannot_verify_historical_as_of(self):
        cap = {"sha256": "later", "path": "/archive/sep21.parquet",
               "observed": datetime(2026, 9, 21, 16, tzinfo=timezone.utc),
               "rows": [sample()]}
        result, _ = mod.recover([sample()], "sourcehash", self.games, [cap])
        self.assertEqual(result[0]["evidence_class"],
                         "historical_weekly_report_undated")

    def test_pre_kickoff_capture_of_different_status_cannot_verify_final_revision(self):
        cap = {"sha256": "earlier", "path": "/archive/sep19.parquet",
               "observed": datetime(2026, 9, 19, 16, tzinfo=timezone.utc),
               "rows": [sample("Questionable")]}
        result, _ = mod.recover([sample("Out")], "hash", self.games, [cap])
        self.assertEqual(result[0]["evidence_class"],
                         "historical_weekly_report_undated")

    def test_unverified_status_joins_do_not_drop_full_weekly_rows(self):
        rows = [sample("Out"), sample("Questionable")]
        rows[1]["gsis_id"] = "00-9990002"
        got, stats = mod.recover(rows, "hash", self.games)
        self.assertEqual(stats["selected_weekly_rows"], 2)
        self.assertEqual(len(got), 2)
        self.assertEqual({r["report_status"] for r in got},
                         {"Out", "Questionable"})

    def test_schedule_lookup_uses_eastern_kickoff_and_readonly_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp)/"schedule.db"
            with sqlite3.connect(db) as con:
                con.execute("""CREATE TABLE nfl_schedule(
                    game_id TEXT,season INTEGER,week INTEGER,gameday TEXT,gametime TEXT,
                    away_team TEXT,home_team TEXT,game_type TEXT)""")
                con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?,?,?)",
                            ("2026_02_WAS_NYG", 2026, 2, "2026-09-20",
                             "13:00", "WAS", "NYG", "REG"))
            lookup = mod.get_schedule(db)
            self.assertEqual(lookup[(2, "NYG")]["kickoff"], self.kickoff)
            self.assertIn((2, "WSH"), lookup)

    def test_capture_index_refuses_fake_hash_or_missing_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blob = root/"injury.parquet"
            blob.write_bytes(b"fake fixture")
            index = root/"index.json"
            index.write_text(json.dumps([
                {"path": "injury.parquet", "sha256": "incorrect",
                 "observed_at_utc": "2026-09-19T16:00:00Z"}]))
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                mod.captures_from_index(index)
            index.write_text(json.dumps([
                {"path": "injury.parquet",
                 "sha256": hashlib.sha256(b"fake fixture").hexdigest(),
                 "observed_at_utc": "2026-09-19T16:00:00"}]))
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                mod.captures_from_index(index)

    def test_report_outputs_audit_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root/"injuries_2026.parquet"
            src.write_bytes(b"source")
            rows, stats = mod.recover([sample()], "hash", self.games)
            result = mod.write_report(root/"out", rows, stats, src,
                                      "hash", [])
            self.assertEqual(result["summary"]["selected_weekly_rows"], 1)
            csv_text = (root/"out"/"nfl-injury-weeks-2-9.csv").read_text()
            self.assertIn("historical_weekly_report_undated", csv_text)
            self.assertTrue((root/"out"/"README.md").is_file())


if __name__ == "__main__":
    unittest.main()
