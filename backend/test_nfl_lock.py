"""Tests for nfl_lock.py against game_projections. Temp DB, planted fit, no network.

The lock rules are checked against the broken behaviour they exist to prevent: overwriting a
locked projection, locking after a result, a half-written week, and a lock with no run.
"""
import datetime as dt
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
NOW = dt.datetime(2026, 10, 11, 16, 0, tzinfo=dt.timezone.utc)


def fit_for(o_shift=0.0):
    strength = {"AAA": 3, "BBB": 1, "CCC": -1, "DDD": -3}
    games = []
    for a in TEAMS:
        for b in TEAMS:
            if a != b:
                games.append(nr.Game(0.0, a, b, 22.0 + strength[a] - strength[b] + o_shift, 22.0,
                                     False))
    return nr.fit(games, TEAMS, cap=None, prior_games=1e-6)


class LockDB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute(
            "CREATE TABLE nfl_schedule (game_id TEXT PRIMARY KEY, season INT, game_type TEXT, "
            "week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL, "
            "away_score REAL, spread_line REAL, total_line REAL, home_moneyline REAL, "
            "away_moneyline REAL, gameday TEXT, gametime TEXT, ingested_at TEXT)")
        # Kickoff 2026-10-11 13:00 Eastern = 17:00Z. NOW is an hour before it.
        for gid, h, a, loc in GAMES_W5:
            self.con.execute("INSERT INTO nfl_schedule VALUES (?,2026,'REG',5,?,?,?,NULL,NULL,"
                             "3.5,44.5,-170,145,'2026-10-11','13:00','2026-10-11 10:00:01')",
                             (gid, h, a, loc))
        nl.ensure_schema(self.con)
        self.run = nl.start_run(self.con, "run-a", 2026, 5, "v1", {"sigma": 13.4})

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def rows(self, gid):
        return self.con.execute("SELECT locked, proj_margin, locked_at FROM game_projections "
                                "WHERE game_id = ? ORDER BY rowid", (gid,)).fetchall()

    def lock(self, fit=None, run_id=None, now=None, **kw):
        return nl.lock_week(self.con, run_id or self.run, 2026, 5,
                            nl.v1_projector(fit or fit_for(), 13.4), now=now or NOW, **kw)


class FirstLock(LockDB):
    def test_first_run_locks_every_game_in_the_week(self):
        out = self.lock(as_of="t0")
        self.assertEqual(out, {"new_locks": 2, "refreshes": 0, "skipped": [], "started": []})
        for gid, _, _, _ in GAMES_W5:
            self.assertEqual(len([r for r in self.rows(gid) if r[0] == 1]), 1, gid)

    def test_market_line_is_stored_with_the_lock(self):
        self.lock(as_of="t0")
        got = nl.locked_projection(self.con, "g1", "v1")
        self.assertEqual(got["market_spread"], 3.5)
        self.assertEqual(got["market_total"], 44.5)
        self.assertEqual(got["market_source"], "nflverse")
        self.assertEqual(got["run_id"], "run-a")

    def test_lock_requires_a_recorded_run(self):
        with self.assertRaises(ValueError):
            self.lock(run_id="never-started", as_of="t0")
        n, = self.con.execute("SELECT COUNT(*) FROM game_projections").fetchone()
        self.assertEqual(n, 0)


