import json
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_narrative_relevance import (
    CORE_PREVIEW_SYSTEM,
    QUARANTINED_CATEGORIES,
    build_matchup_relationship,
    claim_cutoff_rejection,
    _claim_rows,
    render_relationship_preview,
    rank_matchup_candidates,
    run_local_inventory,
    _write_blind_packet,
)


AS_OF = "2026-11-01T09:00:00Z"
TARGET = {
    "league": "nfl", "game_id": "target-1", "target_game_id": "target-1", "away_team": "CHI",
    "home_team": "SEA", "start_utc": "2026-11-02T00:00:00Z",
    "as_of": AS_OF,
}


def relationship(**changes):
    item = {
        "candidate_id": "epa:CHI:SEA", "candidate_type": "team_relationship",
        "metric": "epa_per_scrimmage_play", "offense_team": "CHI",
        "defense_team": "SEA", "offense_recent": 0.18,
        "offense_baseline": -0.02, "defense_allowed_recent": 0.11,
        "defense_allowed_baseline": -0.04, "offense_recent_games": 3,
        "offense_baseline_games": 3, "defense_recent_games": 3,
        "defense_baseline_games": 3, "offense_recent_n": 120,
        "offense_baseline_n": 118, "defense_recent_n": 117,
        "defense_baseline_n": 121, "max_recent_age_days": 8,
        "opponent_quality_coverage": 3, "recent_opponent_win_pct": 0.58,
        "supporting_game_ids": ["g1", "g2", "g3", "g4", "g5", "g6"],
        "supporting_event_ids": ["g1:1", "g2:1", "g3:1"],
        "available_at": "2026-10-30T12:00:00Z",
        "occurred_at": "2026-10-29T23:00:00Z", "verified": True,
    }
    item.update(changes)
    return item


