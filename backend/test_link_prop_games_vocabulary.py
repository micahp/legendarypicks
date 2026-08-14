"""The linker's team maps must speak the publisher's vocabulary, not our own.

`_norm_team` turns a sportsbook's club name into an ESPN abbreviation, and the
linker then matches on that abbreviation. So a single wrong value does not raise
and does not warn — it just never matches, and the league quietly carries
unlinked prop_games whose props no game page can reach. That is how MLB sat at
677/745 with every Chicago White Sox game unlinked: the map said `CWS` where ESPN
publishes `CHW`, and this repo had already written the `CWS -> CHW` correction in
two other files (`team_codes.py:43`, `refresh_mlb_player_teams.py:54`).

These fixtures are ESPN's own published abbreviations, captured from
`espn_client.games(league, date)` on 2026-08-15 (MLS, both slates carried all 30
clubs) and 2026-08-12/13 (MLB). They are checked in rather than fetched so the
suite neither needs the network nor spends a request budget that is a count per
host — and so that a drift shows up as a diff in git rather than as a league
whose props stopped linking.
"""
import pytest

from link_prop_games import _MLB_TEAM_MAP, _MLS_TEAM_MAP, _norm_team

# name as ESPN publishes it -> abbreviation as ESPN publishes it
ESPN_MLB = {
    "arizona diamondbacks": "ARI", "athletics": "ATH", "atlanta braves": "ATL",
    "baltimore orioles": "BAL", "boston red sox": "BOS", "chicago cubs": "CHC",
    "chicago white sox": "CHW", "cincinnati reds": "CIN",
    "cleveland guardians": "CLE", "colorado rockies": "COL",
    "detroit tigers": "DET", "houston astros": "HOU", "kansas city royals": "KC",
    "los angeles angels": "LAA", "los angeles dodgers": "LAD",
    "miami marlins": "MIA", "milwaukee brewers": "MIL", "minnesota twins": "MIN",
    "new york mets": "NYM", "new york yankees": "NYY",
    "philadelphia phillies": "PHI", "pittsburgh pirates": "PIT",
    "san diego padres": "SD", "san francisco giants": "SF",
    "seattle mariners": "SEA", "st. louis cardinals": "STL",
    "tampa bay rays": "TB", "texas rangers": "TEX", "toronto blue jays": "TOR",
    "washington nationals": "WSH",
}

ESPN_MLS = {
    "atlanta united fc": "ATL", "austin fc": "ATX", "cf montréal": "MTL",
    "charlotte fc": "CLT", "chicago fire fc": "CHI", "colorado rapids": "COL",
    "columbus crew": "CLB", "d.c. united": "DC", "fc cincinnati": "CIN",
    "fc dallas": "DAL", "houston dynamo fc": "HOU", "inter miami cf": "MIA",
    "la galaxy": "LA", "lafc": "LAFC", "minnesota united fc": "MIN",
    "nashville sc": "NSH", "new england revolution": "NE",
    "new york city fc": "NYC", "orlando city sc": "ORL",
    "philadelphia union": "PHI", "portland timbers": "POR",
    "real salt lake": "RSL", "red bull new york": "RBNY", "san diego fc": "SD",
    "san jose earthquakes": "SJ", "seattle sounders fc": "SEA",
    "sporting kansas city": "SKC", "st. louis city sc": "STL",
    "toronto fc": "TOR", "vancouver whitecaps": "VAN",
}


@pytest.mark.parametrize("league,published", [("mlb", ESPN_MLB), ("mls", ESPN_MLS)])
def test_every_abbreviation_we_emit_is_one_the_publisher_uses(league, published):
    """No map value may be an abbreviation ESPN does not publish for that league.

    Checked as a set rather than per-club so a value invented for a club ESPN
    spells differently still fails — the failure mode is a code we made up, and
    which club it was attached to does not change that.
    """
    ours = set((_MLB_TEAM_MAP if league == "mlb" else _MLS_TEAM_MAP).values())
    assert ours - set(published.values()) == set()


@pytest.mark.parametrize("league,published", [("mlb", ESPN_MLB), ("mls", ESPN_MLS)])
def test_every_published_club_is_reachable(league, published):
    """Feeding ESPN's own club name back in must return ESPN's own abbreviation.

    This is the direction that actually failed: the map is keyed on the
    SPORTSBOOK's spelling, so a club can be present under a name no publisher
    uses and still never match anything.
    """
    unreachable = {name: (_norm_team(name, league), abbrev)
                   for name, abbrev in published.items()
                   if _norm_team(name, league) != abbrev}
    assert unreachable == {}


def test_the_white_sox_specifically():
    """The regression this file was written for, named so it cannot be lost in a set."""
    assert _norm_team("Chicago White Sox", "mlb") == "CHW"
    assert "CWS" not in _MLB_TEAM_MAP.values()


def test_no_club_shares_an_abbreviation_within_a_league():
    """Two clubs on one code is a mislink waiting for the right fixture.

    A duplicate would let a game match the wrong club and settle its props
    against the wrong boxscore, which nothing downstream can detect.
    """
    for league, m in (("mlb", _MLB_TEAM_MAP), ("mls", _MLS_TEAM_MAP)):
        by_abbrev = {}
        for name, abbrev in m.items():
            by_abbrev.setdefault(abbrev, []).append(name)
        # Aliases for the SAME club are expected (both spellings of Montréal,
        # "LAFC" and "Los Angeles FC"). Distinct clubs sharing a code are not, so
        # compare the count of codes against the count of clubs the publisher lists.
        assert len(by_abbrev) == len(set(
            (ESPN_MLB if league == "mlb" else ESPN_MLS).values()
        )), f"{league}: {len(by_abbrev)} codes for a league the publisher gives fewer"
