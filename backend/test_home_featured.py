"""Selection rules and null cases for routers/home.py (GET /api/home/featured).

Temp DB only. Each rule is tested by planting the rival the rule must reject.
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_IMPORT_DB = tempfile.NamedTemporaryFile(prefix="home-import-", suffix=".db", delete=False)
_IMPORT_DB.close()
os.environ["LP_DB_PATH"] = _IMPORT_DB.name

import migrate_nfl_model_tables as migration  # noqa: E402
import nfl_lock as nl  # noqa: E402
import scripts_split_provider_logs as split  # noqa: E402
from routers import home, nfl_model, props  # noqa: E402

NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.timezone.utc)
RECENT = "2026-10-13T05:00:00+00:00"
STALE = "2026-10-11T05:00:00+00:00"        # more than 36 hours before NOW


def build(path, with_odds=True):
    con = sqlite3.connect(path)
    migration.migrate(con)
    con.executescript("""
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT);
        CREATE TABLE player_game_logs(player_id INTEGER, league TEXT, season INTEGER, stats TEXT,
            game_date TEXT, opponent TEXT, home_away TEXT, game_no INTEGER, game_type TEXT, source TEXT);
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL,
            date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT, final_home INTEGER,
            final_away INTEGER, start_time TEXT, cancelled_at TEXT, cancel_reason TEXT, cancel_source TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER, player_id INTEGER,
            market TEXT NOT NULL, line REAL NOT NULL, side TEXT NOT NULL, source TEXT,
            captured_at TEXT NOT NULL, odds INTEGER, odds_captured_at TEXT);
        CREATE TABLE nfl_teams(season INT, team TEXT, team_name TEXT, conference TEXT, division TEXT);
        CREATE TABLE nfl_schedule (game_id TEXT, season INT, game_type TEXT, week INT, home_team TEXT,
            away_team TEXT, location TEXT, home_score REAL, away_score REAL, result REAL,
            spread_line REAL, total_line REAL, home_moneyline REAL, away_moneyline REAL,
            gameday TEXT, gametime TEXT, ingested_at TEXT);
    """)
    split.ensure_espn_columns(con)
    con.executescript(split.DDL_TABLE)
    con.executescript(split.DDL_VIEW)
    for i in range(32):
        conf = "AFC" if i < 16 else "NFC"
        con.execute("INSERT INTO nfl_teams VALUES (2026,?,?,?,?)",
                    ("T%02d" % i, "Team %02d" % i, conf, "%s %d" % (conf, (i % 16) // 4)))
    if with_odds:
        con.execute("INSERT INTO model_runs VALUES ('o1','nfl',2026,5,'m','nfl-playoff-odds-v1.2',"
                    "'2026-10-12T10:00Z',NULL,?,'ok',NULL)", (json.dumps({"n": 20000}),))
        cols = ["run_id", "league", "season", "week", "team", "p_playoffs", "as_of"]
        for i in range(32):
            p = 0.9 - i * 0.02
            con.execute("INSERT INTO playoff_odds (%s) VALUES (?,?,?,?,?,?,?)" % ",".join(cols),
                        ("o1", "nfl", 2026, 5, "T%02d" % i, p, "2026-10-12T10:00Z"))
    con.commit()
    return con


def player(con, pid, name, n_games, yards=100):
    con.execute("INSERT INTO players VALUES (?,?,?,?,?)", (pid, name, "T00", "nfl", "WR"))
    for k in range(n_games):
        con.execute("INSERT INTO player_game_logs(player_id,league,season,stats,game_date,opponent,"
                    "home_away,game_no,source) VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, "nfl", 2025, json.dumps({"rec_yds": yards + k}),
                     "2025-09-%02d" % (k + 1) if k < 30 else "2025-10-%02d" % (k - 29),
                     "OPP", "home", k + 1, "espn"))


def prop(con, pid, captured, market="receiving_yards", line=90.5, league="nfl", side="over"):
    gid = con.execute("INSERT INTO prop_games(league,date,home,away,start_time) "
                      "VALUES (?,?,?,?,?)", (league, "2026-10-18", "T01", "T00",
                                              "2026-10-18T17:00:00Z")).lastrowid
    con.execute("INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) "
                "VALUES (?,?,?,?,?,?,?)", (gid, pid, market, line, side, "src", captured))


class Base(unittest.TestCase):
    with_odds = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "h.db")
        self.con = build(self.path, self.with_odds)

        def connection():
            c = sqlite3.connect(self.path)
            c.row_factory = sqlite3.Row
            return c
        p = mock.patch.object(props, "_db", side_effect=connection)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def payload(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            return home.featured_payload(c, NOW)
        finally:
            c.close()


class PropRule(Base):
    def test_most_settled_games_wins_and_short_history_loses(self):
        player(self.con, 1, "Short", 21)
        player(self.con, 2, "Long", 30)
        player(self.con, 3, "TooShort", 19)
        for pid in (1, 2, 3):
            prop(self.con, pid, RECENT)
        self.con.commit()
        p = self.payload()["prop"]
        self.assertEqual(p["player_id"], 2)
        self.assertEqual(p["hit_rate_n"]["season"], 30)

    def test_stale_other_league_and_under_rows_are_not_candidates(self):
        player(self.con, 1, "Stale", 40)
        player(self.con, 2, "Wrong league", 40)
        player(self.con, 3, "Under only", 40)
        player(self.con, 4, "Eligible", 25)
        prop(self.con, 1, STALE)
        prop(self.con, 2, RECENT, league="nba")
        prop(self.con, 3, RECENT, side="under")
        prop(self.con, 4, RECENT)
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 4)

    def test_tie_goes_to_latest_capture_then_lowest_player_id(self):
        for pid in (5, 6, 7):
            player(self.con, pid, "P%d" % pid, 25)
        prop(self.con, 5, "2026-10-13T04:00:00+00:00")
        prop(self.con, 6, "2026-10-13T06:00:00+00:00")
        prop(self.con, 7, "2026-10-13T06:00:00+00:00")
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 6)

    def test_numbers_equal_prop_history(self):
        player(self.con, 1, "Same", 25)
        prop(self.con, 1, RECENT, line=110.5)
        self.con.commit()
        out = self.payload()["prop"]
        h = props.prop_history(player_id=1, market="receiving_yards", line=110.5, side="over",
                               league="nfl")
        self.assertEqual(out["hit_rate"], h["hit_rate"])
        self.assertEqual(out["hit_rate_n"], h["hit_rate_n"])
        self.assertEqual(len(out["games"]), 20)
        self.assertEqual(out["games"][-1]["value"], h["games"][0]["value"])   # oldest first
        self.assertEqual(out["source"]["as_of"], RECENT)

    def test_latest_line_for_a_player_market_is_used(self):
        player(self.con, 1, "Moved", 25)
        prop(self.con, 1, "2026-10-13T01:00:00+00:00", line=80.5)
        prop(self.con, 1, "2026-10-13T05:00:00+00:00", line=95.5)
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["line"], 95.5)

    def test_null_when_nobody_qualifies_and_chain_player_follows(self):
        player(self.con, 1, "Short", 5)
        prop(self.con, 1, RECENT)
        self.con.commit()
        out = self.payload()
        self.assertIsNone(out["prop"])
        self.assertIn("prop", out["absent"])
        self.assertIsNone(out["chain"]["player"])
        self.assertIn("chain.player", out["absent"])


def lock_game(con, gid, gameday, hs, as_, version=nfl_model.ADOPTED, ml=(105, -125), spread=3.0,
              week=5, graded=True):
    con.execute("INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (gid, 2026, "REG", week, "T01", "T00", "Home", hs, as_, None if hs is None else hs - as_,
                 spread, 45.5, ml[0], ml[1], gameday, "13:00", "i"))
    rid = "run-" + gid + version[:6]
    nl.start_run(con, rid, 2026, week, version, {})
    snap = con.execute("INSERT INTO nfl_line_snapshots (league,game_id,source,captured_at,spread_line,"
                       "total_line,home_moneyline,away_moneyline) VALUES ('nfl',?,?,?,?,?,?,?)",
                       (gid, "s", "t0", spread, 45.5, ml[0], ml[1])).lastrowid
    con.execute("INSERT INTO game_projections (run_id,league,game_id,season,week,home,away,proj_home,"
                "proj_away,proj_margin,proj_total,p_home_win,market_spread,market_total,locked,"
                "locked_at,model_version,line_snapshot_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                (rid, "nfl", gid, 2026, week, "T01", "T00", 24.1, 24.6, -0.5, 48.7, 0.48, spread,
                 45.5, "t1", version, snap))
    if graded and hs is not None:
        con.execute("INSERT INTO projection_grades VALUES ('nfl',?,?,?,?,0.2,0.5,3.5,1.0,'win','g')",
                    (gid, version, hs, as_))
    con.commit()


class GameRule(Base):
    def test_most_recent_graded_adopted_game(self):
        lock_game(self.con, "g1", "2026-10-04", 20, 17)
        lock_game(self.con, "g2", "2026-10-11", 23, 30)
        lock_game(self.con, "g3", "2026-10-12", 10, 3, version="nfl-v1 cap=21.0 sigma=13.4")
        lock_game(self.con, "g4", "2026-10-12", 10, 3, graded=False)       # final, no grade
        g = self.payload()["game"]
        self.assertEqual(g["game_id"], "g2")
        self.assertEqual(g["model_label"], "v1 points")
        self.assertEqual(g["final"], {"home": 23.0, "away": 30.0})
        self.assertEqual(g["pick_result"], "win")
        self.assertEqual(g["pick"]["team"], "T00")
        self.assertAlmostEqual(g["pick"]["gap"], 3.5)
        self.assertEqual(g["pick"]["line"], 3.0)
        self.assertEqual(g["home_name"], "Team 01")

    def test_falls_back_to_next_upcoming_locked_game(self):
        lock_game(self.con, "u1", "2026-10-25", None, None)
        lock_game(self.con, "u2", "2026-10-18", None, None)
        lock_game(self.con, "past", "2026-10-05", None, None)      # kickoff passed, never final
        g = self.payload()["game"]
        self.assertEqual(g["game_id"], "u2")
        self.assertIsNone(g["final"])
        self.assertIsNone(g["pick_result"])

    def test_null_when_nothing_qualifies(self):
        lock_game(self.con, "x", "2026-10-04", 20, 17, version="nfl-v1 cap=21.0 sigma=13.4")
        out = self.payload()
        self.assertIsNone(out["game"])
        self.assertIn("game", out["absent"])
        self.assertIsNone(out["chain"]["game"])
        self.assertIsNone(out["chain"]["market"])

    def test_market_probability_is_vig_free_and_absent_without_moneylines(self):
        lock_game(self.con, "m", "2026-10-11", 23, 30, ml=(100, -100))
        c = self.payload()["chain"]["market"]
        self.assertAlmostEqual(c["market_p_home_win"], 0.5)
        self.assertEqual(c["model_p_home_win"], 0.48)
        self.con.execute("UPDATE nfl_line_snapshots SET home_moneyline=NULL")
        self.con.commit()
        out = self.payload()
        self.assertIsNone(out["chain"]["market"])
        self.assertIn("chain.market", out["absent"])
        self.assertIsNotNone(out["game"])

    def test_no_pick_when_our_line_equals_the_market(self):
        self.assertIsNone(home._pick("H", "A", 3.0, 3.0))
        self.assertIsNone(home._pick("H", "A", 3.0, None))
        self.assertEqual(home._pick("H", "A", 5.0, 3.0), {"team": "H", "line": -3.0, "gap": 2.0})


class PlayoffRule(Base):
    def test_top_five_by_probability(self):
        o = self.payload()["playoff_odds"]
        self.assertEqual([t["team"] for t in o["top"]], ["T00", "T01", "T02", "T03", "T04"])
        self.assertEqual((o["sims"], o["week"]), (20000, 5))
        self.assertEqual(self.payload()["chain"]["season"]["top"]["team"], "T00")
        self.assertEqual(len(self.payload()["chain"]["season"]["next"]), 3)

    def test_odds_sorting_breaks_ties_by_team_code(self):
        self.con.execute("UPDATE playoff_odds SET p_playoffs=0.99 WHERE team IN ('T09','T05')")
        self.con.commit()
        top = [t["team"] for t in self.payload()["playoff_odds"]["top"]]
        self.assertEqual(top[:2], ["T05", "T09"])


class PlayoffAbsent(Base):
    with_odds = False

    def test_no_complete_run_is_null_not_zero(self):
        out = self.payload()
        self.assertIsNone(out["playoff_odds"])
        self.assertIsNone(out["chain"]["season"])
        self.assertIn("playoff_odds", out["absent"])


if __name__ == "__main__":
    unittest.main()
