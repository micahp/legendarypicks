#!/usr/bin/env python3
"""settlement — prop settlement pipeline (package root).

This package splits the original settlement.py into modules by concern:

  market_mapping   — canonical market names, aliases, league→stat maps
  boxscore_extract — read a single stat for a player from an ESPN boxscore
  mlb_api          — MLB Stats API: schedule, gamePk, boxscore, final
  mlb_settle       — settle MLB props from the MLB Stats API boxscore
  ufc_settle       — settle UFC props from durable per-fight logs
  mls_settle       — settle MLS props from the summary roster-stat surface
  grading          — write one numeric actual to prop_results
  settle_game      — top-level driver: grade all unsettled props for one game

The public API of this package matches the original settlement.py exactly —
callers can `from settlement import settle_game` or `import settlement` and
find every name they used to rely on.
"""
from settlement.market_mapping import (
    MARKET_STAT,
    MARKET_ALIASES,
    normalize_market,
    resolve_market,
)
from settlement.boxscore_extract import (
    _find_player_stat,
    _find_player_compound_stat,
    _norm_name,
)
from settlement.mlb_api import (
    # `_mlb_schedule` was a module-level name on the pre-split settlement.py and
    # the regrade tests monkeypatch it to stand in for the MLB Stats API. Losing
    # it from this surface turned four tests that exercise doubleheaders and the
    # UTC date shift into AttributeError -- they stopped testing settlement at
    # all rather than failing on anything about settlement.
    _mlb_schedule,
    _fetch_mlb_gamepk,
    _fetch_mlb_boxscore,
    _fetch_mlb_final,
)
from settlement.mlb_settle import _settle_mlb_props
from settlement.ufc_settle import (
    _settle_ufc_props,
    _ufc_scoreboard_competition,
    _ufc_actual,
)
from settlement.mls_settle import _settle_mls_props
from settlement.tennis_settle import _settle_tennis_props, _tennis_snapshot
from settlement.grading import _grade_actual
from settlement.settle_game import settle_game

__all__ = [
    "MARKET_STAT",
    "MARKET_ALIASES",
    "normalize_market",
    "resolve_market",
    "_find_player_stat",
    "_find_player_compound_stat",
    "_norm_name",
    "_fetch_mlb_gamepk",
    "_fetch_mlb_boxscore",
    "_fetch_mlb_final",
    "_settle_mlb_props",
    "_settle_ufc_props",
    "_ufc_scoreboard_competition",
    "_ufc_actual",
    "_settle_mls_props",
    "_settle_tennis_props",
    "_tennis_snapshot",
    "_grade_actual",
    "settle_game",
]


# Names that were module-level on the pre-split file. Nothing re-exported them,
# so `<pkg>.<name>` raised AttributeError -- a surface the split promised to keep.
# None of these are ever REBOUND, only read or mutated in place, so importing them
# here yields the same objects the submodules use.
from .market_mapping import (  # noqa: E402,F401
    _BATTING_LABELS,
    _BATTING_ONLY,
    _PITCHING_LABELS,
    _PITCHING_ONLY,
)
from .mlb_api import (  # noqa: E402,F401
    _MLB_BOXSCORE,
    _MLB_HDR,
    _MLB_SCHEDULE,
    _MLB_SCHEDULE_CACHE,
)
from .mlb_settle import (  # noqa: E402,F401
    _MLB_BATTING_STATS,
    _MLB_MARKET_MAP,
    _MLB_PITCHING_STATS,
)
from .mls_settle import (  # noqa: E402,F401
    _MLS_EVENT_MARKETS,
    _MLS_ROSTER_MARKETS,
    _MLS_ROSTER_SUM_MARKETS,
    _soccer_name,
)
from .ufc_settle import (  # noqa: E402,F401
    _UFC_METHOD_MARKETS,
    _UFC_NUMERIC_MARKETS,
)

# `DB` was a module-level name on the pre-split settlement.py and no submodule
# defines it, so `settlement.DB` raised AttributeError outright. Restored here.
# TWO dirnames, not one: the original sat at `backend/settlement.py`, this file
# sits one directory deeper, and a wrong path here would not raise -- sqlite3
# CREATES the file, so a caller would quietly settle against an empty database.
import os as _os  # noqa: E402

DB = _os.environ.get("LP_DB_PATH") or _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "data", "picks.db")
