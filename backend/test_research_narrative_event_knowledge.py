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
    PUBLISH_NFL_FOURTH_DOWN_FACTS,
    _select_preview_facts,
    _audit_nfl_fourth_down,
    _classify_nfl_fourth_down_attempt,
    _duplicate_audit,
    _nba_play_by_play_tables,
    espn_summary_metadata,
    nba_com_game_metadata,
    normalize_summary_timeline,
    _render_deterministic_preview,
    _player_log_available_at,
    _recent_team_streak_facts,
    _schedule_available_at,
    _unsupported_numbers,
    load_local_narrative_events,
    open_readonly,
)


class ResearchNarrativeEventKnowledgeTests(unittest.TestCase):
    def test_player_log_availability_does_not_mistake_recent_ingestion_for_capture_time(self):
        captured, basis = _player_log_available_at(
            "2026-10-31", "2026-11-01 06:15:00")
        self.assertEqual("2026-11-01T12:00:00Z", captured)
        self.assertEqual("player_game_logs_game_date_plus_one_day_12_utc_conservative", basis)

    def test_player_log_availability_uses_chronological_boundary_for_backfills(self):
        captured, basis = _player_log_available_at(
            "2025-03-01", "2026-10-31 06:15:00")
        self.assertEqual("2025-03-02T12:00:00Z", captured)
        self.assertEqual("player_game_logs_game_date_plus_one_day_12_utc_conservative", basis)

    def test_schedule_availability_uses_near_game_capture_and_backfill_cutoffs(self):
        captured, basis = _schedule_available_at("2026-10-31", "2026-11-01T03:00:00Z")
        self.assertEqual("2026-11-01T03:00:00Z", captured)
        self.assertEqual("schedule.ingested_at_near_game_date", basis)
        backfilled, basis = _schedule_available_at("2025-03-01", "2026-10-31T03:00:00Z")
        self.assertEqual("2025-03-02T12:00:00Z", backfilled)
        self.assertEqual("schedule_game_date_plus_one_day_12_utc_conservative", basis)

    def test_recent_team_streak_uses_three_completed_local_games_and_cutoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "picks.dev.test.db"
            con = sqlite3.connect(db_path)
            con.row_factory = sqlite3.Row
            con.execute("""CREATE TABLE nba_schedule(
                game_id TEXT,season INTEGER,season_type TEXT,game_date TEXT,start_utc TEXT,
                home_team TEXT,away_team TEXT,home_score INTEGER,away_score INTEGER,
                status INTEGER,ingested_at TEXT)""")
            con.executemany("INSERT INTO nba_schedule VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
                ("g1", 2027, "REG", "2026-10-20", "2026-10-20T23:00:00Z",
                 "ATL", "BOS", 110, 100, 3, "2026-10-21T03:00:00Z"),
                ("g2", 2027, "REG", "2026-10-22", "2026-10-22T23:00:00Z",
                 "NY", "ATL", 99, 105, 3, "2026-10-23T03:00:00Z"),
                ("g3", 2027, "REG", "2026-10-24", "2026-10-24T23:00:00Z",
                 "ATL", "BOS", 120, 101, 3, "2026-10-25T03:00:00Z"),
            ])
            con.commit()
            con.close()
            with open_readonly(db_path) as db:
                target = {"league": "nba", "season": 2027, "home_team": "ATL",
                          "away_team": "BOS", "start_utc": "2026-10-28T23:00:00Z"}
                facts = _recent_team_streak_facts(db, target, "2026-10-27T00:00:00Z")
                self.assertEqual(1, len(facts))
                self.assertEqual("win", facts[0]["calculation"]["streak_result"])
                self.assertEqual(3, facts[0]["calculation"]["streak_length"])
                self.assertEqual({"g1", "g2", "g3"}, set(facts[0]["supporting_game_ids"]))
                self.assertEqual([], _recent_team_streak_facts(
                    db, target, "2026-10-24T00:00:00Z"))

    def test_fourth_down_positive_epa_without_conversion_is_failed(self):
        plays = [
            {"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
             "ydstogo": 2, "yards_gained": 1, "success": 1,
             "series_result": "Turnover on downs", "play_type": "pass"},
            {"play_id": 2, "posteam": "BUF", "defteam": "NYJ", "down": 1,
             "series": 2, "play_type": "run"},
        ]
        self.assertEqual("failed", _classify_nfl_fourth_down_attempt(plays, 0)["outcome"])

    def test_fourth_down_conversion_with_nonpositive_epa_is_converted(self):
        plays = [
            {"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
             "series": 1, "ydstogo": 3, "yards_gained": 4, "success": 0,
             "series_result": "First down", "play_type": "run"},
            {"play_id": 2, "posteam": "NYJ", "defteam": "BUF", "down": 1,
             "series": 2, "play_type": "pass"},
        ]
        self.assertEqual("converted", _classify_nfl_fourth_down_attempt(plays, 0)["outcome"])

    def test_fourth_down_defensive_penalty_requires_possession_progression(self):
        plays = [
            {"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
             "series": 1, "ydstogo": 5, "yards_gained": 0, "success": 0,
             "series_result": "First down", "penalty": 1, "penalty_team": "BUF",
             "play_type": "pass"},
            {"play_id": 2, "posteam": "NYJ", "defteam": "BUF", "down": 1,
             "series": 2, "play_type": "run"},
        ]
        result = _classify_nfl_fourth_down_attempt(plays, 0)
        self.assertEqual("converted", result["outcome"])
        self.assertEqual("defensive_penalty", result["reason"])

    def test_fourth_down_first_down_label_without_series_transition_is_unresolved(self):
        plays = [{"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
                  "series": 1, "ydstogo": 5, "yards_gained": 0, "success": 0,
                  "series_result": "First down", "penalty": 1, "penalty_team": "BUF",
                  "play_type": "pass"}]
        result = _classify_nfl_fourth_down_attempt(plays, 0)
        self.assertEqual("unresolved", result["outcome"])
        self.assertEqual("first_down_conflicts_with_next_series", result["reason"])

    def test_fourth_down_goal_to_go_conversion_uses_series_transition(self):
        plays = [
            {"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
             "series": 8, "ydstogo": 1, "yards_gained": 1, "success": 0,
             "series_result": "First down", "play_type": "run"},
            {"play_id": 2, "posteam": "NYJ", "defteam": "BUF", "down": 1,
             "series": 9, "play_type": "run"},
        ]
        self.assertEqual("converted", _classify_nfl_fourth_down_attempt(plays, 0)["outcome"])

    def test_fourth_down_touchdown_is_converted(self):
        plays = [{"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
                  "ydstogo": 1, "yards_gained": 1, "touchdown": 1,
                  "series_result": "Touchdown", "success": 0, "play_type": "run"}]
        self.assertEqual("converted", _classify_nfl_fourth_down_attempt(plays, 0)["outcome"])

    def test_fourth_down_without_terminal_or_next_state_is_unresolved(self):
        plays = [{"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
                  "ydstogo": 7, "yards_gained": 2, "success": 1, "play_type": "pass"}]
        self.assertEqual("unresolved", _classify_nfl_fourth_down_attempt(plays, 0)["outcome"])

    def test_fourth_down_audit_records_corrected_outcomes_without_publishing_quarantined_facts(self):
        plays = [
            {"play_id": 1, "posteam": "NYJ", "defteam": "BUF", "down": 4,
             "ydstogo": 2, "yards_gained": 2, "series": 1, "series_result": "First down",
             "success": 0, "play_type": "run"},
            {"play_id": 2, "posteam": "NYJ", "defteam": "BUF", "down": 1,
             "series": 2, "play_type": "pass"},
        ]
        audit = _audit_nfl_fourth_down(plays)
        self.assertEqual({"attempts": 1, "converted": 1, "failed": 0, "unresolved": 0},
                         {key: audit[key] for key in ("attempts", "converted", "failed", "unresolved")})
        self.assertFalse(audit["success_epa_used"])
        self.assertFalse(PUBLISH_NFL_FOURTH_DOWN_FACTS)

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
        self.assertEqual("", preview)
        self.assertNotIn("won", preview)
        self.assertEqual([], _unsupported_numbers(preview, context))

    def test_preview_ranker_limits_category_repeats_and_filters_low_value_claims(self):
        target = {"league": "nba", "home_team": "DET", "away_team": "TOR",
                  "start_utc": "2026-12-08T00:00:00Z"}
        facts = [
            {"category": "comeback", "verified": True, "team": "DET",
             "source_game_date": "2026-12-07", "source_game_opponent": "BOS",
             "event_id": "comeback", "calculation": {"largest_deficit_overcome": 15}},
            {"category": "turnover_events", "verified": True, "team": None,
             "source_game_date": "2026-12-07", "event_id": "turnovers-1",
             "calculation": {"giveaways_by_team": {"DET": 4}}},
            {"category": "turnover_events", "verified": True, "team": None,
             "source_game_date": "2026-12-06", "event_id": "turnovers-2",
             "calculation": {"giveaways_by_team": {"DET": 5}}},
            {"category": "player_outlier", "verified": True, "team": "TOR",
             "source_game_date": "2026-12-07", "source_game_opponent": "BKN",
             "event_id": "player-pts", "calculation": {"player_id": "p1", "stat": "PTS",
                 "value": 30, "prior_mean": 18.5, "prior_games": 10, "z_score": 2.8}},
            {"category": "player_outlier", "verified": True, "team": "TOR",
             "source_game_date": "2026-12-07", "source_game_opponent": "BKN",
             "event_id": "player-fantasy", "calculation": {"player_id": "p1", "stat": "fpts_ppr",
                 "value": 100, "prior_mean": 10, "prior_games": 10, "z_score": 99}},
            {"category": "team_box_summary", "verified": True, "team": "DET",
             "source_game_date": "2026-11-01", "event_id": "stale-box",
             "calculation": {"turnovers": 22}},
        ]
        selected = _select_preview_facts(target, facts, {"p1": "Jamal Murray"})
        self.assertEqual(["comeback", "player_outlier"], [fact["category"] for fact in selected])
        preview = _render_deterministic_preview(
            target, facts, {"p1": "Jamal Murray"},
            {"DET": "Detroit Pistons", "TOR": "Toronto Raptors", "BOS": "Boston Celtics",
             "BKN": "Brooklyn Nets"})
        self.assertEqual(2, preview.count(". ") + (1 if preview else 0))
        self.assertIn("The Detroit Pistons erased a 15-point deficit", preview)
        self.assertIn("Jamal Murray scored 30 points", preview)
        self.assertNotIn("fantasy", preview.lower())
        self.assertNotIn("turnovers", preview.lower())

    def test_team_streak_preview_uses_full_names_and_clean_grammar(self):
        fact = {"category": "recent_streak", "verified": True, "team": "DET",
                "source_game_date": "2026-12-07", "source_game_opponent": "BOS",
                "event_id": "streak", "calculation": {"streak_length": 3,
                    "streak_result": "win"}}
        preview = _render_deterministic_preview(
            {"league": "nba", "home_team": "DET", "away_team": "BOS",
             "start_utc": "2026-12-08T00:00:00Z"}, [fact], {},
            {"DET": "Detroit Pistons", "BOS": "Boston Celtics"})
        self.assertEqual(
            "The Detroit Pistons have won three straight games, most recently beating the Boston Celtics on Dec 7.",
            preview)

    def test_preview_relevance_uses_shared_team_aliases(self):
        fact = {"category": "player_outlier", "verified": True, "team": "LA",
                "source_game_date": "2026-10-25", "event_id": "alias-player",
                "calculation": {"player_id": "p1", "stat": "carries", "value": 12,
                                "prior_mean": 5, "prior_games": 10, "z_score": 3}}
        selected = _select_preview_facts(
            {"league": "nfl", "home_team": "LAR", "away_team": "SEA",
             "start_utc": "2026-11-02T00:00:00Z"}, [fact], {"p1": "Player One"})
        self.assertEqual([fact], selected)

    def test_player_preview_uses_chronological_game_reference_and_deduplicates_player(self):
        facts = [{"category": "player_outlier", "verified": True, "team": "DET",
                  "source_game_date": "2026-03-31", "source_game_opponent": "TOR",
                  "calculation": {"player_id": "p1", "stat": "AST", "value": 12,
                                  "prior_mean": 2.526, "prior_games": 57, "z_score": 3}},
                 {"category": "player_outlier", "verified": True, "team": "DET",
                  "source_game_date": "2026-03-31", "source_game_opponent": "TOR",
                  "calculation": {"player_id": "p1", "stat": "PTS", "value": 30,
                                  "prior_mean": 10.37, "prior_games": 57, "z_score": 3}}]
        preview = _render_deterministic_preview(
            {"league": "nba", "home_team": "DET", "away_team": "TOR"}, facts,
            {"p1": "Tobias Harris"},
            {"DET": "Detroit Pistons", "TOR": "Toronto Raptors"})
        self.assertEqual(
            "Tobias Harris recorded 12 assists for the Detroit Pistons against the Toronto Raptors on Mar 31; the prior 57-game average was 2.5 assists.",
            preview)
        self.assertNotIn("in its", preview)
        self.assertEqual([], _unsupported_numbers(preview, facts))

    def test_numeric_scan_does_not_treat_digits_inside_team_names_as_claims(self):
        self.assertEqual(["10"], _unsupported_numbers(
            "The Philadelphia 76ers won 10 games.", []))

    def test_combined_stat_outlier_has_readable_label_and_team_attribution(self):
        fact = {"category": "player_outlier", "verified": True, "team": "GS",
                "source_game_date": "2026-10-28", "source_game_opponent": "MIN",
                "event_id": "pra", "calculation": {"player_id": "p1", "stat": "PRA",
                    "value": 58, "prior_mean": 28.8, "prior_games": 10, "z_score": 3}}
        preview = _render_deterministic_preview(
            {"league": "nba", "home_team": "GS", "away_team": "LAC"}, [fact],
            {"p1": "Stephen Curry"},
            {"GS": "Golden State Warriors", "LAC": "LA Clippers",
             "MIN": "Minnesota Timberwolves"})
        self.assertEqual(
            "Stephen Curry recorded 58 combined points, rebounds, and assists for the Golden State Warriors against the Minnesota Timberwolves on Oct 28; the prior 10-game average was 28.8 combined points, rebounds, and assists.",
            preview)

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
                    series REAL,series_result TEXT,down REAL,ydstogo REAL,yards_gained REAL,
                    pass_attempt REAL,
                    rush_attempt REAL,success REAL,interception REAL,fumble_lost REAL,
                    touchdown REAL,two_point_attempt REAL,play_type TEXT,penalty REAL,
                    penalty_team TEXT,qtr REAL,game_seconds_remaining REAL
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
            con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?,?,?,?)",
                        ("2026_04_LA_WAS", 2026, 4, "2026-10-25", "LA", "WAS", 0, 0, "402TEST"))
            con.executemany("INSERT INTO nfl_pbp VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                ("2026_04_GB_DET", 1, "GB", "DET", 1, 1, "Turnover", 4, 1, 0,
                 1, 0, 1, 1, 0, 0, 0, "pass", 0, None, 1, 100),
                ("2026_04_GB_DET", 2, "DET", "GB", 2, 2, "Touchdown", 1, 1, 1,
                 0, 1, 0, 0, 0, 1, 0, "run", 0, None, 1, 90),
                ("2026_04_GB_DET", 3, "DET", "GB", 2, 2, "Touchdown", None, 0, 0,
                 0, 0, 1, 0, 0, 0, 0, "extra_point", 0, None, 1, 85),
            ])
            con.execute("INSERT INTO nfl_pbp VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("2026_04_LA_WAS", 1, "LA", "WAS", 1, 1, "Turnover", 4, 1, 0,
                         1, 0, 0, 1, 0, 0, 0, "pass", 0, None, 1, 100))
            con.execute("INSERT INTO nfl_snap_counts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (1, 99, 2026, 4, "GB", 62, .95, 0, 0, 3, .15))
            con.execute("INSERT INTO team_game_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("nba", "401NBA", "2026-10-30T23:59:00Z", "GS", 12,
                         40, 25, 8, 6, 17, .48, .37, .81, None, None))
            con.executemany("INSERT INTO team_game_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                ("nfl", "401TEST", "2026-10-26T12:00:00Z", "GB", 1,
                 None, None, None, None, None, None, None, None, None, None),
                ("nfl", "401TEST", "2026-10-26T12:00:00Z", "DET", 0,
                 None, None, None, None, None, None, None, None, None, None),
                ("nfl", "402TEST", "2026-10-26T12:00:00Z", "LAR", 1,
                 None, None, None, None, None, None, None, None, None, None),
                ("nfl", "402TEST", "2026-10-26T12:00:00Z", "WSH", 0,
                 None, None, None, None, None, None, None, None, None, None),
            ])
            con.commit()
            con.close()

            games = [
                {"league": "nfl", "source_game_id": "2026_04_GB_DET", "game_id": "2026_04_GB_DET"},
                {"league": "nfl", "source_game_id": "2026_04_LA_WAS", "game_id": "2026_04_LA_WAS"},
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
        self.assertEqual("incomplete_missing_scoring_result_fields",
                         nfl["scoring_reconciliation"]["status"])
        self.assertFalse(nfl["available_at_is_ingestion_time"])
        self.assertFalse(any(f["category"] == "fourth_down_attempts" for f in result["facts"]))
        self.assertEqual(1, nfl["fourth_down_audit"]["failed"])
        self.assertFalse(any(f["category"] in {"drive_summary", "scoring_summary"}
                             for f in result["facts"]))
        self.assertTrue(any(f["category"] == "turnover_events" for f in result["facts"]))
        self.assertTrue(nfl["turnover_snapshot_matches"])
        self.assertTrue(nfl["turnover_narrative_fact_emitted"])
        alias_nfl = next(row for row in result["rows"]
                         if row["game_id"] == "2026_04_LA_WAS")
        self.assertTrue(alias_nfl["turnover_snapshot_matches"])
        alias_recon = alias_nfl["turnover_reconciliation"]
        self.assertEqual(1, alias_recon["LAR"]["pbp_giveaways"])
        self.assertEqual(0, alias_recon["WSH"]["pbp_giveaways"])
        self.assertTrue(any(f["category"] == "snap_workload" for f in result["facts"]))
        nba = next(row for row in result["rows"] if row["league"] == "nba")
        self.assertEqual("local_team_box_only", nba["status"])
        nba_fact = next(f for f in result["facts"] if f["league"] == "nba")
        self.assertEqual("2026-10-30T23:59:00Z", nba_fact["available_at"])
        self.assertEqual("0022500001", nba_fact["game_id"])


if __name__ == "__main__":
    unittest.main()
