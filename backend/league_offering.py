"""Which leagues this database is willing to put in front of a user.

One question, one answer, read from the enablement registry rather than a list.

The hub already asks it on the client (`useCoverage.isVouched` plus the UFC/WC
shape exception in `useLeagueRouteState`). Nothing asked it on the SERVER, so
every route that walks `players` directly — search above all — happily returned
rows for leagues the hub refuses to link to. Measured on production 2026-08-11:
the hub offered mlb/nba/nfl/nhl, and `/api/players/search?q=Bates` returned 4 NFL
players and **7 NCAAF** players, each linking to a working player page. NCAAF was
hidden from the one surface that had a gate and reachable from the one that did
not.

Derived from `team_stats_coverage`, never from a hardcoded league list, so a
league turns on the moment its coverage row is promoted and turns off the moment
it is not vouched — no second place to remember. That property is the point: the
literal `['mlb','nba','nhl','nfl']` this replaces is exactly the kind of list
that goes stale silently.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

# A status we are willing to put in front of a user. Mirrors isVouched() in
# components/Leagues/hooks/useCoverage.ts — the two must agree, because a league
# the server serves and the hub hides is the bug this module exists to close.
VOUCHED_STATUSES = frozenset({"complete", "in_progress"})

# UFC and the World Cup are not team-stats leagues and are not in
# team_stats_coverage at all, so they are named here as SHAPE, not as permission
# — the same exception useLeagueRouteState makes. Gating them on a team-stats row
# they will never have would hide two leagues that ship today.
ALWAYS_OFFERED = frozenset({"ufc", "wc"})


def offered_leagues(con: sqlite3.Connection) -> frozenset[str]:
    """Leagues this database may offer: vouched in coverage, plus the shape set.

    A missing or unreadable team_stats_coverage yields only ALWAYS_OFFERED. That
    is deliberate: no registry means nothing is vouched, and "we could not check"
    must fail closed rather than open the whole players table.
    """
    try:
        rows = con.execute(
            "SELECT DISTINCT LOWER(league) FROM team_stats_coverage WHERE status IN (%s)"
            % ",".join("?" * len(VOUCHED_STATUSES)),
            tuple(sorted(VOUCHED_STATUSES)),
        ).fetchall()
    except sqlite3.Error:
        return frozenset(ALWAYS_OFFERED)
    return frozenset(ALWAYS_OFFERED | {r[0] for r in rows if r[0]})


def sql_league_filter(leagues: Iterable[str], column: str = "p.league") -> tuple[str, list]:
    """An `AND LOWER(col) IN (...)` fragment plus its parameters.

    Returned as a fragment rather than applied by string interpolation so the
    league names stay bound parameters.
    """
    names = sorted({(l or "").lower() for l in leagues if l})
    if not names:
        # Nothing is offered. Return a predicate that is false rather than an
        # empty IN (), which is a syntax error, and rather than no filter at all,
        # which would return everything — the failure mode this module prevents.
        return " AND 0", []
    return " AND LOWER(%s) IN (%s)" % (column, ",".join("?" * len(names))), names
