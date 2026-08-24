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
from ingest_ufc_fight_stats import roster


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

    def test_a_first_name_divergence_resolves_on_the_opponents_espn_id(self):
        """The real 2026-08-24 pair, both standing SKIPs on the prod card.

        We hold "Sergey Spivak"; ESPN publishes "Serghei Spivac". Two publishers' spellings
        of one person, not a typo, so every name ladder refuses and should keep refusing.
        His opponent Vitor Petrino was already resolved on our side as 5060483, and ESPN's
        card pairs 4421246 with 5060483. That identifies him without reading his name.
        """
        games = [
            {
                "game_id": "401887540",
                "home": {"id": "4421246", "name": "Serghei Spivac"},
                "away": {"id": "5060483", "name": "Vitor Petrino"},
            }
        ]

        self.assertIsNone(
            ingest.resolve_from_card("Sergey Spivak", "Vitor Petrino", games),
            "the name ladders must still refuse a first-name divergence",
        )

        identity = ingest.resolve_from_card(
            "Sergey Spivak", "Vitor Petrino", games, opponent_espn_id="5060483"
        )

        self.assertIsNotNone(identity)
        self.assertEqual("4421246", identity.athlete_id)
        self.assertEqual("opponent_id", identity.method)
        self.assertEqual("401887540", identity.fight_id)

    def test_a_shortened_first_name_resolves_on_the_opponents_espn_id(self):
        """The other one: "Stanley Dorsainvil" against ESPN's "Stan Dorsainvil"."""
        games = [
            {
                "game_id": "401911626",
                "home": {"id": "5085318", "name": "Gauge Young"},
                "away": {"id": "5397038", "name": "Stan Dorsainvil"},
            }
        ]

        identity = ingest.resolve_from_card(
            "Stanley Dorsainvil", "Gauge Young", games, opponent_espn_id="5085318"
        )

        self.assertIsNotNone(identity)
        self.assertEqual("5397038", identity.athlete_id)
        self.assertEqual("opponent_id", identity.method)

    def test_an_opponent_id_absent_from_the_card_resolves_nothing(self):
        """The counter-case. An id we hold that is not on this card must not fall through
        to a name ladder and match something else."""
        games = [
            {
                "game_id": "irrelevant",
                "home": {"id": "1", "name": "Some Fighter"},
                "away": {"id": "2", "name": "Another Fighter"},
            }
        ]

        self.assertIsNone(
            ingest.resolve_from_card(
                "Sergey Spivak", "Vitor Petrino", games, opponent_espn_id="5060483"
            )
        )

    def test_an_opponent_id_on_two_fights_of_one_card_refuses(self):
        """A duplicated fixture must not make the match ambiguous and still pick one.

        `dedupe_prop_games.py` exists because duplicate fixtures are a real state in this
        data, so the ladder has to survive seeing the same opponent id twice.
        """
        games = [
            {
                "game_id": "a",
                "home": {"id": "4421246", "name": "Serghei Spivac"},
                "away": {"id": "5060483", "name": "Vitor Petrino"},
            },
            {
                "game_id": "b",
                "home": {"id": "9999999", "name": "Someone Else"},
                "away": {"id": "5060483", "name": "Vitor Petrino"},
            },
        ]

        self.assertIsNone(
            ingest.resolve_from_card(
                "Sergey Spivak", "Vitor Petrino", games, opponent_espn_id="5060483"
            )
        )

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


def _current_min_interval():
    """Read the shared client's spacing without a private attribute."""
    prev = ingest.espn.set_min_interval(0)
    ingest.espn.set_min_interval(prev)
    return prev


