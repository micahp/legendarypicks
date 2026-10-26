"""Tests for nba_standings_store: standings derived from scored regular-season games, read-only.

Run: python3 -m pytest backend/test_nba_standings_store.py
"""
import sqlite3

import pytest

import nba_standings_store as store

FOUR = ["BOS", "NY", "MIA", "CHI"]


def _db(tmp_path, games):
    path = tmp_path / "nba.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE nba_schedule(game_id TEXT PRIMARY KEY, season INT, season_type TEXT, game_date TEXT,"
                " home_team TEXT, away_team TEXT, home_score INT, away_score INT, status INT, sub_label TEXT,"
                " ingested_at TEXT)")
    store.seed(con, 2027)
    for n, game in enumerate(games, start=1):
        day, home, away, hs, as_ = game[:5]
        sub_label = game[5] if len(game) > 5 else None
        con.execute("INSERT INTO nba_schedule(game_id, season, season_type, game_date, home_team, away_team,"
                    " home_score, away_score, status, sub_label, ingested_at)"
                    " VALUES(?, 2027, 'REG', ?, ?, ?, ?, ?, ?, ?, '2026-10-26T12:00:00+00:00')",
                    (f"00226{n:05d}", day, home, away, hs, as_, 3 if hs is not None else 1, sub_label))
    con.commit()
    return con


def test_wins_and_losses_balance_and_rows_carry_story_fields(tmp_path):
    con = _db(tmp_path, [
        ("2026-10-21", "BOS", "NY", 110, 102),
        ("2026-10-23", "MIA", "BOS", 99, 104),
        ("2026-10-25", "CHI", "NY", 120, 118),
    ])
    st = store.read_standings(con, season=2027)
    rows = {r["abbrev"]: r for r in st["teams"]}
    assert (rows["BOS"]["wins"], rows["BOS"]["losses"]) == (2, 0)
    assert rows["BOS"]["win_pct"] == 1.0
    assert rows["BOS"]["streak"] == "W2"
    assert rows["BOS"]["last10"] == "2-0"
    assert rows["BOS"]["differential"] == pytest.approx((110 - 102 + 104 - 99) / 2, abs=0.01)
    assert (rows["NY"]["wins"], rows["NY"]["losses"]) == (0, 2)
    assert rows["NY"]["streak"] == "L2"
    assert rows["NY"]["name"] == "New York Knicks"
    assert st["teams"][0]["abbrev"] == "BOS"  # sorted by win percentage
    assert set(rows["BOS"]) == {"abbrev", "name", "wins", "losses", "win_pct", "differential", "streak",
                                "last10", "games_played"}


def test_every_club_is_listed_even_before_it_plays(tmp_path):
    con = _db(tmp_path, [("2026-10-21", "BOS", "NY", 110, 102)])
    st = store.read_standings(con, season=2027)
    assert len(st["teams"]) == store.EXPECTED_CLUBS
    idle = next(r for r in st["teams"] if r["abbrev"] == "LAL")
    assert idle["games_played"] == 0 and idle["win_pct"] is None


def test_as_of_counts_only_games_played_by_that_day(tmp_path):
    con = _db(tmp_path, [
        ("2026-10-21", "BOS", "NY", 110, 102),
        ("2026-10-25", "MIA", "BOS", 99, 104),
    ])
    rows = {r["abbrev"]: r for r in store.read_standings(con, season=2027, as_of="2026-10-22")["teams"]}
    assert (rows["BOS"]["wins"], rows["BOS"]["losses"]) == (1, 0)
    assert rows["MIA"]["games_played"] == 0


def test_a_cup_knockout_game_is_not_a_standings_game(tmp_path):
    con = _db(tmp_path, [
        ("2026-10-21", "BOS", "NY", 110, 102),
        ("2026-12-04", "BOS", "MIA", 120, 100, "Quarterfinal"),
    ])
    rows = {r["abbrev"]: r for r in store.read_standings(con, season=2027)["teams"]}
    assert rows["BOS"]["games_played"] == 1 and rows["MIA"]["games_played"] == 0


