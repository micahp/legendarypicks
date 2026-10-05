"""Shared safeguards for scheduled production history refreshes."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
from contextlib import closing
from typing import Optional
from urllib.parse import quote


# A scheduled apply runs BEGIN IMMEDIATE against production and must not find the
# database in a mode where that transaction cannot be rolled back. Both `delete` and
# `wal` are rollback-safe; `off` is the one that is not, because it discards the journal
# entirely and a crash mid-apply leaves a half-written database with no way back.
#
# This list used to be the single string "delete", which is why it is spelled out here.
# `delete` was prod's mode and `wal` was dev's, so an equality check against "delete"
# read as "am I really pointed at production?" -- an environment assertion wearing a
# durability assertion's clothes. It was never load-bearing for correctness: BEGIN
# IMMEDIATE behaves identically in both modes. When prod moved to WAL on 2026-08-19 to
# stop readers and writers blocking each other, that check would have failed every
# scheduled run for a property it was not actually testing. Identify the database by its
# path, never by an incidental pragma.
ROLLBACK_SAFE_JOURNAL_MODES = frozenset({"delete", "wal", "truncate", "persist", "memory"})

# The 5s SQLite default is what surfaced as `database is locked` -> HTTP 500 on prod's
# props ingest. Our writes are short; a writer that cannot start within 30s is a real
# problem, not contention.
BUSY_TIMEOUT_SECONDS = 30


def read_only_connection(path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(path)
    connection = sqlite3.connect(
        "file:{}?mode=ro".format(quote(absolute, safe="/")),
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def integrity_check(path: str) -> str:
    with closing(read_only_connection(path)) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "no result"


def json_dump(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def backup_database(
    db_path: str,
    label: str,
    now: Optional[dt.datetime] = None,
) -> str:
    safe_label = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")
    if not safe_label:
        raise ValueError("backup label must contain a letter or number")
    timestamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup_path = "{}.bak-premigrate-{}-{}".format(
        os.path.abspath(db_path), safe_label, timestamp
    )
    if os.path.exists(backup_path):
        raise RuntimeError("backup already exists: {}".format(backup_path))
    # A file copy can capture a logically torn delete-mode database while a
    # live writer is active. SQLite's backup API produces one coherent snapshot.
    with closing(read_only_connection(db_path)) as source:
        source.execute("PRAGMA busy_timeout=60000")
        with closing(sqlite3.connect(backup_path)) as destination:
            with destination:
                source.backup(destination)
    if os.path.getsize(backup_path) <= 0:
        raise RuntimeError("backup is empty: {}".format(backup_path))
    integrity = integrity_check(backup_path)
    if integrity != "ok":
        raise RuntimeError(
            "backup integrity_check returned {}: {}".format(
                integrity, backup_path
            )
        )
    prune_backups(db_path, safe_label, keep=BACKUP_KEEP)
    return backup_path


# 2026-10-05: nothing ever deleted these. The UFC roster refresh alone left one full
# 0.4 GB copy per run, and 171 old backups (51 GB) had piled up by October 5.
BACKUP_KEEP = 3


def prune_backups(db_path: str, safe_label: str, keep: int = BACKUP_KEEP) -> list:
    """Delete all but the newest `keep` backups for this exact label.

    Matches `<db>.bak-premigrate-<label>-YYYYMMDD-HHMMSS` exactly, so the label
    `ufc` never touches `ufc-roster` backups. Runs only after the new backup has
    passed its integrity check, so the newest copy is always a good one. A failed
    delete raises: a prune that silently stops is how 51 GB built up.
    """
    if keep < 1:
        raise ValueError("keep must be at least 1")
    base = os.path.abspath(db_path)
    folder, name = os.path.split(base)
    pattern = re.compile(
        r"^{}\.bak-premigrate-{}-(\d{{8}}-\d{{6}})$".format(
            re.escape(name), re.escape(safe_label)
        )
    )
    found = sorted(
        (m.group(1), entry)
        for entry in os.listdir(folder)
        for m in [pattern.match(entry)]
        if m
    )
    removed = []
    for _, entry in found[:-keep]:
        for suffix in ("", "-wal", "-shm"):
            path = os.path.join(folder, entry + suffix)
            if os.path.exists(path):
                os.remove(path)
                removed.append(path)
    return removed
