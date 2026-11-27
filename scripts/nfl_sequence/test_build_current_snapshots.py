"""Prop preflight must resolve stored full team names and exact ESPN event IDs."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import build_current_snapshots as builder


class MarketQuarterbacks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'props.sqlite'
        with sqlite3.connect(str(self.db)) as con:
            con.executescript('''
                CREATE TABLE prop_games (
                    id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, away TEXT,
                    espn_event_id TEXT
                );
                CREATE TABLE props (
                    game_id INTEGER, player_id INTEGER, market TEXT, captured_at TEXT
                );
                CREATE TABLE players (
                    id INTEGER PRIMARY KEY, team TEXT, nfl_gsis_id TEXT
                );
                INSERT INTO prop_games VALUES (
                    32927, 'nfl', '2026-11-27', 'Pittsburgh Steelers',
                    'Denver Broncos', '401873083'
                );
                INSERT INTO players VALUES (16511, 'DEN', '00-0039732');
                INSERT INTO players VALUES (19303, 'PIT', '00-0034771');
                INSERT INTO props VALUES (32927, 16511, 'passing_yards', '2026-11-27T17:00:00Z');
                INSERT INTO props VALUES (32927, 19303, 'passing_yards', '2026-11-27T17:00:00Z');
            ''')

    def tearDown(self):
        self.temp.cleanup()

    def test_uses_exact_event_id_when_props_store_full_team_names(self):
        self.assertEqual(
            builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27', '401873083', as_of='2026-11-27T18:30:00Z'),
            {'DEN': {'00-0039732'}, 'PIT': {'00-0034771'}},
        )

    def test_falls_back_to_canonical_team_name_match(self):
        self.assertEqual(
            builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27', as_of='2026-11-27T18:30:00Z'),
            {'DEN': {'00-0039732'}, 'PIT': {'00-0034771'}},
        )

    def test_conflicting_known_event_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'conflicting ESPN'):
            builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27', '999999999',
                               as_of='2026-11-27T18:30:00Z')

    def test_exact_event_wrong_teams_is_refused(self):
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE prop_games SET away='Kansas City Chiefs'")
        with self.assertRaisesRegex(ValueError, 'conflicts with matchup'):
            builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27', '401873083',
                               as_of='2026-11-27T18:30:00Z')

    def test_late_quotes_are_excluded(self):
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE props SET captured_at='2026-11-27T18:30:01Z' WHERE player_id=16511")
        self.assertEqual(builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27', '401873083',
                                            as_of='2026-11-27T18:30:00Z'), {'PIT': {'00-0034771'}})

    def test_missing_event_and_matchup_returns_empty(self):
        self.assertEqual(builder.market_qbs(self.db, '2026_12_KC_BUF', '2026-11-27', '999999999',
                                            as_of='2026-11-27T18:30:00Z'), {})


if __name__ == '__main__':
    unittest.main()
