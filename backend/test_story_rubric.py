"""Executable regression tests for the offline grading algorithm."""
import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy

from story_rubric import VERSION, grade_record, grade_jsonl, normalize_pattern, write_html


def sample_row(story=None):
    story = story or (
        "The 5-2 Bears bring a two-game winning streak to Seattle, where the Seahawks sit at 4-3. "
        "Jaxon Smith-Njigba has been on a tear for Seattle, topping 100 receiving yards in "
        "four of his last five games."
    )
    cutoff = "2026-11-02T00:00:00Z"
    game_rows = [
        {"id": f"CHI-g{i}", "available_at": "2026-10-25T22:00:00Z", "date": f"2026-10-{20+i:02d}",
         "for": 25, "against": 20}
        for i in range(7)
    ]
    recv = [112, 119, 71, 130, 145]
    player = {
        "player_id": 27, "name": "Jaxon Smith-Njigba", "team": "SEA", "league": "nfl",
        "evidence": [{"id": f"jsn-{i}", "available_at": "2026-10-25T22:00:00Z",
                      "date": f"2026-10-{20+i:02d}", "stats": {"rec_yds": y}}
                     for i, y in enumerate(recv)]}
    selected = {"id": "player_form:27", "kind": "player_form", "player": "Jaxon Smith-Njigba",
                "team": "SEA", "evidence_ids": [x["id"] for x in player["evidence"]],
                "evidence": deepcopy(player["evidence"])}
    facts = {"league": "nfl", "away": "CHI", "home": "SEA", "as_of": cutoff,
             "start_utc": "2026-11-03T01:15:00Z", "teams": {
                 "CHI": {"code": "CHI", "name": "Chicago Bears", "games": 7, "wins": 5,
                         "losses": 2, "record_verified": True, "evidence": game_rows},
                 "SEA": {"code": "SEA", "name": "Seattle Seahawks", "games": 7,
                         "wins": 4, "losses": 3, "record_verified": True}},
             "players": [player]}
    return {"story": story, "target_game_id": "2026_08_CHI_SEA", "league": "nfl",
            "angle": {"kind": "records", "lead_team": "SEA"},
            "manifest": {"selected_facts": [selected]}, "input_facts": facts,
            "mechanical_audit": {
                "nonempty_story": True,
                "selected_facts_have_linked_source_rows": True,
                "team_record_and_streak_claims_recompute": True,
                "head_to_head_claims_recompute": True,
                "league_rank_claims_recompute": True,
                "player_stat_claims_recompute": True,
                "player_team_attribution_matches_prose": True,
                "all_input_evidence_is_cutoff_safe": True,
                "target_game_absent_from_prior_evidence": True,
                "player_team_codes_match_matchup": True,
            }}


