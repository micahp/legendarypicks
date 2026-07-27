"""Tests for the nflverse games.csv schedule ingest.

Every assertion below was checked against a deliberately broken implementation,
not just a passing one -- an assertion that cannot fail is not a test. The two
that matter most are the pair that guards re-running: an unplayed fixture must
not be stored as a 0-0 tie, and re-running a not-yet-played season must not
blank out a result some other ingest already recorded.

No network: a synthetic games.csv is written to a temp dir.
"""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HEADER = ("game_id,season,game_type,week,gameday,weekday,gametime,away_team,"
          "away_score,home_team,home_score,location,result,total,overtime,"
          "old_game_id,gsis,nfl_detail_id,pfr,pff,espn,ftn,away_rest,home_rest,"
          "away_moneyline,home_moneyline,spread_line,away_spread_odds,"
          "home_spread_odds,total_line,under_odds,over_odds,div_game,roof,"
          "surface,temp,wind,away_qb_id,home_qb_id,away_qb_name,home_qb_name,"
          "away_coach,home_coach,referee,stadium_id,stadium")

# A finished 2025 game (SEA 24, ARI 17) and an unplayed 2026 fixture. The 2026
# row carries empty score/result cells exactly as the real file does.
PLAYED = ("2025_01_ARI_SEA,2025,REG,1,2025-09-07,Sunday,13:00,ARI,17,SEA,24,"
          "Home,7,41,0,2025090700,,,,,401772718,,7,7,150,-180,-3.5,-110,-110,"
          "44.5,-110,-110,0,outdoors,grass,68,5,00-0000001,00-0000002,"
          "Kyler Murray,Sam Darnold,Jonathan Gannon,Mike Macdonald,Ref A,"
          "SEA00,Lumen Field")
UNPLAYED = ("2026_01_NE_SEA,2026,REG,1,2026-09-09,Wednesday,20:20,NE,,SEA,,"
            "Home,,,,2026090900,,,,,,,7,7,164,-198,3.5,-110,-110,44.5,-110,"
            "-110,0,outdoors,fieldturf,,,,,,,Mike Vrabel,Mike Macdonald,,"
            "SEA00,Lumen Field")


