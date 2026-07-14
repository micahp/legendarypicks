from __future__ import annotations

"""Pick ledger — Step 1 of the esports Pick Desk MVP.

Records a device's pick (side A or B) for a match identified by match_key. No
settlement, scoring, or auth yet — those are later steps. Identity is the
`X-Device-Id` request header.

This module creates exactly one new table (`esports_picks`) and exposes the
ledger endpoints. It touches no other table and no other module.
"""

import os
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

# Resolve the DB path exactly like the surrounding backend does.
_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "picks.db"
)


def _conn():
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    """Create the ledger table + index once, never crashing the app on failure."""
    try:
        c = _conn()
        try:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS esports_picks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    match_key TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('A','B')),
                    created_at INTEGER NOT NULL,
                    lock_at INTEGER,
                    settled_at INTEGER,
                    result TEXT,
                    points REAL,
                    crowd_share_at_lock REAL,
                    UNIQUE(device_id, match_key)
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_esports_picks_match ON esports_picks(match_key)"
            )
            c.commit()
        finally:
            c.close()
    except Exception:
        # A failed ledger create must never bring down the whole app.
        pass


_init_db()

router = APIRouter()


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status)


def _device_id(x_device_id: Optional[str]) -> Optional[str]:
    """Return a stripped device id, or None if missing/empty."""
    if not x_device_id:
        return None
    d = x_device_id.strip()
    return d or None


def _signed_streak(results):
    """Signed run length of the most recent consecutive same-result rows.

    `results` is an iterable of result strings ('win'|'loss'|'void') ordered by
    settled_at DESC. 'void' rows are ignored. E.g. 3 wins -> 3, 2 losses -> -2,
    none -> 0.
    """
    seq = [r for r in results if r in ("win", "loss")]
    if not seq:
        return 0
    first = seq[0]
    sign = 1 if first == "win" else -1
    n = 0
    for r in seq:
        if r == first:
            n += 1
        else:
            break
    return sign * n


@router.post("/api/esports/picks")
async def post_pick(request: Request, x_device_id: Optional[str] = Header(None)):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "device id required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    match_key = data.get("matchKey")
    side = data.get("side")
    lock_at = data.get("lockAt")

    if not match_key or not str(match_key).strip():
        return _json({"error": "matchKey required"}, status=400)
    if side not in ("A", "B"):
        return _json({"error": "side must be A or B"}, status=400)

    match_key = str(match_key).strip()
    if lock_at is not None:
        try:
            lock_at = int(lock_at)
        except Exception:
            lock_at = None

    now = int(time.time() * 1000)

    c = _conn()
    try:
        row = c.execute(
            "SELECT settled_at FROM esports_picks WHERE device_id=? AND match_key=?",
            (device_id, match_key),
        ).fetchone()
        if row is not None and row["settled_at"] is not None:
            return _json({"error": "already settled"}, status=409)

        # INSERT OR REPLACE so an unsettled existing pick is overwritten with the
        # new side/lock_at and a fresh created_at. A settled row never reaches
        # here (returned 409 above).
        c.execute(
            """INSERT OR REPLACE INTO esports_picks
               (device_id, match_key, side, created_at, lock_at,
                settled_at, result, points, crowd_share_at_lock)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL)""",
            (device_id, match_key, side, now, lock_at),
        )
        c.commit()
    finally:
        c.close()

    return _json({"matchKey": match_key, "side": side, "lockAt": lock_at, "createdAt": now})


@router.delete("/api/esports/picks")
async def delete_pick(
    matchKey: Optional[str] = Query(None),
    x_device_id: Optional[str] = Header(None),
):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "device id required"}, status=400)
    if not matchKey or not str(matchKey).strip():
        return _json({"error": "matchKey required"}, status=400)
    match_key = str(matchKey).strip()

    c = _conn()
    try:
        res = c.execute(
            "DELETE FROM esports_picks WHERE device_id=? AND match_key=? AND settled_at IS NULL",
            (device_id, match_key),
        )
        c.commit()
        deleted = (res.rowcount or 0) > 0
    finally:
        c.close()

    return _json({"deleted": deleted})


