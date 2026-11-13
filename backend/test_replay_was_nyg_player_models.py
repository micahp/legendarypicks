"""Fast tests for as-of WAS-NYG reconstruction. No production DB dependency."""
import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nfl_player_projection_v2 as eng
import replay_was_nyg_player_models as m


class ReplayAsOfTests(unittest.TestCase):
    def test_source_timestamps_require_timezone(self):
        self.assertIsNone(m.utc_stamp(None))
        self.assertIsNone(m.utc_stamp("2026-11-08T17:00:00"))
        self.assertIsNone(m.utc_stamp("corrupt"))
        self.assertEqual(m.utc_stamp("2026-11-08T12:00:00-05:00").isoformat(),
                         "2026-11-08T17:00:00+00:00")

    def test_eastern_kickoff_uses_actual_timezone(self):
        self.assertEqual(m.kickoff("2026-11-08", "13:00").hour, 18)
        self.assertEqual(m.kickoff("2026-10-04", "13:00").hour, 17)
        self.assertIsNone(m.kickoff("2026-11-08", None))

    def test_target_week_logs_and_availability_removed(self):
        old = eng.Row(3, 2026, 9, "NYG", "WSH", "2026_09_NYG_WAS",
                      "WR", {"rec_yds": 20})
        target = eng.Row(3, 2026, 10, "NYG", "WSH", m.GAME,
                         "WR", {"rec_yds": 500})
        future = eng.Row(3, 2026, 11, "NYG", "WSH", "2026_11_NYG_WAS",
                         "WR", {"rec_yds": 1000})
        statuses = {
            (2026, "2026_09_NYG_WAS", "NYG"): {3: ("Questionable", 1)},
            (2026, m.GAME, "NYG"): {3: ("Out", 0)},
            (2026, "2026_11_NYG_WAS", "NYG"): {3: ("Out", 0)},
        }
        safe = m.prior_history(eng.History([old, target, future], statuses))
        self.assertEqual([r.rec_yds for r in safe.rows], [20])
        self.assertEqual(len(safe.status), 1)
        self.assertNotIn((2026, m.GAME, "NYG"), safe.status)

    def test_loader_never_queries_week10_or_later_player_or_injury_rows(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
        CREATE TABLE players (id INT, position TEXT, league TEXT);
        CREATE TABLE nfl_schedule (game_id TEXT, season INT, week INT,
            away_team TEXT, home_team TEXT, game_type TEXT);
        CREATE TABLE player_game_logs (player_id INT,team TEXT,game_id TEXT,
            stats TEXT,league TEXT,source TEXT,game_type TEXT);
        CREATE TABLE player_game_availability (
            season INT,game_id TEXT,team TEXT,player_id INT,
            report_status TEXT,played INT,league TEXT);
        """)
        con.execute("INSERT INTO players VALUES(?,?,?)", (3, "WR", "nfl"))
        for week, yds in ((9, 25), (10, 999)):
            gid = f"2026_{week:02}_WAS_NYG"
            con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?)",
                        (gid, 2026, week, "WSH", "NYG", "REG"))
            con.execute("INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?)",
                        (3, "NYG", gid, '{"rec_yds": %d}' % yds,
                         "nfl", "nflverse_weekly", "REG"))
            con.execute("INSERT INTO player_game_availability VALUES(?,?,?,?,?,?,?)",
                        (2026, gid, "NYG", 3, "Out", 0, "nfl"))
        hist = m.load_as_of_history(con)
        self.assertEqual(len(hist.rows), 1)
        self.assertEqual(hist.rows[0].rec_yds, 25)
        self.assertEqual(list(hist.status), [(2026, "2026_09_WAS_NYG", "NYG")])
        con.close()

    def test_pinned_cohort_has_unique_exact_player_market_line(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            p = folder / "graded-player-props.csv"
            with p.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["stable_player_id", "market", "line"])
                w.writeheader()
                for i in range(323):
                    w.writerow({"stable_player_id": f"00-{i:05d}",
                                "market": "receiving_yards", "line": "29.5"})
            self.assertEqual(len(m.read_cohort(folder)), 323)
            with p.open("a") as f:
                f.write("00-00000,receiving_yards,29.5\n")
            with self.assertRaisesRegex(ValueError, "expected pinned 323"):
                m.read_cohort(folder)

    def test_marcel_only_uses_earlier_games(self):
        rows = [eng.Row(3, 2026, week, "NYG", "WSH",
                        f"2026_{week:02}_NYG_WAS", "WR",
                        {"rec_yds": value})
                for week, value in ((7, 10), (8, 20), (9, 30))]
        history = m.prior_history(eng.History(rows, {}))
        got = m.raw_player_projections(history, 3, "NYG", "WSH",
                                       "WR", "receiving_yards", sims=100)
        self.assertEqual(got["marcel-lite"]["mean"], 20.0)
        self.assertEqual(m.p_over("marcel-lite", got["marcel-lite"], 15.5), .667)
        self.assertEqual(got["marcel-lite"]["n"], 3)

    def test_platt_probability_not_a_point_distribution(self):
        prediction = {"values": [0, 5, 6, 10]}
        self.assertEqual(m.p_over("spec-b-v2", prediction, 5.5), .5)
        self.assertIsNone(m.p_over("spec-b-v2", {"values": None}, 5.5))

    def test_strict_training_excludes_late_and_week10_quotes(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
        CREATE TABLE nfl_schedule (game_id TEXT, season INT, week INT,
            gameday TEXT, gametime TEXT, away_team TEXT, home_team TEXT, game_type TEXT);
        CREATE TABLE prop_games (id INT, league TEXT, date TEXT, home TEXT, away TEXT);
        CREATE TABLE props (game_id INT, player_id INT, market TEXT,
            source TEXT, line REAL, side TEXT, odds INT, captured_at TEXT);
        """)
        con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?,?,?)",
                    ("2026_09_WAS_NYG", 2026, 9, "2026-11-08", "13:00", "WSH", "NYG", "REG"))
        con.execute("INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?,?,?)",
                    (m.GAME, 2026, 10, "2026-11-12", "20:15", "WSH", "NYG", "REG"))
        con.execute("INSERT INTO prop_games VALUES(?,?,?,?,?)",
                    (7, "nfl", "2026-11-08", "NYG", "WSH"))
        con.execute("INSERT INTO prop_games VALUES(?,?,?,?,?)",
                    (8, "nfl", "2026-11-12", "NYG", "WSH"))
        for pg, at in ((7, "2026-11-08T17:30:00Z"),
                       (7, "2026-11-08T18:05:00Z"),
                       (8, "2026-11-12T23:00:00Z")):
            for side in ("over", "under"):
                con.execute("INSERT INTO props VALUES(?,?,?,?,?,?,?,?)",
                            (pg, 3, "receiving_yards", "bovada",
                             29.5 if at.endswith("30:00Z") else 45.5,
                             side, -110, at))
        # Week 9 outcome (known at the Week 10 kickoff) is training-only.
        r = eng.Row(3, 2026, 9, "NYG", "WSH", "2026_09_WAS_NYG",
                    "WR", {"rec_yds": 70})
        hist = eng.History([r], {})
        class Fake:
            def __init__(self, _hist):
                pass
            def draws(self, season, row, kind):
                return [(2, 60, 0, 3), (1, 20, 0, 2)]
        with patch.object(m.historical_grader, "Projector", Fake):
            fit, excluded, n = m.historic_training(con, hist, min_items=500)
        self.assertIsNone(fit)
        self.assertEqual(n, 1)
        self.assertGreater(excluded["unknown_or_late_capture"], 0)
        con.close()

    def test_select_player_team_only_from_pregame_evidence(self):
        hist = eng.History([], {})
        team, provenance = m.choose_team(hist, "00-00001",
                                         {"00-00001": "NYG"},
                                         {"WSH", "NYG"}, 3)
        self.assertEqual((team, provenance), ("NYG", "saved_pregame_slc_roster"))
        team, provenance = m.choose_team(hist, "00-00002", {},
                                         {"WSH", "NYG"}, 3)
        self.assertIsNone(team)


if __name__ == "__main__":
    unittest.main()
