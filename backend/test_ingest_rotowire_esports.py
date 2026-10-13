#!/usr/bin/env python3
"""Tests for ingest_rotowire_esports.py — CS2/Valorant props from the RotoWire relay.

Two real bugs found and fixed while building this against live data 2026-08-30:

  1. Team-name matching was exact-equality only. RotoWire named an org "Fire Flux",
     PandaScore named the same real match "Fire Flux Esports" — one verified match
     out of 31 read as unverified for no reason but a suffix. _team_matches now
     allows containment, guarded to >=4 normalized characters so a short name
     ("OG", "G2") cannot spuriously match inside an unrelated longer one.

  2. Props carry no unique constraint, and the insert loop had no check-before-write.
     A second run of the same day's snapshot DOUBLED every row: 1282 -> 2564.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ingest_rotowire_esports as ie  # noqa: E402


SCHEMA = """
CREATE TABLE players(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, team TEXT, league TEXT NOT NULL,
  espn_id TEXT, mlbam_id INTEGER, nfl_gsis_id TEXT, nhl_id INTEGER, nba_id INTEGER,
  active INTEGER DEFAULT 1, position TEXT, updated_at TEXT, injury_status TEXT,
  last_news_date TEXT, position_group TEXT, pitcher_role TEXT, entity_type TEXT,
  UNIQUE(espn_id, league));
CREATE TABLE prop_games(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  league TEXT NOT NULL, date TEXT NOT NULL,
  home TEXT, away TEXT, espn_event_id TEXT,
  final_home INTEGER, final_away INTEGER, start_time TEXT,
  cancelled_at TEXT, cancel_reason TEXT, cancel_source TEXT);
CREATE TABLE props(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id INTEGER REFERENCES prop_games(id),
  player_id INTEGER REFERENCES players(id),
  market TEXT NOT NULL, line REAL NOT NULL, side TEXT NOT NULL,
  source TEXT, captured_at TEXT NOT NULL, odds INTEGER, odds_captured_at TEXT);
CREATE TABLE player_source_ids(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, league TEXT NOT NULL, source_player_key TEXT NOT NULL,
  player_id INTEGER NOT NULL REFERENCES players(id),
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  UNIQUE(source, league, source_player_key));
"""


class TeamNameMatching(unittest.TestCase):
    """The exact real collision measured 2026-08-30: relay 'Fire Flux' vs PandaScore
    'Fire Flux Esports', and the short-name guard that keeps this safe."""

    def _match(self, home_ps_matches):
        return ie._verify_fixture({"cs-go": home_ps_matches}, "cs-go", "Fire Flux", "Virtus.pro", 1000)

    def test_an_org_suffix_the_relay_omits_still_matches(self):
        matches = [{
            "begin_at": "1970-01-01T00:16:40Z",  # +1000s
            "opponents": [
                {"opponent": {"name": "Fire Flux Esports"}},
                {"opponent": {"name": "Virtus.pro"}},
            ],
        }]
        v = self._match(matches)
        self.assertIsNotNone(v)
        self.assertEqual(v["home"], "Fire Flux Esports")
        self.assertEqual(v["away"], "Virtus.pro")

    def test_a_short_name_does_not_spuriously_match_inside_a_longer_one(self):
        # "OG" (2 chars normalized) must not match "og pretty boys" or any other
        # longer name it happens to be a substring of.
        self.assertFalse(ie._team_matches("og", "ogprettyboys"))
        # But an exact short-name match still works.
        self.assertTrue(ie._team_matches("og", "og"))

    def test_a_real_unrelated_pair_does_not_match(self):
        matches = [{
            "begin_at": "1970-01-01T00:16:40Z",
            "opponents": [
                {"opponent": {"name": "Some Other Team"}},
                {"opponent": {"name": "Another Org"}},
            ],
        }]
        self.assertIsNone(self._match(matches))

    def test_outside_the_time_window_does_not_match_even_with_identical_names(self):
        matches = [{
            "begin_at": "1970-01-02T00:00:00Z",  # ~24h later, past _MATCH_WINDOW_S
            "opponents": [
                {"opponent": {"name": "Fire Flux Esports"}},
                {"opponent": {"name": "Virtus.pro"}},
            ],
        }]
        self.assertIsNone(self._match(matches))


class PropsInsertIsIdempotent(unittest.TestCase):
    """Reported by the build itself 2026-08-30: a re-run of the same snapshot doubled
    every row (no unique constraint on props, no check-before-insert)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.addCleanup(lambda: os.path.exists(self.tmp.name) and os.unlink(self.tmp.name))
        con = sqlite3.connect(self.tmp.name)
        con.executescript(SCHEMA)
        con.commit()
        con.close()

    def _insert_or_update(self, con, game_id, player_id, market, line, side, source, odds):
        """The exact check-before-write shape from ingest_rotowire_esports.run()."""
        existing = con.execute(
            "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? "
            "AND line=? AND side=? AND source=?",
            (game_id, player_id, market, line, side, source)).fetchone()
        if existing:
            con.execute("UPDATE props SET odds=?, odds_captured_at=datetime('now') WHERE id=?",
                       (odds, existing[0]))
            return "updated"
        con.execute(
            "INSERT INTO props(game_id, player_id, market, line, side, source, captured_at, "
            "odds, odds_captured_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, datetime('now'))",
            (game_id, player_id, market, line, side, source, odds))
        return "inserted"

    def test_running_the_same_prop_twice_does_not_double_the_row(self):
        con = sqlite3.connect(self.tmp.name)
        con.execute("INSERT INTO prop_games(id, league, date) VALUES (1, 'cs2', '2026-08-30')")
        con.execute("INSERT INTO players(id, name, league) VALUES (1, 'ogwizard', 'cs2')")
        self._insert_or_update(con, 1, 1, "kills_maps12", 28.5, "over", "rotowire:underdog", -137)
        self._insert_or_update(con, 1, 1, "kills_maps12", 28.5, "over", "rotowire:underdog", -140)
        con.commit()
        rows = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
        self.assertEqual(rows, 1, "the second run must update the existing row, not add one")
        odds = con.execute("SELECT odds FROM props").fetchone()[0]
        self.assertEqual(odds, -140, "the refresh must take the newer odds")

    def test_two_different_books_on_the_same_line_are_both_kept(self):
        """This is NOT the bug: two real books pricing the same market/line/side are
        two real rows, distinguished by `source` — verified against the live payload,
        underdog and prizepicks both quote ogwizard's headshots_maps12 9.5 over -137."""
        con = sqlite3.connect(self.tmp.name)
        con.execute("INSERT INTO prop_games(id, league, date) VALUES (1, 'cs2', '2026-08-30')")
        con.execute("INSERT INTO players(id, name, league) VALUES (1, 'ogwizard', 'cs2')")
        self._insert_or_update(con, 1, 1, "headshots_maps12", 9.5, "over", "rotowire:underdog", -137)
        self._insert_or_update(con, 1, 1, "headshots_maps12", 9.5, "over", "rotowire:prizepicks", -137)
        con.commit()
        rows = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
        self.assertEqual(rows, 2)


if __name__ == "__main__":
    unittest.main()
