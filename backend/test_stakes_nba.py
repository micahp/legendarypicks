"""NBA stakes: a line is stated only when the standings make it certain.

`lo` is the wins a club already has, `hi` the most it can still reach. The rule is an elimination: a club that cannot win
its division and has ten conference clubs certain to finish ahead of it is out of the playoffs and the play-in.
"""
import sqlite3
import warnings

import pytest

import _core
import nba_standings_store as store
import stakes

TEAMS = store.TEAMS
EAST_NOT_BOS = ["ATL", "CHA", "CHI", "CLE", "DET", "IND", "MIL", "MIA", "ORL", "WSH", "TOR"]


def _open(lo_default=0, hi_default=82):
    lo = {t: lo_default for t in TEAMS}
    hi = {t: hi_default for t in TEAMS}
    return lo, hi


def test_nba_is_supported_and_for_matchup_reads_the_nba_lines(monkeypatch):
    assert "nba" in stakes.SUPPORTED
    seen = []
    monkeypatch.setattr(stakes, "_nba", lambda a, b, season: seen.append((a, b, season)) or ["line"])
    assert stakes.for_matchup("nba", "BOS", "NY", 2027) == ["line"]
    assert seen == [("BOS", "NY", 2027)]


def test_ten_conference_clubs_certain_ahead_and_no_division_title_is_elimination():
    lo, hi = _open()
    hi["BOS"] = 30
    lo["PHI"] = 40  # a division rival certain to finish ahead of BOS: BOS cannot win the Atlantic
    for team in EAST_NOT_BOS[:8]:
        lo[team] = 40  # PHI plus eight more: nine ahead, not ten
    assert stakes._nba_stake("BOS", TEAMS, lo, hi) is None
    lo["WSH"] = 40  # the ninth other club: PHI plus nine is ten
    assert stakes._nba_stake("BOS", TEAMS, lo, hi) == "Boston Celtics are eliminated from the playoffs and the play-in."


def test_a_club_that_can_still_win_its_division_is_never_called_out():
    lo, hi = _open()
    hi["BOS"] = 30
    for team in EAST_NOT_BOS:
        if TEAMS[team]["division"] != "Atlantic":
            lo[team] = 40  # ten clubs from other divisions ahead, but nobody in the Atlantic is certain to beat BOS
    assert sum(1 for t in EAST_NOT_BOS if lo[t] > hi["BOS"]) >= 10
    assert stakes._nba_stake("BOS", TEAMS, lo, hi) is None


def test_bounds_count_wins_so_far_and_unplayed_games():
    games = [
        {"home_team": "BOS", "away_team": "NY", "home_score": 110, "away_score": 102},
        {"home_team": "MIA", "away_team": "BOS", "home_score": None, "away_score": None},
    ]
    lo, hi = stakes._nba_bounds(games, TEAMS)
    assert (lo["BOS"], hi["BOS"]) == (1, 2)
    assert (lo["NY"], hi["NY"]) == (0, 0)
    assert (lo["MIA"], hi["MIA"]) == (0, 1)


def _db(monkeypatch, tmp_path, games):
    path = tmp_path / "picks.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE nba_schedule(game_id TEXT, season INT, season_type TEXT, game_date TEXT,"
                " home_team TEXT, away_team TEXT, home_score INT, away_score INT, sub_label TEXT)")
    store.seed(con, 2027)
    for n, (day, home, away, hs, as_) in enumerate(games, start=1):
        con.execute("INSERT INTO nba_schedule VALUES(?, 2027, 'REG', ?, ?, ?, ?, ?, NULL)",
                    (f"00226{n:05d}", day, home, away, hs, as_))
    # Cup knockout slots: numbered in the regular-season block, no clubs yet, and never a standings game
    con.execute("INSERT INTO nba_schedule VALUES('0022601201', 2027, 'REG', '2026-10-22', NULL, NULL, NULL, NULL,"
                " 'Quarterfinal')")
    con.commit()
    con.close()

    def connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(_core, "_db", connect)


def test_a_past_game_without_a_score_means_the_schedule_is_behind(monkeypatch, tmp_path):
    _db(monkeypatch, tmp_path, [
        ("2026-10-21", "BOS", "NY", 110, 102),
        ("2026-10-22", "MIA", "BOS", None, None),
    ])
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        assert stakes._nba("BOS", "NY", 2027) == []
    assert any("no NBA stakes" in str(w.message) for w in seen)


def test_no_season_means_no_nba_lines_and_no_database_read(monkeypatch):
    def fail():
        raise AssertionError("an NBA game with no season must not read the DB")
    monkeypatch.setattr(_core, "_db", fail)
    assert stakes._nba("BOS", "NY", None) == []


def test_an_unknown_club_code_is_refused_by_the_club_lookup(monkeypatch, tmp_path):
    import team_codes
    _db(monkeypatch, tmp_path, [("2026-10-21", "BOS", "NY", 110, 102)])
    with pytest.raises(team_codes.UnknownTeamCode):
        stakes._nba("ZZZ", "BOS", 2027)
