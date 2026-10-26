"""Tests for nfl_standings_store: standings derived from scored regular-season games, read-only.

Run: python3 -m pytest backend/test_nfl_standings_store.py
"""
import sqlite3

import pytest

import nfl_standings_store as store


def _db(tmp_path, clubs, games):
    path = tmp_path / "nfl.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE nfl_teams(season INT, team TEXT, conference TEXT, division TEXT, team_name TEXT)")
    con.execute("CREATE TABLE nfl_schedule(season INT, game_type TEXT, week INT, gameday TEXT, home_team TEXT,"
                " away_team TEXT, home_score INT, away_score INT)")
    for code in clubs:
        con.execute("INSERT INTO nfl_teams VALUES(2026, ?, 'AFC', 'AFC X', ?)", (code, f"{code} Name"))
    for week, day, home, away, hs, as_ in games:
        con.execute("INSERT INTO nfl_schedule VALUES(2026, 'REG', ?, ?, ?, ?, ?, ?)", (week, day, home, away, hs, as_))
    con.commit()
    return con


CLUBS = ["AAA", "BBB", "CCC", "DDD"]


def test_wins_and_losses_balance_and_rows_carry_story_fields(tmp_path):
    con = _db(tmp_path, CLUBS, [
        (1, "2026-09-13", "AAA", "BBB", 24, 17),
        (2, "2026-09-20", "CCC", "AAA", 10, 31),
        (3, "2026-09-27", "BBB", "DDD", 20, 20),
    ])
    st = store.read_standings(con, season=2026, expected_clubs=4)
    rows = {r["abbrev"]: r for r in st["teams"]}
    assert rows["AAA"]["record"] == "2-0"
    assert rows["AAA"]["streak"] == "W2"
    assert rows["AAA"]["last10"] == "2-0"
    assert rows["AAA"]["differential"] == pytest.approx((24 - 17 + 31 - 10) / 2)
    assert rows["BBB"]["record"] == "0-1-1"
    assert rows["BBB"]["win_pct"] == pytest.approx(0.25)
    assert rows["BBB"]["streak"] == "T1"
    assert st["teams"][0]["abbrev"] == "AAA"  # sorted by win percentage


def test_as_of_counts_only_games_played_by_that_day(tmp_path):
    con = _db(tmp_path, CLUBS, [
        (1, "2026-09-13", "AAA", "BBB", 24, 17),
        (2, "2026-09-20", "CCC", "AAA", 10, 31),
    ])
    rows = {r["abbrev"]: r for r in store.read_standings(con, season=2026, as_of="2026-09-14", expected_clubs=4)["teams"]}
    assert rows["AAA"]["record"] == "1-0"
    assert rows["CCC"]["games_played"] == 0


def test_a_season_with_no_scored_game_has_no_standings(tmp_path):
    con = _db(tmp_path, CLUBS, [(1, "2026-09-13", "AAA", "BBB", None, None)])
    assert store.read_standings(con, season=2026, expected_clubs=4) is None
    assert store.read_standings(con, season=2027) is None


def test_a_club_list_that_is_not_32_is_refused(tmp_path):
    con = _db(tmp_path, CLUBS, [(1, "2026-09-13", "AAA", "BBB", 24, 17)])
    with pytest.raises(store.NFLStandingsError):
        store.read_standings(con, season=2026)


def test_a_game_between_unknown_clubs_is_refused(tmp_path):
    con = _db(tmp_path, CLUBS, [(1, "2026-09-13", "AAA", "ZZZ", 24, 17)])
    with pytest.raises(store.NFLStandingsError):
        store.read_standings(con, season=2026, expected_clubs=4)



def test_a_cached_nfl_story_with_no_new_stakes_makes_no_espn_request(tmp_path, monkeypatch):
    import sqlite3 as _sqlite3
    import core_stories
    import _core
    import espn_client as espn

    path = tmp_path / "story.db"
    con = _sqlite3.connect(path)
    con.row_factory = _sqlite3.Row
    con.execute("CREATE TABLE game_story(league TEXT, game_id TEXT, story TEXT, generated_at TEXT, has_form INTEGER,"
                " has_stakes INTEGER, form_suppressed INTEGER, PRIMARY KEY(league, game_id))")
    con.execute("INSERT INTO game_story VALUES('nfl', '401', 'CACHED', '2026-10-25 05:00:00', 1, 0, 0)")
    con.execute("CREATE TABLE nfl_teams(season INT, team TEXT, conference TEXT, division TEXT, team_name TEXT)")
    con.execute("CREATE TABLE nfl_schedule(season INT, game_type TEXT, week INT, gameday TEXT, home_team TEXT,"
                " away_team TEXT, home_score INT, away_score INT, espn TEXT)")
    for code in CLUBS:
        con.execute("INSERT INTO nfl_teams VALUES(2026, ?, 'AFC', 'AFC X', ?)", (code, code))
    con.execute("INSERT INTO nfl_schedule VALUES(2026, 'REG', 7, '2026-10-25', 'AAA', 'BBB', NULL, NULL, '401')")
    con.commit()
    con.close()

    def _open():
        c = _sqlite3.connect(path)
        c.row_factory = _sqlite3.Row
        return c

    monkeypatch.setattr(core_stories, "_db", _open)
    monkeypatch.setattr(_core, "_db", _open)

    def no_espn(*args, **kwargs):
        raise AssertionError("ESPN was called for a cached NFL story with no new stakes")

    monkeypatch.setattr(espn, "game_result", no_espn)
    monkeypatch.setattr(espn, "summary", no_espn)
    monkeypatch.setattr(espn, "team_strength_standings", no_espn)

    result = core_stories.generate_game_story("nfl", "401")
    assert result == {"league": "nfl", "game_id": "401", "story": "CACHED", "cached": True}
