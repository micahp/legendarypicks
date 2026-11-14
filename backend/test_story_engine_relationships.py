"""Adapter tests: story_engine stays unchanged, relationships are added only when proven."""
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import ingest_nba_player_movement as ingest
import story_engine as se
import story_engine_relationships as adapter
import storyline_templates as tp
from test_sports_relationships import BROOKS, DURANT, GREEN, extra, sample_payload
from test_story_engine import matchup_facts

GAME = {"league": "nba", "game_id": "rel-1", "away": "HOU", "home": "PHX"}
BUNDLE_KW = dict(away="HOU", home="PHX", away_results=["W", "W", "W"], home_results=["L", "W"])


def bundle(**kw):
    b = matchup_facts(**dict(BUNDLE_KW, **kw))
    b["game_id"] = "rel-1"
    return b


def make_db(path, snapshot_at="2026-10-30T12:00:00+00:00", meetings=(), first_game="2025-01-01", payload=None):
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE player_source_ids(player_id INT, league TEXT, source TEXT, source_player_key TEXT);
      CREATE TABLE roster_snapshots(id INTEGER PRIMARY KEY, league TEXT, season INT, source TEXT, captured_at TEXT);
      CREATE TABLE roster_memberships(id INTEGER PRIMARY KEY, snapshot_id INT, player_id INT,
        source_player_key TEXT, team TEXT, roster_status TEXT, display_name TEXT);
      CREATE TABLE team_game_results(league TEXT, game_id TEXT, team TEXT, game_date TEXT, opponent TEXT);
    """)
    ingest.ingest(con, payload or sample_payload(), now="2026-11-13T00:00:00+00:00")
    con.execute("INSERT INTO roster_snapshots VALUES(1,'nba',2027,'nba.com:team-roster',?)", (snapshot_at,))
    for i, (key, team, name) in enumerate([(DURANT, "HOU", "Kevin Durant"), (GREEN, "PHX", "Jalen Green"),
                                           (BROOKS, "PHX", "Dillon Brooks")], 1):
        con.execute("INSERT INTO roster_memberships VALUES(?,1,?,?,?, 'active', ?)", (i, i, key, team, name))
    con.execute("INSERT INTO team_game_results VALUES('nba','old','HOU',?, 'PHX')", (first_game,))
    for i, d in enumerate(meetings):
        con.execute("INSERT INTO team_game_results VALUES('nba',?,'HOU',?, 'PHX')", ("m%d" % i, d))
    con.commit()
    con.close()


class Adapter(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "t.db")
        make_db(self.db, first_game="2025-01-01")
        self.inputs = adapter.collect_relationship_inputs(self.db, GAME, as_of="2026-11-02T22:00:00Z")

    def tearDown(self):
        self.dir.cleanup()

    def test_without_inputs_the_output_is_exactly_the_existing_engine(self):
        b = bundle()
        self.assertEqual(adapter.generate_story_with_relationships(copy.deepcopy(b), None), se.generate_story(copy.deepcopy(b)))

    def test_a_first_meeting_after_a_trade_replaces_a_generic_streak_lead(self):
        out = adapter.generate_story_with_relationships(bundle(), self.inputs)
        self.assertEqual(out["manifest"]["relationships"]["status"], "relationship_lead")
        self.assertEqual(out["angle"]["kind"], "relationship:first_team_meeting_after_trade")
        self.assertIn("first time since the July 6, 2025 trade", out["story"])
        self.assertIn("Kevin Durant went from the Phoenix Suns to the Houston Rockets", out["story"])
        self.assertIsNone(se.RESEARCH_JARGON.search(out["story"]))

    def test_the_story_keeps_the_one_to_three_sentence_contract_and_house_style(self):
        out = adapter.generate_story_with_relationships(bundle(), self.inputs)
        self.assertLessEqual(len([s for s in out["story"].split(". ") if s]), 3)
        self.assertNotIn("\u2014", out["story"])

    def test_the_manifest_records_the_decision_and_the_displaced_facts(self):
        out = adapter.generate_story_with_relationships(bundle(), self.inputs)
        rel = out["manifest"]["relationships"]
        self.assertEqual(rel["base_angle"]["kind"], "winning_streak")
        self.assertEqual([f["kind"] for f in out["manifest"]["selected_facts"]], ["relationship"])
        self.assertTrue(out["manifest"]["selected_facts"][0]["evidence_ids"])
        self.assertTrue(any(f["reason"] == "displaced by relationship lead" for f in out["manifest"]["omitted_facts"]))
        self.assertIn("rubric_version", rel)
        self.assertTrue(rel["log"])
        self.assertIn("availability source: none", rel["notes"][0])

    def test_a_trade_dated_on_the_cutoff_day_is_not_used(self):
        late = extra(sample_payload())
        for row in late["NBA_Player_Movement"]["rows"]:
            row["TRANSACTION_DATE"] = "2026-11-02T00:00:00"
        db = os.path.join(self.dir.name, "late.db")
        make_db(db, payload=late)
        inputs = adapter.collect_relationship_inputs(db, GAME, as_of="2026-11-02T22:00:00Z")
        out = adapter.generate_story_with_relationships(bundle(), inputs)
        self.assertEqual(out["story"], se.generate_story(bundle())["story"])

    def test_an_earlier_meeting_since_the_trade_removes_the_first_claim(self):
        db = os.path.join(self.dir.name, "met.db")
        make_db(db, meetings=["2025-11-24"])
        inputs = adapter.collect_relationship_inputs(db, GAME, as_of="2026-11-02T22:00:00Z")
        out = adapter.generate_story_with_relationships(bundle(), inputs)
        self.assertNotIn("first time", out["story"])
        reasons = [e["reason"] for e in out["manifest"]["relationships"]["log"] if e["role"] == "rejected_by_detector"]
        self.assertIn("prior_meeting_exists", reasons)

    def test_a_four_sentence_trade_summary_is_cut_to_three_sentences(self):
        db = os.path.join(self.dir.name, "recip.db")
        make_db(db, meetings=["2025-11-24"])
        inputs = adapter.collect_relationship_inputs(db, GAME, as_of="2026-11-02T22:00:00Z")
        out = adapter.generate_story_with_relationships(
            bundle(away_results=["W", "L"], home_results=["L", "W"]), inputs)
        self.assertEqual(out["angle"]["kind"], "relationship:reciprocal_trade_reunion")
        self.assertEqual(len([x for x in out["story"].split(". ") if x]), 3)
        self.assertNotIn("Atlanta Hawks", out["story"])

    def test_meeting_history_that_starts_after_the_trade_proves_nothing(self):
        db = os.path.join(self.dir.name, "late_start.db")
        make_db(db, first_game="2025-10-21")
        inputs = adapter.collect_relationship_inputs(db, GAME, as_of="2026-11-02T22:00:00Z")
        out = adapter.generate_story_with_relationships(bundle(), inputs)
        self.assertNotIn("first time", out["story"])
        reasons = [e["reason"] for e in out["manifest"]["relationships"]["log"] if e["role"] == "rejected_by_detector"]
        self.assertIn("meeting_history_incomplete", reasons)

    def test_a_failed_audit_keeps_the_existing_story_and_says_so(self):
        real = tp.render

        def bad(c, names):
            out = real(c, names)
            return dict(out, headline=out["headline"] + " A grudge match.")
        with patch.object(tp, "render", bad):
            out = adapter.generate_story_with_relationships(bundle(), self.inputs)
            self.assertEqual(out["manifest"]["relationships"]["status"], "audit_failed")
            self.assertEqual(out["story"], se.generate_story(bundle())["story"])
            self.assertIn("banned_word", [f["check"] for f in out["manifest"]["relationships"]["audit"]["failures"]])
            with self.assertRaises(ValueError):
                adapter.generate_story_with_relationships(bundle(), self.inputs, strict=True)

    def test_an_angle_without_an_editorial_score_is_never_replaced(self):
        b = bundle()
        b["teams"] = {}
        base = se.generate_story(copy.deepcopy(b))
        out = adapter.generate_story_with_relationships(b, self.inputs)
        self.assertEqual(out["story"], base["story"])
        self.assertEqual(out["manifest"]["relationships"]["status"], "base_angle_not_ranked")

    def test_a_much_bigger_existing_angle_keeps_the_lead(self):
        out = adapter.generate_story_with_relationships(
            bundle(away_results=["W"] * 4, home_results=["L", "W"]), self.inputs)
        self.assertEqual(out["manifest"]["relationships"]["base_angle"]["kind"], "undefeated")
        self.assertEqual(out["manifest"]["relationships"]["status"], "kept_existing_lead")
        self.assertNotIn("trade", out["story"])

    def test_same_inputs_give_identical_output(self):
        one = json.dumps(adapter.generate_story_with_relationships(bundle(), self.inputs), sort_keys=True, default=str)
        two = json.dumps(adapter.generate_story_with_relationships(bundle(), copy.deepcopy(self.inputs)),
                         sort_keys=True, default=str)
        self.assertEqual(one, two)

    def test_inputs_are_not_mutated(self):
        before = json.dumps(self.inputs, sort_keys=True, default=str)
        adapter.generate_story_with_relationships(bundle(), self.inputs)
        self.assertEqual(json.dumps(self.inputs, sort_keys=True, default=str), before)


class Collector(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "t.db")

    def tearDown(self):
        self.dir.cleanup()

    def test_a_roster_captured_after_the_cutoff_is_refused(self):
        make_db(self.db, snapshot_at="2026-11-12T12:00:00+00:00")
        with self.assertRaises(adapter.RelationshipDataMissing) as ctx:
            adapter.collect_relationship_inputs(self.db, GAME, as_of="2026-11-02T22:00:00Z")
        self.assertIn("roster snapshot", str(ctx.exception))

    def test_a_missing_movement_table_is_refused(self):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE roster_snapshots(id INT)")
        con.commit()
        con.close()
        with self.assertRaises(adapter.RelationshipDataMissing):
            adapter.collect_relationship_inputs(self.db, GAME, as_of="2026-11-02T22:00:00Z")

    def test_a_team_with_no_active_players_is_refused(self):
        make_db(self.db)
        con = sqlite3.connect(self.db)
        con.execute("UPDATE roster_memberships SET roster_status='inactive' WHERE team='PHX'")
        con.commit()
        con.close()
        with self.assertRaises(adapter.RelationshipDataMissing):
            adapter.collect_relationship_inputs(self.db, GAME, as_of="2026-11-02T22:00:00Z")

    def test_the_collector_never_writes(self):
        make_db(self.db)
        before = (os.path.getmtime(self.db), os.path.getsize(self.db))
        adapter.collect_relationship_inputs(self.db, GAME, as_of="2026-11-02T22:00:00Z")
        self.assertEqual((os.path.getmtime(self.db), os.path.getsize(self.db)), before)

    def test_only_nba_is_supported(self):
        make_db(self.db)
        with self.assertRaises(adapter.RelationshipDataMissing):
            adapter.collect_relationship_inputs(self.db, dict(GAME, league="nfl"), as_of="2026-11-02T22:00:00Z")


if __name__ == "__main__":
    unittest.main()
