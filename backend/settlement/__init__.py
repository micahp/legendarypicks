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
    "_grade_actual",
    "settle_game",
]
