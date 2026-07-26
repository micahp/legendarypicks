import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest

import pandas as pd


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_mlb_daily_history_ingest as runner


def _create_db(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA journal_mode=delete;
        CREATE TABLE players(
          id INTEGER PRIMARY KEY,
          name TEXT,
          league TEXT,
          mlbam_id INTEGER
        );
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY,
          league TEXT,
          date TEXT
        );
        CREATE TABLE props(
          id INTEGER PRIMARY KEY,
          game_id INTEGER,
          player_id INTEGER,
          market TEXT,
          captured_at TEXT
        );
        CREATE TABLE player_game_logs(
          id INTEGER PRIMARY KEY,
          player_id INTEGER,
          league TEXT NOT NULL,
          season INTEGER NOT NULL,
          game_no TEXT,
          game_id TEXT,
          game_date TEXT,
          team TEXT,
          opponent TEXT,
          home_away TEXT,
          stats TEXT NOT NULL,
          source TEXT,
          source_player_key TEXT,
          ingested_at TEXT DEFAULT (datetime('now')),
          UNIQUE(league,source_player_key,season,game_no)
        );
        CREATE TABLE unresolved_players(
          id INTEGER PRIMARY KEY,
          source TEXT NOT NULL,
          raw_name TEXT NOT NULL,
          league TEXT NOT NULL,
          team TEXT,
          first_seen TEXT NOT NULL,
          count INTEGER DEFAULT 1,
          source_player_key TEXT,
          reason TEXT
        );
        """
    )
    connection.commit()
    connection.close()


def _frame():
    return pd.DataFrame(
        [
            {
                "events": "single",
                "batter": 111,
                "game_pk": 900,
                "game_date": "2026-07-25",
                "inning_topbot": "Top",
                "home_team": "HOM",
                "away_team": "AWY",
            },
            {
                "events": "strikeout",
                "batter": 111,
                "game_pk": 900,
                "game_date": "2026-07-25",
                "inning_topbot": "Top",
                "home_team": "HOM",
                "away_team": "AWY",
            },
        ]
    )


class MlbDailyHistoryTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="mlb-daily-history-", suffix=".db", delete=False
        )
        handle.close()
        self.db_path = handle.name
        _create_db(self.db_path)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def _connection(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def test_source_rows_require_final_games_and_add_boxscore_runs_rbi(self):
        rows, errors, conflicts = runner.source_rows_from_frame(
            _frame(),
            "2026-07-25",
            {"900"},
            {
                ("900", "111"): {
                    "name": "Batter",
                    "team": "AWY",
                    "R": 1,
                    "RBI": 2,
                }
            },
        )

        self.assertEqual([], errors)
        self.assertEqual([], conflicts)
        self.assertEqual(1, len(rows))
        self.assertEqual(
            {
                "H": 1,
                "2B": 0,
                "3B": 0,
                "HR": 0,
                "BB": 0,
                "K": 1,
                "TB": 1,
                "PA": 2,
                "R": 1,
                "RBI": 2,
            },
            rows[0].stats,
        )

    def test_latest_prop_player_wins_duplicate_mlbam_for_new_rows(self):
        connection = self._connection()
        connection.executemany(
            "INSERT INTO players VALUES(?,?, 'mlb',111)",
            [(1, "Old Log"), (2, "Current Prop")],
        )
        connection.execute(
            """INSERT INTO player_game_logs
               (id,player_id,league,season,game_no,game_id,game_date,stats,
                source,source_player_key)
               VALUES(1,1,'mlb',2026,'2026-07-24','899','2026-07-24',
                      '{"H":1}','statcast','111')"""
        )
        connection.execute(
            "INSERT INTO prop_games VALUES(1,'mlb','2026-07-26')"
        )
        connection.execute(
            """INSERT INTO props
               VALUES(1,1,2,'hits','2026-07-26T12:00:00')"""
        )
        connection.commit()
        row = runner.SourceRow(
            source_player_key="111",
            player_name="Current Prop",
            season=2026,
            game_no="900",
            game_id="900",
            game_date="2026-07-25",
            team="AWY",
            opponent="HOM",
            home_away="away",
            stats={"H": 1, "R": 1, "RBI": 2},
        )

        plan = runner.build_plan(
            connection, "2026-07-25", {"900"}, [row]
        )
        connection.close()

        self.assertEqual([], plan.identity_conflicts)
        self.assertEqual(1, len(plan.inserts))
        self.assertEqual(2, plan.inserts[0].player_id)

    def test_existing_json_keys_win_collisions(self):
        connection = self._connection()
        connection.execute("INSERT INTO players VALUES(1,'Two Way','mlb',111)")
        connection.execute(
            """INSERT INTO player_game_logs
               (id,player_id,league,season,game_no,game_id,game_date,stats,
                source,source_player_key)
               VALUES(1,1,'mlb',2026,'2026-07-25','900','2026-07-25',
                      '{"K":9,"outs":3}','statcast_pitcher','111')"""
        )
        connection.commit()
        row = runner.SourceRow(
            source_player_key="111",
            player_name="Two Way",
            season=2026,
            game_no="900",
            game_id="900",
            game_date="2026-07-25",
            team="AWY",
            opponent="HOM",
            home_away="away",
            stats={"H": 1, "K": 1, "R": 1, "RBI": 2},
        )

        plan = runner.build_plan(
            connection, "2026-07-25", {"900"}, [row]
        )
        connection.close()

        self.assertEqual(1, plan.collision_rows)
        self.assertEqual(1, len(plan.updates))
        self.assertEqual(
            {"H": 1, "K": 9, "R": 1, "RBI": 2, "outs": 3},
            json.loads(plan.updates[0].new_stats),
        )

    def test_doubleheader_rows_use_distinct_game_ids_as_natural_keys(self):
        data = pd.concat(
            [_frame(), _frame().assign(game_pk=901)],
            ignore_index=True,
        )
        rows, errors, conflicts = runner.source_rows_from_frame(
            data,
            "2026-07-25",
            {"900", "901"},
            {
                ("900", "111"): {
                    "name": "Batter",
                    "team": "AWY",
                    "R": 1,
                    "RBI": 2,
                },
                ("901", "111"): {
                    "name": "Batter",
                    "team": "AWY",
                    "R": 0,
                    "RBI": 1,
                },
            },
        )

        self.assertEqual([], errors)
        self.assertEqual([], conflicts)
        self.assertEqual(["900", "901"], sorted(row.game_no for row in rows))

    def test_apply_is_one_guarded_union_and_insert_transaction(self):
        connection = self._connection()
        connection.execute("INSERT INTO players VALUES(1,'Batter','mlb',111)")
        connection.execute(
            """INSERT INTO player_game_logs
               (id,player_id,league,season,game_no,game_id,game_date,stats,
                source,source_player_key)
               VALUES(1,1,'mlb',2026,'2026-07-25','900','2026-07-25',
                      '{"H":1}','statcast','111')"""
        )
        connection.commit()
        source = runner.SourceRow(
            source_player_key="111",
            player_name="Batter",
            season=2026,
            game_no="900",
            game_id="900",
            game_date="2026-07-25",
            team="AWY",
            opponent="HOM",
            home_away="away",
            stats={"H": 1, "R": 1, "RBI": 2},
        )
        plan = runner.build_plan(
            connection, "2026-07-25", {"900"}, [source]
        )
        connection.close()

        result = runner.apply_plan(self.db_path, plan)

        self.assertEqual({"updated": 1, "inserted": 0, "queued": 0}, result)
        connection = self._connection()
        stats = json.loads(
            connection.execute(
                "SELECT stats FROM player_game_logs WHERE id=1"
            ).fetchone()[0]
        )
        state = connection.execute(
            "SELECT source_cursor,status FROM history_refresh_state WHERE league='mlb'"
        ).fetchone()
        connection.close()
        self.assertEqual({"H": 1, "R": 1, "RBI": 2}, stats)
        self.assertEqual(("2026-07-25", "ok"), tuple(state))

    def test_select_target_uses_first_source_day_missing_game_ids(self):
        connection = self._connection()
        connection.execute("INSERT INTO players VALUES(1,'Batter','mlb',111)")
        connection.execute(
            """INSERT INTO player_game_logs
               (id,player_id,league,season,game_no,game_id,game_date,stats,
                source,source_player_key)
               VALUES(1,1,'mlb',2026,'2026-07-24','899','2026-07-24',
                      '{"H":1}','statcast','111')"""
        )
        connection.commit()

        target, game_ids, detail = runner.select_target_date(
            connection,
            dt.date(2026, 7, 26),
            schedule_fetcher=lambda start, end: {
                "2026-07-24": {"899"},
                "2026-07-25": {"900"},
            },
        )
        connection.close()

        self.assertEqual("2026-07-25", target)
        self.assertEqual({"900"}, game_ids)
        self.assertEqual(["900"], detail["missing_game_ids"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
