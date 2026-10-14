"""Bovada match prices attach by ESPN event id, to the right players, and only while fresh."""
import datetime as dt
import sqlite3
import unittest

from tennis_bovada_odds import bovada_odds

NOW = dt.datetime(2026, 10, 14, 17, 0, tzinfo=dt.timezone.utc)


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE prop_games (id INTEGER PRIMARY KEY, league TEXT, espn_event_id TEXT);
        CREATE TABLE props (id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER, market TEXT,
                            line REAL, side TEXT, source TEXT, odds INTEGER, odds_captured_at TEXT);
        INSERT INTO prop_games VALUES (1, 'atp', '184950');
    """)
    return con


def _prop(con, market, player_id, line, side, odds, captured, source="bovada"):
    con.execute("INSERT INTO props (game_id, player_id, market, line, side, source, odds, odds_captured_at) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, ?)", (player_id, market, line, side, source, odds, captured))


class BovadaTennisOddsTest(unittest.TestCase):
    def test_moneyline_and_total_attach_to_the_matching_players_and_newest_prices(self):
        con = _db()
        fresh = "2026-10-14T16:30:00+00:00"
        _prop(con, "match_winner", 100, 0.5, "over", -150, fresh)
        _prop(con, "match_winner", 200, 0.5, "over", 120, fresh)
        _prop(con, "match_winner", 100, 0.5, "over", -110, "2026-10-14T15:00:00+00:00")  # older, ignored
        _prop(con, "total_games", None, 21.5, "over", -115, fresh)
        _prop(con, "total_games", None, 21.5, "under", -105, fresh)
        out = bovada_odds(con, "184950", "atp", 100, 200, NOW)
        self.assertEqual(out["matchWinner"], {"home": -150, "away": 120})
        self.assertEqual(out["totalGames"], {"line": 21.5, "over": -115, "under": -105})

    def test_stale_prices_are_dropped(self):
        con = _db()
        _prop(con, "match_winner", 100, 0.5, "over", -150, "2026-10-13T08:00:00+00:00")
        self.assertIsNone(bovada_odds(con, "184950", "atp", 100, 200, NOW))

    def test_a_total_with_one_side_is_not_shown(self):
        con = _db()
        _prop(con, "total_games", None, 21.5, "over", -115, "2026-10-14T16:30:00+00:00")
        self.assertIsNone(bovada_odds(con, "184950", "atp", 100, 200, NOW))

    def test_other_sources_and_other_tours_do_not_attach(self):
        con = _db()
        _prop(con, "match_winner", 100, 0.5, "over", -150, "2026-10-14T16:30:00+00:00", source="underdog")
        self.assertIsNone(bovada_odds(con, "184950", "wta", 100, 200, NOW))
        self.assertIsNone(bovada_odds(con, "184950", "atp", 100, 200, NOW))


if __name__ == "__main__":
    unittest.main()
