"""Tests for the published NBA Stats release ingest and settlement path."""
import copy
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ingest_nba_sportsdataverse as ingest
import nba_sportsdataverse as sdv
from settlement import stored_summary
from settlement.settle_game import settle_game
from settlement.nba_settle import settle_from_sportsdataverse


def _box(person_id, name, team, side, stats, comment=""):
    first, family = name.split(" ", 1)
    row = {
        "person_id": person_id,
        "first_name": first,
        "family_name": family,
        "team_tricode": team,
        "side": side,
        "game_id": "0022500001",
        "season": 2026,
        "season_type_id": "2",
        "comment": comment,
        "minutes": "" if comment else "32:15",
    }
    row.update({
        "points": stats.get("PTS"),
        "rebounds_total": stats.get("REB"),
        "assists": stats.get("AST"),
        "steals": stats.get("STL"),
        "blocks": stats.get("BLK"),
        "turnovers": stats.get("TO"),
        "three_pointers_made": stats.get("3PM"),
        "field_goals_made": stats.get("FGM"),
        "field_goals_attempted": stats.get("FGA"),
        "free_throws_made": stats.get("FTM"),
        "free_throws_attempted": stats.get("FTA"),
    })
    return row


def _line(pts=22):
    return {
        "PTS": pts, "REB": 6, "AST": 5, "STL": 2, "BLK": 1,
        "TO": 3, "3PM": 4, "FGM": 8, "FGA": 16, "FTM": 6, "FTA": 7,
    }


def _release():
    boxes = [
        _box(100, "Known Player", "BOS", "home", _line()),
        _box(200, "New Player", "NYK", "away", _line(18)),
        _box(300, "Bench Player", "BOS", "home", {}, "DNP - Coach's Decision"),
    ]
    schedules = [{
        "game_id": "0022500001",
        "season": 2026,
        "game_date": "2025-10-21",
        "home_team_abbreviation": "BOS",
        "away_team_abbreviation": "NYK",
        "home_pts": 110,
        "away_pts": 105,
    }]
    return {
        "start_year": 2025,
        "source_season": 2026,
        "boxes": boxes,
        "schedules": schedules,
        "release_hash": "release-hash",
        "boxscore_bytes": 100,
        "schedule_bytes": 100,
    }


class SportsDataverseIngestTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="nba-sdv-", suffix=".db", delete=False)
        handle.close()
        self.path = handle.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY,name TEXT NOT NULL,team TEXT,league TEXT NOT NULL,
                                 espn_id TEXT,nba_id TEXT,active INTEGER DEFAULT 1,
                                 UNIQUE(espn_id,league));
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY,source TEXT NOT NULL,league TEXT NOT NULL,
                source_player_key TEXT NOT NULL,player_id INTEGER NOT NULL,first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,UNIQUE(source,league,source_player_key));
            CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY,player_id INTEGER,league TEXT NOT NULL,
                season INTEGER NOT NULL,game_no TEXT,game_id TEXT,game_date TEXT,team TEXT,opponent TEXT,
                home_away TEXT,stats TEXT NOT NULL,source TEXT,source_player_key TEXT,game_type TEXT);
            CREATE TABLE prop_games(id INTEGER PRIMARY KEY,league TEXT NOT NULL,date TEXT NOT NULL,
                home TEXT,away TEXT,espn_event_id TEXT,final_home INTEGER,final_away INTEGER);
        """)
        con.executemany("INSERT INTO players(id,name,team,league,espn_id) VALUES(?,?,?,?,?)", [
            (10, "Known Player", "BOS", "nba", "101"),
            (20, "New Player", "NY", "nba", "202"),
            (30, "Bench Player", "BOS", "nba", "303"),
        ])
        con.executemany(
            "INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
            "VALUES('nba.com','nba',?,?,?,?)",
            [("100", 10, "2025-10-01", "2025-10-01"),
             ("300", 30, "2025-10-01", "2025-10-01")],
        )
        line1, line2 = _line(), _line(18)
        con.executemany(
            """INSERT INTO player_game_logs(player_id,league,season,game_no,game_id,game_date,
                     team,opponent,home_away,stats,source,source_player_key,game_type)
                 VALUES(?,'nba',2026,'2025-10-21','401809243','2025-10-21',?,?,?,?,'espn',?,'REG')""",
            [(10, "BOS", "NY", "home", json.dumps(line1), "101"),
             (20, "NY", "BOS", "away", json.dumps(line2), "202")],
        )
        con.execute(
            "INSERT INTO prop_games(id,league,date,home,away,espn_event_id) VALUES(1,'nba',?,?,?,?)",
            ("2025-10-21", "BOS", "NY", "401809243"),
        )
        con.commit()
        con.close()

    def test_market_lines_and_explicit_dnp_are_normalized_without_guessing(self):
        played, status, comment = ingest._normalize_line(_box(100, "Known Player", "BOS", "home", _line()))
        self.assertEqual(status, "played")
        self.assertIsNone(comment)
        self.assertEqual((played["PTS"], played["FGM"], played["FTM"], played["PRA"]),
                         (22, 8, 6, 33))
        self.assertEqual(played["MIN"], 32.25)

        dnp, status, comment = ingest._normalize_line(
            _box(300, "Bench Player", "BOS", "home", {}, "DNP - Coach's Decision")
        )
        self.assertEqual(status, "dnp")
        self.assertIn("Coach's Decision", comment)
        self.assertEqual((dnp["PTS"], dnp["FGM"], dnp["FTM"], dnp["MIN"]), (0, 0, 0, 0))

        missing = _box(400, "Unknown Player", "BOS", "home", _line())
        missing["minutes"] = ""
        self.assertEqual(ingest._normalize_line(missing)[1], "unknown")

    def test_release_crosswalk_is_strict_and_apply_is_idempotent(self):
        release = ingest.validate_release(_release())
        self.assertEqual(release["boxscore_games"], 1)
        self.assertEqual(release["dnp_rows"], 1)
        self.assertEqual(release["market_missing"], {})

        with mock.patch.object(ingest, "fetch_release", side_effect=lambda _year: copy.deepcopy(_release())):
            result = ingest.ingest(self.path, season_start_years=[2025])
            self.assertEqual(result["mapped_games"], 1)
            self.assertEqual(result["mapped_players"], 3)
            self.assertEqual(result["inferred_player_ids"], 1)
            self.assertEqual(result["unresolved_player_ids"], 0)

            second = ingest.ingest(self.path, season_start_years=[2025])
            self.assertEqual(second["written_player_rows"], 3)

        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        logs = con.execute(
            "SELECT player_id,source_player_key,game_id,appearance_status,stats,dnp_comment "
            "FROM player_game_logs_sportsdataverse ORDER BY source_player_key"
        ).fetchall()
        self.assertEqual(len(logs), 3)
        self.assertEqual([row["player_id"] for row in logs], [10, 20, 30])
        self.assertEqual(logs[2]["appearance_status"], "dnp")
        self.assertEqual(logs[2]["game_id"], "401809243")
        self.assertEqual(json.loads(logs[2]["stats"])["FTM"], 0)
        self.assertIn("Coach's Decision", logs[2]["dnp_comment"])
        self.assertEqual(con.execute(
            "SELECT player_id FROM player_source_ids WHERE source='nba.com' AND source_player_key='200'"
        ).fetchone()[0], 20)
        self.assertEqual(tuple(con.execute(
            "SELECT final_home,final_away FROM prop_games WHERE id=1"
        ).fetchone()), (110, 105))
        con.close()

    def test_dry_run_keeps_the_database_read_only(self):
        with mock.patch.object(ingest, "fetch_release", side_effect=lambda _year: copy.deepcopy(_release())):
            result = ingest.ingest(self.path, dry_run=True, season_start_years=[2025])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["inferred_player_ids"], 1)
        con = sqlite3.connect(self.path)
        self.assertIsNone(con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_game_logs_sportsdataverse'"
        ).fetchone())
        con.close()

    def test_espn_event_rosters_resolve_dnp_ids_and_create_inactive_missing_identity(self):
        release = _release()
        release["boxes"].extend([
            _box(400, "ESPN Veteran", "BOS", "home", {}, "DNP - Coach's Decision"),
            _box(500, "ESPN Newcomer", "NYK", "away", {}, "DNP - Coach's Decision"),
        ])
        con = sqlite3.connect(self.path)
        con.execute(
            "INSERT INTO players(id,name,team,league,espn_id,nba_id,active) "
            "VALUES(40,'ESPN Veteran','BOS','nba','404',NULL,0)"
        )
        con.commit()
        con.close()
        summary = {
            "header": {
                "id": "401809243",
                "competitions": [{
                    "id": "401809243",
                    "competitors": [
                        {"team": {"abbreviation": "BOS"}},
                        {"team": {"abbreviation": "NY"}},
                    ],
                }],
            },
            "boxscore": {"players": [
                {"team": {"abbreviation": "BOS"}, "statistics": [{"athletes": [
                    {"athlete": {"id": "404", "displayName": "ESPN Veteran"}},
                ]}]},
                {"team": {"abbreviation": "NY"}, "statistics": [{"athletes": [
                    {"athlete": {"id": "505", "displayName": "ESPN Newcomer"}},
                ]}]},
            ]},
        }

        with mock.patch.object(ingest, "fetch_release", return_value=copy.deepcopy(release)), \
             mock.patch.object(ingest, "fetch_espn_event_summary", return_value=summary):
            result = ingest.ingest(self.path, season_start_years=[2025])

        self.assertEqual(result["espn_resolved_player_ids"], 2)
        self.assertEqual(result["unresolved_player_ids"], 0)
        self.assertEqual(result["new_espn_player_identities"], [{
            "espn_id": "505",
            "name": "ESPN Newcomer",
            "player_id_created_in_apply": True,
        }])

        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        logs = {
            row["source_player_key"]: row["player_id"]
            for row in con.execute(
                "SELECT source_player_key,player_id FROM player_game_logs_sportsdataverse"
            )
        }
        veteran_id = logs["400"]
        newcomer_id = logs["500"]
        self.assertEqual(veteran_id, 40)
        newcomer = con.execute(
            "SELECT name,team,league,espn_id,active FROM players WHERE id=?", (newcomer_id,)
        ).fetchone()
        self.assertEqual(tuple(newcomer), ("ESPN Newcomer", None, "nba", "505", 0))
        self.assertEqual(con.execute(
            "SELECT player_id FROM player_source_ids WHERE source='nba.com' AND source_player_key='500'"
        ).fetchone()[0], newcomer_id)
        self.assertEqual(con.execute(
            "SELECT player_id FROM player_source_ids WHERE source='espn' AND source_player_key='505'"
        ).fetchone()[0], newcomer_id)
        self.assertEqual(con.execute(
            "SELECT player_id FROM player_source_ids WHERE source='espn' AND source_player_key='404'"
        ).fetchone()[0], veteran_id)
        con.close()


class SportsDataverseSettlementTests(unittest.TestCase):
    def test_settle_game_uses_published_stats_and_final_score_without_espn_summary(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY,name TEXT,team TEXT,league TEXT,espn_id TEXT);
            CREATE TABLE prop_games(id INTEGER PRIMARY KEY,league TEXT,home TEXT,away TEXT,date TEXT,
                espn_event_id TEXT,final_home INTEGER,final_away INTEGER,start_time TEXT);
            CREATE TABLE props(id INTEGER PRIMARY KEY,game_id INTEGER,player_id INTEGER,market TEXT,
                line REAL,side TEXT);
            CREATE TABLE prop_results(prop_id INTEGER PRIMARY KEY,actual_value REAL,hit INTEGER,settled_at TEXT);
        """)
        sdv.ensure_schema(con)
        con.execute("INSERT INTO players VALUES(10,'Known Player','BOS','nba','101')")
        con.execute(
            "INSERT INTO prop_games VALUES(1,'nba','BOS','NY','2025-10-21','event-1',NULL,NULL,NULL)"
        )
        con.execute("INSERT INTO props VALUES(1,1,10,'field_goals_made',7.5,'over')")
        con.execute(
            "INSERT INTO nba_sportsdataverse_releases VALUES(2025,2026,'hash',1,1,1,0,'now','now')"
        )
        con.execute(
            """INSERT INTO nba_sportsdataverse_games
                 (source_game_id,season,source_season,espn_event_id,game_date,home,away,
                  home_score,away_score,game_type,release_hash,ingested_at)
               VALUES('0022500001',2025,2026,'event-1','2025-10-21','BOS','NY',110,105,'REG','hash','now')"""
        )
        con.execute(
            """INSERT INTO player_game_logs_sportsdataverse
                 (player_id,league,season,game_no,game_id,source_game_id,game_date,team,
                  opponent,home_away,stats,source,source_player_key,appearance_status,
                  dnp_comment,release_hash,ingested_at,game_type)
               VALUES(10,'nba',2025,'0022500001','event-1','0022500001','2025-10-21',
                      'BOS','NY','home','{\"FGM\":8}','sportsdataverse_nba_stats','100',
                      'played',NULL,'hash','now','REG')"""
        )

        with mock.patch.object(stored_summary, "boxscore", side_effect=AssertionError("ESPN summary called")):
            result = settle_game(con, 1)

        self.assertEqual(result["settled"], 1)
        self.assertEqual(tuple(con.execute(
            "SELECT actual_value,hit FROM prop_results WHERE prop_id=1"
        ).fetchone()), (8, 1))
        self.assertEqual(tuple(con.execute(
            "SELECT final_home,final_away FROM prop_games WHERE id=1"
        ).fetchone()), (110, 105))
        con.close()

    def test_all_ten_markets_settle_and_dnp_or_missing_rows_do_not_become_zero(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        sdv.ensure_schema(con)
        con.execute("""CREATE TABLE props(id INTEGER PRIMARY KEY,game_id INTEGER,player_id INTEGER,
                      market TEXT,line REAL,side TEXT)""")
        con.execute("CREATE TABLE prop_results(prop_id INTEGER PRIMARY KEY,actual_value REAL,hit INTEGER,settled_at TEXT)")
        con.execute(
            "INSERT INTO nba_sportsdataverse_releases VALUES(2025,2026,'hash',3,1,1,0,'now','now')"
        )
        con.execute(
            """INSERT INTO nba_sportsdataverse_games
                 (source_game_id,season,source_season,espn_event_id,game_date,home,away,
                  home_score,away_score,game_type,release_hash,ingested_at)
               VALUES('0022500001',2025,2026,'event-1','2025-10-21','BOS','NY',110,105,'REG','hash','now')"""
        )
        stats = {"PTS": 22, "REB": 6, "AST": 5, "STL": 2, "BLK": 1,
                 "TO": 3, "3PM": 4, "FGM": 8, "FGA": 16, "FTM": 6, "FTA": 7,
                 "PRA": 33, "MIN": 32.25}
        dnp_stats = {key: 0 for key in ("PTS", "REB", "AST", "STL", "BLK", "TO", "3PM", "FGM", "FGA", "FTM", "FTA", "PRA", "MIN")}
        rows = [
            (10, "0022500001", "played", json.dumps(stats), None),
            (30, "0022500001", "dnp", json.dumps(dnp_stats), "DNP - Coach's Decision"),
        ]
        for player_id, source_game_id, status, payload, comment in rows:
            con.execute(
                """INSERT INTO player_game_logs_sportsdataverse
                     (player_id,league,season,game_no,game_id,source_game_id,game_date,team,
                      opponent,home_away,stats,source,source_player_key,appearance_status,
                      dnp_comment,release_hash,ingested_at,game_type)
                   VALUES(?,'nba',2025,?,'event-1',?,'2025-10-21','BOS','NY','home',?,
                          'sportsdataverse_nba_stats',?,?,?,'hash','now','REG')""",
                (player_id, source_game_id, source_game_id, payload,
                 str(player_id + 90), status, comment),
            )
        markets = ["points", "rebounds", "assists", "steals", "blocks", "turnovers",
                   "threes", "pra", "field_goals_made", "free_throws_made"]
        for index, market in enumerate(markets, 1):
            con.execute("INSERT INTO props VALUES(?,1,10,?,0.5,'over')", (index, market))
        con.execute("INSERT INTO props VALUES(11,1,30,'points',1.5,'under')")
        con.execute("INSERT INTO props VALUES(12,1,99,'points',1.5,'under')")
        props = con.execute("SELECT * FROM props ORDER BY id").fetchall()
        result = settle_from_sportsdataverse(con, 1, "event-1", props)
        self.assertEqual((result["settled"], result["void"], result["pending"]), (10, 1, 1))
        actuals = con.execute(
            "SELECT actual_value,hit FROM prop_results WHERE prop_id BETWEEN 1 AND 10 ORDER BY prop_id"
        ).fetchall()
        self.assertEqual([row["actual_value"] for row in actuals], [22, 6, 5, 2, 1, 3, 4, 33, 8, 6])
        self.assertEqual(tuple(con.execute(
            "SELECT actual_value,hit FROM prop_results WHERE prop_id=11"
        ).fetchone()), (None, None))
        self.assertIsNone(con.execute("SELECT 1 FROM prop_results WHERE prop_id=12").fetchone())
        con.close()

    def test_unpublished_game_falls_back_to_existing_settlement_path(self):
        con = sqlite3.connect(":memory:")
        sdv.ensure_schema(con)
        self.assertIsNone(settle_from_sportsdataverse(con, 1, "unknown-event", []))
        con.close()


if __name__ == "__main__":
    unittest.main()
