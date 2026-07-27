"""Tests for NFL play retention and the game_date/home_away fix.

This ingest had no coverage at all while being the sole writer of the 2025 NFL
season. Every assertion below was checked against a deliberately broken
implementation, not just a passing one -- an assertion that cannot fail is not a
test.

No network: nfl_data_py.import_pbp_data is replaced with a synthetic frame.
"""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _frame():
    import pandas as pd
    import ingest_nfl_pbp_logs as mod
    # Two teams, one game, four plays. SEA is home, so a SEA row must resolve to
    # 'home' and the ARI row to 'away' -- the pair is what makes the assertion
    # meaningful rather than a coin flip that passes half the time.
    rows = []
    common = dict(game_id="2025_01_ARI_SEA", season=2025, week=1,
                  home_team="SEA", away_team="ARI", game_date="2025-09-07",
                  season_type="REG",
                  # Eligibility + lateral columns default to "ordinary play".
                  sack=0, two_point_attempt=0,
                  lateral_receiver_player_id=None, lateral_receiver_player_name=None,
                  lateral_receiving_yards=None,
                  lateral_rusher_player_id=None, lateral_rusher_player_name=None,
                  lateral_rushing_yards=None)
    rows.append(dict(common, play_id=1, posteam="SEA", defteam="ARI", qtr=1, down=1,
                     ydstogo=10, yardline_100=75, game_seconds_remaining=3600,
                     play_type="pass", epa=0.5, wpa=0.02, qb_epa=0.5, air_yards=12.0,
                     yards_gained=12, cpoe=3.1, passer_player_id="00-0000001",
                     rusher_player_id=None, receiver_player_id="00-0000002",
                     pass_location="left", run_location=None, run_gap=None,
                     complete_pass=1, touchdown=0, series=1, series_result="First down",
                     drive=1, success=1, shotgun=1, pass_attempt=1, rush_attempt=0,
                     passing_yards=12.0, rushing_yards=0.0, receiving_yards=12.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name="QB One", rusher_player_name=None,
                     receiver_player_name="WR Two"))
    rows.append(dict(common, play_id=2, posteam="SEA", defteam="ARI", qtr=1, down=1,
                     ydstogo=10, yardline_100=63, game_seconds_remaining=3560,
                     play_type="run", epa=-0.2, wpa=-0.01, qb_epa=0.0, air_yards=None,
                     yards_gained=3, cpoe=None, passer_player_id=None,
                     rusher_player_id="00-0000003", receiver_player_id=None,
                     pass_location=None, run_location="middle", run_gap="guard",
                     complete_pass=0, touchdown=0, series=1, series_result="First down",
                     drive=1, success=0, shotgun=0, pass_attempt=0, rush_attempt=1,
                     passing_yards=0.0, rushing_yards=3.0, receiving_yards=0.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name=None, rusher_player_name="RB Three",
                     receiver_player_name=None))
    rows.append(dict(common, play_id=3, posteam="ARI", defteam="SEA", qtr=2, down=3,
                     ydstogo=2, yardline_100=40, game_seconds_remaining=1800,
                     play_type="pass", epa=0.9, wpa=0.04, qb_epa=0.9, air_yards=5.0,
                     yards_gained=8, cpoe=1.0, passer_player_id="00-0000004",
                     rusher_player_id=None, receiver_player_id="00-0000005",
                     pass_location="right", run_location=None, run_gap=None,
                     complete_pass=1, touchdown=0, series=2, series_result="First down",
                     drive=2, success=1, shotgun=1, pass_attempt=1, rush_attempt=0,
                     passing_yards=8.0, rushing_yards=0.0, receiving_yards=8.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name="QB Four", rusher_player_name=None,
                     receiver_player_name="WR Five"))
    # A postseason play, to prove the REG filter still applies to retention.
    rows.append(dict(common, play_id=4, posteam="SEA", defteam="ARI", qtr=1, down=1,
                     ydstogo=10, yardline_100=75, game_seconds_remaining=3600,
                     play_type="pass", epa=0.1, wpa=0.0, qb_epa=0.1, air_yards=4.0,
                     yards_gained=4, cpoe=0.0, passer_player_id="00-0000001",
                     rusher_player_id=None, receiver_player_id="00-0000002",
                     pass_location="left", run_location=None, run_gap=None,
                     complete_pass=1, touchdown=0, series=1, series_result="First down",
                     drive=1, success=1, shotgun=1, pass_attempt=1, rush_attempt=0,
                     passing_yards=4.0, rushing_yards=0.0, receiving_yards=4.0,
                     pass_touchdown=0, rush_touchdown=0, interception=0,
                     passer_player_name="QB One", rusher_player_name=None,
                     receiver_player_name="WR Two"))
    rows[-1]["season_type"] = "POST"
    return pd.DataFrame(rows)


class PbpRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        con = sqlite3.connect(self.db)
        con.execute("""CREATE TABLE players (id INTEGER PRIMARY KEY, league TEXT,
                       name TEXT, nfl_gsis_id TEXT)""")
        for pid, gsis in ((1, "00-0000001"), (2, "00-0000002"), (3, "00-0000003"),
                          (4, "00-0000004"), (5, "00-0000005")):
            con.execute("INSERT INTO players VALUES (?,'nfl',?,?)", (pid, f"p{pid}", gsis))
        con.commit(); con.close()

        import nfl_data_py
        import ingest_nfl_pbp_logs as mod
        self.mod = mod
        mod.DB = self.db
        self._orig = nfl_data_py.import_pbp_data
        nfl_data_py.import_pbp_data = lambda years: _frame()

    def tearDown(self):
        import nfl_data_py
        nfl_data_py.import_pbp_data = self._orig

    def _run(self):
        self.mod.ingest(2025)
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return con

    def test_plays_are_retained_and_regular_season_only(self):
        con = self._run()
        n = con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0]
        # 3 REG plays retained, the POST play dropped by the existing filter.
        self.assertEqual(n, 3)
        seasons = [r[0] for r in con.execute("SELECT DISTINCT season FROM nfl_pbp")]
        self.assertEqual(seasons, [2025])

    def test_retained_play_keeps_the_columns_charts_need(self):
        con = self._run()
        row = con.execute("SELECT * FROM nfl_pbp WHERE play_id=1").fetchone()
        self.assertEqual(row["epa"], 0.5)
        self.assertEqual(row["air_yards"], 12.0)
        self.assertEqual(row["down"], 1)
        self.assertEqual(row["ydstogo"], 10)
        self.assertEqual(row["run_gap"], None)
        self.assertEqual(row["receiver_player_id"], "00-0000002")
        self.assertEqual(row["series_result"], "First down")

    def test_game_date_and_home_away_are_populated(self):
        """The bug this fixes left both NULL on all 10,717 NFL rows."""
        con = self._run()
        rows = con.execute(
            "SELECT team, game_date, home_away FROM player_game_logs WHERE league='nfl'"
        ).fetchall()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["game_date"], "2025-09-07")
            self.assertIsNotNone(r["home_away"])
        sides = {r["team"]: r["home_away"] for r in rows}
        # SEA is home_team, ARI is not. Both directions asserted so a constant
        # would fail.
        self.assertEqual(sides["SEA"], "home")
        self.assertEqual(sides["ARI"], "away")

    def test_missing_source_column_fails_loud(self):
        """Silent narrowing is the drift that went unnoticed between 2024/2025."""
        import nfl_data_py
        nfl_data_py.import_pbp_data = lambda years: _frame().drop(columns=["run_gap"])
        with self.assertRaises(RuntimeError) as ctx:
            self.mod.ingest(2025)
        self.assertIn("run_gap", str(ctx.exception))

    def test_rerunning_does_not_duplicate_plays(self):
        self.mod.ingest(2025)
        self.mod.ingest(2025)
        con = sqlite3.connect(self.db)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM nfl_pbp").fetchone()[0], 3)

    def test_existing_enrichment_and_legacy_keys_are_preserved(self):
        con = sqlite3.connect(self.db)
        self.mod.ensure_table(con)
        existing_stats = {
            "pass_yds": 999,
            "fpts": 999,
            "off_pct": 0.82,
            "separation": 2.4,
            "passing_yards": 999,
        }
        cursor = con.execute(
            """INSERT INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (1, 'nfl', 2025, '1', '2025_01_ARI_SEA', NULL, 'SEA',
                       'ARI', NULL, ?, 'nflverse', '00-0000001')""",
            (json.dumps(existing_stats),),
        )
        original_row_id = cursor.lastrowid
        con.commit()
        con.close()

        output = io.StringIO()
        with redirect_stdout(output):
            self.mod.ingest(2025)

        con = sqlite3.connect(self.db)
        row = con.execute(
            """SELECT id, stats FROM player_game_logs
               WHERE league='nfl' AND source_player_key='00-0000001'
                 AND season=2025 AND game_no='1'"""
        ).fetchone()
        con.close()
        stats = json.loads(row[1])

        self.assertEqual(original_row_id, row[0])
        self.assertEqual(12, stats["pass_yds"])
        self.assertEqual(0.48, stats["fpts"])
        self.assertEqual(0.82, stats["off_pct"])
        self.assertEqual(2.4, stats["separation"])
        self.assertEqual(999, stats["passing_yards"])
        self.assertIn(
            "preserved 3 existing stat keys across 1 player-game rows",
            output.getvalue().lower(),
        )