class NeverOverwrite(LockDB):
    def test_second_run_refreshes_without_touching_the_lock(self):
        self.lock(fit=fit_for(0.0), as_of="t0")
        first = nl.locked_projection(self.con, "g1", "v1")
        run2 = nl.start_run(self.con, "run-b", 2026, 5, "v1", {"sigma": 13.4})
        out = self.lock(fit=fit_for(5.0), run_id=run2, as_of="t1")
        self.assertEqual(out, {"new_locks": 0, "refreshes": 2, "skipped": [], "started": []})
        after = nl.locked_projection(self.con, "g1", "v1")
        self.assertEqual(after["proj_margin"], first["proj_margin"])
        self.assertEqual(after["locked_at"], "t0")
        self.assertEqual(after["run_id"], "run-a")
        refreshed = [r for r in self.rows("g1") if r[0] == 0]
        self.assertEqual(len(refreshed), 1)
        self.assertNotAlmostEqual(refreshed[0][1], first["proj_margin"], places=3)

    def test_database_index_refuses_a_second_lock(self):
        self.lock(as_of="t0")
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute(
                "INSERT INTO game_projections (run_id, league, game_id, season, week, home, away, "
                "proj_margin, proj_total, p_home_win, locked, locked_at, model_version) "
                "VALUES ('run-a','nfl','g1',2026,5,'AAA','BBB',1,44,0.5,1,'t9','v1')")

    def test_a_second_model_version_locks_the_same_game(self):
        self.lock(as_of="t0")
        run2 = nl.start_run(self.con, "run-c", 2026, 5, "v2", {"sigma": 13.4})
        out = self.lock(fit=fit_for(5.0), run_id=run2, as_of="t1")
        self.assertEqual(out["new_locks"], 2)
        a = nl.locked_projection(self.con, "g1", "v1")
        b = nl.locked_projection(self.con, "g1", "v2")
        self.assertEqual((a["run_id"], b["run_id"]), ("run-a", "run-c"))
        self.assertNotAlmostEqual(a["proj_margin"], b["proj_margin"], places=3)


class Refusals(LockDB):
    def test_locking_after_a_result_is_refused_and_writes_nothing(self):
        self.con.execute("UPDATE nfl_schedule SET home_score=24, away_score=20 WHERE game_id='g2'")
        self.con.commit()
        with self.assertRaises(ValueError):
            self.lock(as_of="t0")
        n, = self.con.execute("SELECT COUNT(*) FROM game_projections").fetchone()
        self.assertEqual(n, 0)

    def test_skip_mode_locks_unplayed_and_leaves_played_unwritten(self):
        self.con.execute("UPDATE nfl_schedule SET home_score=24, away_score=20 WHERE game_id='g2'")
        self.con.commit()
        out = self.lock(as_of="t0", skip_scored=True)
        self.assertEqual(out, {"new_locks": 1, "refreshes": 0, "skipped": ["g2"], "started": []})
        self.assertEqual(self.rows("g2"), [])

    def test_skip_mode_keeps_lock_of_a_game_locked_before_its_result(self):
        self.lock(as_of="t0")
        self.con.execute("UPDATE nfl_schedule SET home_score=24, away_score=20 WHERE game_id='g2'")
        self.con.commit()
        run2 = nl.start_run(self.con, "run-b", 2026, 5, "v1", {"sigma": 13.4})
        out = self.lock(fit=fit_for(5.0), run_id=run2, as_of="t1", skip_scored=True)
        self.assertEqual(out, {"new_locks": 0, "refreshes": 2, "skipped": [], "started": []})
        self.assertEqual(nl.locked_projection(self.con, "g2", "v1")["locked_at"], "t0")

    def test_missing_team_rating_is_refused(self):
        fit = nr.fit([nr.Game(0.0, "AAA", "BBB", 20.0, 17.0)], ["AAA", "BBB"], prior_games=1.0)
        with self.assertRaises(KeyError):
            self.lock(fit=fit, as_of="t0")

    def test_empty_week_is_refused(self):
        with self.assertRaises(ValueError):
            nl.lock_week(self.con, self.run, 2026, 9, nl.v1_projector(fit_for(), 13.4),
                         as_of="t0", now=NOW)

    def test_bad_sigma_is_refused(self):
        with self.assertRaises(ValueError):
            nl.v1_projector(fit_for(), 0.0)


class RunRecord(LockDB):
    def test_run_status_and_params_are_recorded(self):
        nl.finish_run(self.con, "run-a", "ok")
        row = self.con.execute("SELECT status, params_json, finished_at FROM model_runs "
                               "WHERE run_id='run-a'").fetchone()
        self.assertEqual(row[0], "ok")
        self.assertIn('"sigma": 13.4', row[1])
        self.assertIsNotNone(row[2])


