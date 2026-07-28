"""ppr_per_team_game must divide by the player's own team_games.

This is a gate for a defect that is not live: every team played 17 regular
season games in 2024 and 2025, so a hardcoded 17 and the per-player value are
indistinguishable against the real database. It stops being indistinguishable
the first time a player's team plays a different number of games -- which the
comment in _availability_aggregates already anticipates for mid-season moves --
and by then the number is wrong on every surface with nothing to catch it.

The fixture therefore builds a team that played 16 weeks, which no row in the
shipped database does.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Importing the router initializes its draft tables; point that side effect at
# a disposable file (same approach as test_mock_draft_pool_parity).
_IMPORT_DB = tempfile.NamedTemporaryFile(
    prefix="team-games-denominator-", suffix=".db", delete=False
)
_IMPORT_DB.close()
_ORIGINAL_LP_DB_PATH = os.environ.get("LP_DB_PATH")
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

from routers import nfl_mock_draft  # noqa: E402
from routers.nfl_offseason import _regular_season_aggregates  # noqa: E402

if _ORIGINAL_LP_DB_PATH is None:
    os.environ.pop("LP_DB_PATH", None)
else:
    os.environ["LP_DB_PATH"] = _ORIGINAL_LP_DB_PATH

TEAM = "ZZZ"
PLAYER_ID = 999001
TEAM_WEEKS = 16
PPR_PER_WEEK = 10.0


def _build_fixture(path: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE players (
            id INTEGER PRIMARY KEY, name TEXT, team TEXT, position TEXT,
            active INTEGER, league TEXT
        );
        CREATE TABLE nfl_adp (
            player_id INTEGER, season INTEGER, adp REAL, percent_owned REAL
        );
        CREATE TABLE player_game_logs (
            player_id INTEGER, league TEXT, season INTEGER, game_no TEXT,
            game_type TEXT, team TEXT, stats TEXT
        );
        CREATE TABLE nfl_schedule (
            season INTEGER, week INTEGER, home_team TEXT, away_team TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO players VALUES (?,?,?,?,?,?)",
        (PLAYER_ID, "Fixture Player", TEAM, "WR", 1, "nfl"),
    )
    connection.execute(
        "INSERT INTO nfl_adp VALUES (?,?,?,?)", (PLAYER_ID, 2026, 50.0, 10.0)
    )
    # A 16-week team, and the player present for every one of those weeks.
    for week in range(1, TEAM_WEEKS + 1):
        connection.execute(
            "INSERT INTO nfl_schedule VALUES (?,?,?,?)",
            (2025, week, TEAM, "OPP"),
        )
        connection.execute(
            "INSERT INTO player_game_logs VALUES (?,?,?,?,?,?,?)",
            (
                PLAYER_ID,
                "nfl",
                2025,
                str(week),
                "REG",
                TEAM,
                json.dumps({"fpts_ppr": PPR_PER_WEEK, "target_share": 0.1}),
            ),
        )
    connection.commit()
    connection.close()


class TeamGamesDenominatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmpdir.name, "fixture.db")
        _build_fixture(cls.db_path)
        cls.original_db = nfl_mock_draft._DB
        nfl_mock_draft._DB = cls.db_path

    @classmethod
    def tearDownClass(cls):
        nfl_mock_draft._DB = cls.original_db
        cls.tmpdir.cleanup()

    def test_team_games_reflects_the_schedule_not_the_constant(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            aggregates = _regular_season_aggregates(connection, 2025)
        finally:
            connection.close()
        self.assertEqual(aggregates[PLAYER_ID]["team_games"], TEAM_WEEKS)

    def test_ppr_per_team_game_uses_the_players_own_denominator(self):
        detail = json.loads(
            nfl_mock_draft.player_detail(player_id=PLAYER_ID).body
        )
        self.assertEqual(detail["team_games"], TEAM_WEEKS)
        self.assertEqual(detail["games_played"], TEAM_WEEKS)
        # 160.0 over the team's 16 games is 10.0. Dividing by the 17-constant
        # would report 9.4 for a player who did not miss a single game.
        self.assertEqual(detail["ppr_per_team_game"], PPR_PER_WEEK)
        self.assertEqual(detail["ppr_per_game_played"], PPR_PER_WEEK)
        self.assertEqual(detail["games_missed"], 0)


if __name__ == "__main__":
    unittest.main()
