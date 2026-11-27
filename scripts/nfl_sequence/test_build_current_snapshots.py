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
                    game_id INTEGER, player_id INTEGER, market TEXT
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
                INSERT INTO props VALUES (32927, 16511, 'passing_yards');
                INSERT INTO props VALUES (32927, 19303, 'passing_yards');
            ''')

    def tearDown(self):
        self.temp.cleanup()

    def test_uses_exact_event_id_when_props_store_full_team_names(self):
        self.assertEqual(
            builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27', '401873083'),
            {'DEN': {'00-0039732'}, 'PIT': {'00-0034771'}},
        )

    def test_falls_back_to_canonical_team_name_match(self):
        self.assertEqual(
            builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27'),
            {'DEN': {'00-0039732'}, 'PIT': {'00-0034771'}},
        )

    def test_unknown_event_without_team_match_returns_no_priced_qbs(self):
        self.assertEqual(
            builder.market_qbs(self.db, '2026_12_DEN_PIT', '2026-11-27', '999999999'),
            {'DEN': {'00-0039732'}, 'PIT': {'00-0034771'}},
        )


if __name__ == '__main__':
    unittest.main()