def test_the_club_table_is_seeded_and_re_seeding_changes_nothing(tmp_path):
    con = sqlite3.connect(tmp_path / "teams.db")
    store.seed(con, 2026)
    store.seed(con, 2027)
    store.seed(con, 2027)
    assert store.load_teams(con, 2027).keys() == store.TEAMS.keys()
    assert con.execute("SELECT COUNT(*) FROM nba_teams").fetchone()[0] == 60
    assert store.load_teams(con, 2026)["BOS"]["conference"] == "East"


def test_a_season_with_no_seeded_clubs_is_refused(tmp_path):
    con = _db(tmp_path, [("2026-10-21", "BOS", "NY", 110, 102)])
    con.execute("DELETE FROM nba_teams WHERE season=2027")
    with pytest.raises(store.NBAStandingsError):
        store.read_standings(con, season=2027)


def test_a_season_with_no_scored_game_has_no_standings(tmp_path):
    con = _db(tmp_path, [("2026-10-21", "BOS", "NY", None, None)])
    assert store.read_standings(con, season=2027) is None
    assert store.read_standings(con, season=2026) is None


def test_a_club_count_that_is_not_thirty_is_refused(tmp_path):
    con = _db(tmp_path, [("2026-10-21", "BOS", "NY", 110, 102)])
    with pytest.raises(store.NBAStandingsError):
        store.read_standings(con, season=2027, expected_clubs=31)


def test_a_game_between_unknown_clubs_is_refused(tmp_path):
    con = _db(tmp_path, [("2026-10-21", "BOS", "ZZZ", 110, 102)])
    with pytest.raises(store.NBAStandingsError):
        store.read_standings(con, season=2027)


def test_the_club_table_matches_the_espn_display_names():
    import json
    from pathlib import Path
    names = json.loads((Path(__file__).resolve().parent.parent / "docs" / "espn-team-codes-2026-07-27.json")
                       .read_text())["nba"]
    assert {code: row["name"] for code, row in store.TEAMS.items()} == names


def test_the_alignment_is_six_divisions_of_five_in_two_conferences():
    from collections import Counter
    assert Counter(r["conference"] for r in store.TEAMS.values()) == {"East": 15, "West": 15}
    assert sorted(Counter(r["division"] for r in store.TEAMS.values()).values()) == [5] * 6


def test_the_facts_marker_is_the_newest_regular_season_final_and_ignores_knockouts(tmp_path):
    import core_stories
    con = sqlite3.connect(tmp_path / "story.db")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE nba_schedule(game_id TEXT, season INT, season_type TEXT, game_date TEXT,"
                " home_team TEXT, away_team TEXT, home_score INT, away_score INT, status INT, sub_label TEXT,"
                " ingested_at TEXT)")
    assert core_stories._nba_facts_as_of(con) is None
    con.execute("INSERT INTO nba_schedule VALUES('0022600001', 2027, 'REG', '2026-10-24', 'BOS', 'NY', 110, 102, 3,"
                " NULL, '2026-10-25T02:00:00+00:00')")
    con.execute("INSERT INTO nba_schedule VALUES('0022601201', 2027, 'REG', '2026-10-30', 'BOS', 'NY', 120, 100, 3,"
                " 'Quarterfinal', '2026-10-31T02:00:00+00:00')")
    assert core_stories._nba_facts_as_of(con) == "2026-10-25T02:00:00+00:00"