class EligibilityAndLateralTests(unittest.TestCase):
    """The rollup once read raw pbp flags as if they were official stat
    definitions. Reconciled against nflverse's own weekly artifact for 2025,
    that was wrong on 514 player-games for `att`, 88 for `targets` and 19 for
    yardage. These fix the definitions in place."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        con = sqlite3.connect(self.db)
        con.execute("""CREATE TABLE players (id INTEGER PRIMARY KEY, league TEXT,
                       name TEXT, nfl_gsis_id TEXT)""")
        for pid, gsis in ((1, "00-0000001"), (2, "00-0000002"), (3, "00-0000003"),
                          (4, "00-0000004"), (5, "00-0000005"), (6, "00-0000006")):
            con.execute("INSERT INTO players VALUES (?,'nfl',?,?)", (pid, f"p{pid}", gsis))
        con.commit(); con.close()
        import nfl_data_py
        import ingest_nfl_pbp_logs as mod
        self.mod = mod
        mod.DB = self.db
        self._orig = nfl_data_py.import_pbp_data

    def tearDown(self):
        import nfl_data_py
        nfl_data_py.import_pbp_data = self._orig

    def _stats(self, gsis):
        con = sqlite3.connect(self.db)
        row = con.execute(
            """SELECT stats FROM player_game_logs WHERE league='nfl'
               AND source_player_key=? AND season=2025 AND game_no='1'""",
            (gsis,)).fetchone()
        con.close()
        return json.loads(row[0]) if row else None

    def _ingest(self, extra_rows):
        import nfl_data_py, pandas as pd
        base = _frame()
        nfl_data_py.import_pbp_data = lambda years: pd.concat(
            [base, pd.DataFrame(extra_rows)], ignore_index=True)
        with redirect_stdout(io.StringIO()):
            self.mod.ingest(2025)

    def _play(self, **kw):
        """A pass from QB One to WR Two, overridable."""
        base = dict(game_id="2025_01_ARI_SEA", season=2025, week=1, home_team="SEA",
                    away_team="ARI", game_date="2025-09-07", season_type="REG",
                    play_id=99, posteam="SEA", defteam="ARI", qtr=3, down=1,
                    ydstogo=10, yardline_100=50, game_seconds_remaining=900,
                    play_type="pass", epa=-1.0, wpa=-0.05, qb_epa=-1.0,
                    air_yards=None, yards_gained=-7, cpoe=None,
                    passer_player_id="00-0000001", rusher_player_id=None,
                    receiver_player_id=None, pass_location=None, run_location=None,
                    run_gap=None, complete_pass=0, touchdown=0, series=3,
                    series_result="Punt", drive=3, success=0, shotgun=1,
                    pass_attempt=1, rush_attempt=0, passing_yards=0.0,
                    rushing_yards=0.0, receiving_yards=0.0, pass_touchdown=0,
                    rush_touchdown=0, interception=0, sack=0, two_point_attempt=0,
                    passer_player_name="QB One", rusher_player_name=None,
                    receiver_player_name=None,
                    lateral_receiver_player_id=None, lateral_receiver_player_name=None,
                    lateral_receiving_yards=None, lateral_rusher_player_id=None,
                    lateral_rusher_player_name=None, lateral_rushing_yards=None)
        base.update(kw)
        return base

    def test_sacks_are_not_pass_attempts(self):
        """432 of 514 wrong 2025 rows were off by exactly the passer's sacks."""
        self._ingest([self._play(sack=1)])
        s = self._stats("00-0000001")
        # QB One has exactly one eligible attempt in the base frame (the other
        # base pass is postseason). The sack must not become a second.
        self.assertEqual(1, s["att"])

    def test_two_point_conversions_are_not_attempts_or_targets(self):
        self._ingest([self._play(play_id=98, two_point_attempt=1, complete_pass=1,
                                 receiver_player_id="00-0000002",
                                 receiver_player_name="WR Two",
                                 receiving_yards=3.0, passing_yards=3.0)])
        self.assertEqual(1, self._stats("00-0000001")["att"])
        wr = self._stats("00-0000002")
        # Base frame gives WR Two exactly one target for 12 yards.
        self.assertEqual(1, wr["targets"])
        self.assertEqual(12, wr["rec_yds"])

    def test_sack_still_counts_as_a_dropback_and_keeps_its_epa(self):
        """A sack is a real outcome of a dropback; excluding it from EPA would
        flatter every quarterback who took one."""
        self._ingest([self._play(sack=1)])
        s = self._stats("00-0000001")
        self.assertEqual(2, s["dropbacks"])
        self.assertNotEqual(s["att"], s["dropbacks"])
        # base frame qb_epa 0.5 + 0.1(POST, dropped) ... only REG: 0.5, plus -1.0
        self.assertAlmostEqual(-0.5, s["pass_epa"], places=3)

    def test_lateral_receiving_yards_are_credited_to_the_lateral_player(self):
        """DJ Moore's 2025 week 1 was stored as 57 against an official 68."""
        self._ingest([self._play(
            play_id=97, complete_pass=1, receiver_player_id="00-0000002",
            receiver_player_name="WR Two", receiving_yards=10.0, passing_yards=25.0,
            yards_gained=25, lateral_receiver_player_id="00-0000006",
            lateral_receiver_player_name="WR Six", lateral_receiving_yards=15.0)])
        # The catching receiver keeps only his own yards: 12 base + 10.
        self.assertEqual(22, self._stats("00-0000002")["rec_yds"])
        # The lateral player had no other touch, so this row exists only because
        # of the outer merge -- the case the old code dropped entirely.
        six = self._stats("00-0000006")
        self.assertIsNotNone(six, "lateral-only player produced no game log row")
        self.assertEqual(15, six["rec_yds"])

    def test_lateral_rushing_yards_are_credited(self):
        self._ingest([self._play(
            play_id=96, play_type="run", pass_attempt=0, rush_attempt=1,
            passer_player_id=None, passer_player_name=None,
            rusher_player_id="00-0000003", rusher_player_name="RB Three",
            rushing_yards=5.0, yards_gained=20,
            lateral_rusher_player_id="00-0000006",
            lateral_rusher_player_name="WR Six", lateral_rushing_yards=15.0)])
        self.assertEqual(8, self._stats("00-0000003")["rush_yds"])  # 3 base + 5
        self.assertEqual(15, self._stats("00-0000006")["rush_yds"])

    def test_stale_rollup_keys_are_cleared_but_enrichment_survives(self):
        """A row the tightened rule no longer produces would otherwise keep the
        looser run's numbers forever, since it is never updated again."""
        con = sqlite3.connect(self.db)
        self.mod.ensure_table(con)
        con.execute(
            """INSERT INTO player_game_logs
               (player_id, league, season, game_no, game_id, team, opponent,
                stats, source, source_player_key)
               VALUES (6, 'nfl', 2025, '1', '2025_01_ARI_SEA', 'SEA', 'ARI',
                       ?, 'nflverse_pbp', '00-0000006')""",
            (json.dumps({"targets": 1, "rec_yds": 3, "fpts": 0.3, "off_pct": 0.11}),))
        con.commit(); con.close()

        self._ingest([])  # WR Six has no eligible play at all

        s = self._stats("00-0000006")
        self.assertNotIn("targets", s)
        self.assertNotIn("rec_yds", s)
        self.assertNotIn("fpts", s)
        self.assertEqual(0.11, s["off_pct"], "another ingest's data must survive")

    def test_quarterbacks_do_not_get_a_zero_receiving_line(self):
        """Filling the lateral sum with 0 would put rec_yds on every passer."""
        self._ingest([])
        self.assertNotIn("rec_yds", self._stats("00-0000001"))


if __name__ == "__main__":
    unittest.main()
