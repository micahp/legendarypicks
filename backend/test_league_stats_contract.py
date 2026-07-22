#!/usr/bin/env python3
"""Deterministic contract tests for GET /api/{league}/leaders."""
import json
import os
import sqlite3
import tempfile
import unittest

# _core initializes its configured database on import. Point that initialization
# at an isolated temp path; each test then monkeypatches players._db separately.
_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

from fastapi import HTTPException
from routers import players


def all_metrics():
    ordered = []
    formats = {}
    for definitions in players._LEAGUE_CATEGORIES.values():
        for category in definitions:
            for metric in category["stats"]:
                if metric["key"] not in ordered:
                    ordered.append(metric["key"])
                formats[metric["key"]] = metric["format"]
    return ordered, formats


ALL_METRICS, METRIC_FORMATS = all_metrics()


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def create_schema(path, omitted=(), with_logs=True):
    omitted = set(omitted)
    metric_columns = []
    for key in ALL_METRICS:
        if key in omitted:
            continue
        sql_type = "INTEGER" if METRIC_FORMATS[key] == "integer" else "REAL"
        if METRIC_FORMATS[key] == "time":
            sql_type = "TEXT"
        metric_columns.append(f"{key} {sql_type}")
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE player_stats("
            "player_id INTEGER, player_name TEXT, league TEXT, team TEXT, "
            "season INTEGER, games INTEGER, stat_type TEXT, "
            + ", ".join(metric_columns)
            + ")"
        )
        if with_logs:
            con.execute(
                "CREATE TABLE player_game_logs("
                "player_id INTEGER, league TEXT, season INTEGER, "
                "game_date TEXT, game_no TEXT, stats TEXT)"
            )


def metric_values(definition_key, high=True):
    values = {}
    definitions = players._LEAGUE_CATEGORIES[definition_key]
    for category in definitions:
        for metric in category["stats"]:
            key = metric["key"]
            if metric["format"] == "integer":
                values[key] = 20 if high else 10
            elif metric["format"] == "decimal_3":
                values[key] = 0.3766 if high else 0.3214
            elif metric["format"] == "time":
                values[key] = "20:00" if high else "10:00"
            else:
                values[key] = 20.26 if high else 10.14
    return values


def insert_row(path, player_id, name, league, season, games, stat_type=None, values=None):
    values = values or {}
    with sqlite3.connect(path) as con:
        db_columns = {row[1] for row in con.execute("PRAGMA table_info(player_stats)")}
        data = {
            "player_id": player_id,
            "player_name": name,
            "league": league,
            "team": "TST",
            "season": season,
            "games": games,
            "stat_type": stat_type,
            **{key: value for key, value in values.items() if key in db_columns},
        }
        columns = list(data)
        placeholders = ",".join("?" for _ in columns)
        con.execute(
            f"INSERT INTO player_stats ({','.join(columns)}) VALUES ({placeholders})",
            [data[column] for column in columns],
        )


def insert_logs(path, player_id, league, stats_rows, season=2026, dated=False):
    with sqlite3.connect(path) as con:
        con.executemany(
            "INSERT INTO player_game_logs(player_id,league,season,game_date,game_no,stats) "
            "VALUES (?,?,?,?,?,?)",
            [
                (
                    player_id, league, season,
                    f"2026-01-{index:02d}" if dated else None,
                    str(index),
                    value if isinstance(value, str) else json.dumps(value),
                )
                for index, value in enumerate(stats_rows, 1)
            ],
        )


def call(league, *, stat=None, category=None, type=None, season=None, min_games=0, limit=25):
    return players.league_leaders(
        league,
        stat=stat,
        category=category,
        type=type,
        season=season,
        min_games=min_games,
        limit=limit,
    )


class LeagueStatsContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "leaders.db")
        create_schema(self.db_path)
        self.original_db = players._db
        players._db = lambda: connect(self.db_path)

    def tearDown(self):
        players._db = self.original_db
        self.tmp.cleanup()

    def populate_all(self):
        fixtures = [
            ("nba", None, "nba", 82),
            ("nfl", None, "nfl", 17),
            ("nhl", None, "nhl", 82),
            ("mlb", "batting", "mlb_batting", 60),
            ("mlb", "pitching", "mlb_pitching", 20),
        ]
        player_id = 1
        for league, stat_type, definition_key, games in fixtures:
            insert_row(
                self.db_path, player_id, f"{definition_key} Low", league, 2026,
                games, stat_type, metric_values(definition_key, high=False),
            )
            insert_row(
                self.db_path, player_id + 1, f"{definition_key} High", league, 2026,
                games, stat_type, metric_values(definition_key, high=True),
            )
            player_id += 2

    def assert_http_400(self, function):
        with self.assertRaises(HTTPException) as raised:
            function()
        self.assertEqual(raised.exception.status_code, 400)
        self.assertTrue(raised.exception.detail)

    def test_defaults_metadata_and_ordering_for_every_league_and_mlb_type(self):
        self.populate_all()
        cases = [
            ("nba", None, "scoring", "pts", ["scoring", "playmaking", "rebounding", "defense", "efficiency"]),
            ("nfl", None, "passing", "pass_yds_g", ["passing", "rushing", "receiving"]),
            ("nhl", None, "scoring", "points_nhl", ["scoring", "shooting", "special_teams", "possession"]),
            ("mlb", "batting", "production", "avg", ["production", "contact_quality", "discipline"]),
            ("mlb", "pitching", "strikeouts", "k_pct", ["strikeouts", "contact_suppression"]),
        ]
        for league, stat_type, expected_category, expected_stat, category_keys in cases:
            with self.subTest(league=league, type=stat_type):
                response = call(league, type=stat_type)
                self.assertEqual(response["season"], 2026)
                self.assertEqual(response["stat_type"], stat_type)
                self.assertEqual(response["category"], expected_category)
                self.assertEqual(response["stat"], expected_stat)
                self.assertEqual([item["key"] for item in response["categories"]], category_keys)
                self.assertEqual(response["columns"], response["categories"][0]["stats"])
                self.assertEqual(len(response["leaders"]), 2)
                self.assertTrue(response["leaders"][0]["name"].endswith("High"))
                self.assertGreater(
                    response["leaders"][0][expected_stat],
                    response["leaders"][1][expected_stat],
                )

        nba = call("nba")
        self.assertEqual(
            [(column["key"], column["format"]) for column in nba["columns"]],
            [
                ("pts", "decimal_1"), ("fgm", "integer"),
                ("fga", "integer"), ("fg3m", "integer"),
                ("fg3a", "integer"), ("ftm", "integer"),
                ("fta", "integer"),
            ],
        )

    def test_stat_only_infers_first_category_and_category_selects_first_metric(self):
        self.populate_all()
        self.assertEqual(call("nba", stat="pts")["category"], "scoring")
        self.assertEqual(call("nba", stat="ts_pct")["category"], "efficiency")
        self.assertEqual(call("mlb", type="batting", stat="xwoba")["category"], "production")
        defense = call("nba", category="defense")
        self.assertEqual(defense["stat"], "stl")
        self.assertEqual([column["key"] for column in defense["columns"]], ["stl", "blk"])
        self.assertEqual(call("nba", category="defense", stat="blk")["stat"], "blk")

    def test_invalid_category_stat_type_and_cross_category_stat_are_400(self):
        self.populate_all()
        self.assert_http_400(lambda: call("nba", category="goalies"))
        self.assert_http_400(lambda: call("nba", stat="fantasy_pts_g"))
        self.assert_http_400(lambda: call("mlb", type="fielding"))
        self.assert_http_400(lambda: call("nba", type="batting"))
        self.assert_http_400(lambda: call("nba", category="defense", stat="pts"))

    def test_null_metrics_and_categories_are_omitted_and_explicit_requests_fail(self):
        self.populate_all()
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "UPDATE player_stats SET rec_yds_g=NULL, receptions=NULL, targets=NULL "
                "WHERE league='nfl'"
            )
        response = call("nfl")
        self.assertEqual(
            [category["key"] for category in response["categories"]],
            ["passing", "rushing"],
        )
        self.assert_http_400(lambda: call("nfl", category="receiving"))
        self.assert_http_400(lambda: call("nfl", stat="rec_yds_g"))

    def test_missing_column_is_omitted_from_metadata(self):
        missing_path = os.path.join(self.tmp.name, "missing-column.db")
        create_schema(missing_path, omitted={"barrel_pct_against"})
        insert_row(
            missing_path, 1, "Pitcher", "mlb", 2026, 20, "pitching",
            metric_values("mlb_pitching"),
        )
        players._db = lambda: connect(missing_path)
        response = call("mlb", type="pitching", category="contact_suppression")
        self.assertEqual(
            [column["key"] for column in response["columns"]],
            ["xwoba_against", "exit_velo_against"],
        )
        self.assert_http_400(
            lambda: call("mlb", type="pitching", stat="barrel_pct_against")
        )

    def test_empty_season_and_population_with_no_metrics_return_empty_contract(self):
        empty = call("nba")
        self.assertEqual(
            empty,
            {
                "league": "nba", "season": None, "available_seasons": [], "stat": None,
                "stat_type": None, "category": None, "categories": [],
                "columns": [], "leaders": [], "change_metric": None,
                "comparison": None, "changes": [],
            },
        )
        insert_row(self.db_path, 1, "No Metrics", "nba", 2026, 10, values={})
        no_metrics = call("nba", stat="pts")
        self.assertEqual(no_metrics["season"], 2026)
        self.assertEqual(no_metrics["available_seasons"], [2026])
        self.assertIsNone(no_metrics["stat"])
        self.assertEqual(no_metrics["categories"], [])
        self.assertEqual(no_metrics["leaders"], [])
        self.assertIsNone(no_metrics["change_metric"])
        self.assertIsNone(no_metrics["comparison"])
        self.assertEqual(no_metrics["changes"], [])

    def test_season_defaults_to_latest_and_can_be_overridden(self):
        nfl = metric_values("nfl")
        insert_row(self.db_path, 1, "Old Season Passer", "nfl", 2024, 16, values=nfl)
        insert_row(self.db_path, 2, "New Season Passer", "nfl", 2025, 16, values=nfl)

        default = call("nfl")
        self.assertEqual(default["season"], 2025)
        self.assertEqual(default["available_seasons"], [2025, 2024])
        self.assertEqual(default["leaders"][0]["name"], "New Season Passer")

        older = call("nfl", season=2024)
        self.assertEqual(older["season"], 2024)
        self.assertEqual(older["available_seasons"], [2025, 2024])
        self.assertEqual(older["leaders"][0]["name"], "Old Season Passer")

        with self.assertRaises(HTTPException) as ctx:
            call("nfl", season=2099)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("2099", str(ctx.exception.detail))

    def test_mlb_precision_and_integer_values_are_preserved(self):
        batting = metric_values("mlb_batting")
        batting.update({"avg": 0.32149, "woba": 0.3766, "xwoba": 0.3555, "hr": 17})
        insert_row(self.db_path, 1, "Precise Batter", "mlb", 2026, 50, "batting", batting)
        mlb = call("mlb", type="batting")
        leader = mlb["leaders"][0]
        self.assertEqual(leader["avg"], 0.321)
        self.assertEqual(leader["woba"], 0.377)
        self.assertEqual(leader["xwoba"], 0.355)
        self.assertEqual(leader["hr"], 17)
        self.assertIs(type(leader["hr"]), int)

        nba = metric_values("nba")
        nba.update({"pts": 31.26, "fgm": 120})
        insert_row(self.db_path, 2, "Integer Shooter", "nba", 2026, 82, values=nba)
        nba_leader = call("nba")["leaders"][0]
        self.assertEqual(nba_leader["pts"], 31.3)
        self.assertEqual(nba_leader["fgm"], 120)
        self.assertIs(type(nba_leader["fgm"]), int)

    def test_min_games_and_limit_remain_effective(self):
        values = metric_values("mlb_batting")
        insert_row(self.db_path, 1, "Qualified", "mlb", 2026, 30, "batting", values)
        insert_row(self.db_path, 2, "Cup of Coffee", "mlb", 2026, 29, "batting", values)
        self.assertEqual([row["name"] for row in call("mlb")["leaders"]], ["Qualified"])

        insert_row(self.db_path, 3, "NBA A", "nba", 2026, 10, values=metric_values("nba", high=True))
        insert_row(self.db_path, 4, "NBA B", "nba", 2026, 10, values=metric_values("nba", high=False))
        self.assertEqual(len(call("nba", min_games=10, limit=1)["leaders"]), 1)

    def test_nba_last_five_math_max_three_and_deterministic_order(self):
        fixtures = [
            (1, "Alpha", 10, 20),
            (2, "Beta", 30, 10),
            (3, "Charlie", 10, 15),
            (4, "Delta", 10, 30),
        ]
        for player_id, name, baseline, recent in fixtures:
            values = metric_values("nba")
            values.update({"pts": recent, "fgm": 100 + player_id})
            insert_row(self.db_path, player_id, name, "nba", 2026, 10, values=values)
            insert_logs(
                self.db_path, player_id, "nba",
                [{"PTS": baseline}] * 5 + [{"PTS": recent}] * 5,
                dated=True,
            )

        response = call("nba", category="scoring", stat="fgm")
        self.assertEqual(response["change_metric"], {
            "key": "pts", "label": "Points/Game", "format": "decimal_1",
        })
        self.assertEqual(response["comparison"], {
            "recent_label": "Last 5", "baseline_label": "Earlier season",
            "recent_games": 5, "min_baseline_games": 5,
            "status": "display_only", "eligible_leaders": 4,
            "qualified_leaders": 4,
        })
        self.assertEqual([change["name"] for change in response["changes"]], [
            "Beta", "Delta", "Alpha",
        ])
        beta, delta, alpha = response["changes"]
        self.assertEqual(
            (beta["recent_value"], beta["baseline_value"], beta["delta"], beta["direction"]),
            (10.0, 30.0, -20.0, "falling"),
        )
        self.assertEqual(delta["direction"], "rising")
        self.assertEqual(alpha["recent_games"], 5)
        self.assertEqual(alpha["baseline_games"], 5)

    def test_true_shooting_is_derived_separately_for_each_window(self):
        values = metric_values("nba")
        insert_row(self.db_path, 1, "TS Player", "nba", 2026, 10, values=values)
        baseline = {"PTS": 10, "FGA": 8, "FTA": 4}
        recent = {"PTS": 15, "FGA": 10, "FTA": 2}
        insert_logs(self.db_path, 1, "nba", [baseline] * 5 + [recent] * 5)

        response = call("nba", category="efficiency", stat="minutes")
        self.assertEqual(response["change_metric"]["key"], "ts_pct")
        self.assertEqual(response["change_metric"]["format"], "percent_1")
        change = response["changes"][0]
        baseline_ts = 100 * 50 / (2 * (40 + 0.44 * 20))
        recent_ts = 100 * 75 / (2 * (50 + 0.44 * 10))
        self.assertEqual(change["baseline_value"], round(baseline_ts, 1))
        self.assertEqual(change["recent_value"], round(recent_ts, 1))
        self.assertEqual(change["delta"], round(recent_ts - baseline_ts, 1))
        self.assertEqual(change["direction"], "rising")

    def test_nfl_aliases_work_and_missing_values_are_not_zero(self):
        for player_id, name in ((1, "Alias Player"), (2, "Missing Player")):
            insert_row(
                self.db_path, player_id, name, "nfl", 2026, 10,
                values=metric_values("nfl"),
            )
        insert_logs(
            self.db_path, 1, "nfl",
            [{"pass_yds": 100}] * 5 + [{"passing_yards": 200}] * 5,
        )
        insert_logs(
            self.db_path, 2, "nfl",
            [{"pass_yds": 50}] * 5 + [{"pass_yds": 75}] * 4 + [{"pass_td": 2}],
        )

        response = call("nfl", category="passing")
        self.assertEqual(response["comparison"]["eligible_leaders"], 2)
        self.assertEqual(response["comparison"]["qualified_leaders"], 1)
        self.assertEqual([change["name"] for change in response["changes"]], ["Alias Player"])
        self.assertEqual(response["changes"][0]["baseline_value"], 100.0)
        self.assertEqual(response["changes"][0]["recent_value"], 200.0)

    def test_nhl_category_metric_uses_required_raw_key(self):
        insert_row(
            self.db_path, 1, "NHL Player", "nhl", 2026, 10,
            values=metric_values("nhl"),
        )
        insert_logs(
            self.db_path, 1, "nhl",
            [{"powerPlayPoints": 0}] * 5 + [{"powerPlayPoints": 2}] * 5,
        )
        response = call("nhl", category="special_teams", stat="ppg")
        self.assertEqual(response["change_metric"], {
            "key": "ppp", "label": "Power-Play Points/Game", "format": "decimal_1",
        })
        self.assertEqual(response["changes"][0]["delta"], 2.0)

    def test_thresholds_and_malformed_or_non_object_logs_skip_without_failure(self):
        for player_id, name in ((1, "Malformed Baseline"), (2, "Only Nine"), (3, "Bad Recent")):
            insert_row(
                self.db_path, player_id, name, "nba", 2026, 10,
                values=metric_values("nba"),
            )
        insert_logs(
            self.db_path, 1, "nba",
            ["{bad json"] + [{"PTS": 10}] * 5 + [{"PTS": 20}] * 5,
        )
        insert_logs(self.db_path, 2, "nba", [{"PTS": 10}] * 9)
        insert_logs(
            self.db_path, 3, "nba",
            [{"PTS": 10}] * 5 + [{"PTS": 20}] * 4 + [[20]],
        )

        response = call("nba", category="scoring")
        self.assertEqual(response["comparison"]["eligible_leaders"], 3)
        self.assertEqual(response["comparison"]["qualified_leaders"], 1)
        self.assertEqual(response["changes"][0]["name"], "Malformed Baseline")
        self.assertEqual(response["changes"][0]["baseline_games"], 5)

    def test_missing_game_log_table_fails_closed(self):
        old_db = os.path.join(self.tmp.name, "old.db")
        create_schema(old_db, with_logs=False)
        insert_row(
            old_db, 1, "Old DB Player", "nba", 2026, 10,
            values=metric_values("nba"),
        )
        players._db = lambda: connect(old_db)
        response = call("nba", category="scoring")
        self.assertEqual(response["change_metric"]["key"], "pts")
        self.assertEqual(response["comparison"]["eligible_leaders"], 1)
        self.assertEqual(response["comparison"]["qualified_leaders"], 0)
        self.assertEqual(response["changes"], [])

    def test_unrelated_game_log_schema_error_is_not_swallowed(self):
        bad_db = os.path.join(self.tmp.name, "bad-log-schema.db")
        create_schema(bad_db, with_logs=False)
        with sqlite3.connect(bad_db) as con:
            con.execute("CREATE TABLE player_game_logs(wrong_column TEXT)")
        insert_row(
            bad_db, 1, "Schema Error Player", "nba", 2026, 10,
            values=metric_values("nba"),
        )
        players._db = lambda: connect(bad_db)
        with self.assertRaises(sqlite3.OperationalError):
            call("nba", category="scoring")

    def test_mlb_never_queries_game_logs_and_always_has_no_comparison(self):
        insert_row(
            self.db_path, 1, "Batter", "mlb", 2026, 50, "batting",
            metric_values("mlb_batting"),
        )
        log_reads = []

        def monitored_connection():
            con = connect(self.db_path)
            def authorizer(action, arg1, arg2, db_name, trigger):
                if action == sqlite3.SQLITE_READ and arg1 == "player_game_logs":
                    log_reads.append((arg1, arg2))
                return sqlite3.SQLITE_OK
            con.set_authorizer(authorizer)
            return con

        players._db = monitored_connection
        response = call("mlb", type="batting")
        self.assertIsNone(response["change_metric"])
        self.assertIsNone(response["comparison"])
        self.assertEqual(response["changes"], [])
        self.assertEqual(log_reads, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