class WinProbabilityStored(LockDB):
    def test_stored_probability_matches_margin_and_sigma(self):
        self.lock(as_of="t0")
        got = nl.locked_projection(self.con, "g1", "v1")
        self.assertAlmostEqual(got["p_home_win"], nr.win_probability(got["proj_margin"], 13.4),
                               places=12)


class Kickoff(LockDB):
    def test_a_game_past_kickoff_is_never_written(self):
        self.con.execute("UPDATE nfl_schedule SET gametime='09:30' WHERE game_id='g1'")  # 13:30Z
        self.con.commit()
        out = self.lock(as_of="t0")
        self.assertEqual(out["started"], ["g1"])
        self.assertEqual(out["new_locks"], 1)
        self.assertEqual(self.rows("g1"), [])

    def test_kickoff_is_read_as_eastern_not_utc(self):
        # 13:00 read as UTC would be past at 16:00Z; read as Eastern it is 17:00Z, still ahead.
        out = self.lock(as_of="t0", now=dt.datetime(2026, 10, 11, 16, 59, tzinfo=dt.timezone.utc))
        self.assertEqual(out["started"], [])
        out = self.lock(run_id=nl.start_run(self.con, "run-k", 2026, 5, "v1", {}), as_of="t1",
                        now=dt.datetime(2026, 10, 11, 17, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(out["started"], ["g1", "g2"])

    def test_no_audit_row_after_kickoff_either(self):
        self.lock(as_of="t0")
        run2 = nl.start_run(self.con, "run-b", 2026, 5, "v1", {})
        out = self.lock(run_id=run2, as_of="t1",
                        now=dt.datetime(2026, 10, 11, 18, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(out["refreshes"], 0)
        self.assertEqual(len(self.rows("g1")), 1)

    def test_missing_gameday_is_refused(self):
        self.con.execute("UPDATE nfl_schedule SET gameday=NULL WHERE game_id='g2'")
        self.con.commit()
        with self.assertRaises(ValueError):
            self.lock(as_of="t0")
        n, = self.con.execute("SELECT COUNT(*) FROM game_projections").fetchone()
        self.assertEqual(n, 0)


class LineSnapshot(LockDB):
    def test_lock_points_at_a_copy_of_the_line_it_saw(self):
        self.lock(as_of="t0")
        got = nl.locked_projection(self.con, "g1", "v1")
        snap = self.con.execute(
            "SELECT game_id, source, captured_at, source_ingested_at, spread_line, total_line, "
            "home_moneyline, away_moneyline FROM nfl_line_snapshots WHERE snapshot_id = ?",
            (got["line_snapshot_id"],)).fetchone()
        self.assertEqual(snap, ("g1", "nflverse", "t0", "2026-10-11 10:00:01", 3.5, 44.5, -170, 145))

    def test_a_later_schedule_change_does_not_touch_the_snapshot(self):
        self.lock(as_of="t0")
        self.con.execute("UPDATE nfl_schedule SET spread_line=7.0")
        self.con.commit()
        got = nl.locked_projection(self.con, "g1", "v1")
        spread, = self.con.execute("SELECT spread_line FROM nfl_line_snapshots WHERE snapshot_id=?",
                                   (got["line_snapshot_id"],)).fetchone()
        self.assertEqual((got["market_spread"], spread), (3.5, 3.5))


class ModelName(LockDB):
    def test_run_records_the_model_it_was_given(self):
        nl.start_run(self.con, "run-e", 2026, 5, "v2", {}, model="nfl-epa-v2")
        got, = self.con.execute("SELECT model FROM model_runs WHERE run_id='run-e'").fetchone()
        self.assertEqual(got, "nfl-epa-v2")


if __name__ == "__main__":
    unittest.main()
