import json
import os
import sqlite3
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_wc_prop_history_ingest as runner


def _create_db(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA journal_mode=delete;
        CREATE TABLE players(
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          team TEXT,
          league TEXT NOT NULL,
          espn_id TEXT,
          UNIQUE(espn_id,league)
        );
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY,
          league TEXT NOT NULL,
          date TEXT NOT NULL,
          espn_event_id TEXT
        );
        CREATE TABLE props(
          id INTEGER PRIMARY KEY,
          game_id INTEGER NOT NULL,
          player_id INTEGER NOT NULL
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
        """
    )
    connection.commit()
    connection.close()


def _source(
    athlete_id="100",
    name="Alex Example",
    game_id="760517",
    game_date="2026-07-19",
    stats=None,
):
    return runner.SourceRow(
        athlete_id=athlete_id,
        name=name,
        season=2026,
        game_id=game_id,
        game_date=game_date,
        team="ARG",
        opponent="ESP",
        home_away="away",
        stats=stats
        or {"goals": 1, "assists": 0, "shots": 2, "sot": 1},
    )


class WcPropHistoryTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="wc-prop-history-", suffix=".db", delete=False
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

    def test_target_window_uses_latest_prop_date_and_saved_cursor(self):
        connection = self._connection()
        connection.executemany(
            "INSERT INTO prop_games VALUES(?,?,?,?)",
            [
                (3, "wc", "2022-12-18", "old-final"),
                (1, "wc", "2026-07-18", "760516"),
                (2, "wc", "2026-07-19", "760517"),
            ],
        )
        connection.executescript(
            """
            CREATE TABLE history_refresh_state(
              league TEXT PRIMARY KEY,
              source_cursor TEXT,
              refreshed_at TEXT NOT NULL,
              status TEXT NOT NULL,
              details TEXT
            );
            INSERT INTO history_refresh_state
            VALUES('wc','2026-07-18',datetime('now'),'ok','{}');
            """
        )
        connection.commit()

        start, end, expected, cursor = runner.target_window(
            connection, lookback_days=45
        )
        connection.close()

        self.assertEqual("2026-06-04", start.isoformat())
        self.assertEqual("2026-07-19", end.isoformat())
        self.assertEqual({"760516", "760517"}, expected)
        self.assertEqual("2026-07-18", cursor)

    def test_build_plan_links_only_existing_wc_players(self):
        connection = self._connection()
        connection.execute(
            "INSERT INTO players VALUES(1,'Alex Example','ARG','wc',NULL)"
        )
        connection.execute(
            "INSERT INTO prop_games VALUES(1,'wc','2026-07-19','760517')"
        )
        connection.execute("INSERT INTO props VALUES(1,1,1)")
        connection.commit()

        plan = runner.build_plan(
            connection,
            "2026-07-19",
            {"760517"},
            {"760517"},
            [_source(), _source(athlete_id="200", name="Not A Prop Player")],
        )
        connection.close()

        self.assertEqual([], plan.source_errors)
        self.assertEqual([], plan.conflicts)
        self.assertEqual(1, plan.resolved_source_rows)
        self.assertEqual(1, plan.ignored_non_prop_rows)
        self.assertEqual([], plan.uncovered_prop_players)
        self.assertEqual({1: "100"}, plan.identity_updates)
        self.assertEqual(1, len(plan.inserts))
        self.assertEqual(1, plan.inserts[0].player_id)

    def test_build_plan_accepts_unique_formal_first_name_and_clipped_surname(self):
        connection = self._connection()
        connection.execute(
            "INSERT INTO players VALUES(1,'Álex Grimald','ESP','wc',NULL)"
        )
        connection.execute(
            "INSERT INTO prop_games VALUES(1,'wc','2026-07-19','760517')"
        )
        connection.execute("INSERT INTO props VALUES(1,1,1)")
        connection.commit()

        source = runner.SourceRow(
            athlete_id="166396",
            name="Alejandro Grimaldo",
            season=2026,
            game_id="760517",
            game_date="2026-07-19",
            team="ESP",
            opponent="ARG",
            home_away="home",
            stats={"goals": 0, "assists": 0, "shots": 1, "sot": 0},
        )
        plan = runner.build_plan(
            connection,
            "2026-07-19",
            {"760517"},
            {"760517"},
            [source],
        )
        connection.close()

        self.assertEqual([], plan.conflicts)
        self.assertEqual({1: "166396"}, plan.identity_updates)
        self.assertEqual([], plan.uncovered_prop_players)
        self.assertEqual(1, len(plan.inserts))

    def test_build_plan_scopes_duplicate_names_to_active_prop_window(self):
        connection = self._connection()
        connection.executemany(
            "INSERT INTO players VALUES(?,?,?,?,?)",
            [
                (1, "Alex Example", "ARG", "wc", None),
                (2, "Alex Example", "ARG", "wc", None),
            ],
        )
        connection.executemany(
            "INSERT INTO prop_games VALUES(?,?,?,?)",
            [
                (1, "wc", "2022-12-18", "old-final"),
                (2, "wc", "2026-07-19", "760517"),
            ],
        )
        connection.executemany(
            "INSERT INTO props VALUES(?,?,?)",
            [(1, 1, 1), (2, 2, 2)],
        )
        connection.commit()

        plan = runner.build_plan(
            connection,
            "2026-07-19",
            {"760517"},
            {"760517"},
            [_source()],
            target_start="2026-06-04",
            target_end="2026-07-19",
        )
        connection.close()

        self.assertEqual([], plan.conflicts)
        self.assertEqual({2: "100"}, plan.identity_updates)
        self.assertEqual(2, plan.inserts[0].player_id)

    def test_build_plan_rejects_missing_linked_final(self):
        connection = self._connection()
        plan = runner.build_plan(
            connection,
            "2026-07-19",
            {"760516", "760517"},
            {"760516"},
            [],
        )
        connection.close()

        self.assertEqual(
            ["source did not return linked final games 760517"],
            plan.source_errors,
        )

    def test_existing_json_keys_win_and_only_missing_keys_are_added(self):
        connection = self._connection()
        connection.execute(
            "INSERT INTO players VALUES(1,'Alex Example','ARG','wc','100')"
        )
        connection.execute(
            "INSERT INTO prop_games VALUES(1,'wc','2026-07-19','760517')"
        )
        connection.execute("INSERT INTO props VALUES(1,1,1)")
        connection.execute(
            """INSERT INTO player_game_logs
               (id,player_id,league,season,game_no,game_id,game_date,team,
                opponent,home_away,stats,source,source_player_key)
               VALUES(1,1,'wc',2026,'760517','760517','2026-07-19',
                      'ARG','ESP','away','{"goals":9,"manual":1}',
                      'espn','100')"""
        )
        connection.commit()

        plan = runner.build_plan(
            connection,
            "2026-07-19",
            {"760517"},
            {"760517"},
            [_source()],
        )
        connection.close()

        self.assertEqual(1, plan.existing_rows)
        self.assertEqual(1, len(plan.updates))
        self.assertEqual(
            {
                "assists": 0,
                "goals": 9,
                "manual": 1,
                "shots": 2,
                "sot": 1,
            },
            json.loads(plan.updates[0].new_stats),
        )

    def test_apply_updates_identity_inserts_log_and_advances_cursor(self):
        connection = self._connection()
        connection.execute(
            "INSERT INTO players VALUES(1,'Alex Example','ARG','wc',NULL)"
        )
        connection.execute(
            "INSERT INTO prop_games VALUES(1,'wc','2026-07-19','760517')"
        )
        connection.execute("INSERT INTO props VALUES(1,1,1)")
        connection.commit()
        plan = runner.build_plan(
            connection,
            "2026-07-19",
            {"760517"},
            {"760517"},
            [_source()],
        )
        connection.close()

        result = runner.apply_plan(self.db_path, plan)

        self.assertEqual(
            {"identity_updates": 1, "updated": 0, "inserted": 1},
            result,
        )
        connection = self._connection()
        player = connection.execute(
            "SELECT espn_id FROM players WHERE id=1"
        ).fetchone()
        log = connection.execute(
            """SELECT player_id,game_id,source_player_key,stats
               FROM player_game_logs"""
        ).fetchone()
        state = connection.execute(
            """SELECT source_cursor,status FROM history_refresh_state
               WHERE league='wc'"""
        ).fetchone()
        connection.close()

        self.assertEqual("100", player["espn_id"])
        self.assertEqual((1, "760517", "100"), tuple(log)[:3])
        self.assertEqual(1, json.loads(log["stats"])["goals"])
        self.assertEqual(("2026-07-19", "ok"), tuple(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
