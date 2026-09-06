#!/usr/bin/env python3
"""league_membership.py: does this fixture belong to the league claiming it?

WHY.

On 2026-09-05 at 17:18 two fixtures were written into prod as `league='mls'`: Sassuolo @
Bologna (Serie A) and Guadalajara @ Atletico San Luis (Liga MX). RotoWire's guard existed
and would have caught both, but the club vocabulary it reads is built from a live ESPN
request, and a refusal there returned None and skipped the check entirely.

The deeper problem is that the guard lived in ONE ingest. `/api/props/ingest` creates
prop_games too, from `batch.league` on trust, and by row count it is the bigger creator:
bovada made 54 of prod's MLS games against RotoWire's 45. A rule enforced on one surface is
not enforced.

THE CONSTRAINT THAT SHAPES THIS. `/api/props/ingest` is a REQUEST HANDLER. A serving path
must never wait on a publisher, which is the 2026-08-24 lesson where a batch job's ESPN
fan-out put 26 refusals onto uvicorn. So this reads only what the database already holds and
issues no network request, ever.

WHAT IT WILL NOT DO. It will not guess. `belongs()` returns None for "cannot check", and a
caller must decide what that means rather than receive a False dressed up as an answer. It
never says a fixture is foreign because a league is quiet; only because the same clubs are
positively known to play somewhere else.
"""
import json
import re
import sqlite3
import unicodedata
from typing import Dict, Optional, Set

# The rule only means something where a fixture is between INSTITUTIONS drawn from a closed
# set. Running it everywhere was wrong and the first run said so: UFC reported 11 "foreign"
# fixtures because its competitors are people, so every debut is a name we have never seen,
# and tennis is the same shape. Asking "is this club on record" of a fighter is not a strict
# check, it is a category error.
_CLUB_LEAGUES = {"mls", "ligamx", "lcup", "nfl", "mlb", "nba", "nhl", "ncaaf", "wc"}

# A cross-league competition is defined by the crossing. Leagues Cup is MLS against Liga MX,
# so two MLS clubs cannot meet in it and neither can two Liga MX clubs. Membership alone
# cannot see this: every club involved is a legitimate member, which is why 6 of prod's 10
# lcup fixtures passed a membership check while not being Leagues Cup at all. Four were Liga
# MX league games and two were MLS games duplicated from an already-linked mls row.
_CROSS_LEAGUE = {"lcup": ("mls", "ligamx")}

# How many distinct clubs a league must have on record before an absence means anything.
# Below this the league is not "known", it is merely observed, and a missing club says more
# about our coverage than about the fixture.
_MIN_CLUBS_TO_JUDGE = 8

# Shortest folded name that may take part in a prefix match. Abbreviations sit in the same
# set as full names, and a 3-letter code prefix-matches half the world.
_MIN_PREFIX = 6


def fold(value: Optional[str]) -> str:
    """Accent- and case-insensitive, punctuation-free. `Atlético` and `Atletico` are one."""
    ascii_value = (unicodedata.normalize("NFKD", str(value or ""))
                   .encode("ascii", "ignore").decode("ascii"))
    squashed = re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()
    # A trailing club suffix is decoration, not identity: "Toronto FC" and "Toronto".
    return re.sub(r"\b(fc|sc|cf|afc|united|club)\b", "", squashed).strip() or squashed


def squash(value: Optional[str]) -> str:
    """The folded name with its spaces removed, for EXACT comparison only.

    CFBD publishes "Hawai'i" and the book says "Hawaii". Folding turns the apostrophe into a
    space, so the two differ by one character that means nothing. `ingest_rotowire_props`
    already indexes both forms for the same reason.

    Never used for prefix matching: dropping spaces makes short prefixes collide, and the
    prefix rule is already the loose half of this check.
    """
    return fold(value).replace(" ", "")


def _strip_decoration(value: Optional[str]) -> str:
    """Drop a publisher's ranking, so "SMU (#19)" is the same school as "SMU"."""
    return re.sub(r"\(\s*#\s*\d+\s*\)", " ", str(value or ""))


def _on_record(name: str, clubs: Set[str]) -> bool:
    """Is this club known here, allowing for one publisher naming it more fully?

    Exact folding is not enough across a vocabulary boundary. Bovada says "Michigan (#16)"
    where ESPN stores "Michigan Wolverines", and the first version of this rule called seven
    real NCAAF games foreign on exactly that difference. `ingest_cfbd_logs._school_to_code`
    already resolves the same boundary by display-name prefix, so this uses the same rule.

    Loose within a side, strict across the fixture: both sides must clear this, so a
    generous name match here is balanced by there being two of them to satisfy.
    """
    folded = fold(_strip_decoration(name))
    if not folded:
        return False
    if folded in clubs or squash(_strip_decoration(name)) in clubs:
        return True
    # Prefix matching ONLY between names long enough for a prefix to mean something. The
    # club set holds abbreviations too, and "ATL" made "Atletico San Luis" pass as Atlanta
    # United, which turned a Liga MX fixture into a valid MLS one. Three letters are not
    # evidence of anything.
    if len(folded) < _MIN_PREFIX:
        return False
    return any(len(club) >= _MIN_PREFIX
               and (club.startswith(folded) or folded.startswith(club))
               for club in clubs)


