"""Tests for the T-90 snapshot: timing, provenance, idempotence, immutability, failures."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import tempfile
import unittest

import t90_forecasts as t90
from nhl_model_store import (
    LOCK_LEAD, T90_GENERATE_LEAD, T90_PROTOCOL_VERSION, ensure_schema, iso_utc, lock_feed,
    parse_time, sha256_json,
)

UTC = dt.timezone.utc
MODEL_VERSION = "nhl-prospective-2026-27-v1"
START = "2026-10-16T23:00:00Z"
TARGET = dt.datetime(2026, 10, 16, 21, 30, tzinfo=UTC)  # start minus 90 minutes
GENERATED = dt.datetime(2026, 10, 16, 21, 20, tzinfo=UTC)


def game(gid=2026020118, start=START):
    return {"game_id": gid, "season": 2026, "game_date": "2026-10-16", "start_time_utc": start,
            "home_team": "VGK", "away_team": "CGY", "neutral_site": False}


def rows_for(g, generated_at=GENERATED, home_eg=3.0, away_eg=2.5, source_dates=("2026-10-15", "2026-10-14")):
    feature_snapshot = {
        "as_of_utc": iso_utc(generated_at),
        "game_id": str(g["game_id"]), "home_team": g["home_team"], "away_team": g["away_team"],
        "scheduled_start_utc": g["start_time_utc"],
        "feature_max_source_dates": {"home": source_dates[0], "away": source_dates[1]},
        "xg_source_hashes": {g["home_team"]: "a" * 64, g["away_team"]: "b" * 64},
        "schedule_source": {"url": "https://example.test/schedule", "sha256": "c" * 64,
                            "retrieved_at_utc": iso_utc(generated_at)},
        "model_artifact_sha256": "d" * 64,
    }
    out = []
    for key in ("B3_elo", "B5_xg_poisson", "B7_elo_xg_poisson"):
        out.append({"forecast_id": "%s-%s" % (key, "f" * 8), "game_id": str(g["game_id"]),
                    "season": g["season"], "game_date": g["game_date"],
                    "scheduled_start_utc": g["start_time_utc"],
                    "forecasted_at_utc": iso_utc(generated_at), "home_team": g["home_team"],
                    "away_team": g["away_team"], "model_name": key, "model_version": MODEL_VERSION,
                    "model_artifact_sha256": "d" * 64, "feature_snapshot": feature_snapshot,
                    "feature_snapshot_sha256": "e" * 64,
                    "home_expected_goals": home_eg, "away_expected_goals": away_eg,
                    "projected_total_goals": home_eg + away_eg,
                    "projected_goal_differential_home": home_eg - away_eg,
                    "home_win_probability": 0.55, "away_win_probability": 0.45,
                    "p_over_5.5": 0.5, "p_under_5.5": 0.5, "p_over_6.5": 0.35, "p_under_6.5": 0.65,
                    "p_home_minus_1_5": 0.26, "p_home_plus_1_5": 0.8,
                    "p_away_minus_1_5": 0.2, "p_away_plus_1_5": 0.74})
    return out


class T90Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self.tmp.name, "t90.db"))
        self.con.row_factory = sqlite3.Row
        ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def freeze(self, g=None, generated_at=GENERATED, **kwargs):
        g = g or game()
        sources = {(int(g["game_id"]), key): {"forecast_id": "ledger-%s" % key}
                   for key in ("B3_elo", "B5_xg_poisson", "B7_elo_xg_poisson")}
        written = t90.freeze_snapshot(self.con, g, rows_for(g, generated_at=generated_at, **kwargs),
                                      generated_at=generated_at, source_rows=sources)
        self.con.commit()
        return written


class Timing(T90Base):
    def test_plan_waits_for_the_generation_lead_and_ignores_started_games(self):
        g = game()
        self.assertEqual(t90.plan(self.con, [g], TARGET - T90_GENERATE_LEAD - dt.timedelta(seconds=1)), [])
        self.assertEqual(len(t90.plan(self.con, [g], TARGET - T90_GENERATE_LEAD)), 1)
        # Past the cutoff but before puck drop it is still lockable, just late.
        self.assertEqual(len(t90.plan(self.con, [g], TARGET + dt.timedelta(minutes=30))), 1)
        self.assertEqual(len(t90.plan(self.con, [g], TARGET + dt.timedelta(minutes=1))), 1)
        # At and after puck drop the window has passed.
        self.assertEqual(t90.plan(self.con, [g], parse_time(START)), [])
        self.assertEqual(t90.plan(self.con, [g], parse_time(START) + dt.timedelta(hours=1)), [])

    def test_a_late_generation_records_a_negative_lead_rather_than_lying_about_it(self):
        late = TARGET + dt.timedelta(minutes=4)
        self.freeze(generated_at=late)
        row = self.con.execute("SELECT target_lock_utc, generated_at_utc, lead_seconds "
                               "FROM nhl_t90_forecasts LIMIT 1").fetchone()
        self.assertEqual(row["target_lock_utc"], "2026-10-16T21:30:00Z")
        self.assertEqual(row["generated_at_utc"], iso_utc(late))
        self.assertEqual(row["lead_seconds"], -240)

    def test_lead_is_recorded_for_an_on_time_generation(self):
        self.freeze()
        row = self.con.execute("SELECT lead_seconds FROM nhl_t90_forecasts LIMIT 1").fetchone()
        self.assertEqual(row["lead_seconds"], int((TARGET - GENERATED).total_seconds()))


class Idempotence(T90Base):
    def test_plan_stops_listing_a_game_once_a_snapshot_exists(self):
        g = game()
        self.assertEqual(len(t90.plan(self.con, [g], TARGET)), 1)
        self.freeze()
        self.assertEqual(t90.plan(self.con, [g], TARGET), [])

    def test_a_second_snapshot_for_the_same_game_is_refused_not_overwritten(self):
        self.freeze()
        before = [tuple(r) for r in self.con.execute(
            "SELECT model_key, snapshot_sha256 FROM nhl_t90_forecasts ORDER BY model_key")]
        with self.assertRaises(sqlite3.IntegrityError):
            self.freeze(home_eg=9.0)
        after = [tuple(r) for r in self.con.execute(
            "SELECT model_key, snapshot_sha256 FROM nhl_t90_forecasts ORDER BY model_key")]
        self.assertEqual(before, after)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM nhl_t90_forecasts").fetchone()[0], 3)


class Provenance(T90Base):
    def test_a_snapshot_is_self_contained_and_carries_its_sources(self):
        self.freeze()
        rows = self.con.execute("SELECT * FROM nhl_t90_forecasts ORDER BY model_key").fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["model_key"] for r in rows}, {"B3_elo", "B5_xg_poisson", "B7_elo_xg_poisson"})
        self.assertEqual({r["protocol_version"] for r in rows}, {T90_PROTOCOL_VERSION})
        self.assertEqual({r["model_version"] for r in rows}, {MODEL_VERSION})
        self.assertEqual({r["feature_cutoff_utc"] for r in rows}, {"2026-10-15"})
        self.assertEqual({r["features_as_of_utc"] for r in rows}, {iso_utc(GENERATED)})
        self.assertEqual({r["model_artifact_sha256"] for r in rows}, {"d" * 64})
        self.assertTrue(all(r["feature_source_sha256"] for r in rows))
        # The link back to the research ledger row this decision supersedes.
        self.assertEqual({r["source_forecast_id"] for r in rows},
                         {"ledger-B3_elo", "ledger-B5_xg_poisson", "ledger-B7_elo_xg_poisson"})
        self.assertTrue(all(r["source_ledger_sha256"] == sha256_json({"forecast_id": r["source_forecast_id"]})
                            for r in rows))

    def test_the_stored_snapshot_needs_nothing_from_the_research_ledger(self):
        self.freeze()
        payload = json.loads(self.con.execute(
            "SELECT snapshot_json FROM nhl_t90_forecasts WHERE model_key='B7_elo_xg_poisson'").fetchone()[0])
        self.assertEqual(payload["game_id"], 2026020118)
        self.assertEqual(payload["forecasted_at_utc"], iso_utc(GENERATED))
        self.assertEqual(payload["features_as_of_utc"], iso_utc(GENERATED))
        self.assertIn("feature_snapshot", payload)
        forecast = payload["models"]["B7_elo_xg_poisson"]
        # The score distribution is derived inline, so no second ledger is required to price it.
        for key in t90.DISTRIBUTION_KEYS:
            self.assertIn(key, forecast)
        self.assertIn("score_distribution_source", forecast)
        self.assertEqual(len(forecast["score_distribution_goal_support"]), 21)

    def test_t90_payload_is_feed_shaped_and_the_lock_path_accepts_it(self):
        self.freeze()
        payload = t90.t90_payload(self.con, 2026)
        self.assertEqual(payload["model_version"], MODEL_VERSION)
        self.assertEqual(len(payload["games"]), 1)
        self.assertEqual(set(payload["games"][0]["models"]), {"B3_elo", "B5_xg_poisson", "B7_elo_xg_poisson"})
        report = lock_feed(self.con, payload, TARGET)
        self.assertEqual((report["due_games"], report["locked_rows"]), (1, 3))
        # No quote was captured, so the forecast locks and no recommendation is manufactured.
        self.assertEqual((report["pick_rows"], report["unpriced_models"]), (0, 3))
        row = self.con.execute("SELECT protocol_version, features_as_of_utc FROM nhl_game_projections LIMIT 1").fetchone()
        self.assertEqual(row["features_as_of_utc"], iso_utc(GENERATED))


class Failures(T90Base):
    def test_the_failure_log_is_append_only_and_counts_a_repeat_once(self):
        g = game()
        first = t90.record_failure(self.con, g["game_id"], "B3_elo", MODEL_VERSION, "generation",
                                   "features_stale", "latest feature source date 2026-10-01",
                                   GENERATED, TARGET)
        second = t90.record_failure(self.con, g["game_id"], "B3_elo", MODEL_VERSION, "generation",
                                    "features_stale", "latest feature source date 2026-10-01",
                                    GENERATED, TARGET)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM nhl_t90_failures").fetchone()[0], 1)
        # A different stage is a separate fact, not a duplicate.
        self.assertTrue(t90.record_failure(self.con, g["game_id"], "B3_elo", MODEL_VERSION,
                                           "quote_capture", "quote_stale", None, GENERATED, TARGET))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM nhl_t90_failures").fetchone()[0], 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("UPDATE nhl_t90_failures SET reason='other'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("DELETE FROM nhl_t90_failures")

    def test_a_date_only_feature_cutoff_is_read_as_a_date(self):
        # feature_max_source_dates are plain dates, so they cannot go through parse_time,
        # which requires a timezone. Staleness is judged in whole days for the same reason:
        # a date at midnight compared against a wall clock inflates the age by up to a day.
        from nhl_model_store import T90_FEATURE_MAX_AGE
        self.assertEqual(t90.as_date("2026-10-15"), dt.date(2026, 10, 15))
        self.assertEqual(t90.as_date("2026-10-15T18:00:00Z"), dt.date(2026, 10, 15))
        self.assertIsNone(t90.as_date(""))
        self.assertIsNone(t90.as_date("not-a-date"))
        today = dt.date(2026, 10, 16)
        self.assertLessEqual(today - t90.as_date("2026-10-15"), T90_FEATURE_MAX_AGE)
        self.assertGreater(today - t90.as_date("2026-10-06"), T90_FEATURE_MAX_AGE)
        with self.assertRaises(Exception):
            parse_time("2026-10-15")

    def test_the_protocol_effective_dates_are_recorded(self):
        rows = {r["protocol_version"]: r for r in self.con.execute("SELECT * FROM nhl_protocol_versions")}
        self.assertEqual(set(rows), {"legacy-immediate", T90_PROTOCOL_VERSION})
        self.assertLess(rows["legacy-immediate"]["effective_from_utc"], rows[T90_PROTOCOL_VERSION]["effective_from_utc"])
        self.assertIn("T-90", rows[T90_PROTOCOL_VERSION]["description"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("UPDATE nhl_protocol_versions SET effective_from_utc='2020-01-01T00:00:00Z'")


class Immutability(T90Base):
    def test_snapshots_cannot_be_rewritten_or_deleted(self):
        self.freeze()
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("UPDATE nhl_t90_forecasts SET lead_seconds=0")
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("DELETE FROM nhl_t90_forecasts")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM nhl_t90_forecasts").fetchone()[0], 3)


class LedgerCompatibility(unittest.TestCase):
    def test_generating_never_touches_the_research_ledger(self):
        rp = t90.run_pipeline
        before = os.path.getmtime(rp.LEDGER), len(rp.read_jsonl(rp.LEDGER))
        appended = []
        original = rp.append_forecasts
        rp.append_forecasts = lambda rows: appended.append(rows)
        try:
            g = game()
            tmp = tempfile.TemporaryDirectory()
            con = sqlite3.connect(os.path.join(tmp.name, "t.db"))
            con.row_factory = sqlite3.Row
            ensure_schema(con)
            sources = {(int(g["game_id"]), key): {"forecast_id": "ledger-%s" % key}
                       for key in ("B3_elo", "B5_xg_poisson", "B7_elo_xg_poisson")}
            t90.freeze_snapshot(con, g, rows_for(g), generated_at=GENERATED, source_rows=sources)
            con.close()
            tmp.cleanup()
        finally:
            rp.append_forecasts = original
        self.assertEqual(appended, [])
        self.assertEqual((os.path.getmtime(rp.LEDGER), len(rp.read_jsonl(rp.LEDGER))), before)


if __name__ == "__main__":
    unittest.main()
