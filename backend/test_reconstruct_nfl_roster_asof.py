"""Ensure historical roster context cannot silently use post-kickoff revisions."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import reconstruct_nfl_roster_asof as r


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AsOfRosterTests(unittest.TestCase):
    def setUp(self):
        self.kick = stamp("2026-09-20T17:00:00Z")
        self.schedule = {(2, "NYG"): {"game_id": "2026_02_WAS_NYG",
                                      "kickoff": self.kick},
                         (2, "WSH"): {"game_id": "2026_02_WAS_NYG",
                                      "kickoff": self.kick}}
        self.before = stamp("2026-09-19T12:00:00Z")
        self.after = stamp("2026-09-20T17:01:00Z")
        self.depth = {
            ("NYG", self.before): [
                {"gsis_id": "gsis1", "player_name": "Player A",
                 "pos_grp": "3WR 1TE", "pos_abb": "RB", "pos_rank": 1},
                {"gsis_id": "gsis2", "player_name": "Player B",
                 "pos_grp": "3WR 1TE", "pos_abb": "WR", "pos_rank": 1}],
            ("NYG", self.after): [
                {"gsis_id": "gsis3", "player_name": "Future Star",
                 "pos_grp": "3WR 1TE", "pos_abb": "RB", "pos_rank": 1}],
            ("WSH", self.before): [
                {"gsis_id": "gsis4", "player_name": "Player C",
                 "pos_grp": "3WR 1TE", "pos_abb": "QB", "pos_rank": 1}],
        }

    def test_never_use_post_cutoff_depth_rows(self):
        got, counts = r.build(self.schedule, self.depth, {}, "hash")
        self.assertEqual({x["gsis_id"] for x in got}, {"gsis1", "gsis2", "gsis4"})
        self.assertEqual(counts["depth_team_games"], 2)
        self.assertEqual(counts["expected_team_games"], 2)
        self.assertEqual(counts["depth_player_role_rows"], 3)
        self.assertTrue(all(x["reconstruction_status"] ==
                            "depth_and_injury_only_not_finalized" for x in got))
        self.assertTrue(all(x["pregame_inactive"] == "" for x in got))

    def test_undated_injury_status_is_not_pregame_proof(self):
        inj = {(2, "NYG", "gsis1"): {"report_status": "Out",
            "practice_status": "DNP", "evidence_class": "historical_weekly_report_undated"}}
        got, c = r.build(self.schedule, self.depth, inj, "hash")
        row = next(x for x in got if x["gsis_id"] == "gsis1")
        self.assertEqual(row["injury_report_status"], "Out")
        self.assertEqual(row["injury_evidence_class"],
                         "historical_weekly_report_undated")
        self.assertEqual(row["pregame_inactive"], "")

    def test_official_inactives_prior_to_cutoff_can_finalize_availability(self):
        evidence = {("2026_02_WAS_NYG", "NYG"): {
            "gsis_ids": ["gsis2"],
            "source_url": "https://www.nfl.com/news/official-report",
            "source_sha256": "a"*64,
            "source_last_updated_at_utc": "2026-09-20T16:00:00Z"}}
        got, c = r.build(self.schedule, self.depth, {}, "hash",
                         inactive_sources=evidence)
        self.assertEqual(c["reconstructed_with_pregame_dated_inactives_team_games"], 1)
        self.assertEqual(c["depth_and_injury_only_not_finalized_team_games"], 1)
        ng = [x for x in got if x["team"] == "NYG"]
        self.assertEqual({x["gsis_id"]: x["pregame_inactive"] for x in ng},
                         {"gsis1": "", "gsis2": True})

    def test_after_kickoff_inactives_do_not_become_pregame_lock(self):
        evidence = {("2026_02_WAS_NYG", "NYG"): {
            "gsis_ids": ["gsis2"],
            "source_url": "https://www.nfl.com/news/official-report",
            "source_sha256": "a"*64,
            "source_last_updated_at_utc": "2026-09-20T20:00:00Z"}}
        got, counts = r.build(self.schedule, self.depth, {}, "hash",
                              inactive_sources=evidence)
        self.assertEqual(counts["reconstructed_with_retrospective_inactives_team_games"], 1)
        self.assertEqual(next(x for x in got if x["gsis_id"] == "gsis2")["inactive_evidence_class"],
                         "official_not_pregame_verified")

    def test_missing_inactive_from_depth_is_counted(self):
        evidence = {("2026_02_WAS_NYG", "NYG"): {
            "gsis_ids": ["absent"],
            "source_url": "https://www.nfl.com/news/official-report",
            "source_sha256": "a"*64}}
        got, counts = r.build(self.schedule, self.depth, {}, "hash",
                              inactive_sources=evidence)
        self.assertEqual(counts["official_inactives_not_in_depth_chart"], 1)

    def test_inactive_source_requires_hash_gsis_and_url(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)/"inactives.json"
            p.write_text('[{"game_id":"2026_02_WAS_NYG","team":"NYG",'
                         '"source_url":"https://www.nfl.com/news/report",'
                         '"gsis_ids":["abc"],"source_sha256":"123"}]')
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                r.inactive_index(p)

    def test_cutoff_must_precede_kickoff(self):
        with self.assertRaisesRegex(ValueError, "before kickoff"):
            r.build(self.schedule, self.depth, {}, "hash", 0)


if __name__ == "__main__":
    unittest.main()
