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
    return backup_path