def test_a_cached_nba_story_with_no_new_final_makes_no_espn_request(tmp_path, monkeypatch):
    import sqlite3 as _sqlite3
    import core_stories
    import _core
    import espn_client as espn
    import stakes

    path = tmp_path / "story.db"
    con = _sqlite3.connect(path)
    con.row_factory = _sqlite3.Row
    con.execute("CREATE TABLE game_story(league TEXT, game_id TEXT, story TEXT, generated_at TEXT, has_form INTEGER,"
                " has_stakes INTEGER, form_suppressed INTEGER, facts_as_of TEXT, PRIMARY KEY(league, game_id))")
    con.execute("INSERT INTO game_story VALUES('nba', '401', 'CACHED', '2026-10-25 05:00:00', 1, 0, 0,"
                " '2026-10-24T23:00:00+00:00')")
    con.execute("CREATE TABLE nba_schedule(game_id TEXT, season INT, season_type TEXT, game_date TEXT,"
                " home_team TEXT, away_team TEXT, home_score INT, away_score INT, status INT, sub_label TEXT,"
                " ingested_at TEXT)")
    con.execute("INSERT INTO nba_schedule VALUES('0022600001', 2027, 'REG', '2026-10-24', 'BOS', 'NY', 110, 102, 3,"
                " NULL, '2026-10-24T23:00:00+00:00')")
    con.commit()
    con.close()

    def _open():
        c = _sqlite3.connect(path)
        c.row_factory = _sqlite3.Row
        return c

    monkeypatch.setattr(core_stories, "_db", _open)
    monkeypatch.setattr(_core, "_db", _open)
    monkeypatch.setattr(stakes, "SUPPORTED", {"wc", "mlb", "nfl", "nba"})

    def no_espn(*args, **kwargs):
        raise AssertionError("ESPN was called for a cached NBA story with no new final")

    monkeypatch.setattr(espn, "game_result", no_espn)
    monkeypatch.setattr(espn, "summary", no_espn)
    monkeypatch.setattr(espn, "team_strength_standings", no_espn)

    result = core_stories.generate_game_story("nba", "401")
    assert result == {"league": "nba", "game_id": "401", "story": "CACHED", "cached": True}


def test_a_cached_nba_story_written_before_a_new_final_goes_to_the_full_path(tmp_path, monkeypatch):
    import sqlite3 as _sqlite3
    import core_stories
    import _core
    import espn_client as espn
    import stakes

    path = tmp_path / "story.db"
    con = _sqlite3.connect(path)
    con.row_factory = _sqlite3.Row
    con.execute("CREATE TABLE game_story(league TEXT, game_id TEXT, story TEXT, generated_at TEXT, has_form INTEGER,"
                " has_stakes INTEGER, form_suppressed INTEGER, facts_as_of TEXT, PRIMARY KEY(league, game_id))")
    con.execute("INSERT INTO game_story VALUES('nba', '401', 'CACHED', '2026-10-25 05:00:00', 1, 0, 0,"
                " '2026-10-20T23:00:00+00:00')")
    con.execute("CREATE TABLE nba_schedule(game_id TEXT, season INT, season_type TEXT, game_date TEXT,"
                " home_team TEXT, away_team TEXT, home_score INT, away_score INT, status INT, sub_label TEXT,"
                " ingested_at TEXT)")
    con.execute("INSERT INTO nba_schedule VALUES('0022600001', 2027, 'REG', '2026-10-24', 'BOS', 'NY', 110, 102, 3,"
                " NULL, '2026-10-24T23:00:00+00:00')")
    con.commit()
    con.close()

    def _open():
        c = _sqlite3.connect(path)
        c.row_factory = _sqlite3.Row
        return c

    monkeypatch.setattr(core_stories, "_db", _open)
    monkeypatch.setattr(_core, "_db", _open)
    monkeypatch.setattr(stakes, "SUPPORTED", {"wc", "mlb", "nfl", "nba"})
    asked = []

    def record(*args, **kwargs):
        asked.append(args)
        raise RuntimeError("stop after the ESPN request")

    monkeypatch.setattr(espn, "game_result", record)
    core_stories.generate_game_story("nba", "401")
    assert asked, "a cached NBA story written before the newest final must take the full path"
