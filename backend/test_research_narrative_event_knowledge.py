import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_narrative_event_knowledge import (
    ResearchAuditError,
    _THEME_EVENT_CATEGORIES,
    _assert_metadata_only,
    _attach_nba_event_ids,
    _scoreboard_games,
    _article_detector_comparison,
    _duplicate_audit,
    _nba_play_by_play_tables,
    espn_summary_metadata,
    nba_com_game_metadata,
    normalize_summary_timeline,
    _render_deterministic_preview,
    _unsupported_numbers,
    load_local_narrative_events,
    open_readonly,
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
        context = [{"category": "final_lead_change", "team": "SAC",
                    "source_game_date": "2025-12-04", "source_game_opponent": "GS",
                    "calculation": {"play_type": "Free Throw - 2 of 2"}}]
        preview = _render_deterministic_preview(
            {"home_team": "MEM", "away_team": "SAC"}, context, {})
        self.assertEqual("SAC took the lead on a free throw in its Dec 4 game against GS.", preview)
        self.assertNotIn("won", preview)
        self.assertEqual([], _unsupported_numbers(preview, context))

    def test_player_preview_uses_chronological_game_reference_and_deduplicates_player(self):
        facts = [{"category": "player_outlier", "team": "DET",
                  "source_game_date": "2026-03-31", "source_game_opponent": "TOR",
                  "calculation": {"player_id": "p1", "stat": "AST", "value": 6,
                                  "prior_mean": 2.526, "prior_games": 57}},
                 {"category": "player_outlier", "team": "DET",
                  "source_game_date": "2026-03-31", "source_game_opponent": "TOR",
                  "calculation": {"player_id": "p1", "stat": "PTS", "value": 22,
                                  "prior_mean": 10.37, "prior_games": 57}}]
        preview = _render_deterministic_preview(
            {"home_team": "DET", "away_team": "TOR"}, facts, {"p1": "Tobias Harris"})
        self.assertEqual(
            "Tobias Harris recorded 6 assists in the Mar 31 game against TOR, after averaging 2.5 across 57 earlier games.",
            preview)
        self.assertNotIn("in its", preview)
        self.assertEqual([], _unsupported_numbers(preview, facts))

    def test_nba_play_by_play_audit_does_not_match_player_table_names(self):
        self.assertEqual(["nba_play_by_play", "nba_pbp"], _nba_play_by_play_tables(
            ["nba_player_boxes_nbacom", "nba_play_by_play", "nba_pbp"]))

    def test_defense_headline_requires_defensive_evidence_category(self):
        self.assertEqual({"defensive_stop", "defensive_takeaway"},
                         _THEME_EVENT_CATEGORIES["defense"])

    def test_local_events_use_read_only_lp_tables_without_external_requests(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "picks.dev.test.db"
            con = sqlite3.connect(db_path)
            con.executescript("""
                CREATE TABLE nfl_schedule(
                    game_id TEXT,season INTEGER,week INTEGER,gameday TEXT,
                    away_team TEXT,home_team TEXT,away_score INTEGER,home_score INTEGER,espn TEXT
                );
                CREATE TABLE nfl_pbp(
                    game_id TEXT,play_id REAL,posteam TEXT,defteam TEXT,drive REAL,
                    series REAL,series_result TEXT,down REAL,pass_attempt REAL,
                    rush_attempt REAL,success REAL,interception REAL,fumble_lost REAL,
                    touchdown REAL,two_point_attempt REAL,play_type TEXT
                );
                CREATE TABLE team_game_stats(
                    league TEXT,game_id TEXT,captured_at TEXT,team_abbrev TEXT,
                    turnovers INTEGER,rebounds INTEGER,assists INTEGER,steals INTEGER,
                    blocks INTEGER,fouls INTEGER,fg_pct REAL,tp_pct REAL,ft_pct REAL,
                    largest_lead INTEGER,lead_changes INTEGER
                );
                CREATE TABLE scoring_plays(
                    league TEXT,game_id TEXT,play_id TEXT,captured_at TEXT,period INTEGER,
                    clock TEXT,away_score INTEGER,home_score INTEGER,team_abbrev TEXT,play_type TEXT
                );
                CREATE TABLE nfl_snap_counts(
                    id INTEGER,player_id INTEGER,season INTEGER,week INTEGER,team TEXT,
                    off_snaps INTEGER,off_pct REAL,def_snaps INTEGER,def_pct REAL,
                    st_snaps INTEGER,st_pct REAL
                );
                CREATE TABLE team_game_results(
                    league TEXT,game_id TEXT,team TEXT,score_for REAL,score_against REAL
                );
            """)
            con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?,?,?,?)",
                        ("2026_04_GB_DET", 2026, 4, "2026-10-25", "GB", "DET", 0, 7, "401TEST"))
            con.executemany("INSERT INTO nfl_pbp VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                ("2026_04_GB_DET", 1, "GB", "DET", 1, 1, "Turnover on downs", 4, 1, 0, 0, 0, 0, 0, 0, "pass"),
                ("2026_04_GB_DET", 2, "GB", "DET", 1, 1, "Turnover", 1, 1, 0, 0, 1, 0, 0, 0, "pass"),
                ("2026_04_GB_DET", 3, "DET", "GB", 2, 2, "Touchdown", 1, 0, 1, 1, 0, 0, 1, 0, "run"),
                ("2026_04_GB_DET", 4, "DET", "GB", 2, 2, "Touchdown", None, 0, 0, 1, 0, 0, 0, 0, "extra_point"),
            ])
            con.execute("INSERT INTO nfl_snap_counts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (1, 99, 2026, 4, "GB", 62, .95, 0, 0, 3, .15))
            con.execute("INSERT INTO team_game_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("nba", "401NBA", "2026-10-30T23:59:00Z", "GS", 12,
                         40, 25, 8, 6, 17, .48, .37, .81, None, None))
            con.commit()
            con.close()

            games = [
                {"league": "nfl", "source_game_id": "2026_04_GB_DET", "game_id": "2026_04_GB_DET"},
                {"league": "nba", "source_game_id": "0022500001", "espn_event_id": "401NBA",
                 "game_date": "2026-10-30", "home": "GS", "away": "LAL"},
            ]
            with open_readonly(db_path) as db:
                self.assertEqual(1, db.execute("PRAGMA query_only").fetchone()[0])
                with patch("urllib.request.urlopen") as urlopen:
                    result = load_local_narrative_events(db, games)
                urlopen.assert_not_called()

        nfl = next(row for row in result["rows"] if row["league"] == "nfl")
        self.assertEqual("local_pbp_processed", nfl["status"])
        self.assertEqual("matched", nfl["scoring_reconciliation"]["status"])
        self.assertFalse(nfl["available_at_is_ingestion_time"])
        self.assertTrue(any(f["category"] == "fourth_down_attempts" for f in result["facts"]))
        self.assertTrue(any(f["category"] == "turnover_events" for f in result["facts"]))
        self.assertTrue(any(f["category"] == "snap_workload" for f in result["facts"]))
        nba = next(row for row in result["rows"] if row["league"] == "nba")
        self.assertEqual("local_team_box_only", nba["status"])
        nba_fact = next(f for f in result["facts"] if f["league"] == "nba")
        self.assertEqual("2026-10-30T23:59:00Z", nba_fact["available_at"])
        self.assertEqual("0022500001", nba_fact["game_id"])


if __name__ == "__main__":
    unittest.main()