@router.get("/api/esports/picks/me")
async def get_my_picks(x_device_id: Optional[str] = Header(None)):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "device id required"}, status=400)

    c = _conn()
    try:
        rows = c.execute(
            "SELECT match_key, side, created_at, lock_at, settled_at, result, points "
            "FROM esports_picks WHERE device_id=? ORDER BY created_at DESC",
            (device_id,),
        ).fetchall()
        picks = [
            {
                "matchKey": r["match_key"],
                "side": r["side"],
                "createdAt": r["created_at"],
                "lockAt": r["lock_at"],
                "settledAt": r["settled_at"],
                "result": r["result"],
                "points": r["points"],
            }
            for r in rows
        ]

        wins = losses = voids = 0
        for r in c.execute(
            "SELECT result FROM esports_picks WHERE device_id=? AND settled_at IS NOT NULL",
            (device_id,),
        ).fetchall():
            res = r["result"]
            if res == "win":
                wins += 1
            elif res == "loss":
                losses += 1
            elif res == "void":
                voids += 1

        seq = [
            r["result"]
            for r in c.execute(
                "SELECT result FROM esports_picks "
                "WHERE device_id=? AND settled_at IS NOT NULL AND result IN ('win','loss') "
                "ORDER BY settled_at DESC",
                (device_id,),
            ).fetchall()
        ]
        streak = _signed_streak(seq)
    finally:
        c.close()

    return _json(
        {
            "picks": picks,
            "record": {"wins": wins, "losses": losses, "voids": voids, "streak": streak},
        }
    )


@router.get("/api/esports/crowd")
async def get_crowd(matchKey: Optional[str] = Query(None)):
    if not matchKey or not str(matchKey).strip():
        return _json({"error": "matchKey required"}, status=400)
    match_key = str(matchKey).strip()

    c = _conn()
    try:
        counts = {"A": 0, "B": 0}
        for r in c.execute(
            "SELECT side, COUNT(*) AS n FROM esports_picks WHERE match_key=? GROUP BY side",
            (match_key,),
        ).fetchall():
            counts[r["side"]] = r["n"]
        a = counts["A"]
        b = counts["B"]
        total = a + b
        shareA = (a / total) if total else None
    finally:
        c.close()

    return _json({"countA": a, "countB": b, "total": total, "shareA": shareA})


@router.get("/api/esports/leaderboard")
async def get_leaderboard(window: str = Query("season")):
    c = _conn()
    try:
        rows = c.execute(
            """
            SELECT device_id,
                   COALESCE(SUM(CASE WHEN result='win' THEN 1 ELSE 0 END), 0) AS wins,
                   COALESCE(SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END), 0) AS losses,
                   COALESCE(SUM(CASE WHEN result IN ('win','loss')
                                     THEN COALESCE(points, 0) ELSE 0 END), 0) AS points
            FROM esports_picks
            WHERE settled_at IS NOT NULL
            GROUP BY device_id
            ORDER BY wins DESC, COALESCE(points, 0) DESC
            LIMIT 50
            """
        ).fetchall()

        # Signed streak per device (most recent consecutive win/loss run).
        seq_by_device = {}
        for r in c.execute(
            "SELECT device_id, result FROM esports_picks "
            "WHERE settled_at IS NOT NULL AND result IN ('win','loss') ORDER BY settled_at DESC"
        ).fetchall():
            seq_by_device.setdefault(r["device_id"], []).append(r["result"])

        leaders = []
        for r in rows:
            seq = seq_by_device.get(r["device_id"], [])
            leaders.append(
                {
                    "deviceId": r["device_id"],
                    "wins": r["wins"],
                    "losses": r["losses"],
                    "streak": _signed_streak(seq),
                    "points": r["points"],
                }
            )
    finally:
        c.close()

    return _json({"leaders": leaders})
