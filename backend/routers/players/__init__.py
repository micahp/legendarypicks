"""routers/players — players endpoints (package).

Split from the former single-file routers/players.py (2026-08-18) into
modules by concern: search, profile, matchups, projections, news,
stats.

The package exposes the same external surface the module did:
`router` (the APIRouter sports_service includes), the endpoint
functions (search_players, player_profile, player_matchups,
player_projections, player_news, player_fantasy_news, player_stats,
league_leaders), the helpers tests call (_reg_season_game_filter,
_dst_game_logs, _season_stats_for_profile), and the module constants
(_LEAGUE_CATEGORIES, _DST_POSITIONS, ...).
"""
from fastapi import APIRouter
from _core import *
from nfl_news import (  # noqa: F401
    ROTOWIRE_LABEL, load_news_feed, load_player_news_page,
    load_sleeper_crosswalk, merge_player_news, resolve_rotowire_id,
)

router = APIRouter()

from .search import _reg_season_game_filter, search_players  # noqa: E402
from .profile import (  # noqa: E402
    _dst_game_logs, _season_stats_for_profile, player_profile,
)
from .matchups import player_matchups  # noqa: E402
from .projections import player_projections  # noqa: E402
from .news import player_news, player_fantasy_news  # noqa: E402
from .stats import (  # noqa: E402
    player_stats, _metric, _empty_leaders, _format_leader_value,
    _numeric_stat, _parse_log_stats, _window_value, _log_order,
    _change_evidence, league_leaders, _LEAGUE_CATEGORIES,
    _LEAGUE_DEFAULTS, _CHANGE_METRICS, _COMPARISON_BASE, _DST_POSITIONS,
    _PUBLISHED_FANTASY_POSITIONS, _NFL_KEY_NORMALIZE,
    _NFL_PROJECTION_STATS,
)
