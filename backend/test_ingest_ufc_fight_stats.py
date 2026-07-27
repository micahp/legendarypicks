#!/usr/bin/env python3

import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ingest_ufc_fight_stats as ingest


def _create_fixture(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE players(
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          team TEXT,
          league TEXT NOT NULL,
          espn_id TEXT,
          UNIQUE(espn_id, league)
        );
        CREATE TABLE prop_games(
          id INTEGER PRIMARY KEY,
          league TEXT NOT NULL,
          date TEXT NOT NULL,
          home TEXT,
          away TEXT,
          espn_event_id TEXT
        );
        CREATE TABLE props(
          id INTEGER PRIMARY KEY,
          game_id INTEGER,
          player_id INTEGER,
          market TEXT,
          line REAL,
          side TEXT,
          captured_at TEXT
        );
        """
    )
    con.execute("BEGIN")
    ingest.ensure_table(con)
    con.commit()
    con.close()


class UfcIngestTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="ufc-ingest-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        _create_fixture(self.path)

    def test_opponent_pair_resolves_small_source_spelling_error(self):
        games = [
            {
                "game_id": "401874315",
                "home": {"id": "4997217", "name": "Steve Erceg"},
                "away": {"id": "4895691", "name": "Ramazan Temirov"},
            }
        ]

        identity = ingest.resolve_from_card(
            "Ramazan Temurov", "Steve Erceg", games
        )

        self.assertIsNotNone(identity)
        self.assertEqual("4895691", identity.athlete_id)
        self.assertEqual("opponent_pair", identity.method)
        self.assertEqual("401874315", identity.fight_id)

    def test_opponent_pair_does_not_guess_when_both_fighters_are_absent(self):
        games = [
            {
                "game_id": "other",
                "home": {"id": "1", "name": "Some Fighter"},
                "away": {"id": "2", "name": "Another Fighter"},
            }
        ]

        identity = ingest.resolve_from_card(
            "Islam Dulatov", "Wellington Turman", games
        )

        self.assertIsNone(identity)

    def test_load_targets_scopes_to_card_window_and_reads_existing_keys(self):
        con = sqlite3.connect(self.path)
        con.executemany(
            "INSERT INTO players(id,name,league,espn_id) VALUES(?,?,'ufc',?)",
            [
                (1, "Current Fighter", None),
                (2, "Old Fighter", "222"),
            ],
        )
        con.executemany(
            """
            INSERT INTO prop_games(id,league,date,home,away,espn_event_id)
            VALUES(?,'ufc',?,?,?,NULL)
            """,
            [
                (10, "2026-07-25", "Current Fighter", "Opponent"),
                (20, "2026-05-01", "Old Fighter", "Old Opponent"),
            ],
        )
        con.executemany(
            """
            INSERT INTO props(id,game_id,player_id,market,line,side,captured_at)
            VALUES(?,?,?,'fight_time',1.5,'over','now')
            """,
            [(100, 10, 1), (200, 20, 2)],
        )
        con.execute(
            """
            INSERT INTO player_game_logs
              (player_id,league,season,game_no,game_id,game_date,stats,
               source,source_player_key)
            VALUES(2,'ufc',2026,'2026-05-01','fight-old','2026-05-01','{}',
                   'espn_mma_stats','222')
            """
        )
        con.commit()
        con.close()

        targets, existing, owners = ingest.load_targets(
            self.path, dt.date(2026, 7, 26)
        )

        self.assertEqual([1], [target.player_id for target in targets])
        self.assertEqual("Opponent", targets[0].opponent)
        self.assertIn(("ufc", "222", 2026, "2026-05-01"), existing)
        self.assertEqual({"222": 2}, owners)

        all_targets, _, _ = ingest.load_targets(
            self.path, dt.date(2026, 7, 26), all_fighters=True
        )
        self.assertEqual([1, 2], [target.player_id for target in all_targets])

    def test_source_outage_is_an_error_not_an_unresolved_name(self):
        target = ingest.FighterTarget(
            player_id=1,
            name="Current Fighter",
            espn_id=None,
            card_date="2026-07-25",
            prop_game_id=10,
            opponent="Opponent",
        )
        with mock.patch.object(
            ingest,
            "_card_for_date",
            return_value=(None, "scoreboard_unavailable:URLError"),
        ), mock.patch.object(
            ingest.espn, "ufc_fight_history"
        ) as history:
            plan = ingest.build_plan(
                [target], set(), {}, limit=5, emit=lambda _: None
            )

        history.assert_not_called()
        self.assertEqual(1, len(plan.source_errors))
        self.assertEqual([], plan.unresolved)
        self.assertEqual([], plan.logs)

    def test_history_retries_one_rate_limit_and_records_no_false_error(self):
        rate_limit = HTTPError(
            "https://example.invalid",
            429,
            "rate limited",
            {"Retry-After": "0.25"},
            None,
        )
        with mock.patch.object(
            ingest.espn,
            "ufc_fight_history",
            side_effect=[rate_limit, [{"fight_id": "ok"}]],
        ) as history, mock.patch.object(ingest.time, "sleep") as sleep:
            result = ingest.fetch_fight_history("123", limit=5)

        self.assertEqual([{"fight_id": "ok"}], result)
        self.assertEqual(2, history.call_count)
        sleep.assert_called_once_with(0.25)

    def test_existing_log_skips_stats_fetch(self):
        target = ingest.FighterTarget(
            player_id=1,
            name="Stored Fighter",
            espn_id="123",
            card_date=None,
            prop_game_id=None,
            opponent=None,
        )
        fight = {
            "event_id": "event",
            "fight_id": "fight",
            "date": "2026-07-25",
            "opponent": "Opponent",
        }
        existing = {("ufc", "123", 2026, "2026-07-25")}
        with mock.patch.object(
            ingest, "fetch_fight_history", return_value=[fight]
        ), mock.patch.object(ingest, "fetch_stats") as stats:
            plan = ingest.build_plan(
                [target], existing, {"123": 1}, limit=5, emit=lambda _: None
            )

        stats.assert_not_called()
        self.assertEqual(1, plan.candidate_count)
        self.assertEqual(1, plan.existing_count)
        self.assertEqual([], plan.logs)

    def test_current_card_mode_uses_shared_status_and_never_calls_history(self):
        game = {
            "game_id": "fight-1",
            "event_id": "event-1",
            "date": "2026-07-25T20:00:00Z",
            "state": "post",
            "home": {
                "id": "111",
                "name": "Winner Fighter",
                "winner": True,
            },
            "away": {
                "id": "222",
                "name": "Loser Fighter",
                "winner": False,
            },
        }
        targets = [
            ingest.FighterTarget(
                1,
                "Winner Fighter",
                None,
                "2026-07-25",
                10,
                "Loser Fighter",
            ),
            ingest.FighterTarget(
                2,
                "Loser Fighter",
                None,
                "2026-07-25",
                10,
                "Winner Fighter",
            ),
        ]
        status = {
            "type": {"state": "post"},
            "result": {"shortDisplayName": "KO/TKO"},
            "period": 2,
            "clock": 30,
            "displayClock": "0:30",
        }
        with mock.patch.object(
            ingest, "_card_for_date", return_value=([game], None)
        ), mock.patch.object(
            ingest, "fetch_fight_status", return_value=status
        ) as status_fetch, mock.patch.object(
            ingest, "fetch_stats", return_value={"sigStrikesLanded": 20}
        ) as stats_fetch, mock.patch.object(
            ingest, "fetch_fight_history"
        ) as history:
            plan = ingest.build_current_card_plan(
                targets, set(), {}, emit=lambda _: None
            )

        history.assert_not_called()
        status_fetch.assert_called_once_with("event-1", "fight-1")
        self.assertEqual(2, stats_fetch.call_count)
        self.assertEqual(2, len(plan.logs))
        self.assertEqual({10: "fight-1"}, plan.game_links)
        self.assertEqual({1: "111", 2: "222"}, plan.identity_updates)
        by_player = {row.player_id: json.loads(row.stats_json) for row in plan.logs}
        self.assertEqual("W", by_player[1]["result"])
        self.assertEqual("L", by_player[2]["result"])
        self.assertEqual(5.5, by_player[1]["fight_time"])

    def test_current_card_mode_skips_durable_fighter_removed_from_card(self):
        target = ingest.FighterTarget(
            1,
            "Canceled Fighter",
            "111",
            "2026-07-25",
            10,
            "Canceled Opponent",
        )
        with mock.patch.object(
            ingest, "_card_for_date", return_value=([], None)
        ), mock.patch.object(ingest, "fetch_fight_status") as status:
            plan = ingest.build_current_card_plan(
                [target], set(), {"111": 1}, emit=lambda _: None
            )

        status.assert_not_called()
        self.assertEqual([], plan.conflicts)
        self.assertEqual([], plan.logs)

    def test_apply_is_additive_and_preserves_existing_stats(self):
        con = sqlite3.connect(self.path)
        con.execute(
            "INSERT INTO players(id,name,league,espn_id) VALUES(1,'Ramazan Temurov','ufc',NULL)"
        )
        con.execute(
            """
            INSERT INTO prop_games(id,league,date,home,away,espn_event_id)
            VALUES(10,'ufc','2026-07-25','Steve Erceg','Ramazan Temurov',NULL)
            """
        )
        con.execute(
            """
            INSERT INTO player_game_logs
              (player_id,league,season,game_no,game_id,game_date,opponent,stats,
               source,source_player_key)
            VALUES(1,'ufc',2025,'2025-01-01','old-fight','2025-01-01','Old Opponent',
                   '{"old":1}','espn_mma_stats','4895691')
            """
        )
        con.commit()
        con.close()

        duplicate = ingest.PreparedLog(
            player_id=1,
            season=2025,
            game_no="2025-01-01",
            game_id="old-fight",
            game_date="2025-01-01",
            opponent="Old Opponent",
            stats_json='{"replacement":true}',
            source_player_key="4895691",
        )
        new_log = ingest.PreparedLog(
            player_id=1,
            season=2026,
            game_no="2026-07-25",
            game_id="401874315",
            game_date="2026-07-25",
            opponent="Steve Erceg",
            stats_json='{"result":"W"}',
            source_player_key="4895691",
        )
        plan = ingest.IngestPlan(
            target_count=1,
            candidate_count=2,
            identity_updates={1: "4895691"},
            game_links={10: "401874315"},
            logs=[duplicate, new_log],
        )

        result = ingest.apply_plan(self.path, plan)

        self.assertEqual(
            {"identity_updates": 1, "game_links": 1, "inserted_logs": 1},
            result,
        )
        con = sqlite3.connect(self.path)
        player_espn = con.execute(
            "SELECT espn_id FROM players WHERE id=1"
        ).fetchone()[0]
        game_link = con.execute(
            "SELECT espn_event_id FROM prop_games WHERE id=10"
        ).fetchone()[0]
        rows = con.execute(
            "SELECT game_no,stats FROM player_game_logs ORDER BY game_no"
        ).fetchall()
        con.close()
        self.assertEqual("4895691", player_espn)
        self.assertEqual("401874315", game_link)
        self.assertEqual(
            [
                ("2025-01-01", '{"old":1}'),
                ("2026-07-25", '{"result":"W"}'),
            ],
            rows,
        )

    def test_apply_refuses_any_plan_with_source_errors(self):
        plan = ingest.IngestPlan(
            target_count=1,
            source_errors=["fighter: scoreboard_unavailable"],
        )

        with self.assertRaisesRegex(RuntimeError, "source errors"):
            ingest.apply_plan(self.path, plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
