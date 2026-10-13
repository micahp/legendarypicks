"""Tests for player_form — recent form read from our game logs rather than the prop board."""
import datetime
import json
import sqlite3

import player_form as pf


def _con(rows, players):
    """rows: (league, season, team, player_id, game_date, stats dict)."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE player_game_logs(player_id TEXT, league TEXT, season INTEGER,
                   game_no INTEGER, game_date TEXT, team TEXT, stats TEXT)""")
    con.execute("CREATE TABLE players(id TEXT, name TEXT)")
    for i, (league, season, team, pid, date, stats) in enumerate(rows):
        con.execute("INSERT INTO player_game_logs VALUES (?,?,?,?,?,?,?)",
                    (pid, league, season, i, date, team, json.dumps(stats)))
    for pid, name in players.items():
        con.execute("INSERT INTO players VALUES (?,?)", (pid, name))
    return con


def _nba_rows(pid, team, points, season=2026):
    return [("nba", season, team, pid, f"2026-01-{10 + i:02d}", {"PTS": p, "REB": 5, "AST": 4})
            for i, p in enumerate(points)]


def test_reads_form_without_any_props():
    """The whole point: props are not consulted and there is no props table here at all."""
    con = _con(_nba_rows("p1", "NY", [20, 30, 32, 36, 45]), {"p1": "Jalen Brunson"})
    out = pf.lines("nba", ["NY"], con=con, as_of=datetime.date(2026, 1, 15))
    assert len(out) == 1
    assert "Jalen Brunson (NY, 2026 logs" in out[0]
    assert "points [45, 36, 32, 30, 20]" in out[0]


def test_most_recent_first():
    con = _con(_nba_rows("p1", "NY", [10, 20, 30]), {"p1": "A Player"})
    out = pf.lines("nba", ["NY"], con=con, as_of=datetime.date(2026, 1, 13))
    assert "points [30, 20, 10]" in out[0]


def test_the_season_is_always_stated():
    """MLS logs stop at 2025 while the 2026 season is being played. A writer told the
    season cannot call it current form; a writer told nothing will."""
    rows = [("mls", 2025, "CHI", "p1", f"2025-09-0{i}", {"goals": 1, "shots": 3, "assists": 0})
            for i in range(1, 5)]
    out = pf.lines("mls", ["CHI"], con=_con(rows, {"p1": "Hugo Cuypers"}),
                   as_of=datetime.date(2025, 9, 6))
    assert "2025 logs" in out[0]


def test_a_player_who_left_the_team_is_not_named_as_current_form():
    """Reported 2026-08-30: a Chicago Fire preview cited Hugo Cuypers, already transferred
    to Monterrey — his last logged game for the team was four months stale. Naming him
    `as_of` a date well past his last appearance must exclude him, not just print an old
    season label next to his name."""
    rows = [("mls", 2026, "CHI", "p1", f"2026-04-2{i}", {"goals": 1, "shots": 3, "assists": 0})
            for i in range(1, 5)]
    out = pf.lines("mls", ["CHI"], con=_con(rows, {"p1": "Hugo Cuypers"}),
                   as_of=datetime.date(2026, 8, 30))
    assert out == []


def test_only_the_latest_season_is_read():
    con = _con(_nba_rows("p1", "NY", [40, 40, 40], season=2025)
               + _nba_rows("p2", "NY", [10, 10, 10], season=2026),
               {"p1": "Old Season", "p2": "This Season"})
    out = pf.lines("nba", ["NY"], con=con, as_of=datetime.date(2026, 1, 13))
    assert len(out) == 1 and "This Season" in out[0]


def test_players_ranked_by_the_headline_stat():
    con = _con(_nba_rows("p1", "NY", [5, 5, 5]) + _nba_rows("p2", "NY", [30, 30, 30]),
               {"p1": "Bench Guy", "p2": "Star"})
    out = pf.lines("nba", ["NY"], con=con, as_of=datetime.date(2026, 1, 13))
    assert out[0].startswith("Star")


def test_fewer_than_three_games_is_not_form():
    con = _con(_nba_rows("p1", "NY", [30, 30]), {"p1": "Two Games"})
    assert pf.lines("nba", ["NY"], con=con) == []


def test_a_thin_secondary_stat_is_dropped():
    """A quarterback logs rush yards once in five games. Printing 'rush yards [2]' beside
    five PPR scores reads as a five-game trend that collapsed."""
    rows = []
    for i, fp in enumerate([20.0, 18.0, 22.0, 25.0, 19.0]):
        stats = {"fpts_ppr": fp}
        if i == 0:
            stats["rush_yds"] = 2
        rows.append(("nfl", 2025, "KC", "p1", f"2025-10-0{i + 1}", stats))
    out = pf.lines("nfl", ["KC"], con=_con(rows, {"p1": "A Quarterback"}),
                   as_of=datetime.date(2025, 10, 6))
    assert "PPR points" in out[0]
    assert "rush yards" not in out[0]


def test_a_league_with_no_declared_headline_stat_gets_nothing():
    """UFC has no team column and no headline stat here. Better nothing than a column
    picked by shape."""
    assert pf.lines("ufc", ["X"], con=_con([], {})) == []


def test_unknown_league_and_empty_teams():
    con = _con(_nba_rows("p1", "NY", [30, 30, 30]), {"p1": "Star"})
    assert pf.lines("cricket", ["NY"], con=con) == []
    assert pf.lines("nba", [], con=con) == []


def test_a_broken_database_yields_no_lines_rather_than_raising():
    con = sqlite3.connect(":memory:")
    assert pf.lines("nba", ["NY"], con=con) == []
