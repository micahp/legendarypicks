"""Tests for lock_nfl_elo.py: the 90 minute window, the Elo carryover, and the stack arithmetic.

Temp DB, planted fit and ratings, no network. The fit of the stack itself (fit_stack) reads sixteen seasons
of backtests and is checked against the dev DB by hand, see docs/RESULTS-nfl-elo-and-era-2026-10-13.md.
"""
import datetime as dt
import math
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lock_nfl_elo as le  # noqa: E402
import nfl_lock as nl  # noqa: E402
import nfl_elo_replica as er  # noqa: E402
from test_nfl_lock import fit_for  # noqa: E402

UTC = dt.timezone.utc


class Window(unittest.TestCase):
    """Kickoffs are US Eastern: 13:00 on 2026-10-11 is 17:00Z, 20:20 is 00:20Z the next day."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT, week INT, "
            "home_team TEXT, away_team TEXT, location TEXT, home_score REAL, away_score REAL, "
            "spread_line REAL, total_line REAL, home_moneyline REAL, away_moneyline REAL, gameday TEXT, "
            "gametime TEXT, ingested_at TEXT)")
        for gid, gt in (("early", "13:00"), ("late", "16:25"), ("night", "20:20")):
            self.con.execute("INSERT INTO nfl_schedule VALUES (?,2026,'REG',5,'AAA','BBB','Home',NULL,NULL,"
                             "3.5,44.5,-170,145,'2026-10-11',?,'i0')", (gid, gt))
        nl.ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def ids(self, now):
        return [g for g, _, _ in le.due_games(self.con, now)]

    def test_only_games_inside_the_window_are_due(self):
        # early 17:00Z, late 20:25Z, night 00:20Z next day
        self.assertEqual(self.ids(dt.datetime(2026, 10, 11, 15, 29, tzinfo=UTC)), [])
        self.assertEqual(self.ids(dt.datetime(2026, 10, 11, 15, 30, tzinfo=UTC)), ["early"])
        self.assertEqual(self.ids(dt.datetime(2026, 10, 11, 19, 0, tzinfo=UTC)), ["late"])

    def test_a_started_game_is_never_due(self):
        self.assertNotIn("early", self.ids(dt.datetime(2026, 10, 11, 17, 0, tzinfo=UTC)))

    def test_a_game_kicking_off_after_midnight_utc_is_found_the_evening_before(self):
        self.assertEqual(self.ids(dt.datetime(2026, 10, 11, 23, 0, tzinfo=UTC)), ["night"])

    def test_a_game_already_locked_for_this_model_is_not_due_again(self):
        nl.start_run(self.con, "r", 2026, 5, le.version_for(2026), {}, model=le.MODEL)
        out = nl.lock_week(self.con, "r", 2026, 5, lambda h, a, n: (20.0, 17.0, 0.6),
                           now=dt.datetime(2026, 10, 11, 15, 31, tzinfo=UTC), min_lead=le.LEAD)
        self.assertEqual(out["new_locks"], 1)          # only `early` is inside its window
        self.assertEqual(out["too_early"], ["late", "night"])
        self.assertEqual(self.ids(dt.datetime(2026, 10, 11, 15, 40, tzinfo=UTC)), [])

    def test_another_models_lock_does_not_count(self):
        nl.start_run(self.con, "r", 2026, 5, "nfl-v1 other", {})
        nl.lock_week(self.con, "r", 2026, 5, lambda h, a, n: (20.0, 17.0, 0.6),
                     now=dt.datetime(2026, 10, 11, 15, 31, tzinfo=UTC))
        self.assertEqual(self.ids(dt.datetime(2026, 10, 11, 15, 40, tzinfo=UTC)), ["early"])

    def test_a_missing_gameday_is_not_scanned_and_the_week_lock_would_refuse_it(self):
        self.con.execute("UPDATE nfl_schedule SET gameday = NULL WHERE game_id = 'early'")
        self.assertEqual(self.ids(dt.datetime(2026, 10, 11, 15, 40, tzinfo=UTC)), [])


class Arithmetic(unittest.TestCase):
    def test_carryover_applies_only_to_a_team_that_has_not_played_this_season(self):
        rating = {"A": 1600.0, "B": 1400.0}
        season_of = {"A": 2025, "B": 2026}
        carried = 1600.0 * (2 / 3) + er.MEAN / 3
        self.assertAlmostEqual(le.elo_gap(rating, season_of, 2026, "A", "B", False), carried - 1400.0 + 65.0)
        self.assertAlmostEqual(le.elo_gap(rating, season_of, 2026, "A", "B", True), carried - 1400.0)

    def test_an_unrated_team_raises(self):
        with self.assertRaises(KeyError):
            le.elo_gap({"A": 1500.0}, {"A": 2026}, 2026, "A", "Z", False)

    def test_stack_projection_splits_v1_total_and_uses_the_stack_margin(self):
        fit = fit_for()
        beta, sigma = [1.0, 0.5, 0.01], 13.0
        rating = {t: 1500.0 for t in "ABCD"}
        rating.update({"AAA": 1550.0, "BBB": 1450.0})
        season_of = {t: 2026 for t in rating}
        ph, pa, p = le.projector(fit, beta, sigma, rating, season_of, 2026)("AAA", "BBB", False)
        v1h, v1a = le.nr_expected(fit, "AAA", "BBB", False)
        margin = 1.0 + 0.5 * (v1h - v1a) + 0.01 * (100.0 + 65.0)
        self.assertAlmostEqual(ph - pa, margin)
        self.assertAlmostEqual(ph + pa, v1h + v1a)
        self.assertAlmostEqual(p, 0.5 * (1.0 + math.erf(margin / sigma / math.sqrt(2.0))))

    def test_version_string_names_the_season_and_the_lead(self):
        self.assertIn("season=2026", le.version_for(2026))
        self.assertIn("train=2010-2025", le.version_for(2026))
        self.assertIn("lead=90min", le.version_for(2026))
        self.assertTrue(le.version_for(2026).startswith("nfl-v1+elo stack"))


if __name__ == "__main__":
    unittest.main()
