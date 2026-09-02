"""Pool cache helpers for the NFL mock-draft package."""

import time

from .constants import (
    _POOL_CACHE_MAX_ENTRIES,
    _POOL_CACHE_TTL,
    _pool_cache,
    _pool_cache_lock,
)


def _pool_cache_get(key):
    if key is None:
        return None
    now = time.monotonic()
    with _pool_cache_lock:
        entry = _pool_cache.get(key)
        if entry is None:
            return None
        created_at, body = entry
        if now - created_at >= _POOL_CACHE_TTL:
            del _pool_cache[key]
            return None
        del _pool_cache[key]
        _pool_cache[key] = (created_at, body)
        return body


def _pool_cache_put(key, body):
    if key is None:
        return
    with _pool_cache_lock:
        _pool_cache.pop(key, None)
        _pool_cache[key] = (time.monotonic(), bytes(body))
        while len(_pool_cache) > _POOL_CACHE_MAX_ENTRIES:
            oldest = next(iter(_pool_cache))
            del _pool_cache[oldest]


def _clear_pool_cache():
    with _pool_cache_lock:
        _pool_cache.clear()