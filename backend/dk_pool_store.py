"""Stored DraftKings MMA salary pools, so the board never waits on a publisher.

The optimizer used to fetch RotoWire inside the request that rendered the page,
behind a 300-second in-memory cache and nothing else. That has two costs. The
page is only as available as RotoWire is at the instant someone opens it, and a
pool nobody opened was never captured at all, so there is no history of what a
slate looked like before it locked.

A scheduled job writes here; the serving path reads. One row per slate date,
replaced in place as salaries and the fight card move during the week.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS dk_pool_snapshots(
  league        TEXT NOT NULL,
  slate_date    TEXT NOT NULL,
  lock_at       TEXT NOT NULL,
  captured_at   TEXT NOT NULL,
  source        TEXT NOT NULL,
  fight_count   INTEGER NOT NULL,
  fighter_count INTEGER NOT NULL,
  payload       TEXT NOT NULL,
  PRIMARY KEY(league, slate_date)
);
"""


class DKPoolError(RuntimeError):
    """The pool cannot safely be stored or read back."""


def ensure_table(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def _validated(payload: dict[str, Any]) -> dict[str, Any]:
    slate = payload.get("slate") if isinstance(payload, dict) else None
    if not isinstance(slate, dict):
        raise DKPoolError("pool payload carries no slate")
    fighters = slate.get("fighters")
    if not isinstance(fighters, list) or len(fighters) < 6:
        raise DKPoolError(
            f"pool has {len(fighters) if isinstance(fighters, list) else 0} fighters; "
            "a six-fighter lineup cannot be built"
        )
    for key in ("slateDate", "lockAt"):
        if not slate.get(key):
            raise DKPoolError(f"pool slate is missing {key}")
    return slate


def publish(connection: sqlite3.Connection, payload: dict[str, Any], *,
            captured_at: str, league: str = "ufc") -> dict[str, Any]:
    """Write one validated pool inside the caller's transaction."""
    slate = _validated(payload)
    stored = dict(payload)
    stored["stored_captured_at"] = captured_at
    connection.execute(
        """INSERT INTO dk_pool_snapshots(
             league,slate_date,lock_at,captured_at,source,fight_count,fighter_count,payload
           ) VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(league,slate_date) DO UPDATE SET
             lock_at=excluded.lock_at, captured_at=excluded.captured_at,
             source=excluded.source, fight_count=excluded.fight_count,
             fighter_count=excluded.fighter_count, payload=excluded.payload""",
        (league, str(slate["slateDate"]), str(slate["lockAt"]), captured_at,
         str(slate.get("source") or "rotowire_live"), int(slate.get("fightCount") or 0),
         len(slate["fighters"]), json.dumps(stored, sort_keys=True)),
    )
    return {"slate_date": slate["slateDate"], "lock_at": slate["lockAt"],
            "fights": slate.get("fightCount"), "fighters": len(slate["fighters"])}


def read_unlocked(connection: sqlite3.Connection, *, now: dt.datetime,
                  league: str = "ufc") -> dict[str, Any] | None:
    """The stored pool whose contest has not locked yet, or None.

    A locked slate is not served: the optimizer builds lineups for a contest you
    can still enter, and a past one would read as current.
    """
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dk_pool_snapshots'"
    ).fetchone()
    if not table:
        return None
    rows = connection.execute(
        "SELECT payload,captured_at,lock_at FROM dk_pool_snapshots "
        "WHERE league=? ORDER BY lock_at ASC", (league,),
    ).fetchall()
    for row in rows:
        try:
            lock = dt.datetime.fromisoformat(str(row["lock_at"]).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if lock.tzinfo is None:
            lock = lock.replace(tzinfo=dt.timezone.utc)
        if lock <= now:
            continue
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise DKPoolError("stored pool payload is invalid JSON") from exc
        payload["stored_captured_at"] = row["captured_at"]
        return payload
    return None
