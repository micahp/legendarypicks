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
