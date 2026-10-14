"""Tests for isolated NHL per-model locking and official-result grading."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nhl_model_store import (NHLModelError, LOCK_LEAD, ensure_schema, grade_result, lock_feed,
                             normalize_official_result, export_locked, read_feed, DEFAULT_FEED,
                             parse_time)
from grade_nhl_models import grade_due
from routers.nhl_model import locks_payload

UTC = dt.timezone.utc
LOCK_AT = dt.datetime(2026, 10, 14, 16, 30, tzinfo=UTC)
GAME_ID = "2026020106"
MODEL_KEYS = ("B3_elo", "B5_xg_poisson", "B7_elo_xg_poisson")


def feed():
    models = {}
    for i, key in enumerate(MODEL_KEYS):
        models[key] = {
            "forecast_id": "forecast-%d" % i,
            "home_expected_goals": 3.0 + i / 10,
            "away_expected_goals": 2.7,
            "projected_total_goals": 5.7 + i / 10,
            "projected_goal_differential_home": 0.3 + i / 10,
            "home_win_probability": 0.55 + i / 100,
            "p_over_5.5": 0.51,
            "p_over_6.5": 0.35,
        }
    game = {
        "game_id": int(GAME_ID), "game_date": "2026-10-14",
        "scheduled_start_utc": "2026-10-14T18:00:00Z",
        "home_team": "WSH", "away_team": "MTL",
        "forecasted_at_utc": "2026-10-14T15:00:00Z",
        "feature_snapshot": {"as_of_utc": "2026-10-14T14:59:00Z", "elo_pre_game": {"home": 1500, "away": 1500}},
        "models": models,
        "markets": {"source": "Kalshi", "captured_at_utc": "2026-10-14T14:55:00Z", "usable": True},
    }
    return {"model_version": "nhl-prospective-2026-27-v1", "source": "test fixture", "games": [game]}


def final_document(game_id=GAME_ID):
    # Field shape checked against NHL's /v1/gamecenter/2026020002/landing payload.
    return {
        "id": int(game_id), "gameState": "OFF",
        "homeTeam": {"abbrev": "WSH", "score": 3},
        "awayTeam": {"abbrev": "MTL", "score": 2},
        "summary": {"scoring": [
            {"periodDescriptor": {"periodType": "REG"}, "goals": [
                {"teamAbbrev": {"default": "WSH"}}, {"teamAbbrev": {"default": "MTL"}},
                {"teamAbbrev": {"default": "WSH"}}, {"teamAbbrev": {"default": "MTL"}},
            ]},
            {"periodDescriptor": {"periodType": "OT"}, "goals": []},
            {"periodDescriptor": {"periodType": "SO"}, "goals": [
                {"teamAbbrev": {"default": "WSH"}},
            ]},
        ]},
    }


class NHLModelLocks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self.tmp.name, "nhl-model.db"))
        self.con.row_factory = sqlite3.Row
        ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_lock_stores_one_immutable_row_per_model_at_t90(self):
        report = lock_feed(self.con, feed(), LOCK_AT)
        self.assertEqual((report["due_games"], report["locked_rows"]), (1, 3))
        rows = self.con.execute("SELECT model_key,locked_at_utc FROM nhl_game_projections ORDER BY model_key").fetchall()
        self.assertEqual({row["model_key"] for row in rows}, set(MODEL_KEYS))
        self.assertEqual({row["locked_at_utc"] for row in rows}, {"2026-10-14T16:30:00Z"})
        market = self.con.execute("SELECT market_snapshot_json FROM nhl_game_projections LIMIT 1").fetchone()[0]
        self.assertFalse(json.loads(market)["comparison_usable_at_lock"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("UPDATE nhl_game_projections SET home_win_probability=.99")

    def test_committed_forecast_ledger_has_a_complete_three_model_set(self):
        ledger = read_feed(DEFAULT_FEED)
        self.assertEqual(ledger["model_version"], "nhl-prospective-2026-27-v1")
        self.assertGreaterEqual(len(ledger["games"]), 2)
        for game in ledger["games"]:
            self.assertEqual(set(game["models"]), set(MODEL_KEYS))
            self.assertTrue(game["feature_snapshot"].get("model_artifact_sha256"))

    def test_committed_model_probability_matrices_survive_the_lock_and_api_export(self):
        ledger = read_feed(DEFAULT_FEED)
        game = ledger["games"][0]
        lock_at = parse_time(game["scheduled_start_utc"]) - LOCK_LEAD
        lock_feed(self.con, {**ledger, "games": [game]}, lock_at)
        payload = export_locked(self.con, 2026)
        forecast = payload["games"][0]["models"]["B7_elo_xg_poisson"]
        self.assertEqual(len(forecast["joint_score_probability_matrix_home_rows_away_columns"]), 21)
        self.assertEqual(len(forecast["home_goal_marginal_probabilities"]), 21)

    def test_repeat_is_idempotent_but_changed_feed_cannot_rewrite_lock(self):
        lock_feed(self.con, feed(), LOCK_AT)
        repeat = lock_feed(self.con, feed(), LOCK_AT + dt.timedelta(minutes=1))
        self.assertEqual((repeat["locked_rows"], repeat["already_locked"]), (0, 3))
        changed = feed()
        changed["games"][0]["models"]["B3_elo"]["home_win_probability"] = .99
        with self.assertRaisesRegex(NHLModelError, "different immutable snapshot"):
            lock_feed(self.con, changed, LOCK_AT)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM nhl_game_projections").fetchone()[0], 3)

    def test_forecast_after_start_and_wrong_lock_window_fail_closed(self):
        late = feed()
        late["games"][0]["forecasted_at_utc"] = "2026-10-14T18:01:00Z"
        with self.assertRaisesRegex(NHLModelError, "after the scheduled game"):
            lock_feed(self.con, late, LOCK_AT)
        report = lock_feed(self.con, feed(), LOCK_AT + dt.timedelta(minutes=2))
        self.assertEqual((report["locked_rows"], report["missed_window"], report["missed_model_rows"]), (0, 1, 3))
        repeated = lock_feed(self.con, feed(), LOCK_AT + dt.timedelta(minutes=3))
        self.assertEqual((repeated["missed_window"], repeated["missed_model_rows"]), (0, 0))
        events = self.con.execute("SELECT COUNT(*) FROM nhl_projection_lock_events").fetchone()[0]
        self.assertEqual(events, 3)

    def test_feature_snapshot_created_after_lock_is_rejected(self):
        late_feature = feed()
        late_feature["games"][0]["forecasted_at_utc"] = "2026-10-14T16:32:00Z"
        late_feature["games"][0]["feature_snapshot"]["as_of_utc"] = "2026-10-14T16:31:00Z"
        with self.assertRaisesRegex(NHLModelError, "created after the lock timestamp"):
            lock_feed(self.con, late_feature, LOCK_AT)

    def test_shootout_winner_and_statistical_score_are_separate(self):
        result = normalize_official_result(GAME_ID, final_document())
        self.assertEqual(result["official_winner"], "home")
        self.assertEqual((result["official_home_goals"], result["official_away_goals"]), (3, 2))
        self.assertEqual((result["statistical_home_goals"], result["statistical_away_goals"]), (2, 2))
        self.assertEqual(result["shootout_decided"], 1)

    def test_not_final_waits_and_mismatched_score_summary_fails(self):
        pending = final_document()
        pending["gameState"] = "LIVE"
        self.assertIsNone(normalize_official_result(GAME_ID, pending))
        bad = final_document()
        bad["homeTeam"]["score"] = 4
        with self.assertRaisesRegex(NHLModelError, "does not reconcile"):
            normalize_official_result(GAME_ID, bad)

    def test_grading_is_per_model_and_keeps_official_winner_separate(self):
        lock_feed(self.con, feed(), LOCK_AT)
        result = normalize_official_result(GAME_ID, final_document())
        count = grade_result(self.con, GAME_ID, result, LOCK_AT + dt.timedelta(days=1),
                             "a" * 64, "fixture")
        self.assertEqual(count, 3)
        grades = self.con.execute("""SELECT model_key,official_winner,official_home_goals,
            statistical_home_goals,statistical_away_goals,shootout_decided FROM nhl_projection_grades""").fetchall()
        self.assertEqual(len(grades), 3)
        self.assertEqual({(row["official_winner"], row["official_home_goals"], row["statistical_home_goals"],
                           row["statistical_away_goals"], row["shootout_decided"]) for row in grades},
                         {("home", 3, 2, 2, 1)})

    def test_daily_grader_waits_four_hours_and_is_idempotent(self):
        lock_feed(self.con, feed(), LOCK_AT)
        calls = []
        def fetch(gid):
            calls.append(gid)
            return final_document(gid), "b" * 64
        before_grace = LOCK_AT + dt.timedelta(hours=3, minutes=59)
        report = grade_due(self.con, before_grace, False, fetch)
        self.assertEqual((report["graded_games"], calls), (0, []))
        after_grace = LOCK_AT + dt.timedelta(days=1)
        report = grade_due(self.con, after_grace, True, fetch)
        self.assertEqual((report["graded_games"], report["graded_model_rows"]), (1, 3))
        again = grade_due(self.con, after_grace, True, fetch)
        self.assertEqual((again["locked_games"], again["graded_games"], calls.count(GAME_ID)), (0, 0, 1))

    def test_public_export_contains_lock_and_separate_grade(self):
        lock_feed(self.con, feed(), LOCK_AT)
        result = normalize_official_result(GAME_ID, final_document())
        grade_result(self.con, GAME_ID, result, LOCK_AT + dt.timedelta(days=1), "c" * 64, "fixture")
        exported = export_locked(self.con, 2026)
        game = exported["games"][0]
        self.assertEqual(set(game["models"]), set(MODEL_KEYS))
        self.assertEqual(game["models"]["B3_elo"]["grade"]["official_home_goals"], 3)
        self.assertEqual(game["models"]["B3_elo"]["grade"]["statistical_home_goals"], 2)

    def test_read_api_reads_only_the_standalone_database_and_empty_state_is_explicit(self):
        missing = locks_payload(os.path.join(self.tmp.name, "not-created.sqlite3"), 2026)
        self.assertEqual((missing["state"], missing["games"]), ("awaiting_first_lock", []))
        lock_feed(self.con, feed(), LOCK_AT)
        path = os.path.join(self.tmp.name, "nhl-model.db")
        self.con.commit()
        payload = locks_payload(path, 2026)
        self.assertEqual(payload["state"], "available")
        self.assertEqual(set(payload["games"][0]["models"]), set(MODEL_KEYS))


if __name__ == "__main__":
    unittest.main()
