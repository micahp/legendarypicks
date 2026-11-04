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
        "RAM": "LAR",
        "LVR": "LV",
        "ARZ": "ARI",
        "SDG": "LAC",
        # Pro Football Reference spellings (merged from scripts/nfl_team_codes.py, 2026-11-04)
        "GNB": "GB",
        "KAN": "KC",
        "NOR": "NO",
        "NWE": "NE",
        "SFO": "SF",
        "TAM": "TB",
    },
    "mlb": {
        "CWS": "CHW",
        "AZ": "ARI",
        "OAK": "ATH",  # the Athletics' code before 2025 (statsapi and older ESPN box scores)
    },
    "nhl": {
        "UTA": "UTAH",
        "LAK": "LA",
        "TBL": "TB",
        "SJS": "SJ",
        "NJD": "NJ",
        # MoneyPuck spellings (research/nhl/*, merged 2026-11-04)
        "T.B": "TB",
        "N.J": "NJ",
        "L.A": "LA",
        "S.J": "SJ",
        # Relocations map to the current club, as in the NFL (STL to LAR): the Thrashers became the Jets in 2011.
        "ATL": "WPG",
        # The Coyotes' earlier code; the club is a historical one (HISTORICAL below).
        "PHX": "ARI",
    },
    "nba": {
        # nba.com (team pages' TEAM_ABBREVIATION) -> the ESPN codes this database stores.
        # Measured 2026-10-02: 24 of nba.com's 30 codes already agree; these six do not, and
        # the alias table was empty, so an nba.com roster could not name these teams at all.
        "GSW": "GS",
        "NOP": "NO",
        "NYK": "NY",
        "SAS": "SA",
        "UTA": "UTAH",
        "WAS": "WSH",
    },
    "mls": {
        # ESPN publishes RBNY for the New York Red Bulls; Bovada writes NYRB.
        # Measured 2026-08-16: the split held 41 players under RBNY and 4 under
        # NYRB, and it blocked three otherwise-unambiguous identity merges
        # (Cade Cowell, Jorge Ruvalcaba, Justin Che) because same-name matching
        # is scoped to the same team on purpose. ESPN is canonical.
        "NYRB": "RBNY",
        # RotoWire soccer stats spellings (merged from ingest_rotowire_soccer_stats.py, 2026-11-04)
        "DCU": "DC", "GAL": "LA", "LAF": "LAFC", "NER": "NE", "NYR": "RBNY", "SJE": "SJ", "FIR": "CHI",
        "MNU": "MIN", "RAP": "COL", "SOU": "SEA", "WHI": "VAN",
    },
    "ligamx": {
        # RotoWire soccer stats spellings (merged from ingest_rotowire_soccer_stats.py, 2026-11-04)
        "CA": "CAZ", "GUA": "GDL", "MON": "MTY", "NEC": "NCX", "QUE": "QRO", "TIG": "UANL", "UNM": "UNAM",
    },
    "ncaaf": {
        # ESPN's scoreboard flipped Jacksonville State from JVST to JXST in the
        # 2026-09-19 snapshot; the canonical directory (2026-07-27) and the CFBD
        # spine both say JVST (153 players) and one stale spine row says JXST.
        # Without the alias the display name resolved to whichever spelling the
        # last snapshot carried, and the fixture-team identity rule refused every
        # real Jacksonville State player on the board. Measured 2026-10-02.
        "JXST": "JVST",
    },
}

# ---------------------------------------------------------------------------
# Non-franchise codes  (NBA only)
# ---------------------------------------------------------------------------