def known_clubs(con: sqlite3.Connection, league: str) -> Set[str]:
    """Every club name this database has on record for a league, folded.

    Three durable sources, all already stored, none requiring a request:

    `league_clubs`, the publisher's own complete club list, written by the ingest that
    already fetches it. This is the one that lets the check be STRICT: without it the record
    was whatever had happened to appear, and three real NCAAF fixtures read as foreign
    because we had never recorded the opponent.

    `scoreboard_snapshots`, the publisher's fixture list, and `prop_games` rows that already
    carry an ESPN event id, which is our own crosswalk having agreed.

    Unlinked prop_games are deliberately excluded: they are exactly the rows this check
    exists to doubt, and letting them vote would launder a bad fixture into evidence.
    """
    clubs: Set[str] = set()
    try:
        for (name,) in con.execute(
                "SELECT name FROM league_clubs WHERE league=?", (league,)):
            clubs.add(fold(_strip_decoration(name)))
            clubs.add(squash(_strip_decoration(name)))
    except sqlite3.Error:
        pass
    try:
        for (payload,) in con.execute(
                "SELECT payload FROM scoreboard_snapshots WHERE LOWER(league)=?",
                (league.lower(),)):
            try:
                snapshot = json.loads(payload)
            except (TypeError, ValueError):
                continue
            for side in ("home", "away"):
                team = snapshot.get(side) or {}
                for key in ("name", "display_name", "abbrev"):
                    if team.get(key):
                        clubs.add(fold(_strip_decoration(team[key])))
                        clubs.add(squash(_strip_decoration(team[key])))
    except sqlite3.Error:
        pass
    try:
        for home, away in con.execute(
                "SELECT home, away FROM prop_games WHERE league=? "
                "AND COALESCE(espn_event_id,'') <> ''", (league,)):
            clubs.add(fold(_strip_decoration(home)))
            clubs.add(squash(_strip_decoration(home)))
            clubs.add(fold(_strip_decoration(away)))
            clubs.add(squash(_strip_decoration(away)))
    except sqlite3.Error:
        pass
    clubs.discard("")
    return clubs


def belongs(con: sqlite3.Connection, league: str, home: str, away: str,
            _cache: Optional[Dict[str, Set[str]]] = None,
            strict: bool = False) -> Optional[bool]:
    """True, False, or None for "cannot check".

    None means the league cannot be judged at all. Otherwise the answer depends on how much
    is being asked of it, and the two callers ask different things ON PURPOSE.

    strict=True  - BOTH clubs must be on record. This is the AUDIT's question, because a
                   fixture in a league is played between two of its members and one
                   recognised club proves nothing: it is exactly what a cross-competition
                   fixture looks like. It found an MLS-vs-MLS game filed under LEAGUES CUP,
                   which is by definition MLS against Liga MX.
    strict=False - only NEITHER club being on record is a refusal. This is the GUARD's
                   question, because the guard runs in a request handler and a wrong refusal
                   destroys a real fixture. Requiring both there flagged three genuine NCAAF
                   games (Texas State @ Texas, Oklahoma State @ Tulsa, UNLV @ Hawaii) whose
                   opponents we simply had not recorded yet. An incomplete club list is a
                   fact about our coverage, and a serving path must not refuse real data on
                   the strength of it.

    So the strict answer is a finding to look at, and the loose answer is the only one a
    write path acts on.
    """
    if league.lower() not in _CLUB_LEAGUES:
        return None
    cache = _cache if _cache is not None else {}

    def clubs_for(name):
        if name not in cache:
            cache[name] = known_clubs(con, name)
        return cache[name]

    members = _CROSS_LEAGUE.get(league.lower())
    if members:
        first, second = (clubs_for(members[0]), clubs_for(members[1]))
        if min(len(first), len(second)) < _MIN_CLUBS_TO_JUDGE:
            return None
        # One side from each member league, in either order. A club on record in BOTH sets
        # satisfies whichever side it needs to, because the ambiguity is ours and must not
        # convict a real fixture.
        return bool((_on_record(home, first) and _on_record(away, second))
                    or (_on_record(home, second) and _on_record(away, first)))

    clubs = clubs_for(league)
    if len(clubs) < _MIN_CLUBS_TO_JUDGE:
        return None
    home_known, away_known = _on_record(home, clubs), _on_record(away, clubs)
    if strict:
        return home_known and away_known
    return home_known or away_known
