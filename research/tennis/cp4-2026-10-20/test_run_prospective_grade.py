"""The prospective grader reads only frozen, pre-match locks and refuses cells below 200 matches."""
import datetime as dt
import json
import math
import random
import sqlite3
import unittest
from pathlib import Path

import run_prospective_grade as grader
import scoreboard_store
import tennis_count_distributions as tcd
import research_player_outcomes
import tennis_props_rate_backtest as rb

BASE = dt.datetime(2026, 10, 20, 10, 0, tzinfo=dt.timezone.utc)


def poisson(rng, mean):
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def games_pmf():
    weights = [math.exp(-0.5 * ((games - 22) / 3.5) ** 2) for games in range(12, 40)]
    return [w / sum(weights) for w in weights]


class ProspectiveGradeTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(scoreboard_store.SCHEMA)
        self.con.executescript(research_player_outcomes.DDL)
        self.serial = 0

    def _lock(self, league, locked_before_start=True, cells=("aces",), mean=4.0, observed=None, rng=None, double_faults=None):
        self.serial += 1
        game_id = str(900000 + self.serial)
        start = BASE + dt.timedelta(hours=1)
        locked = BASE if locked_before_start else start + dt.timedelta(minutes=5)
        self.con.execute(
            "INSERT INTO tennis_model_locks(league,game_date,game_id,start_time,locked_at,projection,model_version) "
            "VALUES(?,?,?,?,?,'{}','tennis-global-surface-elo-blend-v2')",
            (league, "2026-10-20", game_id, start.isoformat(), locked.isoformat()))
        rows = []
        for cell in cells:
            if cell == "total_games":
                rows.append({"cell": cell, "side": "match", "parameters": {}, "support_start": 12,
                             "pmf": games_pmf(), "trimmed_mass": 0.0})
                continue
            for side in ("home", "away"):
                rows.append({"cell": cell, "side": side, "parameters": {"family": "poisson", "mean": mean},
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
