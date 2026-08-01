import os
import sqlite3
import tempfile
import unittest

from ingest_nfl_season_stats import publish, resolve_rows
from league_stats import PLAYER_STATS_TABLE_SQL
from nfl_rankings import nfl_player_rank_context, nfl_player_stat_ranks_batch


def source_row(source_id, name, **overrides):
    row = {
        "player_id": source_id,
        "player_display_name": name,
        "position": "QB",
        "season": 2025,
        "season_type": "REG",
        "recent_team": "CLE",
        "games": 8,
        "completions": 120,
        "passing_yards": 1400,
        "passing_tds": 7,
        "passing_interceptions": 10,
        "passing_epa": -32.5,
        "carries": 21,
        "rushing_yards": 169,
        "receptions": 0,
        "receiving_yards": 0,
        "targets": 0,
        "fantasy_points": 84.9,
        "fantasy_points_ppr": 84.9,
    }
    row.update(overrides)
    return row


class NflSeasonStatsTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY, name TEXT NOT NULL, team TEXT,
                     league TEXT NOT NULL, position TEXT, nfl_gsis_id TEXT
                   )"""
            )
            connection.execute(PLAYER_STATS_TABLE_SQL)
            connection.executemany(
                "INSERT INTO players VALUES(?,?,?,?,?,?)",
                [
                    (1, "Shedeur Sanders", "CLE", "nfl", "QB", "00-0040668"),
                    (2, "Josh Allen", "BUF", "nfl", "QB", "00-0034857"),
                    (3, "Aaron Rodgers", "PIT", "nfl", "QB", "00-0023459"),
                    (4, "Legacy Player", "OLD", "nfl", "QB", "legacy"),
                ],
            )
            connection.execute(
                """INSERT INTO player_stats(
                     player_id,player_name,league,team,stat_type,season,games,
                     pass_yds_g,source
                   ) VALUES(4,'Legacy Player','nfl','OLD','weekly',2025,17,
                            999.0,'nflverse')"""
            )

    def rows(self):
        return [
            source_row("00-0040668", "Shedeur Sanders"),
            source_row(
                "00-0034857", "Josh Allen", recent_team="BUF", games=16,
                completions=319, passing_yards=3668, passing_tds=25,
                passing_interceptions=10, passing_epa=40.2,
                fantasy_points=364.62, fantasy_points_ppr=364.62,
            ),
            source_row(
                "00-0023459", "Aaron Rodgers", recent_team="PIT", games=16,
                completions=327, passing_yards=3322, passing_tds=24,
                passing_interceptions=7, passing_epa=12.4,
                fantasy_points=226.08, fantasy_points_ppr=227.08,
            ),
        ]

    def resolve(self, rows):
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            return resolve_rows(connection, rows)

    def test_complete_identity_is_required_before_publication(self):
        rows = self.rows() + [source_row("missing", "Missing Player")]
        with self.assertRaisesRegex(RuntimeError, "unresolved.*1"):
            self.resolve(rows)

    def test_publishes_direct_totals_and_only_labelled_per_game_rates(self):
        resolved = self.resolve(self.rows())
        publish(self.path, 2025, resolved)

        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT player_id,stat_type,source,games,pass_yds_g,pass_td,
                          interceptions,cmp_g,fantasy_ppr_g
                     FROM player_stats ORDER BY player_id"""
            ).fetchall()
            self.assertEqual(3, len(rows))
            shedeur = rows[0]
            self.assertEqual("season", shedeur["stat_type"])
            self.assertEqual("nflverse_regular_season", shedeur["source"])
            self.assertEqual(8, shedeur["games"])
            self.assertEqual(175.0, shedeur["pass_yds_g"])
            self.assertEqual(7, shedeur["pass_td"])
            self.assertEqual(10, shedeur["interceptions"])
            self.assertEqual(15.0, shedeur["cmp_g"])
            self.assertEqual(10.6, shedeur["fantasy_ppr_g"])

    def test_rank_context_is_season_scoped_and_reports_sample(self):
        publish(self.path, 2025, self.resolve(self.rows()))
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            context = nfl_player_rank_context(connection, 1, "QB", 2025)
            batch = nfl_player_stat_ranks_batch(connection, 2025)

        self.assertEqual(2025, context["season"])
        self.assertEqual(8, context["games"])
        self.assertEqual(3, context["stats"]["pass_yds_g"]["rank"])
        self.assertEqual(2, context["stats"]["interceptions"]["rank"])
        self.assertEqual(
            context["stats"],
            {key: batch[1][key] for key in context["stats"]},
        )


if __name__ == "__main__":
    unittest.main()