class TestBatchPacing(unittest.TestCase):
    """A fan-out must not spend the burst budget the request handlers need.

    2026-08-24: this plan inherited espn_client's serving-path default of
    min_interval=0 and fired 52 requests in one minute, twice. ESPN refused for
    four minutes and 26 of those refusals landed on uvicorn, the serving path.
    """

    def _target(self):
        return ingest.FighterTarget(
            player_id=1,
            name="Current Fighter",
            espn_id=None,
            card_date="2026-07-25",
            prop_game_id=10,
            opponent="Opponent",
        )

    def test_the_fan_out_is_paced_while_it_fetches(self):
        seen = []

        def _record(*_args, **_kwargs):
            seen.append(_current_min_interval())
            return (None, "scoreboard_unavailable:URLError")

        before = _current_min_interval()
        with mock.patch.object(ingest, "_card_for_date", side_effect=_record):
            ingest.build_current_card_plan([self._target()], set(), {}, emit=lambda _: None)

        self.assertEqual(1, len(seen))
        self.assertGreaterEqual(seen[0], 1.0, "the card fan-out ran unpaced")
        self.assertEqual(before, _current_min_interval(), "pacing leaked out of the plan")

    def test_pacing_is_restored_when_the_plan_raises(self):
        before = _current_min_interval()
        with mock.patch.object(ingest, "_card_for_date", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ingest.build_current_card_plan([self._target()], set(), {}, emit=lambda _: None)
        self.assertEqual(
            before,
            _current_min_interval(),
            "a raising plan left the serving path paced",
        )

    def test_the_history_fan_out_is_paced_too(self):
        seen = []

        def _record(*_args, **_kwargs):
            seen.append(_current_min_interval())
            return (None, "scoreboard_unavailable:URLError")

        with mock.patch.object(ingest, "_card_for_date", side_effect=_record):
            ingest.build_plan([self._target()], set(), {}, limit=5, emit=lambda _: None)

        self.assertEqual(1, len(seen))
        self.assertGreaterEqual(seen[0], 1.0, "the history fan-out ran unpaced")


class CardHarvestTest(unittest.TestCase):
    """The spine is harvested from the published card, not from a name.

    Measured 2026-08-24: ESPN's next 21 days of UFC cards named 94 scheduled fighters,
    every one of them carrying an athlete id, and 93 of the 94 were absent from the prod
    spine. `load_targets` reads its work set from `players`, so a fighter with no row was
    invisible to the whole pipeline forever.
    """

    def _con(self):
        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE players(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,"
            " team TEXT, league TEXT NOT NULL, espn_id TEXT, active INTEGER DEFAULT 1,"
            " updated_at TEXT, UNIQUE(espn_id, league))"
        )
        return con

    def _fetch(self, games):
        return lambda start, end: ({"2026-08-29": games}, 1)

    def _fight(self, home_id, home, away_id, away):
        return {
            "home": {"id": home_id, "name": home},
            "away": {"id": away_id, "name": away},
            "event_id": "600060620",
            "game_id": "401887532",
        }

    def test_a_fighter_we_do_not_hold_is_planned_from_the_card(self):
        con = self._con()
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("4569549", "Umar Nurmagomedov",
                                           "3151289", "Song Yadong")]),
        )
        self.assertEqual({f["espn_id"] for f in plan.new}, {"4569549", "3151289"})
        self.assertEqual(roster.apply_harvest(con, plan), 2)
        held = dict(con.execute("SELECT espn_id, name FROM players WHERE league='ufc'"))
        self.assertEqual(held["4569549"], "Umar Nurmagomedov")

    def test_re_running_the_same_window_inserts_nothing(self):
        con = self._con()
        games = [self._fight("4569549", "Umar Nurmagomedov", "3151289", "Song Yadong")]
        first = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None, fetch=self._fetch(games))
        roster.apply_harvest(con, first)
        second = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None, fetch=self._fetch(games))
        self.assertEqual(second.new, [])
        self.assertEqual(second.already_known, 2)
        self.assertEqual(roster.apply_harvest(con, second), 0)

    def test_a_side_with_no_publisher_id_is_never_created_from_its_name(self):
        con = self._con()
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("", "Nameless Challenger", "3151289", "Song Yadong")]),
        )
        self.assertEqual([f["espn_id"] for f in plan.new], ["3151289"])

    def test_the_placeholder_opponent_is_skipped(self):
        """ESPN files an unannounced opponent as a real athlete with a recurring id."""
        con = self._con()
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("4402367", "Opponent TBA", "3151289", "Song Yadong")]),
        )
        self.assertEqual([f["espn_id"] for f in plan.new], ["3151289"])
        self.assertEqual(plan.placeholders, [("4402367", "Opponent TBA")])

    def test_a_real_fighter_on_a_placeholder_id_is_not_dropped(self):
        """Both conditions must hold. If ESPN ever reuses that id for a named fighter,
        skipping on the id alone would silently drop a real person."""
        con = self._con()
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("4402367", "Real Person", "3151289", "Song Yadong")]),
        )
        self.assertIn("4402367", {f["espn_id"] for f in plan.new})
        self.assertEqual(plan.placeholders, [])

    def test_a_fighter_named_tba_without_the_placeholder_id_is_kept(self):
        con = self._con()
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("5999999", "TBA", "3151289", "Song Yadong")]),
        )
        self.assertIn("5999999", {f["espn_id"] for f in plan.new})

    def test_a_different_spelling_is_reported_and_never_renamed(self):
        """The two chronic UFC SKIPs are both name drift: we hold Bovada's `Sergey Spivak`
        where ESPN publishes `Serghei Spivac`. Our name is joined on elsewhere, so a rename
        is a separate deliberate decision, not a side effect of a harvest."""
        con = self._con()
        con.execute(
            "INSERT INTO players(name, league, espn_id) VALUES('Sergey Spivak','ufc','4421246')")
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("4421246", "Serghei Spivac", "5060483", "Vitor Petrino")]),
        )
        self.assertEqual(plan.name_drift, [("4421246", "Sergey Spivak", "Serghei Spivac")])
        self.assertNotIn("4421246", {f["espn_id"] for f in plan.new})
        roster.apply_harvest(con, plan)
        self.assertEqual(
            con.execute("SELECT name FROM players WHERE espn_id='4421246'").fetchone()[0],
            "Sergey Spivak",
        )

    def test_an_id_less_row_is_adopted_rather_than_duplicated(self):
        """Harvesting without this produced 46 duplicate names on dev and then 49
        ownership CONFLICTs: the resolver tried to give the old row an id the newly
        inserted row had already taken. The harvest caused the conflict it tripped over."""
        con = self._con()
        con.execute("INSERT INTO players(name, league, espn_id) VALUES('Edson Barboza','ufc',NULL)")
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("2526299", "Edson Barboza", "3151289", "Song Yadong")]),
        )
        self.assertEqual([a[1] for a in plan.adopt], ["Edson Barboza"])
        self.assertNotIn("2526299", {f["espn_id"] for f in plan.new})
        roster.apply_harvest(con, plan)
        rows = con.execute(
            "SELECT name, espn_id FROM players WHERE league='ufc' AND name='Edson Barboza'"
        ).fetchall()
        self.assertEqual(rows, [("Edson Barboza", "2526299")])

    def test_a_name_shared_by_two_id_less_rows_refuses_to_bind(self):
        """An ambiguous key must refuse, not pick one. A wrong bind is silent and
        permanent, and there is no error to notice later."""
        con = self._con()
        for _ in range(2):
            con.execute("INSERT INTO players(name, league, espn_id) VALUES('Dan Hooker','ufc',NULL)")
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("2559966", "Dan Hooker", "3151289", "Song Yadong")]),
        )
        self.assertEqual(plan.ambiguous, [("Dan Hooker", 2)])
        self.assertEqual(plan.adopt, [])
        self.assertNotIn("2559966", {f["espn_id"] for f in plan.new})
        roster.apply_harvest(con, plan)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM players WHERE espn_id='2559966'").fetchone()[0], 0)

    def test_a_drifted_spelling_is_not_adopted_onto_the_wrong_row(self):
        """Adoption is EXACT name only. A fuzzy or surname match is exactly what a
        two-publisher vocabulary defeats, and binding `Serghei Spivac` onto an id-less
        `Sergey Spivak` row on a surname would be a guess wearing a repair's clothes."""
        con = self._con()
        con.execute("INSERT INTO players(name, league, espn_id) VALUES('Sergey Spivak','ufc',NULL)")
        plan = roster.build_harvest_plan(
            con, today=dt.date(2026, 8, 24), emit=lambda _m: None,
            fetch=self._fetch([self._fight("4421246", "Serghei Spivac", "5060483", "Vitor Petrino")]),
        )
        self.assertEqual(plan.adopt, [])
        self.assertIn("4421246", {f["espn_id"] for f in plan.new})

    def test_a_harvest_with_nothing_to_insert_opens_no_writer_and_takes_no_backup(self):
        """A quiet sweep must cost nothing. The runner writes a 400MB backup before any
        spine write, so taking one on every run because the card was merely READ would be
        a per-run disk cost for no change."""
        import run_ufc_current_card_ingest as runner

        empty = roster.HarvestPlan()
        self.assertEqual(empty.mutations, 0)
        with mock.patch.object(runner, "_connect_readonly", return_value=None), \
                mock.patch.object(runner.roster, "build_harvest_plan", return_value=empty), \
                mock.patch.object(runner.ingest, "load_targets", return_value=([], set(), {})), \
                mock.patch.object(runner.common, "backup_database") as backup, \
                mock.patch.object(runner.sqlite3, "connect") as connect:
            result = runner.run("/tmp/not-opened.db", now=dt.datetime(2026, 8, 24, 13, 0),
                                emit=lambda _m: None)
        self.assertEqual(result["status"], "no_targets")
        backup.assert_not_called()
        connect.assert_not_called()

    def test_a_dry_run_never_writes_the_spine(self):
        """apply=False must not insert, and must not take the roster backup either."""
        import run_ufc_current_card_ingest as runner

        plan = roster.HarvestPlan(new=[{"espn_id": "1", "name": "A", "opponent": None,
                                        "event_id": None, "fight_id": None}])
        self.assertEqual(plan.mutations, 1)
        with mock.patch.object(runner, "_connect_readonly", return_value=None), \
                mock.patch.object(runner.roster, "build_harvest_plan", return_value=plan), \
                mock.patch.object(runner.ingest, "load_targets", return_value=([], set(), {})), \
                mock.patch.object(runner.common, "backup_database") as backup, \
                mock.patch.object(runner.sqlite3, "connect") as connect:
            runner.run("/tmp/not-opened.db", now=dt.datetime(2026, 8, 24, 13, 0),
                       emit=lambda _m: None, apply=False)
        backup.assert_not_called()
        connect.assert_not_called()

    def test_one_request_covers_the_whole_window(self):
        """21 per-day requests and one range request return the same answer. The budget
        skill's first lever is issuing fewer requests."""
        calls = []

        def fetch(start, end):
            calls.append((start, end))
            return {"2026-08-29": [self._fight("4569549", "A", "3151289", "B")]}, 1

        roster.build_harvest_plan(
            self._con(), today=dt.date(2026, 8, 24), emit=lambda _m: None, fetch=fetch)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("2026-08-10", "2026-09-14"))

