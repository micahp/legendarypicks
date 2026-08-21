"""Durable, source-native publisher-response retention.

Normalized tables are product views.  This ledger preserves the complete
publisher body that produced them, so newly useful fields are recoverable
without guessing or re-scraping a historical slate.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any


PUBLISHER_CAPTURE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS publisher_captures(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  league TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  first_captured_at TEXT NOT NULL,
  last_captured_at TEXT NOT NULL,
  capture_count INTEGER NOT NULL DEFAULT 1,
  UNIQUE(source, league, endpoint, payload_sha256)
);
CREATE INDEX IF NOT EXISTS idx_publisher_captures_lookup
  ON publisher_captures(source, league, last_captured_at DESC);
""".strip()


class PublisherCaptureContractError(RuntimeError):
    """The explicit publisher-capture migration has not been applied."""


def create_publisher_capture_schema(connection: sqlite3.Connection) -> None:
    """Create this schema only from its explicit migration transaction."""
    for statement in PUBLISHER_CAPTURE_SCHEMA_SQL.split(";"):
        if statement.strip():
            connection.execute(statement)


def publisher_capture_schema_issues(connection: sqlite3.Connection) -> list[str]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publisher_captures'"
    ).fetchone()
    if not exists:
        return ["missing table publisher_captures"]
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(publisher_captures)")
    }
    required = {
        "id", "source", "league", "endpoint", "payload_sha256", "payload_json",
        "first_captured_at", "last_captured_at", "capture_count",
    }
    missing = sorted(required - columns)
    issues = (["publisher_captures missing columns: " + ", ".join(missing)]
              if missing else [])
    index = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_publisher_captures_lookup'"
    ).fetchone()
    if not index:
        issues.append("missing index idx_publisher_captures_lookup")
    return issues


def require_publisher_capture_schema(connection: sqlite3.Connection) -> None:
    issues = publisher_capture_schema_issues(connection)
    if issues:
        raise PublisherCaptureContractError(
            "publisher capture schema is not migrated: " + "; ".join(issues)
        )


def canonical_payload(payload: Any) -> str:
    """Stable full JSON for hashing and durable retention; reject non-JSON input."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def capture_payload(
    connection: sqlite3.Connection,
    *,
    source: str,
    league: str,
    endpoint: str,
    payload: Any,
    captured_at: str | None = None,
) -> tuple[int, bool]:
    """Retain one complete response and return ``(id, inserted)``.

    Repeated byte-equivalent payloads retain their original body and increase
    an observation counter.  The caller owns the surrounding transaction.
    """
    require_publisher_capture_schema(connection)
    body = canonical_payload(payload)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    now = captured_at or datetime.now(timezone.utc).isoformat()
    existing = connection.execute(
        """SELECT id FROM publisher_captures
           WHERE source=? AND league=? AND endpoint=? AND payload_sha256=?""",
        (source, league, endpoint, digest),
    ).fetchone()
    if existing:
        connection.execute(
            """UPDATE publisher_captures
               SET last_captured_at=?, capture_count=capture_count+1 WHERE id=?""",
            (now, existing[0]),
        )
        return int(existing[0]), False
    cursor = connection.execute(
        """INSERT INTO publisher_captures(
             source,league,endpoint,payload_sha256,payload_json,
             first_captured_at,last_captured_at
           ) VALUES(?,?,?,?,?,?,?)""",
        (source, league, endpoint, digest, body, now, now),
    )
    return int(cursor.lastrowid), True


def http_error_payload(error: Any) -> dict[str, Any]:
    """Return the complete response evidence available on an HTTP failure.

    ``urllib.error.HTTPError`` is also a response stream.  Reading it here is
    deliberate: callers retain the refusal before propagating it, rather than
    reducing a publisher answer to a status line in the spend log.  The body is
    base64 so non-UTF-8 error documents remain byte-for-byte recoverable.
    """
    try:
        raw_body = error.read()
    except Exception as exc:  # a transport failure can have no readable body
        raw_body = None
        body_read_error = "{}: {}".format(type(exc).__name__, exc)
    else:
        body_read_error = None
    try:
        headers = [[str(key), str(value)] for key, value in error.headers.items()]
    except Exception:
        headers = []
    payload = {
        "capture_kind": "http_error",
        "http_status": getattr(error, "code", None),
        "reason": str(getattr(error, "reason", "") or ""),
        "response_headers": headers,
        "body_base64": (b64encode(raw_body).decode("ascii")
                        if raw_body is not None else None),
    }
    if body_read_error:
        payload["body_read_error"] = body_read_error
    return payload


def capture_http_error(
    connection: sqlite3.Connection,
    *,
    source: str,
    league: str,
    endpoint: str,
    error: Any,
    captured_at: str | None = None,
) -> tuple[int, bool]:
    """Retain an HTTP refusal's status, headers, and exact response body."""
    return capture_payload(
        connection, source=source, league=league, endpoint=endpoint,
        payload=http_error_payload(error), captured_at=captured_at,
    )
