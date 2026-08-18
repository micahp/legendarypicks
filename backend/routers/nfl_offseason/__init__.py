"""routers/nfl_offseason — NFL offseason endpoints (package).

Split from the former single-file routers/nfl_offseason.py (2026-08-18)
into modules by concern: constants, cache, context, transactions,
aggregates, board.

The package exposes the same external surface the module did:
`router` (the APIRouter sports_service includes), the endpoint
functions (nfl_season_context, nfl_transactions, nfl_draft_board),
the helpers and aggregates callers use (_availability_aggregates,
_regular_season_aggregates, _pk_aggregates, _dst_aggregates,
_build_nfl_season_context, _clear_draft_board_cache,
_database_cache_token, _today, _percentage, _rounded_ratio), and
_db / _normalize_team.
"""
from fastapi import APIRouter
from _core import _db, _normalize_name
from team_codes import normalize, normalize_optional

router = APIRouter()

from .constants import (  # noqa: E402,F401
    _CONTEXT_CONTRACT, _DRAFT_BOARD_CONTRACT, _CURRENT_SEASON,
    _DRAFT_BOARD_CACHE_TTL, _DRAFT_BOARD_CACHE_MAX_ENTRIES,
    _DATABASE_TOKEN_MEMO_MAX_ENTRIES, _DRAFT_CACHE_SOURCES,
    _REG_SEASON_TEAM_GAMES, _REG_SEASON_LAST_WEEK, _POSTSEASON_FIRST_WEEK,
    _THIN_SAMPLE_GAMES, _CALENDAR_VALID_THROUGH, _NFL_CALENDAR_SOURCE,
    _NFL_CAMP_SOURCE, _NFL_MILESTONES, _SKILL_POSITIONS, _DEF_POSITION,
    _FANTASY_DRAFT_POSITIONS, _POSITION_FILTERS, _SORT_FIELDS,
    _SEARCH_MAX_LEN, _SEARCH_MAX_TOKENS, _TRANSACTIONS_CONTRACT,
    _POSITION_PREFIX, _SENTENCE_SPLIT, _TRAILING_INITIAL,
    _SIGNIFICANCE_CACHE_TTL,
)
from .cache import (  # noqa: E402
    _table_publication_signature, _database_cache_token,
    _draft_board_cache_get, _draft_board_cache_put,
    _clear_draft_board_cache,
)
from .context import (  # noqa: E402
    _today, _table_columns, _phase_for, _milestones_for, _timestamp_date,
    _roster_freshness, _reference_coverage, _build_nfl_season_context,
    nfl_season_context,
)
from .transactions import (  # noqa: E402
    _player_significance_lookup, _outgoing_player, _split_trade_sentences,
    _dedupe_trade_rows, nfl_transactions,
)
from .aggregates import (  # noqa: E402
    _availability_aggregates, _regular_season_aggregates, _pk_aggregates,
    _dst_aggregates,
)
from .board import (  # noqa: E402
    _draft_board_schema, _round, _rounded_ratio, _percentage, _escape_like,
    _name_search, nfl_draft_board,
)


# Names that were module-level on the pre-split file. Nothing re-exported them,
# so `<pkg>.<name>` raised AttributeError -- a surface the split promised to keep.
# None of these are ever REBOUND, only read or mutated in place, so importing them
# here yields the same objects the submodules use.
from .cache import (  # noqa: E402,F401
    _database_token_memo,
    _database_token_memo_lock,
    _draft_board_cache,
    _draft_board_cache_lock,
)
from .transactions import (  # noqa: E402,F401
    _significance_cache,
)
