"""Single published vocabulary for all four leagues + NFL positions.

Loads canonical team codes from docs/espn-team-codes-2026-07-27.json.
Never derives from DB.  Position data is sourced from
docs/espn-position-codes-2026-07-27.json (NFL only for now).
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Load canonical team codes from the ESPN snapshot
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_DOCS = _HERE.parent / "docs"

with open(_DOCS / "espn-team-codes-2026-07-27.json") as fh:
    _raw = json.load(fh)

CANONICAL: dict[str, frozenset[str]] = {
    league: frozenset(codes)
    for league, codes in _raw.items()
}

# ---------------------------------------------------------------------------
# Aliases  (non-canonical -> canonical)
# ---------------------------------------------------------------------------

ALIASES: dict[str, dict[str, str]] = {
    "nfl": {
        "LA": "LAR",
        "WAS": "WSH",
        "AZ": "ARI",
        "JAC": "JAX",
        "OAK": "LV",
        "SD": "LAC",
        "STL": "LAR",
    },
    "mlb": {
        "CWS": "CHW",
        "AZ": "ARI",
    },
    "nhl": {
        "UTA": "UTAH",
        "LAK": "LA",
        "TBL": "TB",
        "SJS": "SJ",
        "NJD": "NJ",
    },
    "nba": {},
}

# ---------------------------------------------------------------------------
# Non-franchise codes  (NBA only)
# ---------------------------------------------------------------------------

NON_FRANCHISE: dict[str, frozenset[str]] = {
    "nba": frozenset({"STRIPES", "STARS", "WORLD"}),
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnknownTeamCode(ValueError):
    """A team code is not recognised for the given league."""


class UnknownPositionCode(ValueError):
    """A position code is not recognised for the given league."""


# ---------------------------------------------------------------------------
# Core helpers — team codes
# ---------------------------------------------------------------------------


def _sanitise(code: str | None) -> str:
    """Uppercase + strip; raises UnknownTeamCode on None or whitespace-only."""
    if code is None:
        raise UnknownTeamCode("code is None")
    clean = code.strip().upper()
    if not clean:
        raise UnknownTeamCode("code is empty or whitespace-only")
    return clean


def normalize(league: str, code: str) -> str:
    """Return the canonical team code for *league*, raising UnknownTeamCode
    if *code* is not recognised."""
    if league not in CANONICAL:
        raise UnknownTeamCode(f"unknown league: {league!r}")

    clean = _sanitise(code)

    # 1) Already canonical
    if clean in CANONICAL[league]:
        return clean

    # 2) Alias
    alias_map = ALIASES.get(league, {})
    if clean in alias_map:
        return alias_map[clean]

    # 3) Non-franchise pass-through  (NBA only)
    nf = NON_FRANCHISE.get(league, frozenset())
    if clean in nf:
        return clean

    raise UnknownTeamCode(f"{league!r} team code not recognised: {code!r}")


def normalize_optional(league: str, code: str | None) -> str | None:
    """Like `normalize` but returns None when *code* is None or the
    empty string.  Any other unrecognised value still raises."""
    if code is None or code == "":
        return None
    return normalize(league, code)


def is_canonical(league: str, code: str) -> bool:
    """Return True when *code* is a published canonical team code for *league*.

    Non-franchise codes (e.g. NBA STRIPES / STARS / WORLD) are NOT canonical,
    even though `normalize` passes them through unchanged.
    """
    if league not in CANONICAL:
        return False
    clean = code.strip().upper()
    return clean in CANONICAL[league]


# ===================================================================
# Position codes  (NFL only for now)
# ===================================================================

CANONICAL_POSITIONS: dict[str, frozenset[str]] = {
    "nfl": frozenset({
        "ATH", "B", "C", "CB", "DB", "DE", "DEF", "DL", "DT",
        "EDGE", "FB", "FL", "FS", "G", "H", "HB", "ILB", "KR",
        "LB", "LCB", "LDE", "LDT", "LG", "LHB", "LILB", "LLB",
        "LOLB", "LS", "LSF", "LT", "MG", "MLB", "NB", "NG", "NT",
        "OFF", "OG", "OL", "OLB", "OT", "P", "PK", "PR", "QB",
        "RB", "RCB", "RDE", "RDT", "RG", "RHB", "RILB", "RLB",
        "ROLB", "RSF", "RT", "S", "SE", "SETTER", "SLB", "SS",
        "ST", "T", "TB", "TE", "UT", "WLB", "WR",
    }),
    "mlb": frozenset(),
    "nba": frozenset(),
    "nhl": frozenset(),
}

POSITION_ALIASES: dict[str, dict[str, str]] = {
    "nfl": {
        "K": "PK",
        "OLB": "LB",
        "ILB": "LB",
        "MLB": "LB",
        "FS": "S",
        "SS": "S",
        "SAF": "S",
        "NT": "DT",
        # "OL": "G" was here and it was a fabrication, not a collapse. Every
        # other entry maps a code to its OWN published parent -- ESPN's
        # hierarchy says NT->DT, FS/SS->S, OLB/ILB/MLB->LB. It says OL->OFF,
        # and G has no parent at all. So this asserted that every lineman we
        # only know as "offensive line" is specifically a guard, inventing a
        # position the publisher never gave us. `OL` is already in
        # CANONICAL_POSITIONS, so it now passes through as itself.
        #
        # Check C could never have caught this: it detects a code sitting
        # beside its own ancestor, and G is not OL's ancestor. A gate built to
        # catch coarsening cannot catch a wrong answer dressed as one.
    },
    "mlb": {},
    "nba": {},
    "nhl": {},
}


def _sanitise_position(code: str | None) -> str:
    """Uppercase + strip; raises UnknownPositionCode on None/whitespace-only."""
    if code is None:
        raise UnknownPositionCode("position code is None")
    clean = code.strip().upper()
    if not clean:
        raise UnknownPositionCode("position code is empty or whitespace-only")
    return clean


def normalize_position(league: str, code: str) -> str:
    """Return the canonical position code for *league*, raising
    UnknownPositionCode if *code* is not recognised."""
    if league not in CANONICAL_POSITIONS:
        raise UnknownPositionCode(f"unknown league for positions: {league!r}")

    clean = _sanitise_position(code)

    # Alias first — some alias sources (OLB, FS, etc.) are also canonical
    # ESPN codes; the alias is the preferred normalisation.
    alias_map = POSITION_ALIASES.get(league, {})
    if clean in alias_map:
        return alias_map[clean]

    # Already canonical
    if clean in CANONICAL_POSITIONS[league]:
        return clean

    raise UnknownPositionCode(
        f"{league!r} position code not recognised: {code!r}"
    )


def normalize_position_optional(
    league: str, code: str | None
) -> str | None:
    """Like `normalize_position` but returns None when *code* is None
    or the empty string.  Any other unrecognised value still raises."""
    if code is None or code == "":
        return None
    return normalize_position(league, code)
