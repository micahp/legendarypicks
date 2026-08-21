"""routers/games — games endpoints (package). Handlers only; shared code lives in _core.

Split from the former single-file routers/games.py (2026-08-18). The package
exposes the same external surface the module did: `router` (the APIRouter,
included by sports_service.py), the endpoint functions, and the underscore
helpers tests call directly (`_scoreboard_snapshot`, `_local_event_starts`,
`_cap_schedule_candidates`, `_offer_only_seasons_we_hold`, ...).

Two names are special: `_db` and `kick_game_stories` are PATCHED AT PACKAGE
LEVEL by tests (`patch.object(games, "_db", fixture)`), so the submodules that
call them resolve them through this namespace at call time via wrapper
functions — never as import-time bindings.
"""
import datetime as dt
import html
import json
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from team_stats_contract import build_team_aggregates
from provenance import publishers_for

router = APIRouter()

from .contexts import (  # noqa: E402
    wc_knockout, wc_context, wc_context_episode, cod_game_context,
    lcup_game_context, _attach_cod_detail_ids, _BROADCAST_DIR,
    _SIGNAL_TAGS, _LCUP_RADIO,
)
from .scoreboard import (  # noqa: E402
    get_games, _scoreboard_snapshot, _capture_completed_day,
    _nothing_newer_to_have, _games_from_db, _SNAPSHOT_MAX_AGE,
)
from .schedule import (  # noqa: E402
    get_schedule_dates, get_nfl_schedule_weeks, get_nfl_schedule_week,
    get_ncaaf_schedule_weeks, get_ncaaf_schedule_week,
    _parse_anchor_date, _default_nfl_season, _default_start_year_season, _flatten_nfl_weeks,
    _default_nfl_week, _event_start, _is_guaranteed_directional_start,
    _cap_schedule_candidates, _local_event_starts, _schedule_candidates,
    _SCHEDULE_DATES_CONTRACT, _NFL_SCHEDULE_WEEKS_CONTRACT,
    _NFL_SCHEDULE_WEEK_CONTRACT, _NCAAF_SCHEDULE_WEEKS_CONTRACT,
    _NCAAF_SCHEDULE_WEEK_CONTRACT, _SCHEDULE_SEARCH_RANGES,
    _SCHEDULE_CANDIDATE_LIMIT, _MIN_VIEWER_OFFSET, _MAX_VIEWER_OFFSET,
)
from .standings import (  # noqa: E402
    get_strength, get_standings, get_team_strength, seasons_we_hold,
    _offer_only_seasons_we_hold, _strength_from_db, _SEASON_EVIDENCE_TABLES,
)
from .ufc import ufc_rankings, ufc_fighter_form  # noqa: E402
from .game_detail import (  # noqa: E402
    get_team_stats, get_team_aggregates, get_boxscore, get_game_detail,
    get_game_boxscore, get_game_playbyplay, get_game_gameinfo, get_roster,
    _summary_not_started,
)
from .predictions import submit_prediction, list_predictions  # noqa: E402
from .misc import root, health, coverage, stream_league_audio  # noqa: E402
