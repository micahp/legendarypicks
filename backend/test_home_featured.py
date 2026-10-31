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
import nba_sportsdataverse  # noqa: E402
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
    nba_sportsdataverse.ensure_schema(con)
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


def offer(con, pid, line, n_sources, captured=RECENT, market="receiving_yards", league="nfl",
          side="over", prefix="s", start="2026-10-18T17:00:00Z"):
    gid = con.execute("INSERT INTO prop_games(league,date,home,away,start_time) VALUES (?,?,?,?,?)",
                      (league, "2026-10-18", "T01", "T00", start)).lastrowid
    for k in range(n_sources):
        con.execute("INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) "
                    "VALUES (?,?,?,?,?,?,?)", (gid, pid, market, line, side, "%s%d" % (prefix, k), captured))


class PropRule(Base):
    def test_highest_consensus_line_wins(self):
        player(self.con, 1, "Low", 25)
        player(self.con, 2, "High", 25)
        player(self.con, 3, "Mid", 25)
        offer(self.con, 1, 60.5, 9)
        offer(self.con, 2, 93.5, 11)
        offer(self.con, 3, 75.5, 12)
        self.con.commit()
        p = self.payload()["prop"]
        self.assertEqual((p["player_id"], p["line"], p["sources"]), (2, 93.5, 11))

    def test_a_finished_game_is_excluded_even_with_more_sources(self):
        player(self.con, 1, "Played", 25)
        player(self.con, 2, "Upcoming", 25)
        player(self.con, 3, "NoStart", 25)
        offer(self.con, 1, 120.5, 14, start="2026-10-13T00:15:00Z")    # kicked off before NOW
        offer(self.con, 3, 130.5, 14, start=None)
        offer(self.con, 2, 60.5, 8)
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 2)

    def test_start_time_formats_compare_as_instants(self):
        player(self.con, 1, "Just started", 25)
        player(self.con, 2, "Just ahead", 25)
        offer(self.con, 1, 120.5, 10, start="2026-10-13T11:59:00+00:00")
        offer(self.con, 2, 60.5, 8, start="2026-10-13T12:00:30+00:00")
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 2)

    def test_null_when_only_finished_games_have_lines(self):
        player(self.con, 1, "Played", 25)
        offer(self.con, 1, 120.5, 14, start="2026-10-13T00:15:00Z")
        self.con.commit()
        out = self.payload()
        self.assertIsNone(out["prop"])
        self.assertEqual(out["absent"]["prop"], "no upcoming game has a widely offered receiving yards line")

    def test_consensus_line_beats_a_thin_outlier_line(self):
        player(self.con, 1, "Outlier", 25)
        offer(self.con, 1, 29.5, 2, captured="2026-10-13T06:00:00+00:00")    # newer, 2 sources
        offer(self.con, 1, 31.5, 9, captured="2026-10-13T04:00:00+00:00")    # consensus
        self.con.commit()
        p = self.payload()["prop"]
        self.assertEqual((p["line"], p["sources"]), (31.5, 9))

    def test_a_player_line_tie_goes_to_latest_capture_then_higher_line(self):
        player(self.con, 1, "Tie", 25)
        offer(self.con, 1, 70.5, 9, captured="2026-10-13T04:00:00+00:00")
        offer(self.con, 1, 72.5, 9, captured="2026-10-13T05:00:00+00:00")
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["line"], 72.5)
        offer(self.con, 1, 74.5, 9, captured="2026-10-13T05:00:00+00:00")   # same capture: higher line
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["line"], 74.5)

    def test_same_line_ties_go_to_more_sources_then_lowest_player_id(self):
        for pid in (5, 6, 7):
            player(self.con, pid, "P%d" % pid, 25)
        offer(self.con, 7, 80.5, 10)
        offer(self.con, 6, 80.5, 9)
        offer(self.con, 5, 80.5, 9)
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 7)
        self.con.execute("DELETE FROM props WHERE player_id=7")
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 5)

    def test_threshold_history_and_filters(self):
        player(self.con, 1, "SevenSources", 25)
        player(self.con, 2, "ShortHistory", 19)
        player(self.con, 3, "Stale", 25)
        player(self.con, 4, "Rushing", 25)
        player(self.con, 5, "Under", 25)
        player(self.con, 6, "Wrong league", 25)
        player(self.con, 7, "Eligible", 25)
        offer(self.con, 1, 120.5, 7)
        offer(self.con, 2, 120.5, 12)
        offer(self.con, 3, 120.5, 12, captured=STALE)
        offer(self.con, 4, 120.5, 12, market="rushing_yards")
        offer(self.con, 5, 120.5, 12, side="under")
        offer(self.con, 6, 120.5, 12, league="nba")
        offer(self.con, 7, 50.5, 8)
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 7)

    def test_relaxes_once_to_five_sources(self):
        player(self.con, 1, "Five", 25)
        player(self.con, 2, "Six", 25)
        offer(self.con, 1, 100.5, 5)
        offer(self.con, 2, 60.5, 6)
        self.con.commit()
        p = self.payload()["prop"]
        self.assertEqual((p["player_id"], p["sources"]), (1, 5))      # highest line among >= 5
        self.con.execute("DELETE FROM props WHERE player_id=1")
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 2)

    def test_the_strict_rule_is_tried_before_the_relaxed_one(self):
        player(self.con, 1, "Five", 25)
        player(self.con, 2, "Eight", 25)
        offer(self.con, 1, 100.5, 5)
        offer(self.con, 2, 60.5, 8)
        self.con.commit()
        self.assertEqual(self.payload()["prop"]["player_id"], 2)

    def test_numbers_equal_prop_history(self):
        player(self.con, 1, "Same", 25)
        offer(self.con, 1, 110.5, 9)
        self.con.commit()
        out = self.payload()["prop"]
        h = props.prop_history(player_id=1, market="receiving_yards", line=110.5, side="over",
                               league="nfl")
        self.assertEqual(out["hit_rate"], h["hit_rate"])
        self.assertEqual(out["hit_rate_n"], h["hit_rate_n"])
        self.assertEqual(len(out["games"]), 20)
        self.assertEqual(out["games"][-1]["value"], h["games"][0]["value"])   # oldest first
        self.assertEqual(out["source"]["as_of"], RECENT)

    def test_home_chart_uses_the_latest_twenty_individual_games(self):
        self.con.execute("INSERT INTO players VALUES (1,'Jaxon Smith-Njigba','SEA','nfl','WR')")
        seasons = {
            2025: [
                (1, "2025-09-07", "REG"), (2, "2025-09-14", "REG"),
                (3, "2025-09-21", "REG"), (4, "2025-09-28", "REG"),
                (5, "2025-10-05", "REG"), (6, "2025-10-12", "REG"),
                (7, "2025-10-20", "REG"), (9, "2025-11-02", "REG"),
                (10, "2025-11-09", "REG"), (11, "2025-11-16", "REG"),
                (12, "2025-11-23", "REG"), (13, "2025-11-30", "REG"),
                (14, "2025-12-07", "REG"), (15, "2025-12-14", "REG"),
                (16, "2025-12-18", "REG"), (17, "2025-12-28", "REG"),
                (18, "2026-01-04", "REG"), (20, "2026-01-17", "DIV"),
                (21, "2026-01-25", "CON"), (22, "2026-02-08", "SB"),
            ],
            2026: [
                (1, "2026-09-09", "REG"), (2, "2026-09-20", "REG"),
                (3, "2026-09-27", "REG"), (4, "2026-10-04", "REG"),
                (5, "2026-10-11", "REG"),
            ],
        }
        for season, games in seasons.items():
            for week, gameday, game_type in games:
                game_id = f"{season}_{week:02d}_SEA_OPP"
                self.con.execute(
                    "INSERT INTO player_game_logs(player_id,league,season,game_no,game_id,"
                    "game_date,team,opponent,home_away,stats,source,game_type) "
                    "VALUES(1,'nfl',?,?,?,NULL,'SEA','OPP','home',?,'espn',?)",
                    (season, str(week), game_id, json.dumps({"rec_yds": 50 + week}), game_type),
                )
                self.con.execute(
                    "INSERT INTO nfl_schedule(game_id,season,game_type,week,home_team,away_team,gameday) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (game_id, season, game_type, week, "SEA", "OPP", gameday),
                )
        # This dated 2023 row previously sorted ahead of newer NFL rows that had
        # a null game_date, making the homepage chart look three seasons old.
        self.con.execute(
            "INSERT INTO player_game_logs(player_id,league,season,game_no,game_id,game_date,"
            "team,opponent,home_away,stats,source,game_type) "
            "VALUES(1,'nfl',2023,'6','2023_06_SEA_OPP','2023-10-15','SEA','OPP','home',?,'espn','REG')",
            (json.dumps({"rec_yds": 56}),),
        )
        offer(self.con, 1, 110.5, 9)
        self.con.commit()

        prop = self.payload()["prop"]
        expected = [(2025, week, day) for week, day, _ in seasons[2025] if week >= 6]
        expected += [(2026, week, day) for week, day, _ in seasons[2026]]
        self.assertEqual(len(prop["games"]), 20)
        self.assertEqual([game["date"] for game in prop["games"]],
                         [day for _, _, day in expected])
        self.assertEqual([game["value"] for game in prop["games"]],
                         [50 + week for _, week, _ in expected])

    def test_null_when_nobody_qualifies_and_chain_player_follows(self):
        player(self.con, 1, "FewSources", 25)
        player(self.con, 2, "ShortHistory", 5)
        offer(self.con, 1, 90.5, 4)
        offer(self.con, 2, 90.5, 12)
        self.con.commit()
        out = self.payload()
        self.assertIsNone(out["prop"])
        self.assertIn("prop", out["absent"])
        self.assertIn("widely offered", out["absent"]["prop"])
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
    nl.finish_run(con, rid, "ok")
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
        # Spread 3 (T01 home favoured by 3), model margin -0.5: V - M = 3.5 >= 3, so rule 3,
        # the underdog T00 +3. Final 23-30 (away by 7): T00 covers.
        self.assertEqual((g["pick"]["market"], g["pick"]["side"], g["pick"]["line"], g["pick"]["rule"]),
                         ("spread", "away", 3.0, 3))
        self.assertEqual(g["pick"]["label"], "T00 +3")
        self.assertEqual(g["home_name"], "Team 01")

    def test_record_counts_the_adopted_model_pick(self):
        # Every game has the Model Pick away +3 (see the game test). r1: 20-17, margin 3 = the
        # line, a push. r2: 23-30, margin -7, a win. The stored ats_result column is not read:
        # it says 'loss' for r1 here, and the record ignores it.
        lock_game(self.con, "r1", "2026-10-04", 20, 17)
        lock_game(self.con, "r2", "2026-10-11", 23, 30)
        lock_game(self.con, "r3", "2026-10-12", 10, 3, version="nfl-v1 cap=21.0 sigma=13.4")
        self.con.execute("UPDATE projection_grades SET ats_result='loss' WHERE game_id='r1'")
        self.con.commit()
        rec = self.payload()["record"]
        self.assertEqual((rec["win"], rec["loss"], rec["push"], rec["games"]), (1, 0, 1, 2))

    def test_record_is_null_with_no_grades(self):
        lock_game(self.con, "r1", "2026-10-25", None, None)
        out = self.payload()
        self.assertIsNone(out["record"])
        self.assertIn("record", out["absent"])

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

    def test_featured_pick_is_the_model_page_pick(self):
        # The homepage and the Model page cannot disagree: same function, same frozen inputs.
        lock_game(self.con, "p1", "2026-10-11", 23, 30)
        game = self.payload()["game"]
        page = nfl_model.locks_payload(self.con, 2026, 5)
        lock = next(x for x in page["games"] if x["game_id"] == "p1")["locks"][nfl_model.ADOPTED]
        self.assertEqual(game["pick"], lock["pick"])
        self.assertEqual(game["pick_result"], lock["grade"]["pick"])
        self.assertEqual(game["pick_result"], "win")


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
