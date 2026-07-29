#!/usr/bin/env python3

import os
import sqlite3
import tempfile
import unittest

from ingest_nba_stats import (
    NBAStatsIngestError,
    parse_athlete_stats,
    refresh_nba_stats,
)
from league_stats import PLAYER_STATS_TABLE_SQL


def stats_payload(*, games=64, points=33.484375):
    values = {
        "gamesPlayed": games,
        "avgPoints": points,
        "avgRebounds": 7.734375,
        "avgAssists": 8.28125,
        "avgSteals": 1.640625,
        "avgBlocks": 0.53125,
        "avgTurnovers": 3.984375,
        "fieldGoalsMade": 693,
        "fieldGoalsAttempted": 1457,
        "threePointFieldGoalsMade": 254,
        "threePointFieldGoalsAttempted": 694,
        "freeThrowsMade": 503,
        "freeThrowsAttempted": 645,
        "avgMinutes": 35.765625,
        "trueShootingPct": 61.552,
    }
    return {
        "splits": {
            "categories": [
                {
                    "name": "all",
                    "stats": [
                        {"name": name, "value": value}
                        for name, value in values.items()
                    ],
                }
            ]
        }
    }


class NBAStatsIngestTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="nba-stats-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(
            lambda: os.path.exists(self.path) and os.unlink(self.path)
        )
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              league TEXT NOT NULL,
              team TEXT,
              espn_id TEXT,
              active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        connection.execute(PLAYER_STATS_TABLE_SQL)
        connection.executemany(
            """INSERT INTO players(
                 id,name,league,team,espn_id,active
               ) VALUES(?,?,?,?,?,1)""",
            [
                (1, "Canonical One", "nba", "BOS", "101"),
                (2, "Canonical Two", "nba", "DAL", "202"),
            ],
        )
        connection.execute(
            """INSERT INTO player_stats(
                 player_id,player_name,league,team,stat_type,season,
                 games,pts,source
               ) VALUES(1,'Last Good','nba','OLD','season',2026,
                        10,10.0,'espn_core')"""
        )
        connection.commit()
        connection.close()

    def rows(self):
        connection = sqlite3.connect(self.path)
        try:
            return connection.execute(
                """SELECT player_id,player_name,team,games,pts,source
                   FROM player_stats WHERE league='nba' AND season=2026
                   ORDER BY player_id"""
            ).fetchall()
        finally:
            connection.close()

    def test_parser_maps_published_totals_and_per_game_values(self):
        parsed = parse_athlete_stats(stats_payload())
        self.assertEqual(parsed["games"], 64)
        self.assertEqual(parsed["values"]["pts"], 33.5)
        self.assertEqual(parsed["values"]["fgm"], 693)
        self.assertEqual(parsed["values"]["minutes"], 35.8)
        self.assertEqual(parsed["values"]["ts_pct"], 61.6)

    def test_fetch_failure_preserves_the_last_good_snapshot(self):
        before = self.rows()

        def fetcher(espn_id, _season):
            if espn_id == "202":
                raise NBAStatsIngestError("upstream unavailable")
            return stats_payload()

        with self.assertRaisesRegex(
            NBAStatsIngestError, "upstream unavailable"
        ):
            refresh_nba_stats(
                self.path, season=2026, fetcher=fetcher,
                min_coverage=1.0,
            )
        self.assertEqual(self.rows(), before)

    def test_low_coverage_preserves_the_last_good_snapshot(self):
        before = self.rows()
        with self.assertRaisesRegex(
            NBAStatsIngestError, "below required"
        ):
            refresh_nba_stats(
                self.path,
                season=2026,
                fetcher=lambda espn_id, season: (
                    stats_payload() if espn_id == "101" else None
                ),
                min_coverage=0.75,
            )
        self.assertEqual(self.rows(), before)

    def test_complete_fetch_atomically_replaces_the_population(self):
        result = refresh_nba_stats(
            self.path,
            season=2026,
            fetcher=lambda espn_id, season: stats_payload(
                points=20.0 if espn_id == "101" else 25.0
            ),
            min_coverage=1.0,
        )
        self.assertEqual(result["published"], 2)
        self.assertEqual(
            self.rows(),
            [
                (1, "Canonical One", "BOS", 64, 20.0, "espn_core"),
                (2, "Canonical Two", "DAL", 64, 25.0, "espn_core"),
            ],
        )

    def test_duplicate_active_espn_id_fails_closed(self):
        connection = sqlite3.connect(self.path)
        connection.execute(
            """INSERT INTO players(
                 id,name,league,team,espn_id,active
               ) VALUES(3,'Duplicate','nba','NYK','101',1)"""
        )
        connection.commit()
        connection.close()
        before = self.rows()
        with self.assertRaisesRegex(
            NBAStatsIngestError, "duplicate active ESPN IDs"
        ):
            refresh_nba_stats(
                self.path,
                season=2026,
                fetcher=lambda espn_id, season: stats_payload(),
            )
        self.assertEqual(self.rows(), before)

    def test_active_player_without_espn_id_fails_closed(self):
        connection = sqlite3.connect(self.path)
        connection.execute(
            """INSERT INTO players(
                 id,name,league,team,espn_id,active
               ) VALUES(3,'Missing ID','nba','NYK',NULL,1)"""
        )
        connection.commit()
        connection.close()
        before = self.rows()
        with self.assertRaisesRegex(
            NBAStatsIngestError, "lack canonical ESPN IDs"
        ):
            refresh_nba_stats(
                self.path,
                season=2026,
                fetcher=lambda espn_id, season: stats_payload(),
            )
        self.assertEqual(self.rows(), before)

    def test_historical_season_is_rejected_before_fetch(self):
        calls = []
        with self.assertRaisesRegex(
            NBAStatsIngestError, "only after season 2023"
        ):
            refresh_nba_stats(
                self.path,
                season=2023,
                fetcher=lambda espn_id, season: calls.append(espn_id),
            )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
