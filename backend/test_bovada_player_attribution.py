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


def _nba_team_market_event():
    """The real shape from Bovada's NBA board on 2026-08-24, trimmed.

    Bovada files team totals in a display group called "Score Props", and the market
    description carries the club exactly where a player would sit. It splits like a player
    market because it IS shaped like one.
    """
    return {
        "description": "Boston Celtics @ Detroit Pistons",
        "startTime": 1787621880000,
        "competitors": [
            {"name": "Detroit Pistons", "home": True},
            {"name": "Boston Celtics", "home": False},
        ],
        "displayGroups": [{
            "description": "Score Props",
            "markets": [
                {"description": "Highest Scoring Quarter Total Points O/U - Boston Celtics",
                 "outcomes": [
                     {"description": "Over", "price": {"handicap": "31.5", "american": -110}},
                     {"description": "Under", "price": {"handicap": "31.5", "american": -110}},
                 ]},
                {"description": "Total Points - Jayson Tatum",
                 "outcomes": [
                     {"description": "Over", "price": {"handicap": "27.5", "american": -115}},
                 ]},
            ],
        }],
    }


def test_a_team_market_is_not_emitted_as_a_player_prop():
    """The fixture's own club standing where a player's name goes is a team market.

    Emitting it produced "REJECTED all 120 nba props — nothing in `players` matched" on
    2026-08-24 and exit 3 took the whole systemd unit down, on a day Bovada published no NBA
    player props at all. The resolver could only report that nothing matched, which reads
    identically to a broken feed.
    """
    from bovada_scraper.config import _TEAM_LEVEL_OUTCOMES
    _TEAM_LEVEL_OUTCOMES.clear()
    props = b.parse_player_props(_nba_team_market_event(), "nba")
    names = {p["player_name"] for p in props}
    assert "Boston Celtics" not in names
    assert sum(_TEAM_LEVEL_OUTCOMES.values()) == 2


def test_the_real_player_on_the_same_board_still_lands():
    """The counter-case. Dropping team markets must not cost us the player markets sitting
    in the same display group."""
    props = b.parse_player_props(_nba_team_market_event(), "nba")
    assert [(p["player_name"], p["market"], p["line"]) for p in props] == [
        ("Jayson Tatum", "points", 27.5)]


def test_set_betting_is_not_a_player_prop():
    """`<Player> 2 - 0` is the MATCH's scoreline, told from one side.

    It carries a player's name, which is why it was read as player-attributed,
    but it measures nothing about that player's performance and nothing in
    player_game_logs can ever chart it. It belongs with the other match-level
    tennis markets already deferred (Total Sets, game/set spreads, tie-break).
    438 such props existed on dev and 442 on prod when this was removed.
    """
    from bovada_scraper.parsers import _parse_tennis_props
    event = {
        "competitors": [{"id": "1", "name": "Alexander Zverev"},
                        {"id": "2", "name": "Terence Atmane"}],
        "description": "Alexander Zverev vs Terence Atmane",
        "startTime": 1787000000000,
        "displayGroups": [{"markets": [
            {"description": "Set Betting", "period": {"abbreviation": "MT"},
             "outcomes": [
                 {"description": "Alexander Zverev 2 - 0",
                  "price": {"american": "+150"}},
                 {"description": "Terence Atmane 2 - 1",
                  "price": {"american": "+400"}},
             ]},
            # A real player market on the same event must still land, so this
            # asserts a removal rather than a broken parser.
            {"description": "Will Alexander Zverev Win At Least One Set?",
             "period": {"abbreviation": "MT"},
             "outcomes": [{"description": "Yes", "price": {"american": "-400"}}]},
        ]}],
    }
    props = _parse_tennis_props(event, "atp")
    markets = {p["market"] for p in props}
    assert not any(m.startswith("set_betting") for m in markets), markets
    assert "win_a_set" in markets, markets
