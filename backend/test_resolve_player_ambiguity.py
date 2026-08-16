#!/usr/bin/env python3
"""A name shared by two players is not a match.

Prod carried 433 Dodgers Max Muncy props on the Athletics Max Muncy's row. Nothing
raised: the resolver's fast path was `name=? AND league=?` with fetchone(), so both
men collapsed onto whichever row SQLite yielded first. These tests pin the rule that
replaced it — separate them by team, else by who is in the game, else refuse.
"""
import os
import sqlite3
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

from _core import _resolve_player_for_ingest


class ResolveAmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.con = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(
            "CREATE TABLE players("
            "id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT);"
            "CREATE TABLE prop_games("
            "id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, away TEXT);"
            "CREATE TABLE name_alias(alias_norm TEXT, player_id INTEGER);"
            "CREATE TABLE unresolved_players("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, "
            "raw_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT, "
            "first_seen TEXT NOT NULL, count INTEGER DEFAULT 1);"
        )
        self.con.executemany(
            "INSERT INTO players(id,name,team,league) VALUES(?,?,?,?)",
            [(96, "Max Muncy", "ATH", "mlb"),
             (113, "Max Muncy", "LAD", "mlb"),
             (200, "Shohei Ohtani", "LAD", "mlb")],
        )
        # The two vocabularies prop_games actually holds, side by side.
        self.con.executemany(
            "INSERT INTO prop_games(id,league,date,home,away) VALUES(?,?,?,?,?)",
            [(1, "mlb", "2026-08-12", "Los Angeles Dodgers", "Kansas City Royals"),
             (2, "mlb", "2026-07-25", "Minnesota Twins", "Athletics"),
             (3, "mlb", "2026-06-29", "ATH", "LAD")],
        )
        self.con.commit()

    def unresolved(self):
        return [dict(r) for r in self.con.execute("SELECT raw_name, count FROM unresolved_players")]

    def test_unique_name_still_resolves(self):
        self.assertEqual(
            _resolve_player_for_ingest(self.con, "Shohei Ohtani", "", "mlb"), (200, "high"))

    def test_game_breaks_the_tie_when_the_source_gives_no_team(self):
        """The regression itself: a Dodgers game, no team parenthetical."""
        self.assertEqual(
            _resolve_player_for_ingest(self.con, "Max Muncy", "", "mlb", game_id=1), (113, "high"))
        self.assertEqual(
            _resolve_player_for_ingest(self.con, "Max Muncy", "", "mlb", game_id=2), (96, "high"))

    def test_source_team_wins_when_present(self):
        self.assertEqual(
            _resolve_player_for_ingest(self.con, "Max Muncy", "LAD", "mlb"), (113, "high"))

    def test_ambiguous_with_no_signal_is_unresolved_not_a_guess(self):
        self.assertEqual(_resolve_player_for_ingest(self.con, "Max Muncy", "", "mlb"), (None, None))
        self.assertEqual(self.unresolved(), [{"raw_name": "Max Muncy", "count": 1}])

    def test_a_game_holding_both_teams_cannot_disambiguate(self):
        """ATH @ LAD names both men. Refuse rather than pick one."""
        self.assertEqual(
            _resolve_player_for_ingest(self.con, "Max Muncy", "", "mlb", game_id=3), (None, None))
        self.assertEqual(self.unresolved(), [{"raw_name": "Max Muncy", "count": 1}])

    def test_unknown_name_is_still_queued_once_per_repeat(self):
        _resolve_player_for_ingest(self.con, "Nobody Here", "", "mlb")
        _resolve_player_for_ingest(self.con, "Nobody Here", "", "mlb")
        self.assertEqual(self.unresolved(), [{"raw_name": "Nobody Here", "count": 2}])


if __name__ == "__main__":
    unittest.main()
