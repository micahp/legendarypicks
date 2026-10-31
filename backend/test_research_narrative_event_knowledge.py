import json
import unittest

from research_narrative_event_knowledge import (
    ResearchAuditError,
    _assert_metadata_only,
    _attach_nba_event_ids,
    _scoreboard_games,
    _article_detector_comparison,
    _duplicate_audit,
    espn_summary_metadata,
    nba_com_game_metadata,
    normalize_summary_timeline,
    _render_deterministic_preview,
    _unsupported_numbers,
)


class ResearchNarrativeEventKnowledgeTests(unittest.TestCase):
    def test_nba_metadata_parser_discards_embedded_story_text(self):
        data = {
            "props": {"pageProps": {
                "story": {"header": {"headline": "Warriors rally after 25-point deficit"},
                          "byline": "Janie McCauley", "bytitle": "AP",
                          "date": "2026-10-30T00:00:00Z", "storyType": "gameRecap",
                          "content": "article body must not escape parser"},
                "game": {"gameRecap": {"title": "Warriors game recap",
                                        "permalink": "https://www.nba.com/game/0022600023"}},
            }}
        }
        game = {"game_page_id": "0022600023", "espn_event_id": "401909285",
                "game_date": "2026-10-30", "home_team": "GS", "away_team": "LAL",
                "sample_role": "article_coverage_sample", "season_phase": "regular"}
        row = nba_com_game_metadata(
            '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) +
            "</script>", game)
        self.assertEqual("401909285", row["game_id"])
        self.assertEqual("0022600023", row["publisher_game_id"])
        self.assertEqual("ap_origin", row["origin_class"])
        self.assertIn("comeback", row["headline_theme_candidates"])
        self.assertNotIn("content", row)
        self.assertNotIn("story", row)
        _assert_metadata_only(row)

    def test_espn_summary_allows_only_article_metadata(self):
        game = {"espn_event_id": "401872964", "game_date": "2026-10-01",
                "home_team": "CLE", "away_team": "PIT", "sample_role": "four_week_event_sample",
                "season_phase": "regular"}
        row = espn_summary_metadata({"article": {
            "headline": "Late field goal decides Browns win", "source": "AP",
            "published": "2026-10-02T03:55:42Z", "type": "Recap",
            "description": "short description", "story": "full article body",
            "links": {"web": {"href": "https://www.espn.com/nfl/recap/1"}},
        }}, game)
        self.assertEqual("AP", row["publisher"])
        self.assertEqual("ap_origin", row["origin_class"])
        self.assertNotIn("description", row)
        self.assertNotIn("story", row)
        _assert_metadata_only(row)

    def test_scoreboard_crosswalk_requires_team_sides(self):
        rows = _scoreboard_games({"events": [{"id": "1", "date": "2026-11-01T18:00:00Z",
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"abbreviation": "DET"}},
                {"homeAway": "away", "team": {"abbreviation": "GB"}},
            ]}]}]}, "nfl")
        self.assertEqual([{"league": "nfl", "event_id": "1", "date": "2026-11-01T18:00:00Z",
                           "home_team": "DET", "away_team": "GB"}], rows)

    def test_artifact_guard_rejects_article_body_fields(self):
        with self.assertRaises(ResearchAuditError):
            _assert_metadata_only({"publisher": "AP", "body": "not allowed"})

    def test_weekly_rollup_is_excluded_from_per_game_headline_comparison(self):
        rows = _article_detector_comparison(
            [{"league": "nfl", "publisher": "nfl.com", "status": "found",
              "coverage_scope": "weekly_rollup", "headline": "What We Learned"}],
            [], set())
        self.assertEqual([], rows)

    def test_nba_crosswalk_skips_nfl_targets(self):
        targets = [{"league": "nfl", "home_team": "ARI", "away_team": "GB"}]
        _attach_nba_event_ids(targets, [])
        self.assertEqual("ARI", targets[0]["home_team"])

    def test_duplicate_audit_counts_only_comparable_metadata(self):
        result = _duplicate_audit([
            {"status": "found", "headline": "Same recap", "published_at": "2026-10-01T00:00:00Z",
             "url": "https://example.com/recap"},
            {"status": "found", "headline": "Same recap", "published_at": "2026-10-01T12:00:00Z",
             "url": "https://example.com/recap"},
            {"status": "found", "headline": "Date missing", "url": "https://example.com/other"},
        ])
        self.assertEqual(2, result["headline_date_comparable_articles"])
        self.assertEqual(1, result["duplicate_article_copies"])
        self.assertEqual(1, result["url_duplicate_copies"])

    def test_nfl_summary_timeline_uses_only_scoring_snapshots_and_estimated_clock(self):
        game = {"league": "nfl", "espn_event_id": "1"}
        payload = {"header": {"competitions": [{"date": "2026-10-01T20:00:00Z"}]},
                   "scoringPlays": [{"id": "p1", "period": {"number": 1},
                       "clock": {"displayValue": "2:59"}, "homeScore": 0, "awayScore": 7,
                       "team": {"abbreviation": "AWY"}, "type": {"text": "Passing Touchdown"},
                       "text": "must never be kept"}]}
        plays, scope, time_basis = normalize_summary_timeline(
            payload, game, "2026-10-31T19:00:00Z")
        self.assertEqual("scoring_plays_only", scope)
        self.assertEqual("scheduled_kickoff_plus_game_clock_estimate", time_basis)
        self.assertEqual("2026-10-01T20:12:01Z", plays[0]["occurred_at"])
        self.assertNotIn("text", plays[0])
        self.assertEqual(7, plays[0]["away_score"])

    def test_nba_summary_timeline_uses_monotonic_game_clock_estimate(self):
        game = {"league": "nba", "espn_event_id": "1"}
        payload = {"header": {"competitions": [{"date": "2025-10-21T23:30:00Z"}]},
                   "plays": [{"id": "p1", "period": {"number": 1},
                    "clock": {"displayValue": "11:48"}, "wallclock": "2025-10-21T20:00:12Z",
                    "homeScore": 2, "awayScore": 0, "team": {"abbreviation": "GSW"},
                    "type": {"text": "Jump Shot"}, "text": "must never be kept"}]}
        plays, scope, time_basis = normalize_summary_timeline(
            payload, game, "2026-10-31T19:00:00Z")
        self.assertEqual("full_play_by_play", scope)
        self.assertEqual("scheduled_kickoff_plus_game_clock_estimate", time_basis)
        self.assertEqual("GS", plays[0]["team"])
        self.assertEqual("2025-10-21T23:30:12Z", plays[0]["occurred_at"])
        self.assertNotIn("text", plays[0])

    def test_deterministic_preview_removes_attempt_counts_from_play_type(self):
        context = [{"category": "decisive_score", "team": "SAC",
                    "calculation": {"play_type": "Free Throw - 2 of 2"}}]
        preview = _render_deterministic_preview(
            {"home_team": "MEM", "away_team": "SAC"}, context, {})
        self.assertEqual("SAC won its previous game on a free throw.", preview)
        self.assertEqual([], _unsupported_numbers(preview, context))


if __name__ == "__main__":
    unittest.main()
