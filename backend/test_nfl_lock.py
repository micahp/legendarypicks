"""Tests for nfl_lock.py. Temp DB, planted-truth fit, no network.

The lock rules are checked against the broken behaviour they exist to prevent:
overwriting a locked projection, locking after a result, and a half-written week.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_lock as nl  # noqa: E402
import nfl_ratings as nr  # noqa: E402

TEAMS = ["AAA", "BBB", "CCC", "DDD"]
GAMES_W5 = [("g1", "AAA", "BBB", "Home"), ("g2", "CCC", "DDD", "Neutral")]


def fit_for(o_shift=0.0):
    games = []
    for a in TEAMS:
        for b in TEAMS:
            if a != b:
                games.append(nr.Game(0.0, a, b, 22.0 + {"AAA": 3, "BBB": 1, "CCC": -1, "DDD": -3}[a]
                                     - {"AAA": 3, "BBB": 1, "CCC": -1, "DDD": -3}[b] + o_shift,
                                     22.0, False))
    return nr.fit(games, TEAMS, cap=None, prior_games=1e-6)


class LockDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT, "
            "week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL, "
            "away_score REAL, spread_line REAL, total_line REAL)")
        for gid, h, a, loc in GAMES_W5:
            self.con.execute("INSERT INTO nfl_schedule VALUES (?,2026,'REG',5,?,?,?,NULL,NULL,"
                             "3.5,44.5)", (gid, h, a, loc))
        nl.ensure_schema(self.con)

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def rows(self, gid):
        return self.con.execute("SELECT locked, projected_margin, as_of FROM nfl_projections "
                                "WHERE game_id = ? ORDER BY id", (gid,)).fetchall()


class FirstLock(LockDB):
    def test_first_run_locks_every_game_in_the_week(self):
        out = nl.lock_week(self.con, 2026, 5, fit_for(), 13.4, "v1", as_of="2026-10-09T10:00Z")
        self.assertEqual(out, {"new_locks": 2, "refreshes": 0, "skipped": []})
        for gid, _, _, _ in GAMES_W5:
            locked = [r for r in self.rows(gid) if r[0] == 1]
            self.assertEqual(len(locked), 1, gid)

    def test_market_line_is_stored_with_the_lock(self):
        nl.lock_week(self.con, 2026, 5, fit_for(), 13.4, "v1", as_of="t0")
        got = nl.locked_projection(self.con, "g1")
        self.assertEqual(got["market_home_margin"], 3.5)
        self.assertEqual(got["market_total"], 44.5)


class NeverOverwrite(LockDB):
    def test_second_run_refreshes_without_touching_the_lock(self):
        nl.lock_week(self.con, 2026, 5, fit_for(0.0), 13.4, "v1", as_of="t0")
        first = nl.locked_projection(self.con, "g1")
        out = nl.lock_week(self.con, 2026, 5, fit_for(5.0), 13.4, "v1", as_of="t1")
        self.assertEqual(out, {"new_locks": 0, "refreshes": 2, "skipped": []})
        after = nl.locked_projection(self.con, "g1")
        self.assertEqual(after["projected_margin"], first["projected_margin"])
        self.assertEqual(after["as_of"], "t0")
        refreshed = [r for r in self.rows("g1") if r[0] == 0]
        self.assertEqual(len(refreshed), 1)
        self.assertNotAlmostEqual(refreshed[0][1], first["projected_margin"], places=3)

    def test_database_index_refuses_a_second_lock(self):
        nl.lock_week(self.con, 2026, 5, fit_for(), 13.4, "v1", as_of="t0")
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "INSERT INTO nfl_projections (season, week, game_id, home_team, away_team, "
                "neutral, projected_margin, projected_total, p_home_win, sigma, locked, as_of, "
                "model_version) VALUES (2026,5,'g1','AAA','BBB',0,1,44,0.5,13.4,1,'t9','v1')")


class Refusals(LockDB):
    def test_locking_after_a_result_is_refused_and_writes_nothing(self):
        # g2 is already scored, g1 is not. The whole week must be refused, with no partial lock.
        self.con.execute("UPDATE nfl_schedule SET home_score=24, away_score=20 WHERE game_id='g2'")
        self.con.commit()
        with self.assertRaises(ValueError):
            nl.lock_week(self.con, 2026, 5, fit_for(), 13.4, "v1", as_of="t0")
        n, = self.con.execute("SELECT COUNT(*) FROM nfl_projections").fetchone()
        self.assertEqual(n, 0)

    def test_missing_team_rating_is_refused(self):
        fit = nr.fit([nr.Game(0.0, "AAA", "BBB", 20.0, 17.0)], ["AAA", "BBB"], prior_games=1.0)
        with self.assertRaises(KeyError):
            nl.lock_week(self.con, 2026, 5, fit, 13.4, "v1", as_of="t0")

    def test_empty_week_is_refused(self):
        with self.assertRaises(ValueError):
            nl.lock_week(self.con, 2026, 9, fit_for(), 13.4, "v1", as_of="t0")

    def test_bad_sigma_is_refused(self):
        with self.assertRaises(ValueError):
            nl.lock_week(self.con, 2026, 5, fit_for(), 0.0, "v1", as_of="t0")


class SkipPlayed(LockDB):
    def test_skip_mode_locks_unplayed_and_leaves_played_unwritten(self):
        self.con.execute("UPDATE nfl_schedule SET home_score=24, away_score=20 WHERE game_id='g2'")
        self.con.commit()
        out = nl.lock_week(self.con, 2026, 5, fit_for(), 13.4, "v1", as_of="t0", skip_scored=True)
        self.assertEqual(out, {"new_locks": 1, "refreshes": 0, "skipped": ["g2"]})
        self.assertEqual(self.rows("g2"), [])
        self.assertIsNotNone(nl.locked_projection(self.con, "g1"))

    def test_skip_mode_still_refreshes_already_locked_played_game(self):
        # A game locked before its result keeps its lock after the result arrives.
        nl.lock_week(self.con, 2026, 5, fit_for(), 13.4, "v1", as_of="t0")
        self.con.execute("UPDATE nfl_schedule SET home_score=24, away_score=20 WHERE game_id='g2'")
        self.con.commit()
        out = nl.lock_week(self.con, 2026, 5, fit_for(5.0), 13.4, "v1", as_of="t1", skip_scored=True)
        self.assertEqual(out, {"new_locks": 0, "refreshes": 2, "skipped": []})
        self.assertEqual(nl.locked_projection(self.con, "g2")["as_of"], "t0")


class WinProbabilityStored(LockDB):
    def test_stored_probability_matches_margin_and_sigma(self):
        nl.lock_week(self.con, 2026, 5, fit_for(), 13.4, "v1", as_of="t0")
        got = nl.locked_projection(self.con, "g1")
        self.assertAlmostEqual(got["p_home_win"],
                               nr.win_probability(got["projected_margin"], 13.4), places=12)


if __name__ == "__main__":
    unittest.main()
