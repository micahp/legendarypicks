"""Regression tests for published-scoreboard tennis settlement."""
import sqlite3

import settlement


def _competition(completed=True, second_set=True):
    first_scores = [{"value": 6.0, "winner": True}]
    second_scores = [{"value": 3.0, "winner": False}]
    if second_set:
        first_scores.append({"value": 6.0, "winner": True})
        second_scores.append({"value": 2.0, "winner": False})
    return {
        "status": {"type": {"state": "post", "completed": completed}},
        "competitors": [
            {"id": "101", "winner": True, "linescores": first_scores},
            {"id": "202", "winner": False, "linescores": second_scores},
        ],
    }


def _database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games(
            id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT, date TEXT,
            espn_event_id TEXT, final_home REAL, final_away REAL, start_time TEXT
        );
        CREATE TABLE players(
            id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, espn_id TEXT
        );
        CREATE TABLE props(
            id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER,
            market TEXT, line REAL, side TEXT
        );
        CREATE TABLE prop_results(
            prop_id INTEGER PRIMARY KEY, actual_value REAL, hit INTEGER, settled_at TEXT
        );
        INSERT INTO prop_games VALUES(1, 'atp', 'Winner', 'Loser', '2026-08-21',
                                     '999', NULL, NULL, NULL);
        INSERT INTO players VALUES(1, 'Winner', 'Loser', 'atp', '101');
        INSERT INTO players VALUES(2, 'Loser', 'Winner', 'atp', '202');
    """)
    rows = [
        (1, 1, "match_winner", .5, "over"),
        (2, 2, "match_winner", .5, "over"),
        (3, 1, "total_games", 11.5, "over"),
        (4, 2, "total_games", 5.5, "under"),
        (5, 1, "set_betting___2_0", .5, "over"),
        (6, 1, "set_betting___2_1", .5, "over"),
        (7, 2, "set_betting___0_2", .5, "over"),
        (8, 2, "set_betting___1_2", .5, "over"),
        (9, 1, "win_a_set", .5, "over"),
        (10, 2, "win_a_set", .5, "over"),
    ]
    con.executemany(
        "INSERT INTO props(id,game_id,player_id,market,line,side) VALUES(?,?,?, ?,?,?)",
        [(prop_id, 1, player_id, market, line, side) for prop_id, player_id, market, line, side in rows],
    )
    con.commit()
    return con


def _props(con):
    return con.execute("""
        SELECT p.id, p.market, p.line, p.side, p.player_id, pl.espn_id
        FROM props p JOIN players pl ON pl.id=p.player_id ORDER BY p.id
    """).fetchall()


def test_tennis_settlement_grades_all_supported_markets():
    con = _database()
    result = settlement._settle_tennis_props(con, _props(con), _competition())
    assert result == {"settled": 10, "void": 0, "unmappable": 0, "pending": 0, "errors": 0}
    assert [tuple(row) for row in con.execute(
        "SELECT actual_value, hit FROM prop_results ORDER BY prop_id").fetchall()] == [
        (1.0, 1), (0.0, 0), (12.0, 1), (5.0, 1), (1.0, 1),
        (0.0, 0), (1.0, 1), (0.0, 0), (1.0, 1), (0.0, 0),
    ]


def test_tennis_settlement_refuses_incomplete_completed_score():
    con = _database()
    result = settlement._settle_tennis_props(con, _props(con), _competition(second_set=False))
    assert result["settled"] == 0
    assert result["pending"] == 10
    assert result["errors"] == 1
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def test_settle_game_uses_scoreboard_and_leaves_pre_match_unsettled(monkeypatch):
    con = _database()
    monkeypatch.setattr(settlement, "_tennis_scoreboard_competition",
                        lambda *_args: _competition(completed=False))
    result = settlement.settle_game(con, 1)
    assert result["settled"] == 0
    assert result["errors"] == 0
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 0


def test_settle_game_uses_tennis_scoreboard_for_final(monkeypatch):
    con = _database()
    monkeypatch.setattr(settlement, "_tennis_scoreboard_competition",
                        lambda *_args: _competition())
    result = settlement.settle_game(con, 1)
    assert result["settled"] == 10
    assert con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0] == 10
