"""cache — NFL offseason cache layer."""
import copy
import datetime as dt
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Set, Tuple
from fastapi import APIRouter, HTTPException, Query
from _core import _db, _normalize_name
from team_codes import normalize, normalize_optional
from .constants import (_CONTEXT_CONTRACT, _DRAFT_BOARD_CONTRACT, _CURRENT_SEASON, _DRAFT_BOARD_CACHE_TTL, _DRAFT_BOARD_CACHE_MAX_ENTRIES, _DATABASE_TOKEN_MEMO_MAX_ENTRIES, _DRAFT_CACHE_SOURCES, _REG_SEASON_TEAM_GAMES, _REG_SEASON_LAST_WEEK, _POSTSEASON_FIRST_WEEK, _THIN_SAMPLE_GAMES, _CALENDAR_VALID_THROUGH, _NFL_CALENDAR_SOURCE, _NFL_CAMP_SOURCE, _NFL_MILESTONES, _SKILL_POSITIONS, _DEF_POSITION, _FANTASY_DRAFT_POSITIONS, _POSITION_FILTERS, _SORT_FIELDS, _SEARCH_MAX_LEN, _SEARCH_MAX_TOKENS, _TRANSACTIONS_CONTRACT, _POSITION_PREFIX, _SENTENCE_SPLIT, _TRAILING_INITIAL, _SIGNIFICANCE_CACHE_TTL)  # noqa: E402
from . import router

_draft_board_cache_lock = threading.Lock()

_database_token_memo_lock = threading.Lock()


def _pkg__database_cache_token(*args, **kwargs):
    """Resolve `routers.nfl_offseason._database_cache_token` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _database_cache_token as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__draft_board_cache_get(*args, **kwargs):
    """Resolve `routers.nfl_offseason._draft_board_cache_get` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _draft_board_cache_get as _pkg_f
    return _pkg_f(*args, **kwargs)


def _pkg__draft_board_cache_put(*args, **kwargs):
    """Resolve `routers.nfl_offseason._draft_board_cache_put` at call time (tests patch the package attr)."""
    from routers.nfl_offseason import _draft_board_cache_put as _pkg_f
    return _pkg_f(*args, **kwargs)

def _table_publication_signature(connection, table, where, markers, totals):
    """Cheap state marker for one table read by the draft surfaces."""
    columns = {
        row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
    }
    if not columns:
        return (table, None)

    select = ["COUNT(*)", "MAX(rowid)"]
    select.extend(f'MAX("{column}")' for column in markers if column in columns)
    # The two legacy weekly tables have no publication timestamp. Their small
    # numeric totals keep in-place stat corrections visible to the cache key;
    # row count/max(rowid) also catches the normal replace-publication path.
    select.extend(
        f'TOTAL(COALESCE("{column}", 0))'
        for column in totals
        if column in columns
    )
    filter_sql = f" WHERE {where}" if where else ""
    row = connection.execute(
        f'SELECT {", ".join(select)} FROM "{table}"{filter_sql}'
    ).fetchone()
    return (table, tuple(row))

def _database_cache_token(connection: sqlite3.Connection):
    """Identify the NFL publications consumed by the draft surfaces.

    The endpoint is tested against multiple databases in one process, and DEV
    publishers may commit through another connection. Keying on the whole DB
    file made unrelated props/esports writes evict this cache; keying on WAL
    mtime also made a zero-byte WAL created by a read look like a publication.
    Table-local counts, publication markers, and legacy-table totals preserve
    relevant invalidation without coupling NFL reads to unrelated writers.
    """
    database_rows = connection.execute("PRAGMA database_list").fetchall()
    main_path = next(
        (row[2] for row in database_rows if row[1] == "main"),
        None,
    )
    if not main_path:
        return None

    resolved = os.path.realpath(main_path)

    def file_signature(path, *, empty_is_absent=False):
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            return None
        if empty_is_absent and stat.st_size == 0:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    physical_signature = (
        file_signature(resolved),
        file_signature(f"{resolved}-wal", empty_is_absent=True),
    )
    with _database_token_memo_lock:
        memoized = _database_token_memo.get(resolved)
        if memoized is not None and memoized[0] == physical_signature:
            del _database_token_memo[resolved]
            _database_token_memo[resolved] = memoized
            return memoized[1]

        scoped_token = (
            resolved,
            connection.execute("PRAGMA schema_version").fetchone()[0],
            tuple(
                _table_publication_signature(
                    connection, table, where, markers, totals
                )
                for table, where, markers, totals in _DRAFT_CACHE_SOURCES
            ),
        )
        _database_token_memo[resolved] = (physical_signature, scoped_token)
        while len(_database_token_memo) > _DATABASE_TOKEN_MEMO_MAX_ENTRIES:
            oldest = next(iter(_database_token_memo))
            del _database_token_memo[oldest]
        return scoped_token

def _draft_board_cache_get(key):
    if key is None:
        return None
    now = time.monotonic()
    with _draft_board_cache_lock:
        entry = _draft_board_cache.get(key)
        if entry is None:
            return None
        created_at, response = entry
        if now - created_at >= _DRAFT_BOARD_CACHE_TTL:
            del _draft_board_cache[key]
            return None
        # Dicts preserve insertion order on the supported Python runtime. Move
        # a hit to the end so eviction is bounded least-recently-used behavior.
        del _draft_board_cache[key]
        _draft_board_cache[key] = (created_at, response)
        return copy.deepcopy(response)

def _draft_board_cache_put(key, response):
    if key is None:
        return
    with _draft_board_cache_lock:
        _draft_board_cache.pop(key, None)
        _draft_board_cache[key] = (time.monotonic(), copy.deepcopy(response))
        while len(_draft_board_cache) > _DRAFT_BOARD_CACHE_MAX_ENTRIES:
            oldest = next(iter(_draft_board_cache))
            del _draft_board_cache[oldest]

_draft_board_cache: dict = {}
_database_token_memo: dict = {}


def _clear_draft_board_cache():
    """Test/operator hook; publication signatures invalidate normal writes."""
    with _draft_board_cache_lock:
        _draft_board_cache.clear()
    with _database_token_memo_lock:
        _database_token_memo.clear()
