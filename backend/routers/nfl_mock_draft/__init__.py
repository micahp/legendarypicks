"""NFL mock-draft package — pool endpoint + draft CRUD for single-player mock drafts vs. ADP bots.

SPEC-slice-D-mock-draft.md:
  - Pool: GET /api/nfl/mock-draft/pool?season=2026 — the full ESPN player
    universe (~11,515: QB/RB/WR/TE/PK/DEF + IDP + free agents) with copied
    published ADP / PPR ranks. Draftable filtering is the UI's job.
  - Draft CRUD: create, append picks, resume, list — keyed by X-Device-Id.
  - Own _DB from LP_DB_PATH (no _core.py dependency).
"""

from fastapi import APIRouter

# Create the router at package level so existing imports like
# `from routers import nfl_mock_draft; nfl_mock_draft.router` keep working.
router = APIRouter()

# Import constants (sets _DB, _CURRENT_SEASON, etc. at package level)
from . import constants  # noqa: E402, F401
from .constants import (  # noqa: E402
    _CONTRACT,
    _CURRENT_SEASON,
    _DB,
    _DEFAULT_TEAMS,
    _DRAFT_POSITIONS,
    _LEAGUE_SIZES,
    _REG_SEASON_TEAM_GAMES,
    _ROUNDS,
    _THIN_SAMPLE_GAMES,
)

# Import db module (runs _init_db at import time)
from . import db  # noqa: E402, F401
from .db import _conn, _init_db  # noqa: E402

# Import cache helpers
from .cache import _clear_pool_cache, _pool_cache_get, _pool_cache_put  # noqa: E402

# Import shared helpers
from .helpers import (  # noqa: E402
    _compute_round_and_pick,
    _device_id,
    _json,
    _missing_picks,
    _named_stat_line,
)

# Import game log constants
from .game_log import _DST_LOG_FIELDS, _LOG_FIELDS  # noqa: E402

# The offseason aggregates were module-level names on the pre-split
# `nfl_mock_draft.py`, so patching them on this module is part of the surface
# the split promised to keep. Without these lines the pool-cache test dies on
# AttributeError instead of testing the cache.
from ..nfl_offseason import (  # noqa: E402, F401
    _availability_aggregates,
    _dst_aggregates,
)

# Import endpoints (each module registers routes on `router`)
from . import pool  # noqa: E402, F401
from . import crud  # noqa: E402, F401
from . import player_detail  # noqa: E402, F401
from . import game_log  # noqa: E402, F401

# Re-export endpoint functions for backward compatibility
from .pool import pool  # noqa: E402
from .crud import (  # noqa: E402
    append_picks,
    complete_draft,
    create_draft,
    get_draft,
    list_drafts,
)
from .player_detail import player_detail  # noqa: E402
from .game_log import _dst_game_log, player_game_log  # noqa: E402

# Names that were module-level on the pre-split file. Nothing re-exported them,
# so `<pkg>.<name>` raised AttributeError -- a surface the split promised to keep.
# None of these are ever REBOUND, only read or mutated in place, so importing them
# here yields the same objects the submodules use.
from .constants import (  # noqa: E402,F401
    _POOL_CACHE_MAX_ENTRIES,
    _POOL_CACHE_TTL,
    _POSTSEASON_FIRST_WEEK,
    _pool_cache,
    _pool_cache_lock,
)
