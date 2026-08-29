"""Runtime sport/competition navigation derived from published league paths.

The ESPN path registry is the authority for a competition's sport. Database
rows decide which competitions have product coverage; presentation code may
group those rows, but it must never maintain a second league-to-sport map.
"""
from __future__ import annotations

import sqlite3

from espn_client import LEAGUES as ESPN_SITE_LEAGUES
from league_offering import offered_leagues


HIDDEN_DIRECTORY_LEAGUES = frozenset({"wc"})
SOCCER_DIRECTORY_LEAGUES = frozenset({"mls", "lcup"})
# Props navigation describes the product we offer, not whichever competitions
# happen to have rows in today's database. Row presence is feed-dependent: NBA
# can have scheduled games but no player-prop offers, and Leagues Cup can have a
# published scoreboard slate before any prop_game row exists. Using props as the
# enablement registry made both disappear while leaving Soccer visible solely
# because MLS retained historical rows.
#
# Keep this product contract separate from the provider fetch registries. A
# provider can be temporarily empty, and one stray stored row must not silently
# launch a new competition in the UI.
PROP_PRODUCT_LEAGUES = frozenset({
    "atp",
    "lcup",
    "mlb",
    "mls",
    "nba",
    "nfl",
    "nhl",
    "ufc",
    "wta",
})


def sport_for_league(league: str) -> str | None:
    """Return ESPN's published sport path segment for one storage league key."""
    entry = ESPN_SITE_LEAGUES.get(str(league or "").strip().lower())
    if not entry:
        return None
    path = str(entry[0] or "").strip("/")
    return path.split("/", 1)[0] or None


def _rows(leagues) -> list[dict[str, str]]:
    rows = []
    for league in sorted({str(value or "").strip().lower() for value in leagues if value}):
        sport = sport_for_league(league)
        if sport:
            rows.append({"league": league, "sport": sport})
    return rows


def prop_navigation(_con: sqlite3.Connection) -> list[dict[str, str]]:
    """Competitions supported by the Props product, grouped by published sport.

    The database decides what each selected board can render. It does not decide
    whether the selector exists: an empty or unavailable slate gets an honest
    empty state instead of silently removing the competition from navigation.
    """
    return _rows(PROP_PRODUCT_LEAGUES)


def league_directory_navigation(con: sqlite3.Connection) -> list[dict[str, str]]:
    """Competition hubs vouched by the coverage registry.

    Soccer, tennis and esports are roll-up hubs rather than one-competition
    routes, so they are explicit local rows. World Cup remains score-only and
    is omitted.
    """
    rows = _rows(
        offered_leagues(con) - HIDDEN_DIRECTORY_LEAGUES - SOCCER_DIRECTORY_LEAGUES
    )
    rows.append({"league": "soccer", "sport": "soccer"})
    rows.append({"league": "tennis", "sport": "tennis"})
    rows.append({"league": "esports", "sport": "esports"})
    return sorted(rows, key=lambda row: (row["sport"], row["league"]))
