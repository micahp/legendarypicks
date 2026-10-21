"""Event discovery rules, the assembly step's read-only research side, and the coverage shape."""
import datetime as dt
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest

import cp4_evidence_assembly as asm
import research_event_registry as ereg
import research_evidence as rpe
import research_player_outcomes as rpo
import scoreboard_store


class DiscoveryRulesTest(unittest.TestCase):
    def test_candidate_slugs_put_the_city_among_them(self):
        self.assertIn("wuhan", ereg.candidate_slugs("Dongfeng Voyah Wuhan Open"))
        self.assertEqual(ereg.candidate_slugs("BNB Ningbo Open"), ["ningbo"])
        self.assertIn("shanghai", ereg.candidate_slugs("Rolex Shanghai Masters"))

    def test_a_title_must_name_the_candidate_word_as_a_whole_word(self):
        self.assertTrue(ereg.title_names("Tennis WTA Wuhan Scores - WTA - Singles Live", "wuhan"))
        self.assertFalse(ereg.title_names("Tennis Scores", "wuhan"))
        self.assertFalse(ereg.title_names("Wuhanese tennis", "wuhan"))

    def test_results_url_uses_the_tour_and_slug(self):
        self.assertEqual(ereg.results_url("wta", "ningbo"), "https://www.tennis24.com/wta-singles/ningbo/results/")

    def test_seeds_are_supported_and_keyed(self):
        con = sqlite3.connect(":memory:")
        ereg.ensure(con)
        keys = {(s["tournament_id"], s["event"]) for s in ereg.supported(con)}
        self.assertIn(("381", "wuhan-wta-2026"), keys)
        self.assertIn(("315", "shanghai-atp-2026"), keys)


class CoverageShapeTest(unittest.TestCase):
    def test_an_unsupported_tournament_lists_the_candidates_it_tried(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(scoreboard_store.SCHEMA)
        ereg.ensure(con)
        today = dt.date(2026, 10, 20)
        payload = json.dumps({"tournament_id": "963", "event": "BNB Ningbo Open", "status": "Final"})
        con.execute("INSERT INTO scoreboard_snapshots(league,game_date,game_id,payload,state,start_time,fetched_at,source) "
                    "VALUES('wta','2026-10-19','g1',?,'post','2026-10-19T10:00:00+00:00','t','x')", (payload,))
        con.execute("INSERT OR REPLACE INTO tournament_registry(espn_tournament_id,league,espn_event_name,mapping_status,"
                    "candidates_tried,checked_at) VALUES('963','wta','BNB Ningbo Open','unsupported','[\"ningbo\"]','t')")
        rows = ereg.coverage(con, today, 14)
        ningbo = [r for r in rows if r["tournament_id"] == "963"][0]
        self.assertEqual(ningbo["mapping"], "unsupported")
        self.assertEqual(ningbo["candidates_tried"], ["ningbo"])
        self.assertEqual(ningbo["completed_espn"], 1)


class AssemblyTest(unittest.TestCase):
    def test_assembly_copies_outcomes_and_leaves_the_research_file_untouched(self):
        tmp = tempfile.mkdtemp()
        research = os.path.join(tmp, "research.db")
        evaluation = os.path.join(tmp, "evaluation.db")
        con = sqlite3.connect(research)
        con.executescript(rpo.DDL)
        rpe.ensure(con)
        con.execute("INSERT INTO research_player_match_outcomes VALUES('atp','e','g1','A','home','B','Final',6,1,"
                    "'official_labelled','tennis24','m1',NULL,'{}',1,'t')")
        con.commit()
        con.close()
        before = hashlib.sha256(open(research, "rb").read()).hexdigest()
        ev = sqlite3.connect(evaluation)
        ev.executescript(scoreboard_store.SCHEMA)
        ev.close()
        report = asm.assemble(evaluation, research)
        self.assertEqual(report["outcome_rows_copied"], 1)
        self.assertEqual(report["per_tour"]["atp"]["verified_outcome_games"], 1)
        self.assertEqual(report["per_tour"]["atp"]["gradable_both"], 0)  # no frozen distribution yet
        after = hashlib.sha256(open(research, "rb").read()).hexdigest()
        self.assertEqual(before, after)
        ev = sqlite3.connect(evaluation)
        self.assertEqual(ev.execute("SELECT COUNT(*) FROM research_player_match_outcomes").fetchone()[0], 1)

    def test_the_live_database_is_refused_as_an_evaluation_copy(self):
        with self.assertRaises(SystemExit):
            asm.assemble("/root/legendarypicks/backend/data/picks.dev.db", "/tmp/x.db")


if __name__ == "__main__":
    unittest.main()
