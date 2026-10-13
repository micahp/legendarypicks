"""Contract checks for the read-only NFL model API against a disposable SQLite database."""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException, Response  # noqa: E402
import migrate_nfl_model_tables as migration  # noqa: E402
from routers.models import nfl as api  # noqa: E402


class NflModelApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "nfl.db")
        con = sqlite3.connect(self.path)
        migration.migrate(con)
        con.execute("CREATE TABLE nfl_teams (season INT, team TEXT, team_name TEXT, "
                    "conference TEXT, division TEXT)")
        con.execute("CREATE TABLE nfl_schedule (game_id TEXT, season INT, week INT, gameday TEXT, "
                    "home_score REAL, away_score REAL)")
        for i in range(32):
            conf = "AFC" if i < 16 else "NFC"
            division = "%s %s" % (conf, ("East", "North", "South", "West")[(i % 16) // 4])
            team = "T%02d" % i
            con.execute("INSERT INTO nfl_teams VALUES (2026,?,?,?,?)",
                        (team, "Team %s" % team, conf, division))
        con.execute("INSERT INTO model_runs VALUES "
                    "('r1','nfl',2026,5,'nfl-ratings-v1','v1','2026-10-10T10:00Z',NULL,'{}','ok',NULL)")
        seed_cols = ["p_seed_%d" % n for n in range(1, 8)]
        odds_cols = ["run_id", "league", "season", "week", "team", "p_playoffs", "p_division",
                     "p_bye"] + seed_cols + ["wins_mean", "wins_p10", "wins_p90", "d_playoffs", "as_of"]
        odds_values = ["r1", "nfl", 2026, 5, "", 0.5, 0.2, 0.1] + [1 / 16] * 7 + [9.0, 7, 11, None,
                                                                                     "2026-10-10T10:00Z"]
        con.executemany("INSERT INTO playoff_odds (%s) VALUES (%s)" %
                        (",".join(odds_cols), ",".join("?" for _ in odds_cols)),
                        [odds_values[:4] + ["T%02d" % i] + odds_values[5:] for i in range(32)])
        con.executemany(
            'INSERT INTO team_ratings (run_id,league,season,week,team,"off","def",overall,games,as_of) '
            "VALUES ('r1','nfl',2026,5,?,?,?,0,5,'2026-10-10T10:00Z')",
            [("T%02d" % i, float(i), float(-i)) for i in range(32)])
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def test_odds_and_ratings_return_all_32_teams(self):
        with patch.object(api, "_db", self.connect):
            response = Response()
            odds = api.playoff_odds(response, season=2026, week=None, model_version=None)
            self.assertEqual(len(odds["teams"]), 32)
            self.assertEqual(response.headers["X-LP-Data-Source"], api.DATA_SOURCE)

            ratings = api.ratings(Response(), season=2026, week=None, model_version=None)
            self.assertEqual(len(ratings["teams"]), 32)

    def test_api_refuses_an_incomplete_team_mapping(self):
        con = sqlite3.connect(self.path)
        con.execute("DELETE FROM nfl_teams WHERE team='T31'")
        con.commit()
        con.close()
        with patch.object(api, "_db", self.connect):
            with self.assertRaises(HTTPException) as caught:
                api.playoff_odds(Response(), season=2026, week=None, model_version=None)
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
