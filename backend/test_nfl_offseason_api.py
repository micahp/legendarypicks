import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, os.path.dirname(__file__))

from fastapi import HTTPException
from routers import nfl_offseason


class NflOffseasonApiTests(unittest.TestCase):
    def setUp(self):
        nfl_offseason._clear_draft_board_cache()
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE players(
                  id INTEGER PRIMARY KEY,
                  name TEXT NOT NULL,
                  league TEXT NOT NULL,
                  team TEXT,
                  position TEXT,
                  active INTEGER,
                  updated_at TEXT
                );
                CREATE TABLE player_stats(
                  player_id INTEGER,
                  player_name TEXT,
                  league TEXT,
                  team TEXT,
                  season INTEGER,
                  games INTEGER,
                  nfl_position TEXT,
                  nfl_team TEXT,
                  fantasy_ppr_g REAL,
                  fantasy_pts_g REAL,
                  pass_yds_g REAL,
                  rush_yds_g REAL,
                  rec_yds_g REAL,
                  targets INTEGER,
                  receptions INTEGER,
                  carries_g REAL
                );
                CREATE TABLE player_game_logs(
                  player_id INTEGER,
                  league TEXT,
                  season INTEGER,
                  game_no TEXT,
                  game_id TEXT,
                  team TEXT,
                  game_type TEXT,
                  stats TEXT
                );
                CREATE TABLE nfl_adp(
                  player_id INTEGER,
                  season INTEGER,
                  adp REAL,
                  percent_owned REAL,
                  espn_ppr_rank INTEGER
                );
                CREATE TABLE nfl_player_projections(
                  player_id INTEGER,
                  season INTEGER,
                  lp_ppr_projected_points REAL,
                  PRIMARY KEY(player_id, season)
                );
                CREATE TABLE nfl_depth_chart(
                  player_id INTEGER,
                  season INTEGER,
                  team TEXT,
                  pos_abb TEXT,
                  pos_rank INTEGER
                );
                CREATE TABLE team_stats_coverage(
                  run_id TEXT PRIMARY KEY,
                  league TEXT,
                  season INTEGER,
                  status TEXT,
                  fetched_teams INTEGER,
                  fetched_games INTEGER,
                  completed_at TEXT
                );
                """
            )
            connection.executemany(
                "INSERT INTO players VALUES(?,?,?,?,?,?,?)",
                [
                    (1, "Alias Receiver", "nfl", "LAR", "WR", 1, "2026-07-20T12:00:00+00:00"),
                    (2, "Actual Mover", "nfl", "MIN", "QB", 1, "2026-07-20T12:00:00+00:00"),
                    (3, "Inactive Back", "nfl", "DAL", "RB", 0, "2026-07-20T12:00:00+00:00"),
                    (4, "Camp Rookie", "nfl", "NE", "WR", 1, "2026-07-20T12:00:00+00:00"),
                    (5, "Undrafted Body", "nfl", "NE", "WR", 1, "2026-07-20T12:00:00+00:00"),
                    (6, "Team Quarterback", "nfl", "KC", "TQB", 1, "2026-07-20T12:00:00+00:00"),
                ],
            )
            connection.executemany(
                "INSERT INTO player_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (1, "Alias Receiver", "nfl", "LA", 2025, 16, "WR", "LA", 22.4, 16.1, 0.0, 1.2, 101.2, 160, 120, 0.2),
                    (2, "Actual Mover", "nfl", "ARI", 2025, 15, "QB", "ARI", 19.8, 19.8, 251.0, 34.2, 0.0, 0, 0, 5.4),
                    (3, "Inactive Back", "nfl", "DAL", 2025, 17, "RB", "DAL", 18.0, 14.0, 0.0, 82.0, 25.0, 50, 40, 15.0),
                ],
            )
            # Alias Receiver played 16 of 17; Actual Mover only 8, plus one
            # POSTSEASON week that must never count toward availability.
            logs = []
            for week in range(1, 17):
                logs.append((1, "nfl", 2025, str(week), f"2025_{week:02d}_LA_SF", "LA", "REG",
                             '{"fpts_ppr": 20.0, "xfpts_ppr": 18.0, '
                             '"off_pct": 0.9, "target_share": 0.25}'))
            for week in range(1, 9):
                logs.append((2, "nfl", 2025, str(week), f"2025_{week:02d}_ARI_SEA", "ARI", "REG",
                             '{"fpts_ppr": 17.0, "xfpts_ppr": 16.0, "off_pct": 1.0}'))
            logs.append((2, "nfl", 2025, "19", "2025_19_ARI_SEA", "ARI", "POST",
                         '{"fpts_ppr": 30.0, "xfpts_ppr": 28.0, "off_pct": 1.0}'))
            connection.executemany(
                "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?)", logs)
            connection.executemany(
                "INSERT INTO nfl_adp VALUES(?,?,?,?,?)",
                [
                    (1, 2026, 3.5, 99.0, 2),
                    (2, 2026, 25.0, 95.0, 1),
                    (4, 2026, 66.0, 80.0, 3),      # rookie with a real market price
                    (5, 2026, 170.0, 0.1, None),   # copied published ADP
                    (6, 2026, 25.0, 50.0, 4),      # aggregate slot, not a player
                ],
            )
            connection.executemany(
                "INSERT INTO nfl_player_projections VALUES(?,?,?)",
                [(1, 2026, 301.2), (2, 2026, 355.7), (4, 2026, None)],
            )
            connection.executemany(
                "INSERT INTO nfl_depth_chart VALUES(?,?,?,?,?)",
                [
                    (1, 2026, "LA", "WR", 1),
                    (2, 2026, "ARI", "QB", 1),
                    (4, 2026, "NE", "WR", 2),
                    # One player can have multiple published roles. The board
                    # must still emit one entity and attach the best role.
                    (4, 2026, "NE", "RB", 7),
                ],
            )
            connection.execute(
                "INSERT INTO team_stats_coverage VALUES(?,?,?,?,?,?,?)",
                ("run", "nfl", 2025, "complete", 32, 272, "2026-07-14T21:22:17Z"),
            )

        self.original_db = nfl_offseason._db
        self.original_today = nfl_offseason._today
        nfl_offseason._db = lambda: sqlite3.connect(self.db_path)
        nfl_offseason._today = lambda: dt.date(2026, 7, 21)

    def tearDown(self):
        nfl_offseason._clear_draft_board_cache()
        nfl_offseason._db = self.original_db
        nfl_offseason._today = self.original_today
        os.unlink(self.db_path)

    def context(self, as_of=dt.date(2026, 7, 21)):
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            return nfl_offseason._build_nfl_season_context(as_of, connection)

    def board(self, position=None, sort="adp", q=None, limit=50, offset=0):
        return nfl_offseason.nfl_draft_board(
            position=position,
            sort=sort,
            q=q,
            limit=limit,
            offset=offset,
        )

    def test_training_camp_context_is_actionable_and_grounded(self):
        payload = self.context()
        self.assertEqual(payload["contract"], "nfl-season-context-v1")
        self.assertEqual(payload["phase"], "training_camp")
        self.assertEqual(payload["phase_label"], "Training Camp")
        self.assertEqual(payload["reference_season"], 2025)
        self.assertEqual(payload["next_event"]["id"], "all_teams_report")
        self.assertEqual(payload["next_event"]["days_until"], 7)
        self.assertEqual(payload["coverage"]["reference_stats"]["players"], 3)
        self.assertEqual(payload["coverage"]["game_logs"]["rows"], 25)
        self.assertEqual(payload["coverage"]["current_roster"]["players"], 5)
        self.assertEqual(
            payload["coverage"]["current_roster"]["skill_players_with_reference_stats"],
            2,
        )
        self.assertEqual(payload["coverage"]["team_reference"]["games"], 272)

    def test_published_decimal_ratios_round_half_up(self):
        self.assertEqual(nfl_offseason._rounded_ratio(42.4, 16), 2.7)
        self.assertEqual(nfl_offseason._rounded_ratio(8.1, 6), 1.4)
        self.assertEqual(nfl_offseason._rounded_ratio(109.9, 14), 7.9)
        self.assertEqual(
            nfl_offseason._rounded_ratio(109.89999999999998, 14),
            7.9,
        )
        self.assertEqual(nfl_offseason._rounded_ratio(13.760000000000002, 4), 3.4)
        self.assertEqual(nfl_offseason._rounded_ratio(-0.08, 2), 0.0)
        self.assertEqual(nfl_offseason._percentage(0.285, 0), 29.0)

    def test_calendar_phases_fail_closed_after_verified_window(self):
        cases = [
            (dt.date(2026, 7, 16), "offseason"),
            (dt.date(2026, 8, 6), "preseason"),
            (dt.date(2026, 9, 9), "regular_season"),
            (dt.date(2027, 1, 1), "unknown"),
        ]
        for as_of, expected in cases:
            with self.subTest(as_of=as_of):
                payload = self.context(as_of)
                self.assertEqual(payload["phase"], expected)
                self.assertEqual(
                    payload["calendar_status"],
                    "expired" if expected == "unknown" else "current",
                )

    def test_draft_board_uses_active_identity_spine_and_normalizes_aliases(self):
        payload = self.board()
        self.assertEqual(payload["contract"], "nfl-draft-board-v2")
        self.assertEqual(payload["reference_season"], 2025)
        # Every copied ADP is preserved; the inactive player stays off the
        # identity spine.
        self.assertEqual(payload["eligible_players"], 4)
        self.assertEqual(
            [player["player_id"] for player in payload["players"]],
            [1, 2, 4, 5],
        )
        self.assertEqual(
            {"QB", "RB", "WR", "TE", "PK", "DEF"},
            set(nfl_offseason._FANTASY_DRAFT_POSITIONS),
        )
        self.assertNotIn("TQB", {player["position"] for player in payload["players"]})

        alias_receiver, actual_mover, _rookie, _late = payload["players"]
        self.assertEqual(alias_receiver["current_team"], "LAR")
        self.assertEqual(alias_receiver["depth_team"], "LAR")
        self.assertFalse(alias_receiver["team_changed"])
        self.assertTrue(actual_mover["team_changed"])

    def test_draft_board_cache_keeps_alternating_keys_warm(self):
        original = nfl_offseason._regular_season_aggregates
        with mock.patch.object(
            nfl_offseason,
            "_regular_season_aggregates",
            wraps=original,
        ) as aggregates:
            first = self.board(sort="adp")
            projected = self.board(sort="proj")
            repeated = self.board(sort="adp")

        self.assertEqual(first, repeated)
        self.assertNotEqual(
            [player["player_id"] for player in first["players"]],
            [player["player_id"] for player in projected["players"]],
        )
        self.assertEqual(2, aggregates.call_count)

    def test_draft_board_cache_invalidates_after_database_write(self):
        before = {p["name"]: p for p in self.board()["players"]}
        self.assertEqual(8, before["Actual Mover"]["games_played"])

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "DELETE FROM player_game_logs WHERE player_id=2 AND CAST(game_no AS INTEGER) > 2"
            )

        after = {p["name"]: p for p in self.board()["players"]}
        self.assertEqual(2, after["Actual Mover"]["games_played"])

    def test_availability_is_the_headline_and_both_averages_ship_together(self):
        players = {p["name"]: p for p in self.board()["players"]}

        receiver = players["Alias Receiver"]
        self.assertEqual(receiver["games_played"], 16)
        self.assertEqual(receiver["team_games"], 17)
        # Played nearly every game, so the two averages barely differ.
        self.assertEqual(receiver["ppr_per_game_played"], 20.0)
        self.assertEqual(receiver["ppr_per_team_game"], 18.8)

        mover = players["Actual Mover"]
        # Eight regular-season games. The week-19 playoff line must NOT count:
        # counting it would report 9/17 and inflate both averages.
        self.assertEqual(mover["games_played"], 8)
        self.assertEqual(mover["ppr_per_game_played"], 17.0)
        self.assertEqual(mover["ppr_per_team_game"], 8.0)
        self.assertNotIn(19, mover["weeks_played"])
        self.assertEqual(mover["weeks_played"], list(range(1, 9)))

    def test_shared_availability_uses_logs_for_movers_and_snaps_for_snap_only(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE nfl_snap_counts(
                  player_id INTEGER,
                  season INTEGER,
                  week INTEGER,
                  team TEXT
                );
                CREATE TABLE nfl_schedule(
                  season INTEGER,
                  week INTEGER,
                  home_team TEXT,
                  away_team TEXT
                );
                """
            )
            # Actual Mover has authoritative ARI log rows. More MIN snap rows
            # must fill presence without changing the log-derived primary team.
            connection.executemany(
                "INSERT INTO nfl_snap_counts VALUES(2,2025,?,'MIN')",
                [(week,) for week in range(1, 18)],
            )
            # Camp Rookie has no logs; its published snap team is the only
            # grounded source for the schedule denominator.
            connection.executemany(
                "INSERT INTO nfl_snap_counts VALUES(4,2025,?,'NE')",
                [(week,) for week in range(1, 4)],
            )
            for week in range(1, 18):
                connection.execute(
                    "INSERT INTO nfl_schedule VALUES(2025,?,'ARI','OPP')",
                    (week,),
                )
                connection.execute(
                    "INSERT INTO nfl_schedule VALUES(2025,?,'MIN','OPP')",
                    (week,),
                )
                connection.execute(
                    "INSERT INTO nfl_schedule VALUES(2025,?,'NE','OPP')",
                    (week,),
                )
            connection.row_factory = sqlite3.Row
            availability = nfl_offseason._availability_aggregates(connection, 2025)

        mover = availability[2]
        self.assertEqual(mover["primary_team"], "ARI")
        self.assertEqual(mover["games_played"], 17)
        self.assertEqual(mover["team_games"], 17)
        self.assertEqual(mover["team_weeks"], list(range(1, 18)))

        rookie = availability[4]
        self.assertEqual(rookie["primary_team"], "NE")
        self.assertEqual(rookie["games_played"], 3)
        self.assertEqual(rookie["team_games"], 17)
        self.assertEqual(rookie["team_weeks"], list(range(1, 18)))

    def test_kicker_per_game_uses_presence_not_field_goal_attempt_rows(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """CREATE TABLE nfl_snap_counts(
                     player_id INTEGER,
                     season INTEGER,
                     week INTEGER,
                     team TEXT
                   )"""
            )
            for week in range(1, 17):
                connection.execute(
                    "INSERT INTO player_game_logs VALUES(?,?,?,?,?,?,?,?)",
                    (
                        6,
                        "nfl",
                        2025,
                        str(week),
                        f"pk-{week}",
                        "DAL",
                        "REG",
                        '{"fg_att":1,"fg_made_0_19":1}',
                    ),
                )
            connection.executemany(
                "INSERT INTO nfl_snap_counts VALUES(6,2025,?,'DAL')",
                [(week,) for week in range(1, 18)],
            )
            connection.row_factory = sqlite3.Row
            availability = nfl_offseason._availability_aggregates(connection, 2025)
            scoring = nfl_offseason._pk_aggregates(
                connection, 2025, availability
            )

        self.assertEqual(availability[6]["games_played"], 17)
        self.assertEqual(scoring[6]["pk_pts_total"], 48.0)
        self.assertEqual(scoring[6]["pk_pts_per_game"], 2.8)

    def test_no_sample_players_read_as_absent_rather_than_zero(self):
        players = {p["name"]: p for p in self.board()["players"]}

        rookie = players["Camp Rookie"]
        self.assertEqual(rookie["sample"], "none")
        self.assertIsNone(rookie["games_played"])
        self.assertIsNone(rookie["games_missed"])
        self.assertIsNone(rookie["team_games"])
        self.assertEqual(rookie["weeks_played"], [])
        # A zero here would be a claim about the player. Absence is a claim
        # about us, and it is the true one.
        for field in ("ppr_per_game_played", "ppr_per_team_game",
                      "xfp_per_game", "snap_pct", "target_share"):
            self.assertIsNone(rookie[field], field)
        # What he does have: a market price and a current role.
        self.assertEqual(rookie["adp"], 66.0)
        self.assertTrue(rookie["adp_is_ranked"])
        self.assertEqual(rookie["depth_rank"], 2)
        self.assertEqual(rookie["depth_position"], "WR")

    def test_draft_board_returns_current_injury_designation_when_available(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("ALTER TABLE players ADD COLUMN injury_status TEXT")
            connection.execute(
                "UPDATE players SET injury_status='QUESTIONABLE' WHERE id=1"
            )

        receiver = {
            player["player_id"]: player for player in self.board()["players"]
        }[1]
        self.assertEqual(receiver["injury_status"], "QUESTIONABLE")

    def test_draft_board_returns_and_sorts_published_2026_projection(self):
        players = {p["player_id"]: p for p in self.board()["players"]}
        self.assertEqual(players[1]["espn_ppr_rank"], 2)
        self.assertEqual(players[1]["proj_ppr_points"], 301.2)
        self.assertEqual(players[1]["proj_season"], 2026)
        self.assertEqual(players[1]["proj_source"], "espn")
        self.assertIsNone(players[4]["proj_ppr_points"])
        self.assertIsNone(players[4]["proj_source"])

        projected = self.board(sort="proj")
        self.assertEqual(
            [p["player_id"] for p in projected["players"][:2]],
            [2, 1],
        )
        self.assertTrue(
            all(p["proj_ppr_points"] is None for p in projected["players"][2:])
        )

    def test_multi_position_depth_chart_emits_one_player(self):
        players = [p for p in self.board()["players"] if p["player_id"] == 4]
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0]["depth_rank"], 2)
        self.assertEqual(players[0]["depth_position"], "WR")

    def test_target_share_keeps_zero_weeks_but_non_receivers_stay_null(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """UPDATE player_game_logs
                   SET stats=json_set(stats, '$.target_share', 0)
                   WHERE player_id=1 AND game_type='REG' AND game_no!='1'"""
            )
            connection.execute(
                """UPDATE player_game_logs
                   SET stats=json_set(stats, '$.target_share', 0)
                   WHERE player_id=2 AND game_type='REG'"""
            )
            connection.row_factory = sqlite3.Row
            aggregates = nfl_offseason._regular_season_aggregates(
                connection, 2025
            )

        self.assertAlmostEqual(aggregates[1]["target_share"], 0.25 / 16)
        self.assertIsNone(aggregates[2]["target_share"])

    def test_snap_percentage_reads_all_published_snap_rows(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """CREATE TABLE nfl_snap_counts(
                     player_id INTEGER,
                     season INTEGER,
                     week INTEGER,
                     team TEXT,
                     off_pct REAL
                   )"""
            )
            connection.executemany(
                "INSERT INTO nfl_snap_counts VALUES(1,2025,?,'LAR',?)",
                [(1, 0.9), (2, 0.3), (17, 0.0)],
            )
            connection.row_factory = sqlite3.Row
            aggregates = nfl_offseason._regular_season_aggregates(
                connection, 2025
            )

        self.assertAlmostEqual(aggregates[1]["snap_pct"], 0.4)
        self.assertIsNone(aggregates[2]["snap_pct"])

    def test_published_late_adp_is_not_discarded_by_the_reader(self):
        players = {p["name"]: p for p in self.board()["players"]}
        late = players["Undrafted Body"]
        self.assertEqual(late["adp"], 170.0)
        self.assertTrue(late["adp_is_ranked"])

    def test_thin_samples_are_marked_not_silently_ranked(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "DELETE FROM player_game_logs WHERE player_id=2 AND CAST(game_no AS INTEGER) > 2")
        mover = {p["name"]: p for p in self.board()["players"]}["Actual Mover"]
        self.assertEqual(mover["games_played"], 2)
        self.assertEqual(mover["sample"], "thin")

    def test_draft_board_filters_positions_and_is_bounded(self):
        quarterback = self.board(position="qb", limit=1)
        self.assertEqual(quarterback["position"], "QB")
        self.assertEqual(quarterback["eligible_players"], 1)
        self.assertEqual(quarterback["returned_players"], 1)
        self.assertEqual(quarterback["players"][0]["name"], "Actual Mover")

        # FLEX carries the rookie too: no season, but a real ADP and a role.
        flex = self.board(position="FLEX")
        self.assertEqual([player["name"] for player in flex["players"]],
                         ["Alias Receiver", "Camp Rookie", "Undrafted Body"])

    def test_name_search_finds_a_player_without_paging_to_him(self):
        # The whole point: one player back, not the board filtered client-side.
        payload = self.board(q="mover")
        self.assertEqual(payload["query"], "mover")
        self.assertEqual(payload["eligible_players"], 1)
        self.assertEqual([p["name"] for p in payload["players"]], ["Actual Mover"])

        # Case-insensitive, and tokens match in any order -- people type
        # fragments in whatever order they remember them.
        self.assertEqual(
            [p["name"] for p in self.board(q="MOVER actual")["players"]],
            ["Actual Mover"],
        )
        # Interior substring, not just a prefix.
        self.assertEqual(
            [p["name"] for p in self.board(q="eceiv")["players"]],
            ["Alias Receiver"],
        )

    def test_name_search_composes_with_position_and_reports_no_match_honestly(self):
        # Search and position narrow together; they do not override each other.
        both = self.board(q="a", position="QB")
        self.assertEqual([p["name"] for p in both["players"]], ["Actual Mover"])

        empty = self.board(q="nobodyhere")
        self.assertEqual(empty["eligible_players"], 0)
        self.assertEqual(empty["players"], [])
        self.assertEqual(empty["query"], "nobodyhere")

    def test_blank_and_wildcard_searches_cannot_widen_the_board(self):
        unfiltered = self.board()["eligible_players"]

        for blank in (None, "", "   "):
            with self.subTest(blank=blank):
                payload = self.board(q=blank)
                self.assertIsNone(payload["query"])
                self.assertEqual(payload["eligible_players"], unfiltered)

        # LIKE wildcards are escaped, so they match themselves and find nothing
        # rather than matching every player on the board.
        for wildcard in ("%", "_", "%%%", "\\"):
            with self.subTest(wildcard=wildcard):
                self.assertEqual(self.board(q=wildcard)["eligible_players"], 0)

    def test_stale_roster_suppresses_team_change_claims(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE players SET updated_at='2026-06-01T12:00:00+00:00' WHERE league='nfl'"
            )
        context = self.context()
        self.assertEqual(
            context["coverage"]["current_roster"]["freshness"]["status"],
            "stale",
        )
        board = self.board()
        self.assertTrue(all(player["team_changed"] is None for player in board["players"]))

    def test_invalid_filters_are_rejected(self):
        with self.assertRaises(HTTPException) as position_error:
            self.board(position="K")
        self.assertEqual(position_error.exception.status_code, 400)
        with self.assertRaises(HTTPException) as sort_error:
            self.board(sort="name; DROP TABLE players")
        self.assertEqual(sort_error.exception.status_code, 400)

    def test_missing_schema_fails_closed(self):
        empty = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        empty.close()
        try:
            nfl_offseason._db = lambda: sqlite3.connect(empty.name)
            with self.assertRaises(HTTPException) as error:
                self.board()
            self.assertEqual(error.exception.status_code, 503)
        finally:
            os.unlink(empty.name)


if __name__ == "__main__":
    unittest.main()