class ResearchNarrativeRelevanceTests(unittest.TestCase):
    def test_saved_baseline_prompt_matches_production_preview_prompt(self):
        source = Path(__file__).with_name("core_stories.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        opening = next(node.value for node in ast.walk(tree)
                       if isinstance(node, ast.Assign) and
                       any(isinstance(target, ast.Name) and target.id == "opening"
                           for target in node.targets))
        system = next(node.value for node in ast.walk(tree)
                      if isinstance(node, ast.Assign) and
                      any(isinstance(target, ast.Name) and target.id == "system"
                          for target in node.targets))

        def constant_string(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                return constant_string(node.left) + constant_string(node.right)
            self.fail(f"unexpected production prompt expression node: {ast.dump(node)}")

        expected = ast.literal_eval(opening.orelse) + constant_string(system.right)
        self.assertEqual(expected, CORE_PREVIEW_SYSTEM)

    def test_unrelated_accurate_facts_do_not_get_forced_into_a_relationship(self):
        item = relationship(metric="epa_per_scrimmage_play", defense_metric="turnovers")
        ranked = rank_matchup_candidates(TARGET, [item], AS_OF)
        self.assertFalse(ranked[0]["eligible"])
        self.assertIn("same_metric", ranked[0]["rejection_reasons"][0])

    def test_team_development_outweighs_unrelated_modest_player_fact(self):
        player = {
            "candidate_id": "player:7", "candidate_type": "player_outlier",
            "team": "CHI", "relevance_score": 9.9, "verified": True,
            "supporting_game_ids": ["g1"], "supporting_event_ids": ["g1:player:7"],
            "occurred_at": "2026-10-29T23:00:00Z",
            "available_at": "2026-10-30T12:00:00Z",
        }
        ranked = rank_matchup_candidates(TARGET, [player, relationship()], AS_OF)
        self.assertEqual("team_relationship", ranked[0]["candidate_type"])
        self.assertFalse(next(row for row in ranked if row["candidate_type"] == "player_outlier")["eligible"])

    def test_offense_and_opposing_defense_trend_produces_scored_relationship(self):
        result = build_matchup_relationship(TARGET, relationship(), AS_OF)
        self.assertTrue(result["eligible"])
        self.assertGreater(result["selection_score"], 0)
        self.assertEqual(10, result["score_components"]["matchup_relevance"])
        self.assertEqual(2, result["score_components"]["opponent_quality"])

    def test_duplicate_relationship_candidates_receive_repetition_penalty(self):
        ranked = rank_matchup_candidates(
            TARGET, [relationship(candidate_id="first"), relationship(candidate_id="second")], AS_OF)
        eligible = [row for row in ranked if row["eligible"]]
        self.assertEqual(0, eligible[0]["score_components"]["repetition_penalty"])
        self.assertEqual(1.5, eligible[1]["score_components"]["repetition_penalty"])

    def test_high_epa_play_is_never_rendered_as_game_winning(self):
        preview = render_relationship_preview(
            TARGET, build_matchup_relationship(TARGET, relationship(), AS_OF),
            team_names={"CHI": "Chicago Bears", "SEA": "Seattle Seahawks"})
        self.assertNotIn("game-winning", preview.lower())
        self.assertNotIn("won on", preview.lower())
        self.assertNotIn("decisive play", preview.lower())

    def test_quarantined_drive_and_fourth_down_categories_are_rejected(self):
        for category in sorted(QUARANTINED_CATEGORIES):
            result = claim_cutoff_rejection({
                "category": category, "occurred_at": "2026-10-29T23:00:00Z",
                "available_at": "2026-10-30T12:00:00Z", "verified": True,
                "supporting_game_ids": ["g"], "supporting_event_ids": ["g:1"],
            }, TARGET, AS_OF)
            self.assertIn("quarantined", result)

    def test_each_relationship_sentence_has_its_own_supporting_source_rows(self):
        item = relationship(evidence={
            "offense_recent": [{"game_id": "o1", "available_at": "2026-10-30T12:00:00Z",
                                "play_ids": ["1", "2"]}],
            "offense_baseline": [{"game_id": "o0", "available_at": "2026-10-20T12:00:00Z",
                                  "play_ids": ["3"]}],
            "defense_allowed_recent": [{"game_id": "d1", "available_at": "2026-10-30T12:00:00Z",
                                         "play_ids": ["4", "5"]}],
            "defense_allowed_baseline": [{"game_id": "d0", "available_at": "2026-10-20T12:00:00Z",
                                           "play_ids": ["6"]}],
        })
        scored = build_matchup_relationship(TARGET, item, AS_OF)
        preview = render_relationship_preview(
            TARGET, scored, team_names={"CHI": "Chicago Bears", "SEA": "Seattle Seahawks"})
        claims = _claim_rows(TARGET, scored, preview, AS_OF, "event_only")
        self.assertEqual(2, len(claims))
        self.assertEqual({"o0", "o1"}, set(claims[0]["supporting_game_ids"]))
        self.assertEqual({"d0", "d1"}, set(claims[1]["supporting_game_ids"]))
        self.assertTrue(all(claim["mechanical_verification"] == "pass" for claim in claims))

    def test_combined_standings_claim_links_each_source_game_row(self):
        selected = {
            "candidate_id": "streak:CHI:W3", "candidate_type": "team_streak",
            "category": "recent_streak", "verified": True,
            "supporting_game_ids": ["chi-1", "chi-2", "chi-3"],
            "supporting_event_ids": ["chi-1:final_result", "chi-2:final_result", "chi-3:final_result"],
            "available_at": "2026-10-30T12:00:00Z",
            "evidence": {"games": [{"game_id": "chi-3", "available_at": "2026-10-30T12:00:00Z"}]},
        }
        row = lambda game_id, available_at: {
            "game_id": game_id, "available_at": available_at, "date": available_at[:10],
            "result": "W", "for": 24, "against": 17,
        }
        records = {
            "CHI": {"games_detail": [row("chi-1", "2026-10-10T12:00:00Z"),
                                     row("chi-2", "2026-10-20T12:00:00Z")]},
            "SEA": {"games_detail": [row("sea-1", "2026-10-12T12:00:00Z")]},
        }
        preview = (
            "The Chicago Bears have won three straight games. "
            "The Chicago Bears are 5-1; the Seattle Seahawks are 3-3."
        )

        claims = _claim_rows(TARGET, selected, preview, AS_OF, "combined", records)
        standings = next(claim for claim in claims if claim["category"] == "standings_record")

        self.assertEqual({"chi-1", "chi-2", "sea-1"}, set(standings["supporting_game_ids"]))
        self.assertEqual({"chi-1", "chi-2", "sea-1"},
                         {evidence["game_id"] for evidence in standings["source_evidence"]})
        self.assertTrue(all(isinstance(evidence, dict) for evidence in standings["source_evidence"]))
        self.assertEqual("pass", standings["mechanical_verification"])

    def test_blind_evidence_is_linked_per_draft_without_exposing_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "packet"
            event_claim = {
                "variant": "event_only", "claim_text": "A verified fact.",
                "category": "recent_streak", "supporting_game_ids": ["g1"],
                "supporting_event_ids": ["g1:final_result"],
                "source_evidence": [{"game_id": "g1"}],
                "mechanical_verification": "pass",
            }
            combined_claim = {
                "variant": "combined", "claim_text": "A second verified fact.",
                "category": "standings_record", "supporting_game_ids": ["g2"],
                "supporting_event_ids": ["g2:final_result"],
                "source_evidence": [{"game_id": "g2"}],
                "mechanical_verification": "pass",
            }
            pair = {
                "target_game_id": "game-1", "league": "nfl",
                "matchup": {"away": "CHI", "home": "SEA"},
                "as_of": AS_OF, "kickoff_date": "2026-11-02",
                "blind_target_id": "target-001",
                "event_only_preview": "A verified fact.",
                "combined_preview": "A second verified fact.",
                "event_claims": [event_claim], "combined_claims": [combined_claim],
            }

            _write_blind_packet(outdir, [pair])
            read_jsonl = lambda path: [json.loads(line) for line in path.read_text().splitlines()]
            packet = read_jsonl(outdir / "blind_review_packet.jsonl")
            evidence = read_jsonl(outdir / "blind_evidence.jsonl")
            identity = read_jsonl(outdir.parent / "blind_identity_key.jsonl")
            identity_by_id = {row["blind_id"]: row["variant"] for row in identity}
            evidence_by_id = {row["blind_id"]: row for row in evidence}

            self.assertEqual(2, len(packet))
            self.assertEqual(2, len(evidence))
            for item in packet:
                linked = evidence_by_id[item["blind_id"]]
                claim = linked["claim_evidence"][0]
                self.assertNotIn("variant", linked)
                self.assertNotIn("variant", claim)
                self.assertEqual(item["preview"], claim["claim_text"])
                self.assertTrue(identity_by_id[item["blind_id"]] in {"event_only", "combined"})

    def test_cutoff_rejects_post_kickoff_asof_and_future_or_late_claim_evidence(self):
        self.assertIn("after_kickoff", claim_cutoff_rejection(
            {"category": "team_trend"}, {**TARGET, "start_utc": "2026-11-01T08:00:00Z"}, AS_OF))
        self.assertIn("occurred_after_cutoff", claim_cutoff_rejection({
            "category": "team_trend", "occurred_at": "2026-11-01T10:00:00Z",
            "available_at": "2026-11-01T10:00:00Z", "verified": True,
            "supporting_game_ids": ["g"], "supporting_event_ids": ["g:1"],
        }, TARGET, AS_OF))
        self.assertIn("not_available_at_cutoff", claim_cutoff_rejection({
            "category": "team_trend", "occurred_at": "2026-10-30T00:00:00Z",
            "available_at": "2026-11-01T10:00:00Z", "verified": True,
            "supporting_game_ids": ["g"], "supporting_event_ids": ["g:1"],
        }, TARGET, AS_OF))

    def test_insufficient_sample_and_ambiguous_event_facts_are_not_selected(self):
        small = relationship(offense_recent_games=2)
        ambiguous = {"candidate_id": "drive:x", "candidate_type": "drive_outcome",
                     "category": "drive_outcome", "verified": False}
        ranked = rank_matchup_candidates(TARGET, [small, ambiguous], AS_OF)
        self.assertFalse(any(row["eligible"] for row in ranked))
        self.assertTrue(any("minimum_sample" in " ".join(row["rejection_reasons"])
                            for row in ranked))

    def test_local_inventory_is_read_only_and_never_calls_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "picks.dev.test.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE nfl_schedule(game_id TEXT, season INTEGER, game_type TEXT, "
                        "gameday TEXT, gametime TEXT, away_team TEXT, home_team TEXT, espn TEXT, "
                        "ingested_at TEXT, away_score INTEGER, home_score INTEGER)")
            con.execute("CREATE TABLE nba_schedule(game_id TEXT, season INTEGER, season_type TEXT, "
                        "game_date TEXT, start_utc TEXT, away_team TEXT, home_team TEXT, status INTEGER, "
                        "ingested_at TEXT, away_score INTEGER, home_score INTEGER, espn TEXT)")
            con.execute("CREATE TABLE nfl_pbp(game_id TEXT, play_id INTEGER, season INTEGER, game_date TEXT, "
                        "posteam TEXT, defteam TEXT, play_type TEXT, epa REAL)")
            con.execute("CREATE TABLE team_game_stats(league TEXT, game_id TEXT, captured_at TEXT, "
                        "team_abbrev TEXT, pts_off_to INTEGER, source TEXT)")
            con.execute("CREATE TABLE player_game_logs(id INTEGER, player_id INTEGER, league TEXT, season INTEGER, "
                        "game_id TEXT, game_date TEXT, team TEXT, opponent TEXT, stats TEXT, ingested_at TEXT)")
            con.execute("CREATE TABLE nba_sportsdataverse_games(source_game_id TEXT, season INTEGER, "
                        "game_type TEXT, game_date TEXT, home TEXT, away TEXT, home_score INTEGER, "
                        "away_score INTEGER, ingested_at TEXT)")
            con.commit()
            con.close()
            with patch("urllib.request.urlopen", side_effect=AssertionError("network call")):
                result = run_local_inventory(str(db), AS_OF)
            self.assertEqual(1, result["query_only"])
            self.assertEqual(0, result["external_requests"])
            self.assertEqual(0, result["coverage"]["nfl_pbp"]["current_season_2026"]["plays"])


if __name__ == "__main__":
    unittest.main()
