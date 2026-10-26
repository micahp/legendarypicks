"""NFL stakes: a line is stated only when the standings make it certain.

`lo` is the points a team already has and `hi` the most it can still reach. Each test pins one
rule, and the cases beside it check that the rule stays silent when the standings leave it open.
"""
import sqlite3
import warnings

import _core
import stakes


def _teams(spec):
    """spec: {abbrev: (conference, division)} -> nfl_teams-shaped rows."""
    return {t: {"conference": c, "division": d, "team_name": f"{t} Team"}
            for t, (c, d) in spec.items()}


AFC = "AFC"
EAST, WEST = "AFC East", "AFC West"
LEAGUE = _teams({
    "A": (AFC, EAST), "B": (AFC, EAST), "C": (AFC, EAST), "D": (AFC, EAST),
    "E": (AFC, WEST), "F": (AFC, WEST), "G": (AFC, WEST), "H": (AFC, WEST),
})


def test_clinched_division_is_certain_only_when_every_rival_is_out_of_reach():
    lo = {"A": 10, "B": 6, "C": 6, "D": 6, "E": 0, "F": 0, "G": 0, "H": 0}
    hi = {"A": 12, "B": 9, "C": 9, "D": 9, "E": 0, "F": 0, "G": 0, "H": 0}
    assert stakes._nfl_stake("A", LEAGUE, lo, hi) == "A Team have clinched the AFC East and a playoff spot."
    # B can still reach 9, which ties A's 9 points minimum. A tie can be broken either way.
    hi["B"] = 10
    assert stakes._nfl_stake("A", LEAGUE, lo, hi) is None


def test_open_division_race_states_nothing():
    lo = {t: 5 for t in LEAGUE}
    hi = {t: 9 for t in LEAGUE}
    assert stakes._nfl_stake("A", LEAGUE, lo, hi) is None


def test_eliminated_needs_three_certain_non_winners_ahead():
    # D cannot win the East: A is certain to finish ahead of it. E, F and G are each certain to
    # finish ahead of D and certain not to win the West (H is certain to beat each of them).
    lo = {"A": 8, "B": 0, "C": 0, "D": 5, "E": 6, "F": 6, "G": 6, "H": 9}
    hi = {"A": 8, "B": 3, "C": 3, "D": 5, "E": 7, "F": 7, "G": 7, "H": 9}
    assert stakes._nfl_stake("D", LEAGUE, lo, hi) == "D Team are eliminated from the playoffs."
    # With only two of them certain, D still has a path as a wild card.
    hi["F"] = 10
    assert stakes._nfl_stake("D", LEAGUE, lo, hi) == "D Team can no longer win the AFC East."


def test_tie_is_half_a_point_and_unplayed_games_count_toward_reach():
    games = [
        {"home_team": "A", "away_team": "B", "home_score": 20, "away_score": 20},
        {"home_team": "C", "away_team": "D", "home_score": 24, "away_score": 17},
        {"home_team": "A", "away_team": "C", "home_score": None, "away_score": None},
    ]
    lo, hi = stakes._nfl_bounds(games, LEAGUE)
    assert lo["A"] == 0.5 and hi["A"] == 1.5
    assert lo["B"] == 0.5 and hi["B"] == 0.5
    assert lo["C"] == 1.0 and hi["C"] == 2.0
    assert lo["D"] == 0.0 and hi["D"] == 0.0


def _patch_db(monkeypatch, tmp_path, games, teams):
    path = tmp_path / "picks.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE nfl_schedule (season INTEGER, game_type TEXT, home_team TEXT, "
                "away_team TEXT, home_score INTEGER, away_score INTEGER, gameday TEXT)")
    con.execute("CREATE TABLE nfl_teams (season INTEGER, team TEXT, conference TEXT, "
                "division TEXT, team_name TEXT)")
    con.executemany("INSERT INTO nfl_schedule VALUES (2026, 'REG', ?, ?, ?, ?, ?)",
                    [(g["home_team"], g["away_team"], g["home_score"], g["away_score"],
                      g["gameday"]) for g in games])
    con.executemany("INSERT INTO nfl_teams VALUES (2026, ?, ?, ?, ?)",
                    [(t, r["conference"], r["division"], r["team_name"])
                     for t, r in teams.items()])
    con.commit()
    con.close()

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(_core, "_db", connect)


REAL = _teams({"BUF": (AFC, EAST), "MIA": (AFC, EAST), "NYJ": (AFC, EAST), "NE": (AFC, EAST)})


def test_past_game_without_a_score_means_the_schedule_is_behind(monkeypatch, tmp_path):
    games = [
        {"home_team": "BUF", "away_team": "MIA", "home_score": 20, "away_score": 17, "gameday": "2026-10-04"},
        {"home_team": "NYJ", "away_team": "NE", "home_score": None, "away_score": None, "gameday": "2026-10-11"},
    ]
    _patch_db(monkeypatch, tmp_path, games, REAL)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        assert stakes.for_matchup("nfl", "BUF", "MIA", 2026) == []
    assert any("no NFL stakes" in str(w.message) for w in seen)


def test_future_unplayed_games_are_read_as_remaining(monkeypatch, tmp_path):
    games = [
        {"home_team": "BUF", "away_team": "MIA", "home_score": 27, "away_score": 17, "gameday": "2026-10-04"},
        {"home_team": "NYJ", "away_team": "BUF", "home_score": None, "away_score": None, "gameday": "2099-01-03"},
        {"home_team": "MIA", "away_team": "NE", "home_score": None, "away_score": None, "gameday": "2099-01-04"},
        {"home_team": "NE", "away_team": "NYJ", "home_score": None, "away_score": None, "gameday": "2099-01-05"},
    ]
    _patch_db(monkeypatch, tmp_path, games, REAL)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        # Three games are still open, so the division is open and nothing is certain.
        assert stakes.for_matchup("nfl", "BUF", "MIA", 2026) == []
    assert not any("no NFL stakes" in str(w.message) for w in seen)
    lo, hi = stakes._nfl_bounds(games, REAL)
    assert lo["BUF"] == 1.0 and hi["BUF"] == 2.0


def test_no_season_means_no_nfl_lines_and_no_database_read(monkeypatch):
    def fail():
        raise AssertionError("a postseason or unknown-season NFL game must not read the DB")
    monkeypatch.setattr(_core, "_db", fail)
    assert stakes.for_matchup("nfl", "A", "B", None) == []


def test_unknown_team_code_is_warned_not_raised(monkeypatch, tmp_path):
    _patch_db(monkeypatch, tmp_path, [], REAL)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        assert stakes.for_matchup("nfl", "ZZZ", "A", 2026) == []
    assert any("nfl lookup failed" in str(w.message) for w in seen)
