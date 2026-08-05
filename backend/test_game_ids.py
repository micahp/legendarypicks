"""Tests for the shared game-id vocabulary guard.

The defect these exist to prevent is not a crash. It is an INSERT OR REPLACE
keyed on (league, game_id, team) landing BESIDE the row it should have replaced
because the game_id speaks a different vocabulary — nflverse keys (2024_01_BAL_KC)
vs ESPN event ids (401772718) — and the season silently doubling. Every writer of
team_game_results calls `guard_game_id_vocabulary` before writing; these assert
what that guard must do and must never do.
"""
import io
import os
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_ids import foreign_game_ids, guard_game_id_vocabulary


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE team_game_results(
        league TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL,
        game_date TEXT, opponent TEXT, home_away TEXT,
        score_for REAL, score_against REAL, win INTEGER,
        ingested_at TEXT DEFAULT (datetime('now')),
        season INTEGER, status TEXT, source TEXT, run_id TEXT,
        PRIMARY KEY(league, game_id, team))""")
    return con


def _insert(con, league, game_id, team, season):
    con.execute(
        "INSERT INTO team_game_results(league, game_id, team, season) "
        "VALUES (?,?,?,?)", (league, game_id, team, season))
    con.commit()


class GuardRefusalTests(unittest.TestCase):
    def test_refuses_when_season_holds_foreign_vocabulary(self):
        con = _db()
        _insert(con, "nfl", "2024_01_BAL_KC", "BAL", 2024)
        _insert(con, "nfl", "2024_01_BAL_KC", "KC", 2024)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = guard_game_id_vocabulary(con, "nfl", 2024)
        self.assertEqual(rc, 1)
        self.assertIn("REFUSING", buf.getvalue())
        # the refusal deleted nothing
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM team_game_results").fetchone()[0], 2)

    def test_clean_season_passes(self):
        con = _db()
        _insert(con, "nfl", "401772718", "BAL", 2025)
        _insert(con, "nfl", "401772718", "KC", 2025)
        rc = guard_game_id_vocabulary(con, "nfl", 2025)
        self.assertEqual(rc, 0)

    def test_mixed_season_is_refused_until_migrated(self):
        """Both vocabularies present is exactly the poisoned state: 285 -> 557."""
        con = _db()
        _insert(con, "nfl", "2024_01_BAL_KC", "BAL", 2024)
        _insert(con, "nfl", "401772718", "BAL", 2024)
        self.assertEqual(guard_game_id_vocabulary(con, "nfl", 2024), 1)

    def test_replace_vocabulary_drops_foreign_rows_then_passes(self):
        con = _db()
        _insert(con, "nfl", "2024_01_BAL_KC", "BAL", 2024)
        _insert(con, "nfl", "2024_01_BAL_KC", "KC", 2024)
        rc = guard_game_id_vocabulary(con, "nfl", 2024, replace_vocabulary=True)
        self.assertEqual(rc, 0)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM team_game_results").fetchone()[0], 0)

    def test_replace_vocabulary_dry_run_deletes_nothing(self):
        """A dry run must not pretend the migration happened."""
        con = _db()
        _insert(con, "nfl", "2024_01_BAL_KC", "BAL", 2024)
        rc = guard_game_id_vocabulary(con, "nfl", 2024,
                                      replace_vocabulary=True, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM team_game_results").fetchone()[0], 1)


class LeagueScopeTests(unittest.TestCase):
    """team_game_stats has no season column; the league-scoped call is the same
    check over the whole league."""

    def test_league_scope_refuses_on_any_foreign_row(self):
        con = _db()
        _insert(con, "nfl", "2024_01_BAL_KC", "BAL", 2024)
        self.assertEqual(guard_game_id_vocabulary(con, "nfl", season=None), 1)

    def test_league_scope_passes_on_clean_league(self):
        con = _db()
        _insert(con, "nba", "401772718", "BAL", 2026)
        self.assertEqual(guard_game_id_vocabulary(con, "nba", season=None), 0)

    def test_league_scope_replace_deletes_foreign_rows(self):
        con = _db()
        _insert(con, "nfl", "2024_01_BAL_KC", "BAL", 2024)
        rc = guard_game_id_vocabulary(con, "nfl", season=None,
                                      replace_vocabulary=True)
        self.assertEqual(rc, 0)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM team_game_results").fetchone()[0], 0)


class DetectionTests(unittest.TestCase):
    def test_foreign_detector_reports_only_foreign_shape(self):
        con = _db()
        _insert(con, "nfl", "2024_01_BAL_KC", "BAL", 2024)
        _insert(con, "nfl", "401772718", "BAL", 2024)
        self.assertEqual(foreign_game_ids(con, "nfl", 2024), ["2024_01_BAL_KC"])

    def test_esports_digit_style_is_not_foreign(self):
        con = _db()
        _insert(con, "nfl", "401772718", "BAL", 2025)
        self.assertEqual(foreign_game_ids(con, "nfl", 2025), [])


if __name__ == "__main__":
    unittest.main()
