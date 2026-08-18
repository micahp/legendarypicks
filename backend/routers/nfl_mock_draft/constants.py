"""Constants for the NFL mock-draft package."""

import os
import threading

# ---------------------------------------------------------------------------
#  Module-level DB path — mirrors ufc_picks.py / nfl_draft_notes.py
# ---------------------------------------------------------------------------

_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "picks.db",
)

_CONTRACT = "nfl-mock-draft-v1"
_CURRENT_SEASON = 2026
_REG_SEASON_TEAM_GAMES = 17
_POSTSEASON_FIRST_WEEK = 19
_THIN_SAMPLE_GAMES = 4
_POOL_CACHE_TTL = 300
_POOL_CACHE_MAX_ENTRIES = 4

_pool_cache: dict = {}
_pool_cache_lock = threading.Lock()


# Draftable positions: skill positions, kickers, and team defenses.
_DRAFT_POSITIONS = ("QB", "RB", "WR", "TE", "PK", "DEF")

# The league sizes we offer. 11 and 16 are real formats we deliberately do not
# support: the bot roster ceilings and the 15-round roster construction are
# sized for these three, and a size the engine was never built for would draft a
# board we cannot stand behind. 12 stays the default so drafts created before
# league size existed keep round-tripping.
_LEAGUE_SIZES = frozenset({10, 12, 14})
_DEFAULT_TEAMS = 12
_ROUNDS = 15