import datetime as dt
import json
import sqlite3

import league_readiness


def database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE team_stats_coverage(
          league TEXT, season INTEGER, status TEXT, expected_teams INTEGER,
          fetched_teams INTEGER, expected_games INTEGER, fetched_games INTEGER,
          failure_count INTEGER, season_start TEXT, season_end TEXT,
          completed_at TEXT, checked_through TEXT
        );
        CREATE TABLE league_activity(
          league TEXT PRIMARY KEY, calendar_type TEXT, season_start TEXT,
          season_end TEXT, windows TEXT, fetched_at TEXT, checked_at TEXT
        );
        CREATE TABLE scoreboard_snapshots(
          league TEXT, game_date TEXT, payload TEXT
        );
        CREATE TABLE scoreboard_refresh(
          league TEXT, game_date TEXT, fetched_at TEXT, game_count INTEGER
        );
        CREATE TABLE team_game_results(league TEXT, season INTEGER, game_id TEXT);
        CREATE TABLE player_stats(league TEXT, season INTEGER);
        CREATE TABLE player_game_logs(league TEXT, season INTEGER);
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, date TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER);
        CREATE TABLE prop_results(prop_id INTEGER, actual_value REAL);
        """
    )
    con.executemany(
        "INSERT INTO team_stats_coverage"
        " (league,season,status,season_start,season_end,checked_through)"
        " VALUES (?,?,?,?,?,?)",
        [
            ("nfl", 2025, "complete", "2025-09-05", "2026-01-05", None),
            ("nhl", 2026, "complete", "2025-10-07", "2026-04-18", None),
            ("nba", 2026, "complete", "2025-10-21", "2026-04-13", None),
            ("mlb", 2026, "in_progress", "2026-03-25", "2026-09-29", "2026-08-02"),
        ],
    )
    con.execute(
        "INSERT INTO league_activity VALUES (?,?,?,?,?,?,?)",
        ("mlb", "day", "2026-02-19", "2026-11-12", "[]",
         "2026-09-22T17:00:00+00:00", "2026-09-22T17:00:00+00:00"),
    )
    for league, slug in (("nfl", "regular-season"), ("nhl", "preseason"),
                         ("mlb", "regular-season")):
        con.execute(
            "INSERT INTO scoreboard_snapshots VALUES (?,?,?)",
            (league, "2026-09-22", json.dumps({"season_slug": slug})),
        )
        con.execute(
            "INSERT INTO scoreboard_refresh VALUES (?,?,?,?)",
            (league, "2026-09-22", "2026-09-22T17:00:00+00:00", 1),
        )
    con.execute("INSERT INTO team_game_results VALUES ('nfl',2026,'game-1')")
    con.execute("INSERT INTO prop_games VALUES (1,'nfl','2026-09-22')")
    con.execute("INSERT INTO props VALUES (1,1)")
    con.execute("INSERT INTO prop_results VALUES (1,250.0)")
    return con


def by_league(payload, league):
    return next(row for row in payload["leagues"] if row["league"] == league)


def test_old_complete_rows_are_stale_once_the_new_season_is_active():
    payload = league_readiness.build_readiness(database(), dt.date(2026, 9, 22))

    nfl = by_league(payload, "nfl")
    assert nfl["expected_season"] == 2026
    assert nfl["phase"] == "regular_season"
    assert nfl["status"] == "degraded"
    assert nfl["checks"]["coverage_manifest"]["status"] == "stale"
    assert nfl["checks"]["coverage_manifest"]["season"] == 2025
    assert nfl["checks"]["schedule"] == {"status": "available", "count": 1}

    nhl = by_league(payload, "nhl")
    assert nhl["expected_season"] == 2027
    assert nhl["phase"] == "preseason"
    assert nhl["status"] == "degraded"
    assert nhl["checks"]["coverage_manifest"]["season"] == 2026
    assert nhl["checks"]["player_stats"] == {"status": "pending", "count": 0}


def test_nba_warns_before_preseason_then_flips_phase_on_opening_day():
    con = database()
    before = by_league(
        league_readiness.build_readiness(con, dt.date(2026, 9, 22)), "nba"
    )
    assert before["phase"] == "upcoming"
    assert before["expected_season"] == 2027
    assert before["status"] == "attention"
    payload = league_readiness.build_readiness(con, dt.date(2026, 9, 22))
    warning = next(item for item in payload["warnings"] if item["league"] == "nba")
    assert warning["code"] == "season_starting"
    assert warning["days_until_start"] == 11

    opening = by_league(
        league_readiness.build_readiness(con, dt.date(2026, 10, 3)), "nba"
    )
    assert opening["phase"] == "preseason"
    assert opening["expected_season"] == 2027
    assert opening["status"] == "degraded"
    assert opening["checks"]["coverage_manifest"]["status"] == "stale"


def test_in_progress_manifest_expires_when_checked_through_stops_advancing():
    mlb = by_league(
        league_readiness.build_readiness(database(), dt.date(2026, 9, 22)), "mlb"
    )
    assert mlb["checks"]["coverage_manifest"]["status"] == "stale"
    assert "2026-08-02" in mlb["checks"]["coverage_manifest"]["reason"]


def test_contract_names_every_scoreboard_competition():
    payload = league_readiness.build_readiness(database(), dt.date(2026, 9, 22))
    assert {row["league"] for row in payload["leagues"]} == set(league_readiness.LEAGUES)
    assert payload["contract"] == "league-readiness-v1"


def test_a_fetched_empty_scoreboard_is_available_not_missing():
    con = database()
    con.execute(
        "INSERT INTO league_activity VALUES (?,?,?,?,?,?,?)",
        ("atp", "day", "2026-01-01", "2027-01-01", "[]",
         "2026-09-22T17:00:00+00:00", "2026-09-22T17:00:00+00:00"),
    )
    con.execute(
        "INSERT INTO scoreboard_refresh VALUES (?,?,?,?)",
        ("atp", "2026-09-22", "2026-09-22T17:00:00+00:00", 0),
    )
    atp = by_league(
        league_readiness.build_readiness(con, dt.date(2026, 9, 22)), "atp"
    )
    assert atp["status"] == "ready"
    assert atp["checks"]["scoreboard"]["status"] == "available"
    assert atp["checks"]["scoreboard"]["count"] == 0