def _csv(tmp, *rows):
    path = os.path.join(tmp, "games.csv")
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(HEADER + "\n")
        for r in rows:
            fh.write(r + "\n")
    return path


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE team_game_results(
        league TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL,
        game_date TEXT, opponent TEXT, home_away TEXT,
        score_for REAL, score_against REAL, win INTEGER,
        ingested_at TEXT DEFAULT (datetime('now')), season INTEGER, status TEXT,
        PRIMARY KEY(league, game_id, team))""")
    return con


class ReadGames(unittest.TestCase):
    def setUp(self):
        import ingest_nfl_schedule as mod
        self.mod = mod
        self.tmp = tempfile.mkdtemp()

    def test_empty_score_is_none_not_zero(self):
        """The whole point. '' means 'not played', and a 0 here would make all
        272 fixtures look like completed 0-0 ties."""
        rows = self.mod.read_games(_csv(self.tmp, UNPLAYED), {2026})
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["home_score"])
        self.assertIsNone(rows[0]["away_score"])
        self.assertIsNone(rows[0]["result"])
        # ...while a genuine zero-valued column still reads as 0.
        self.assertEqual(rows[0]["div_game"], 0)

    def test_season_filter(self):
        path = _csv(self.tmp, PLAYED, UNPLAYED)
        self.assertEqual([r["game_id"] for r in self.mod.read_games(path, {2026})],
                         ["2026_01_NE_SEA"])
        self.assertEqual(len(self.mod.read_games(path, None)), 2)

    def test_numeric_typing(self):
        rows = self.mod.read_games(_csv(self.tmp, PLAYED), {2025})
        self.assertEqual(rows[0]["home_score"], 24)
        self.assertIsInstance(rows[0]["home_score"], int)
        self.assertEqual(rows[0]["spread_line"], -3.5)
        self.assertEqual(rows[0]["stadium"], "Lumen Field")

    def test_missing_column_fails_loudly(self):
        """A silently renamed upstream column is how the pbp ingest ended up
        justified by a false premise for a year."""
        path = os.path.join(self.tmp, "games.csv")
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write("game_id,season\n2026_01_NE_SEA,2026\n")
        with self.assertRaises(RuntimeError):
            self.mod.read_games(path, {2026})


class Write(unittest.TestCase):
    def setUp(self):
        import ingest_nfl_schedule as mod
        self.mod = mod
        self.tmp = tempfile.mkdtemp()
        self.con = _db()
        self.mod.ensure_schema(self.con)

    def _load(self, *rows, seasons=None):
        got = self.mod.read_games(_csv(self.tmp, *rows), seasons)
        with redirect_stdout(io.StringIO()):
            return self.mod.write(self.con, got)

    def test_reciprocal_pairs(self):
        self._load(PLAYED, seasons={2025})
        got = dict(self.con.execute(
            "SELECT team, home_away FROM team_game_results").fetchall())
        self.assertEqual(got, {"SEA": "home", "ARI": "away"})
        sea = self.con.execute(
            "SELECT opponent,score_for,score_against,win,status FROM "
            "team_game_results WHERE team='SEA'").fetchone()
        self.assertEqual(sea, ("ARI", 24.0, 17.0, 1, "completed"))
        ari = self.con.execute(
            "SELECT score_for,win,status FROM team_game_results "
            "WHERE team='ARI'").fetchone()
        self.assertEqual(ari, (17.0, 0, "completed"))

    def test_unplayed_game_is_scheduled_with_no_score(self):
        self._load(UNPLAYED, seasons={2026})
        rows = self.con.execute(
            "SELECT team,opponent,score_for,score_against,win,status,season "
            "FROM team_game_results ORDER BY team").fetchall()
        self.assertEqual(rows, [
            ("NE", "SEA", None, None, None, "scheduled", 2026),
            ("SEA", "NE", None, None, None, "scheduled", 2026),
        ])

    def test_rerun_does_not_blank_a_recorded_result(self):
        """A completed row written by another ingest must survive a re-run of a
        season whose CSV cells are still empty -- the COALESCE guard."""
        self.con.execute(
            "INSERT INTO team_game_results(league,game_id,team,game_date,opponent,"
            "home_away,score_for,score_against,win,season,status) "
            "VALUES('nfl','2026_01_NE_SEA','SEA','2026-09-09','NE','home',"
            "31,10,1,2026,'completed')")
        self._load(UNPLAYED, seasons={2026})
        row = self.con.execute(
            "SELECT score_for,score_against,win,status FROM team_game_results "
            "WHERE team='SEA'").fetchone()
        self.assertEqual(row, (31.0, 10.0, 1, "completed"))
        # the other side of the same game was genuinely absent, so it lands new
        self.assertEqual(self.con.execute(
            "SELECT status FROM team_game_results WHERE team='NE'").fetchone()[0],
            "scheduled")

    def test_upsert_is_idempotent(self):
        self._load(UNPLAYED, seasons={2026})
        self._load(UNPLAYED, seasons={2026})
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM nfl_schedule").fetchone()[0], 1)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM team_game_results").fetchone()[0], 2)

    def test_schedule_row_keeps_source_detail(self):
        self._load(UNPLAYED, seasons={2026})
        row = self.con.execute(
            "SELECT week,gameday,gametime,roof,surface,home_coach,stadium,source "
            "FROM nfl_schedule").fetchone()
        self.assertEqual(row, (1, "2026-09-09", "20:20", "outdoors", "fieldturf",
                               "Mike Macdonald", "Lumen Field", "nflverse_games"))

    def test_no_coverage_manifest_is_written(self):
        """The NFL team-stats contract bounds its aggregate by the newest
        team_stats_coverage row. Writing one for 2026 would pull 272 unplayed
        games into season totals."""
        self._load(UNPLAYED, seasons={2026})
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='team_stats_coverage'"
        ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
