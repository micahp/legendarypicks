import sqlite3

from sport_navigation import (
    league_directory_navigation,
    prop_navigation,
    sport_for_league,
)
from routers.props import _league_sql


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT)")
    con.execute("CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER)")
    con.execute("CREATE TABLE team_stats_coverage(league TEXT, season INT, status TEXT)")
    return con


def test_sport_comes_from_the_complete_espn_path_registry():
    assert sport_for_league("mls") == "soccer"
    assert sport_for_league("lcup") == "soccer"
    assert sport_for_league("atp") == "tennis"
    assert sport_for_league("nfl") == "football"
    assert sport_for_league("unknown") is None


def test_props_navigation_is_stable_history_not_today_only():
    con = _db()
    con.executemany(
        "INSERT INTO prop_games VALUES(?, ?)",
        [(1, "atp"), (2, "wta"), (3, "mls"), (4, "wc"), (5, "unknown")],
    )
    con.executemany("INSERT INTO props VALUES(?, ?)", [(10, 1), (11, 2), (12, 3), (13, 4), (14, 5)])
    assert prop_navigation(con) == [
        {"league": "atp", "sport": "tennis"},
        {"league": "mls", "sport": "soccer"},
        {"league": "wta", "sport": "tennis"},
    ]


def test_directory_uses_coverage_gate_and_keeps_local_esports():
    con = _db()
    con.executemany(
        "INSERT INTO team_stats_coverage VALUES(?, ?, ?)",
        [("mlb", 2026, "in_progress"), ("mls", 2026, "partial")],
    )
    assert league_directory_navigation(con) == [
        {"league": "mlb", "sport": "baseball"},
        {"league": "esports", "sport": "esports"},
        {"league": "ufc", "sport": "mma"},
    ]


def test_multi_competition_filter_is_bound_and_deduplicated():
    sql, params = _league_sql("pg.league", None, "wta,atp,wta")
    assert sql == " AND LOWER(pg.league) IN (?,?)"
    assert params == ["atp", "wta"]
    sql, params = _league_sql("pg.league", "NFL", "atp,wta")
    assert sql == " AND LOWER(pg.league) = ?"
    assert params == ["nfl"]