class RubricTests(unittest.TestCase):
    def test_dimension_weights_sum_to_100(self):
        from story_rubric import WEIGHTS
        self.assertEqual(sum(WEIGHTS.values()), 100)

    def test_repeat_scoring_is_deterministic(self):
        row = sample_row()
        self.assertEqual(grade_record(row), grade_record(row))
        self.assertEqual(grade_record(row)["rubric_version"], VERSION)

    def test_provenance_without_independent_audit_is_not_full_verification(self):
        row = sample_row()
        row.pop("mechanical_audit")
        result = grade_record(row)
        self.assertEqual(result["gate"], "needs-audit")
        self.assertEqual(result["dimensions"]["grounding"]["score"], 60)

    def test_false_numeric_claim_blocks_publication(self):
        row = sample_row()
        row["mechanical_audit"]["player_stat_claims_recompute"] = False
        result = grade_record(row)
        self.assertEqual(result["gate"], "blocked")
        self.assertEqual(result["dimensions"]["grounding"]["score"], 0)

    def test_future_source_blocks_publication(self):
        row = sample_row()
        row["manifest"]["selected_facts"][0]["evidence"][0]["available_at"] = "2026-11-04T00:00:00Z"
        self.assertEqual(grade_record(row)["gate"], "blocked")

    def test_asof_at_kickoff_blocks_publication(self):
        row = sample_row()
        row["input_facts"]["as_of"] = row["input_facts"]["start_utc"]
        self.assertEqual(grade_record(row)["gate"], "blocked")

    def test_research_jargon_is_not_fan_language(self):
        row = sample_row("The verified evidence shows a selected relationship gate cleared. "
                         "Jaxon Smith-Njigba leads Seattle against Chicago.")
        result = grade_record(row)
        self.assertEqual(result["dimensions"]["fan_voice"]["score"], 0)
        self.assertEqual(result["gate"], "review")

    def test_no_player_data_does_not_punish_or_force_filler(self):
        row = sample_row("Chicago visits Seattle for an NFC matchup. Both clubs will look to improve their records.")
        row["input_facts"]["players"] = []
        row["manifest"]["selected_facts"] = [{"id": "record", "kind": "record",
              "evidence": [{"id": "CHI-g0", "available_at": "2026-10-25T22:00:00Z"}],
              "evidence_ids": ["CHI-g0"]}]
        result = grade_record(row)
        self.assertFalse(result["dimensions"]["players"]["applicable"])

    def test_low_impact_one_of_four_100yard_claim_gets_penalized(self):
        row = sample_row("The 5-2 Bears visit the 4-3 Seahawks. "
                         "Seattle's Test Runner has topped 100 rushing yards in one of his last four games.")
        player = {"player_id": 9, "name": "Test Runner", "team": "SEA", "league": "nfl",
                  "evidence": [{"id": f"r{i}", "available_at": "2026-10-25T22:00:00Z",
                                "date": f"2026-10-{20+i:02d}",
                                "stats": {"rush_yds": val}} for i, val in enumerate([101, 20, 30, 25])]}
        row["input_facts"]["players"] = [player]
        row["manifest"]["selected_facts"] = [{"id": "player_form:9", "kind": "player_form",
                "team": "SEA", "player": "Test Runner", "evidence": player["evidence"],
                "evidence_ids": [x["id"] for x in player["evidence"]]}]
        g = grade_record(row)
        self.assertLess(g["dimensions"]["players"]["score"], 60)
        self.assertLess(g["dimensions"]["fan_voice"]["score"], 90)
        self.assertEqual(g["gate"], "review")

    def test_48hour_window_and_longrange_distinction(self):
        row = sample_row()
        close = grade_record(row)
        self.assertEqual(close["dimensions"]["freshness"]["score"], 100)
        row["input_facts"]["start_utc"] = "2026-12-30T01:15:00Z"
        far = grade_record(row)
        self.assertEqual(far["dimensions"]["freshness"]["score"], 15)

    def test_nfl_placeholder_time_cannot_get_full_freshness_credit(self):
        row = sample_row()
        row["start_utc_basis"] = "published_gameday_midnight_utc_boundary"
        self.assertFalse(grade_record(row)["dimensions"]["freshness"]["applicable"])

    def test_html_inlines_data_and_escapes_story(self):
        row = sample_row("The <b>Bears</b> meet the Seahawks. Jaxon Smith-Njigba has 112 receiving yards.")
        grade = grade_record(row)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "report.html"
            write_html([grade], p)
            contents = p.read_text()
            self.assertIn("<div id=\"cards\"></div>", contents)
            self.assertIn("--paper", contents)
            self.assertIn("The <b>Bears<\\/b>", contents)
            self.assertIn("Facts & evidence", contents)
            self.assertNotIn("https://cdn", contents)

    def test_batch_cli_inputs_preserve_scores(self):
        row = sample_row()
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "one.jsonl"
            p.write_text(json.dumps(row) + "\n")
            result = grade_jsonl(p)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["score"], grade_record(row)["score"])


class LedgerTests(unittest.TestCase):
    def test_append_only_versioned_ledger_is_idempotent(self):
        from story_rubric import append_ledger, read_grades
        grade = grade_record(sample_row())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            self.assertEqual(append_ledger([grade], path), 1)
            self.assertEqual(append_ledger([grade], path), 0)
            self.assertEqual(len(read_grades(path)), 1)


if __name__ == "__main__":
    unittest.main()
