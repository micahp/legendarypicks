"""Persistent, input-verified memo for immutable historical SLC setup data.

Reuse historical rows and tables across batch processes. Cache hits never skip
pregame cutoff checks or change simulator RNG; callers still get fresh mutable
objects from disk. Only local per-user entries written by this code are read.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import fit_cache


def database_identity(db):
    """Track SQLite main DB plus write-ahead log/journal (without reading GBs).

    The identity intentionally invalidates on any file change, including other
    tables: a false miss costs time; a false hit would contaminate a simulation.
    Use pinned, non-writing snapshots for reproducible comparisons.
    """
    path = Path(db).resolve(strict=True)
    result = []
    for suffix in ('', '-wal', '-journal'):
        item = Path(str(path) + suffix)
        try:
            stat = item.stat()
        except FileNotFoundError:
            result.append((suffix, None))
            continue
        result.append((suffix, (stat.st_dev, stat.st_ino, stat.st_size,
                                stat.st_mtime_ns, stat.st_ctime_ns)))
    return str(path), tuple(result)


def memo_db(name, db, settings, builder, code_files):
    """Reuse one DB-derived table; require an unchanged DB during its load.

    The existing fit cache supplies code/Python fingerprints, atomic writes,
    and a distinct object on every cache hit. No cache on ordinary direct calls
    when SLC_FIT_CACHE_DIR is unset/empty. A full cache disk does not block a
    simulation after the data were successfully built.
    """
    if not os.environ.get('SLC_FIT_CACHE_DIR'):
        return builder()
    before = database_identity(db)
    completed = []

    def build():
        value = builder()
        completed.append(value)
        return value

    try:
        result = fit_cache.memo('reference_' + name, (before, settings), build,
                                code_files=tuple(code_files) + (__file__,))
    except OSError as error:
        # Cache I/O is an optimization, never a reason to lose a finished build.
        print(f'reference-cache {name}: {error}; bypassing cache', file=sys.stderr)
        result = completed[0] if completed else builder()
    if database_identity(db) != before:
        raise RuntimeError(f'reference source database changed while loading {name}; retry with a frozen copy')
    return result
