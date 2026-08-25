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
HIDDEN_PROP_LEAGUES = frozenset({"wc"})


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


def prop_navigation(con: sqlite3.Connection) -> list[dict[str, str]]:
    """Competitions with at least one stored prop, grouped later by published sport.

    This intentionally measures the stored product rather than today's slate. A
    top-level sport is stable across the calendar, while a competition only earns
    a props filter after its first real prop lands.
    """
    try:
        leagues = {
            row[0]
            for row in con.execute(
                """SELECT DISTINCT LOWER(pg.league)
                   FROM prop_games pg
                   JOIN props p ON p.game_id = pg.id
                   WHERE COALESCE(pg.league, '') <> ''"""
            ).fetchall()
            if row[0]
        }
    except sqlite3.Error:
        return []
    return _rows(leagues - HIDDEN_PROP_LEAGUES)


def league_directory_navigation(con: sqlite3.Connection) -> list[dict[str, str]]:
    """Competition hubs vouched by the coverage registry.

    Tennis and esports are roll-up hubs rather than one-competition routes, so
    they are explicit local rows. World Cup remains score-only and is omitted.
    """
    rows = _rows(offered_leagues(con) - HIDDEN_DIRECTORY_LEAGUES)
    rows.append({"league": "tennis", "sport": "tennis"})
    rows.append({"league": "esports", "sport": "esports"})
    return sorted(rows, key=lambda row: (row["sport"], row["league"]))
