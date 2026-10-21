"""Tests for the prospective CP4 grader (research/tennis/cp4-2026-10-20/run_prospective_grade.py).

Fixtures are written with the same helper the lock sweep uses (tennis_count_distributions.store_distributions),
so the grader reads the real frozen-row shape. Where a number is checked, it is checked against a hand
calculation on a known distribution, not against the grader's own output.
"""
import datetime as dt
import json
import math
import random
import sqlite3
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "tennis" / "cp4-2026-10-20"))

import run_prospective_grade as grader  # noqa: E402
import research_player_outcomes  # noqa: E402
import scoreboard_store  # noqa: E402
import tennis_count_distributions as tcd  # noqa: E402
import tennis_props_rate_backtest as rb  # noqa: E402

BASE = dt.datetime(2026, 10, 20, 10, 0, tzinfo=dt.timezone.utc)
MATCH_DATE = "2026-10-20"  # every fixture match starts at 11:00 UTC on this date


def poisson(rng, mean):
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def games_pmf():
    weights = [math.exp(-0.5 * ((games - 22) / 3.5) ** 2) for games in range(12, 40)]
    return [w / sum(weights) for w in weights]


def sample_from(rng, pmf, start):
    draw, cumulative = rng.random(), 0.0
    for index, probability in enumerate(pmf):
        cumulative += probability
        if draw < cumulative:
            return start + index
    return start + len(pmf) - 1


def target(observed, pmf, start=0):
    return {"game_id": str(observed), "side": "home", "start": start, "pmf": pmf, "observed": observed,
            "support": None}


class ProspectiveGradeTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(scoreboard_store.SCHEMA)
        scoreboard_store.ensure_distribution_schema(self.con)
        self.con.executescript(research_player_outcomes.DDL)
        self.serial = 0

    def _lock(self, league, locked_before_start=True, cells=("aces",), mean=4.0, observed=None,
              double_faults=None, model_day=MATCH_DATE):
        self.serial += 1
        game_id = str(900000 + self.serial)
        start = BASE + dt.timedelta(hours=1)
        locked = BASE if locked_before_start else start + dt.timedelta(minutes=5)
        self.con.execute(
            "INSERT INTO tennis_model_locks(league,game_date,game_id,start_time,locked_at,projection,model_version) "
            "VALUES(?,?,?,?,?,'{}','tennis-global-surface-elo-blend-v2')",
            (league, MATCH_DATE, game_id, start.isoformat(), locked.isoformat()))
        rows = []
        for cell in cells:
            if cell == "total_games":
                rows.append({"cell": cell, "side": "match", "parameters": {"model_day": model_day},
                             "support_start": 12, "pmf": games_pmf(), "trimmed_mass": 0.0})
                continue
            for side in ("home", "away"):
                rows.append({"cell": cell, "side": side,
                             "parameters": {"family": "poisson", "mean": mean, "model_day": model_day},
                             "support_start": 0, "pmf": rb.poisson_pmf(mean, 0), "trimmed_mass": 0.0})
        tcd.store_distributions(self.con, league, game_id, locked.isoformat(), rows)
        if observed is not None and "aces" in cells:
            self.verified(league, game_id, aces=observed)
        if double_faults is not None:
            self.verified(league, game_id, double_faults=double_faults)
        return game_id

    def verified(self, league, game_id, aces=None, double_faults=None):
        """One verified outcome row per side, as research_player_outcomes writes them."""
        for side, index in (("home", 0), ("away", 1)):
            self.con.execute(
                "INSERT OR REPLACE INTO research_player_match_outcomes(tour,event,espn_game_id,espn_athlete_id,side,"
                "opponent_athlete_id,espn_status,aces,double_faults,verification_tier,provider,provider_match_id,"
                "official_url,raw_values,eligible_cp4,built_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (league, f"{league}-test", game_id, f"{side}-{game_id}", side, f"opp-{game_id}", "Final",
                 None if aces is None else aces[index], None if double_faults is None else double_faults[index],
                 "official_labelled", "test", game_id, None, "{}", 1, "2026-10-21T00:00:00+00:00"))

    def _final_total(self, game_id, total):
        payload = {"completed": True, "status": "Final", "home": {"sets": [total // 2]},
                   "away": {"sets": [total - total // 2]}}
        self.con.execute(
            "INSERT INTO scoreboard_snapshots(league,game_date,game_id,payload,state,start_time,fetched_at,source) "
            "VALUES('atp',?,?,?,'post',?,'2026-10-20T14:00:00+00:00','test')",
            (MATCH_DATE, game_id, json.dumps(payload), (BASE + dt.timedelta(hours=1)).isoformat()))

    # Accounting and the prospective boundary

    def test_only_locks_made_before_the_match_started_are_graded(self):
        self._lock("atp")
        self._lock("atp", locked_before_start=False)
        self.con.execute(
            "INSERT INTO tennis_model_locks(league,game_date,game_id,start_time,locked_at,projection,model_version) "
            "VALUES('atp','2026-10-20','1','2026-10-20T11:00:00+00:00','2026-10-20T10:00:00+00:00','{}',"
            "'tennis-global-surface-elo-blend-v2')")
        accounting = grader.load_frozen(self.con)["accounting"]
        self.assertEqual(accounting["locks_total"], 3)
        self.assertEqual(accounting["locks_with_frozen_distribution"], 1)
        self.assertEqual(accounting["excluded_not_prospective"], 1)
        self.assertEqual(accounting["locks_no_distribution_frozen"], 1)

    def test_a_cell_below_200_matches_reports_n_and_no_metrics(self):
        rng = random.Random(1)
        for _ in range(50):
            self._lock("atp", observed=(poisson(rng, 4.0), poisson(rng, 4.0)))
        entry = grader.grade(self.con)["cells"]["atp/aces"]
        self.assertEqual(entry["matches_graded"], 50)
        self.assertEqual(entry["verdict"], "INSUFFICIENT_PROSPECTIVE_DATA")
        self.assertNotIn("pit", entry)
        self.assertNotIn("gates", entry)

    def test_the_refusal_boundary_is_exactly_200_matches(self):
        rng = random.Random(4)
        for _ in range(199):
            self._lock("atp", observed=(poisson(rng, 4.0), poisson(rng, 4.0)))
        entry = grader.grade(self.con)["cells"]["atp/aces"]
        self.assertEqual((entry["matches_graded"], entry["verdict"]), (199, "INSUFFICIENT_PROSPECTIVE_DATA"))
        self._lock("atp", observed=(poisson(rng, 4.0), poisson(rng, 4.0)))
        entry = grader.grade(self.con)["cells"]["atp/aces"]
        self.assertEqual(entry["matches_graded"], 200)
        self.assertIn("pit", entry)
        self.assertIn(entry["verdict"], ("CALIBRATION_GATES_PASS", "CALIBRATION_GATES_FAIL"))

    def test_double_faults_are_not_graded_without_verified_rows(self):
        for _ in range(250):
            self._lock("atp", cells=("double_faults",))
        entry = grader.grade(self.con)["cells"]["atp/double_faults"]
        self.assertEqual(entry["matches_graded"], 0)
        self.assertEqual(entry["verdict"], "INSUFFICIENT_PROSPECTIVE_DATA")
        self.assertNotIn("pit", entry)

    def test_a_match_with_only_one_side_verified_is_not_graded(self):
        game_id = self._lock("atp", cells=("aces",))
        self.con.execute("DELETE FROM research_player_match_outcomes WHERE espn_game_id=? AND side='away'", (game_id,))
        self.assertIsNone(grader.observed_player_values(self.con, "atp", game_id, "aces"))

    def test_a_retirement_row_marked_ineligible_is_not_graded(self):
        game_id = self._lock("atp", cells=("aces",))
        self.con.execute("UPDATE research_player_match_outcomes SET eligible_cp4=0 WHERE espn_game_id=?", (game_id,))
        self.assertIsNone(grader.observed_player_values(self.con, "atp", game_id, "aces"))

    # Look-ahead guard

    def test_a_history_cutoff_after_the_match_date_fails_loudly(self):
        self._lock("atp", model_day="2026-10-21")
        with self.assertRaises(grader.LookAheadError):
            grader.load_frozen(self.con)

    def test_a_missing_history_cutoff_fails_loudly(self):
        self._lock("atp", model_day=None)
        with self.assertRaises(grader.LookAheadError):
            grader.load_frozen(self.con)

    def test_a_history_cutoff_on_the_match_date_is_allowed(self):
        self._lock("atp", model_day=MATCH_DATE)
        self.assertEqual(len(grader.load_frozen(self.con)["locks"]), 1)

    def test_the_guard_reads_the_match_date_on_the_utc_clock(self):
        self.assertEqual(grader.match_date_utc("2026-10-21T01:30:00+02:00"), "2026-10-20")
        with self.assertRaises(ValueError):
            grader.match_date_utc("2026-10-21T01:30:00")

    def test_a_guard_check_on_its_own(self):
        grader.check_no_look_ahead("2026-10-19", MATCH_DATE, "x")
        grader.check_no_look_ahead(MATCH_DATE, MATCH_DATE, "x")
        with self.assertRaises(grader.LookAheadError):
            grader.check_no_look_ahead("2026-10-21", MATCH_DATE, "x")
        with self.assertRaises(grader.LookAheadError):
            grader.check_no_look_ahead("", MATCH_DATE, "x")

    # Missing tables: a zero, reported, never a crash

    def test_missing_tables_report_zero_not_an_error(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        report = grader.grade(con)
        self.assertEqual(report["accounting"]["locks_total"], 0)
        self.assertFalse(report["accounting"]["distribution_table_present"])
        self.assertFalse(any(report["source_tables"].values()))
        for entry in report["cells"].values():
            self.assertEqual(entry["matches_graded"], 0)
            self.assertEqual(entry["verdict"], "INSUFFICIENT_PROSPECTIVE_DATA")
            self.assertNotIn("pit", entry)

    def test_locks_without_the_distribution_table_count_as_none_frozen(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(scoreboard_store.SCHEMA)
        for game_id in ("1", "2"):
            con.execute("INSERT INTO tennis_model_locks(league,game_date,game_id,start_time,locked_at,projection,"
                        "model_version) VALUES('atp','2026-10-20',?,'2026-10-20T11:00:00+00:00',"
                        "'2026-10-20T10:00:00+00:00','{}','tennis-global-surface-elo-blend-v2')", (game_id,))
        accounting = grader.load_frozen(con)["accounting"]
        self.assertEqual(accounting["locks_total"], 2)
        self.assertEqual(accounting["locks_no_distribution_frozen"], 2)
        self.assertFalse(accounting["distribution_table_present"])
        self.assertEqual(grader.grade(con)["cells"]["atp/aces"]["matches_graded"], 0)

    def test_a_missing_outcome_table_counts_as_zero_verified_matches(self):
        self.con.execute("DROP TABLE research_player_match_outcomes")
        for _ in range(250):
            self._lock("atp", cells=("aces",))
        report = grader.grade(self.con)
        self.assertFalse(report["source_tables"]["research_player_match_outcomes"])
        entry = report["cells"]["atp/aces"]
        self.assertEqual(entry["matches_graded"], 0)
        self.assertEqual(entry["skipped"]["outcome_missing"], 250)
        self.assertEqual(entry["verdict"], "INSUFFICIENT_PROSPECTIVE_DATA")

    def test_a_distribution_row_with_no_lock_is_counted_not_dropped_silently(self):
        tcd.store_distributions(self.con, "atp", "777", BASE.isoformat(), [{
            "cell": "aces", "side": "home", "parameters": {"model_day": MATCH_DATE}, "support_start": 0,
            "pmf": [1.0], "trimmed_mass": 0.0}])
        self.assertEqual(grader.load_frozen(self.con)["accounting"]["distribution_rows_without_lock"], 1)

    # Metrics on known distributions

    def test_pit_and_coverage_match_hand_values_on_a_known_distribution(self):
        # Uniform over 0..15 with each probability 1/16, exact in binary. Observed values cycle 1000 times.
        pmf = [1 / 16] * 16
        targets = [target(i % 16, pmf) for i in range(16 * 1000)]
        metrics = grader.metrics_for(targets, "atp", "aces")
        # Central intervals: 50% is [3, 11] (9 of 16 values), 80% is [1, 14] (14 of 16), 90% is [0, 15] (16 of 16).
        self.assertAlmostEqual(metrics["coverage"]["50"], 9 / 16)
        self.assertAlmostEqual(metrics["coverage"]["80"], 14 / 16)
        self.assertAlmostEqual(metrics["coverage"]["90"], 1.0)
        # PIT of value k is uniform on [k/16, (k+1)/16). Only value 0 can fall below 0.05 and only 15 above
        # 0.95, each for 0.8 of its 1/16 share, so both tails are 0.05.
        self.assertAlmostEqual(metrics["pit"]["share_below_0.05"], 0.05, delta=0.008)
        self.assertAlmostEqual(metrics["pit"]["share_above_0.95"], 0.05, delta=0.008)
        for decile in metrics["pit"]["deciles"]:
            self.assertAlmostEqual(decile, 0.1, delta=0.01)
        self.assertLess(metrics["pit"]["ks"], grader.KS_MAX)
        # The 95th and 99th percentiles are both 15, the top of the support, so nothing is above them.
        self.assertEqual(metrics["upper_tail"]["share_above_p95"], 0.0)
        self.assertEqual(metrics["upper_tail"]["share_above_p99"], 0.0)

    def test_upper_tail_shares_are_exact_on_a_dyadic_pmf(self):
        # P(X<=0)=1/2, P(X<=1)=31/32, P(X<=2)=1. So the 95th percentile is 1 and the 99th is 2.
        pmf = [0.5, 15 / 32, 1 / 32]
        probe = target(0, pmf)
        self.assertEqual(grader._quantile(probe, 0.95), 1)
        self.assertEqual(grader._quantile(probe, 0.99), 2)
        targets = [target(2, pmf) for _ in range(4)] + [target(0, pmf) for _ in range(96)]
        metrics = grader.metrics_for(targets, "atp", "aces")
        self.assertAlmostEqual(metrics["upper_tail"]["share_above_p95"], 0.04)
        self.assertEqual(metrics["upper_tail"]["share_above_p99"], 0.0)

    def test_a_forecast_too_narrow_for_its_outcomes_fails_the_upper_tail_gate(self):
        rng = random.Random(2)
        for _ in range(400):
            self._lock("atp", mean=4.0, observed=(poisson(rng, 6.0), poisson(rng, 6.0)))
        entry = grader.grade(self.con)["cells"]["atp/aces"]
        self.assertEqual(entry["matches_graded"], 400)
        self.assertFalse(entry["gates"]["upper_tail"])
        self.assertEqual(entry["verdict"], "CALIBRATION_GATES_FAIL")
        self.assertGreater(entry["upper_tail"]["share_above_p95"], 0.06)

    def test_a_calibrated_forecast_has_nominal_coverage_and_tails(self):
        rng = random.Random(3)
        for _ in range(1200):
            self._lock("atp", mean=4.0, observed=(poisson(rng, 4.0), poisson(rng, 4.0)))
        entry = grader.grade(self.con)["cells"]["atp/aces"]
        self.assertEqual(entry["matches_graded"], 1200)
        for label, nominal in grader.NOMINAL.items():
            self.assertGreaterEqual(entry["coverage"][label], nominal - 0.02)
        self.assertGreaterEqual(entry["upper_tail"]["share_above_p95"], 0.005)
        self.assertLessEqual(entry["upper_tail"]["share_above_p95"], 0.05)
        self.assertLess(entry["pit"]["ks"], 0.06)
        for row in entry["threshold_reliability"]:
            self.assertLess(abs(row["gap"]), 0.05)

    def test_total_games_are_graded_end_to_end_from_settled_scores(self):
        rng = random.Random(5)
        pmf = games_pmf()
        for index in range(200):
            game_id = self._lock("atp", cells=("total_games",))
            self._final_total(game_id, sample_from(rng, pmf, 12))
        entry = grader.grade(self.con)["cells"]["atp/total_games"]
        self.assertEqual(entry["matches_graded"], 200)
        self.assertIn("pit", entry)
        self.assertEqual(set(entry["coverage"]), {"50", "80", "90"})

    def test_observed_total_games_come_from_the_settled_set_scores(self):
        def insert(game_id, payload):
            self.con.execute(
                "INSERT INTO scoreboard_snapshots(league,game_date,game_id,payload,state,start_time,fetched_at,source) "
                "VALUES('atp','2026-10-20',?,?,'post','2026-10-20T11:00:00+00:00','2026-10-20T14:00:00+00:00','test')",
                (game_id, json.dumps(payload)))
        insert("1", {"completed": True, "status": "Final",
                     "home": {"sets": [6, 6]}, "away": {"sets": [4, 3]}})
        insert("2", {"completed": True, "status": "Retired", "home": {"sets": [6, 2]}, "away": {"sets": [4, 0]}})
        insert("3", {"completed": True, "status": "Final", "home": {"sets": [6, 6]}, "away": {"sets": [4]}})
        insert("4", {"completed": None, "status": "Final", "home": {"sets": [6, 6]}, "away": {"sets": [4, 3]}})
        self.assertEqual(grader.observed_games(self.con, "atp", "1"), 19)
        self.assertEqual(grader.observed_games(self.con, "atp", "4"), 19)
        self.assertIsNone(grader.observed_games(self.con, "atp", "2"))
        self.assertIsNone(grader.observed_games(self.con, "atp", "3"))


if __name__ == "__main__":
    unittest.main()
