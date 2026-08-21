"""Exact-identity tennis prop-game linking regressions."""
import sqlite3

from link_prop_games import link_prop_game


def _database(player_ids=("101", "202")):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY, league TEXT, home TEXT, away TEXT);
        CREATE TABLE players(id INTEGER PRIMARY KEY, league TEXT, espn_id TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY, game_id INTEGER, player_id INTEGER);
        INSERT INTO prop_games VALUES(1, 'atp', 'Daniel Merida Aguilar', 'Taylor Fritz');
        INSERT INTO players VALUES(1, 'atp', '101');
        INSERT INTO players VALUES(2, 'atp', '202');
        INSERT INTO props VALUES(1, 1, 1);
        INSERT INTO props VALUES(2, 1, 2);
    """)
    if player_ids != ("101", "202"):
        con.execute("UPDATE players SET espn_id=? WHERE id=1", (player_ids[0],))
        con.execute("UPDATE players SET espn_id=? WHERE id=2", (player_ids[1],))
    return con


def _row(con):
    return con.execute("SELECT * FROM prop_games WHERE id=1").fetchone()


def _game(game_id, home, away, home_name="Daniel Merida", away_name="Taylor Fritz"):
    return {"game_id": game_id,
            "home": {"athlete_id": home, "name": home_name},
            "away": {"athlete_id": away, "name": away_name}}


def test_tennis_links_by_exact_player_pair_despite_display_name_drift():
    con = _database()
    slate = [_game("181913", "101", "202")]
    assert link_prop_game(con, _row(con), slate) == "181913"


def test_tennis_refuses_one_player_or_ambiguous_pair():
    con = _database()
    con.execute("DELETE FROM props WHERE player_id=2")
    # One ESPN athlete plus the exact publisher matchup still resolves one event.
    assert link_prop_game(con, _row(con), [_game("181913", "101", "202")]) == "181913"

    con = _database()
    slate = [_game("181913", "101", "202"), _game("181914", "202", "101")]
    assert link_prop_game(con, _row(con), slate) == ""


def test_tennis_refuses_a_different_published_pair():
    con = _database()
    assert link_prop_game(con, _row(con), [_game("181913", "101", "303")]) == ""


def test_tennis_one_id_fallback_accepts_order_and_one_extra_surname_only():
    con = _database()
    con.execute("DELETE FROM props WHERE player_id=2")
    reversed_name = _game("182328", "1797", "3155", "Elina Svitolina", "Wang Xiyu")
    con.execute("UPDATE players SET espn_id='1797' WHERE id=1")
    con.execute("UPDATE prop_games SET home='Elina Svitolina', away='Xiyu Wang' WHERE id=1")
    assert link_prop_game(con, _row(con), [reversed_name]) == "182328"

    wrong = _game("182329", "1797", "3155", "Elina Svitolina", "Wrong Wang Name")
    assert link_prop_game(con, _row(con), [wrong]) == ""
