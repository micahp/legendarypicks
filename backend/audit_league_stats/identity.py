"""identity — league stats audit identity layer."""
import json
import os
import re
import sqlite3
import sys
import unicodedata
import argparse
import name_aliases

import json
import re
import sqlite3
import unicodedata

# Written by fetch_identity_names.py and committed, for the same reason as the
# vocabulary above: the audit runs offline and an identity map read at audit
# time could not be reviewed in a diff.
_IDENTITY_NAMES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "published-identity-names.json")

_IDENTITY_NAMES_CACHE = {}

def _identity_name_key(name):
    """Compare two spellings of a name without tolerating two different people.

    Publishers disagree on decoration, never on who someone is. MLB writes
    'Jeremy Peña' and 'Nasim Nuñez' where this database holds ASCII, and a
    literal comparison called 25 of those a corrupt id -- noise that would have
    buried the 224 real ones. So fold accents, case, punctuation and generational
    suffixes, and nothing else. 'Kyle Harrison' and 'Edmundo Sosa' must stay
    different, because on prod they shared an mlbam_id and they are not the same
    man.
    """
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^a-z ]", "", folded.lower())
    folded = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", folded)
    # Drop a bare middle initial. MLB publishes BOTH Max Muncys as 'Max Muncy'
    # (571970 LAD and 691777 ATH), so this database disambiguates one of them
    # locally as 'Max P. Muncy' -- correct data that a literal comparison calls
    # a corrupt id. An initial carries no identity the surname does not already
    # carry; two different people never differ by it alone.
    folded = re.sub(r"\b[a-z]\b", "", folded)
    return " ".join(folded.split())

def _published_identity_names(league):
    """{id_column, names} as the publisher publishes them, or None if never fetched."""
    if not _IDENTITY_NAMES_CACHE:
        try:
            with open(_IDENTITY_NAMES_PATH) as f:
                _IDENTITY_NAMES_CACHE["data"] = json.load(f)
        except (OSError, json.JSONDecodeError):
            _IDENTITY_NAMES_CACHE["data"] = None
    artifact = _IDENTITY_NAMES_CACHE.get("data")
    if not artifact:
        return None
    entry = artifact.get("leagues", {}).get(league)
    if not entry or not entry.get("names"):
        return None
    return {"id_column": entry.get("id_column"), "names": entry["names"]}

def _observed_positions(con, league, active_only=False):
    """The distinct position codes in use for a league.

    Fantasy constructs (team defences, TQB, coaches) are excluded once
    `entity_type` exists: a D/ST plays no position, and its former
    `position='DEF'` must not read as a second vocabulary fighting the real
    defensive positions.
    """
    scope = " AND active=1" if active_only and "active" in _columns(con, "players") else ""
    if "entity_type" in _columns(con, "players"):
        scope += " AND COALESCE(entity_type, 'player') = 'player'"
    return {
        r[0] for r in con.execute(
            f"SELECT position FROM players WHERE league=?{scope} "
            "AND position IS NOT NULL AND TRIM(position) != '' GROUP BY 1", (league,))
    }

def _declares_group_column(con, league, spec):
    """True when the league declares a populated group column for `position`.

    MLB's `position_group` carries the parent type (Outfielder/Infielder/...)
    beside the abbreviation in `position`, so a published parent value (OF)
    coexisting with its children (LF/CF/RF) is addressable -- anyone wanting
    the group filters position_group -- rather than a vocabulary clash. It
    must be BOTH in the league's spec AND actually carrying values: an empty
    column would hide the very split the overlap check exists to catch.
    """
    column = "position_group"
    if column not in (spec.get("single_vocabulary") or []):
        return False
    if column not in _columns(con, "players"):
        return False
    filled = con.execute(
        f"SELECT COUNT(*) FROM players WHERE league=? AND {column} IS NOT NULL "
        f"AND TRIM({column}) != ''", (league,)).fetchone()[0]
    return filled > 0

def _position_vocabulary(league):
    """{positions, ancestry, source} as published, or None if never fetched.

    None is answered honestly as UNVERIFIED rather than falling back to a guess:
    the guess is what this replaced.
    """
    if not _VOCABULARY_CACHE:
        try:
            with open(_VOCABULARY_PATH) as f:
                _VOCABULARY_CACHE["data"] = json.load(f)
        except (OSError, json.JSONDecodeError):
            _VOCABULARY_CACHE["data"] = None
    artifact = _VOCABULARY_CACHE.get("data")
    if not artifact:
        return None
    entry = artifact.get("leagues", {}).get(league)
    if not entry:
        return None
    return {
        "positions": entry.get("positions", {}),
        "ancestry": entry.get("ancestry", {}),
        "source": artifact.get("_provenance", {}).get("source", "ESPN"),
    }

# Written by fetch_position_vocabulary.py and committed. The audit must run
# offline, and a vocabulary read at audit time could not be reviewed in a diff.
_VOCABULARY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "position-vocabulary.json")

_VOCABULARY_CACHE = {}

def _columns(con, table):
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()