NON_FRANCHISE: dict[str, frozenset[str]] = {
    "nba": frozenset({"STRIPES", "STARS", "WORLD"}),
    # MLS All-Star rosters are published as teams ("MLS All-Stars", "Liga MX
    # All-Stars") with their own codes in the season's team collection. They
    # are not franchises; pass them through so an All-Star game row does not
    # raise, and `is_canonical` still answers False for them.
    "mls": frozenset({"MLS", "LMX"}),
    # NCAAF group-80 team list carries post-season all-star / combine sides
    # (Senior Bowl Team Gaither / Team Robinson, East/West/North All-Stars,
    # South/North Florida Stars, "American", "National") that never play a
    # regular-season game. They appear in no team_game_results and must not
    # count toward FBS coverage.
    "ncaaf": frozenset({"AMER", "EAST", "GAIT", "NAT", "NOR", "ROB", "SFX", "UNF", "WEST"}),
}

# Clubs that no longer play but appear in historical seasons: normalize accepts
# them as themselves, and they are not CANONICAL (not a current club). The
# Coyotes (ARI) suspended operations after 2023-24; Utah (UTAH) is a new club.
HISTORICAL: dict[str, frozenset[str]] = {
    "nhl": frozenset({"ARI"}),
}

# All-star / combine sides are published in some leagues' team lists but never
# play a league game. Keep them pass-through (normalize accepts them) but strip
# them from CANONICAL so is_canonical — the count used by coverage gates and
# team aggregates — answers False. NBA STRIPES/STARS/WORLD and the MLS
# All-Star sides were already absent from their lists; NCAAF group 80 carries
# nine of them inside the JSON, so subtract everywhere.
for _league, _nf in NON_FRANCHISE.items():
    if _league in CANONICAL:
        CANONICAL[_league] = frozenset(CANONICAL[_league] - _nf)

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

    # 4) A historical club, as itself
    if clean in HISTORICAL.get(league, frozenset()):
        return clean

    raise UnknownTeamCode(f"{league!r} team code not recognised: {code!r}")


def normalize_optional(league: str, code: str | None) -> str | None:
    """Like `normalize` but returns None when *code* is None or the
    empty string.  Any other unrecognised value still raises."""
    if code is None or code == "":
        return None
    return normalize(league, code)


# ---------------------------------------------------------------------------
# Source vocabularies (canonical -> how one outside source spells the club)
# ---------------------------------------------------------------------------
# Only for writing a key the source's own files use (a game_id, a file name, a
# column we join against without loading it). Reading a source never needs
# this: `normalize` already accepts every spelling in ALIASES. A club a source
# spells canonically is left out.

