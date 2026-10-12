"""Hand-computed checks for the season-to-date turnover, penalty and FTN blitz features."""
import sqlite3

import pytest

import nfl_feature_backtest as fb


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE nfl_schedule(game_id TEXT, season INTEGER, game_type TEXT, week INTEGER,
            home_team TEXT, away_team TEXT);
        CREATE TABLE nfl_pbp(game_id TEXT, play_id INTEGER, season INTEGER, week INTEGER,
            posteam TEXT, defteam TEXT, penalty_team TEXT, fumble_lost REAL, interception REAL,
            qb_dropback REAL);
        CREATE TABLE nfl_hist_ftn_charting(nflverse_game_id TEXT, nflverse_play_id INTEGER,
            season INTEGER, week INTEGER, n_blitzers INTEGER);
        """
    )
    return con


def _game(con, gid, week, home, away):
    con.execute("INSERT INTO nfl_schedule VALUES (?,2025,'REG',?,?,?)", (gid, week, home, away))


def _play(con, gid, pid, week, pos, dfn, pen=None, lost=None, intc=None, dropback=None):
    con.execute("INSERT INTO nfl_pbp VALUES (?,?,2025,?,?,?,?,?,?,?)",
                (gid, pid, week, pos, dfn, pen, lost, intc, dropback))


def test_turnover_margin_is_shrunk_takeaways_minus_giveaways():
    con = _db()
    _game(con, "g1", 1, "A", "B")
    _game(con, "g2", 2, "A", "C")
    _play(con, "g1", 1, 1, "B", "A", lost=1)  # B loses a fumble: a takeaway for A
    tw = fb._team_week_events(con, 2025)
    d = fb._to_date(con, 2025, 2, tw)
    # A: 1 game, 1 takeaway, 0 giveaways -> rate 1, shrunk by 1 / (1 + 8)
    assert fb._turnover_rating(d["A"]) == pytest.approx(1.0 / 9.0)
    # C has no games before week 2 and rates 0
    assert fb._turnover_rating(d.get("C")) == 0.0


def test_penalty_rate_is_shrunk_toward_league_and_signed_negative_for_home():
    con = _db()
    _game(con, "g1", 1, "A", "B")
    _game(con, "g2", 2, "A", "B")
    _play(con, "g1", 1, 1, "A", "B", pen="A")  # A is penalised once in week 1
    tw = fb._team_week_events(con, 2025)
    d = fb._to_date(con, 2025, 2, tw)
    a = fb._penalty_rating(d, "A")
    b = fb._penalty_rating(d, "B")
    # league average to date is (1 + 0) / 2 = 0.5; A's rate 1 and B's rate 0 shrink by 1 / 9
    assert a == pytest.approx(0.5 + (1.0 / 9.0) * 0.5)
    assert b == pytest.approx(0.5 + (1.0 / 9.0) * -0.5)


def test_ftn_rate_to_date_shrinks_each_team_toward_the_league_rate():
    con = _db()
    _game(con, "g1", 1, "A", "B")
    _game(con, "g2", 2, "A", "B")
    week_map = {"A": {1: (10, 5)}, "B": {1: (10, 10)}}  # A blitzes 0.5 per dropback, B 1.0
    r = fb._ftn_rate_to_date(con, 2025, 2, week_map)
    league = 15.0 / 20.0
    assert r["A"] == pytest.approx(league + (1.0 / 9.0) * (0.5 - league))
    assert r["B"] == pytest.approx(league + (1.0 / 9.0) * (1.0 - league))


def test_ftn_team_with_no_games_to_date_sits_at_the_league_rate():
    con = _db()
    _game(con, "g1", 1, "A", "B")
    week_map = {"A": {1: (10, 5)}, "B": {1: (10, 10)}}
    r = fb._ftn_rate_to_date(con, 2025, 1, week_map)  # nothing before week 1
    # no data to date, so the league rate computed from it is 0 and both teams sit there
    assert r["A"] == pytest.approx(0.0)
    assert r["B"] == pytest.approx(0.0)
