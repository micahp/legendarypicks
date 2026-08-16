"""Tests for splitting the player off a Bovada market description.

One nameless MLB players row (id 28987) had accumulated 3,729 props belonging to Cooper
Pratt, Raynel Delgado, Kahlil Watson, Kyler Fedko and others. The parser demanded an
uppercase team parenthetical, and every market written without one produced an empty name
that nothing downstream rejected — so the props were emitted anyway and piled onto a single
fake identity, while the unparsed name stayed welded into the market key
("total_hits,_runs_and_rbis___cooper_pratt": one market per player, groupable by nothing).
"""
import bovada_scraper as b


def test_the_documented_shape_still_parses():
    assert b._split_market_and_player("Total Strikeouts - Ryan Gusto (MIA)") == (
        "Total Strikeouts", "Ryan Gusto", "MIA")


def test_a_market_with_no_team_parenthetical_still_yields_the_player():
    """The shape that caused it. Bovada writes plenty of markets with no team at all."""
    assert b._split_market_and_player("Total Hits, Runs and RBIs - Cooper Pratt") == (
        "Total Hits, Runs and RBIs", "Cooper Pratt", "")


def test_a_team_code_that_is_not_all_caps():
    """`[A-Z]+` rejected "D-Backs" and dropped Ketel Marte with it."""
    head, player, team = b._split_market_and_player("Total Bases - Ketel Marte (D-Backs)")
    assert (head, player) == ("Total Bases", "Ketel Marte")
    assert team == "D-BACKS"


def test_a_game_level_market_has_no_player_and_that_is_not_a_failure():
    """"Total Hits, Runs and Errors" is a real market about the game, not a broken parse.
    It reports no player so the caller skips it instead of bucketing it."""
    assert b._split_market_and_player("Total Hits, Runs and Errors") == (
        "Total Hits, Runs and Errors", "", "")


def test_the_market_head_no_longer_carries_the_name():
    """The head is what gets canonicalised. Leaving the name on it minted one market key
    per player for every market the map does not recognise."""
    head, _p, _t = b._split_market_and_player("Total Doubles - Raynel Delgado")
    assert head == "Total Doubles"
    assert "delgado" not in head.lower()


def test_empty_and_malformed_descriptions_do_not_raise():
    assert b._split_market_and_player("") == ("", "", "")
    assert b._split_market_and_player(None) == ("", "", "")
    assert b._split_market_and_player(" - ")[1] == ""