SOURCE_VOCABULARIES: dict[str, dict[str, dict[str, str]]] = {
    "nfl": {
        # nflverse files (play-by-play, schedules, rosters, snap counts, depth
        # charts, weekly stats) and every table built from them.
        "nflverse": {"LAR": "LA", "WSH": "WAS"},
    },
    "mlb": {
        # statsapi.mlb.com /teams abbreviations.
        "statsapi": {"ARI": "AZ", "CHW": "CWS"},
        # Kalshi KXMLBGAME tickers (routers/live_discounts.py).
        "kalshi": {"ARI": "AZ", "CHW": "CWS"},
    },
    "nhl": {
        # api.nhle.com tricodes, verified against the publisher 2026-09-07 (migrate_nhl_tricodes.py).
        "nhle": {"LA": "LAK", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA", "NJ": "NJD"},
    },
}


def to_source(league: str, source: str, code: str) -> str:
    """The spelling *source* uses for this club. Raises on an unknown code,
    league or source."""
    try:
        vocabulary = SOURCE_VOCABULARIES[league][source]
    except KeyError:
        raise UnknownTeamCode(f"no {source!r} vocabulary registered for {league!r}") from None
    canonical = normalize(league, code)
    return vocabulary.get(canonical, canonical)


# Leagues where every club the app holds is registered above. Measured
# 2026-11-04: every players.team value in picks.db and picks.dev.db normalizes
# for these. Not complete: ncaaf (the list is the 146 FBS clubs; 101 FCS codes
# appear in players) and mls (GDL, a Liga MX club, appears in Leagues Cup rows).
COMPLETE_VOCABULARY = frozenset({"nfl", "mlb", "nba", "nhl", "ligamx"})

# Unregistered codes seen by same_team in a league without a complete
# vocabulary: (league, code) -> times. Read it, or see the log, to register them.
UNREGISTERED_SEEN: dict[tuple[str, str], int] = {}


def key_code(league: str, code: str) -> str:
    """The code a lookup should use: canonical for a registered spelling.

    In a league with a complete vocabulary an unknown code raises. In one
    without (ncaaf, mls) an unregistered code is kept as written, uppercased,
    and counted in UNREGISTERED_SEEN and the log, so the gap is visible rather
    than silent."""
    try:
        return normalize(league, code)
    except UnknownTeamCode:
        if league in COMPLETE_VOCABULARY or league not in CANONICAL:
            raise
        clean = _sanitise(code)
        key = (league, clean)
        if key not in UNREGISTERED_SEEN:
            import logging
            logging.getLogger(__name__).warning(
                "team code %r is not registered for %s; used as written", clean, league)
        UNREGISTERED_SEEN[key] = UNREGISTERED_SEEN.get(key, 0) + 1
        return clean


def same_team(league: str, a: str, b: str) -> bool:
    """Whether two spellings name the same club in *league* (see key_code for
    an unregistered code)."""
    return key_code(league, a) == key_code(league, b)


class TeamKeyed(dict):
    """A table keyed by team that cannot miss on spelling.

    Every key is stored under its canonical code for *league*, and every read
    and write (`[]`, `get`, `in`, `pop`, `setdefault`, `update`) normalizes
    the asked-for code the same way, so a table built from one source's
    spelling and a caller holding another meet on one key. An unknown code
    raises instead of missing (in ncaaf and mls, see key_code). *team_at* is None when the key is the team code
    itself, or the position of the team in a tuple key ((team, week),
    (player, team, group), ...). It stays a dict, so code that only reads it
    is protected without being changed, and it serializes as one.

    Measured 2026-11-04: the simulator's streak table (nflverse LA/WAS) was
    read with LAR/WSH, and for every Rams and Washington game the three streak
    layers silently ran on half the plays. Nothing raised.
    """

    def __init__(self, league: str, items=(), team_at: int | None = None):
        if league not in CANONICAL:
            raise UnknownTeamCode(f"unknown league: {league!r}")
        super().__init__()
        self.league = league
        self.team_at = team_at
        self.update(items)

    def _key(self, key):
        if self.team_at is None:
            return key_code(self.league, key)
        if not isinstance(key, tuple) or len(key) <= self.team_at:
            raise TypeError(
                f"team-keyed table expects a tuple key with the team at position {self.team_at}: {key!r}")
        i = self.team_at
        return key[:i] + (key_code(self.league, key[i]),) + key[i + 1:]

    def __getitem__(self, key):
        return super().__getitem__(self._key(key))

    def __setitem__(self, key, value):
        super().__setitem__(self._key(key), value)

    def __delitem__(self, key):
        super().__delitem__(self._key(key))

    def __contains__(self, key):
        return super().__contains__(self._key(key))

    def get(self, key, default=None):
        return super().get(self._key(key), default)

    def pop(self, key, *default):
        return super().pop(self._key(key), *default)

    def setdefault(self, key, default=None):
        return super().setdefault(self._key(key), default)

    def update(self, items=(), **kwargs):
        if kwargs:
            raise TypeError("TeamKeyed.update takes a mapping or (key, value) pairs only")
        for key, value in (items.items() if hasattr(items, "items") else items):
            self[key] = value

    def copy(self):
        return TeamKeyed(self.league, self, team_at=self.team_at)

    def __reduce__(self):
        return (TeamKeyed, (self.league, (), self.team_at), None, None, iter(dict.items(self)))

    def teams(self) -> set:
        """The canonical codes present."""
        return {key if self.team_at is None else key[self.team_at] for key in dict.keys(self)}


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
