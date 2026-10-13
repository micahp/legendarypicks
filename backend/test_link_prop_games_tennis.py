import sqlite3

from link_prop_games import link_prop_game


def _row(home="Stefanos Tsitsi", away="Jenson Broo", start="2026-08-24T22:30:00+00:00"):
    return {
        "league": "atp", "home": home, "away": away,
        "start_time": start,
    }


def _game(game_id="match-1", home="Stefanos Tsitsipas", away="Jenson Brooksby",
          start="2026-08-24T22:30Z"):
    return {
        "game_id": game_id, "date": start,
        "home": {"name": home}, "away": {"name": away},
    }


def test_tennis_links_two_publisher_truncations_at_the_same_instant():
    assert link_prop_game(sqlite3.connect(":memory:"), _row(), [_game()]) == "match-1"


def test_tennis_pair_is_unordered_and_accent_folded():
    row = _row(home="Renata Zarazua", away="Clara Tauso", start=None)
    game = _game(home="Clara Tauson", away="Renata Zarazúa")
    assert link_prop_game(sqlite3.connect(":memory:"), row, [game]) == "match-1"


def test_tennis_short_prefix_fails_but_unique_pair_survives_estimated_time():
    short = _row(home="Stef", away="Jenson Broo")
    assert link_prop_game(sqlite3.connect(":memory:"), short, [_game()]) == ""
    moved = _row()
    assert link_prop_game(
        sqlite3.connect(":memory:"), moved,
        [_game(start="2026-08-24T23:30Z")],
    ) == "match-1"


def test_tennis_ambiguous_pair_never_chooses_by_list_order():
    row = _row(start=None)
    assert link_prop_game(
        sqlite3.connect(":memory:"), row,
        [_game("match-1"), _game("match-2")],
    ) == ""


def test_tennis_exact_time_can_break_a_duplicate_pair_tie():
    assert link_prop_game(
        sqlite3.connect(":memory:"), _row(),
        [_game("match-1"), _game("match-2", start="2026-08-24T23:30Z")],
    ) == "match-1"
