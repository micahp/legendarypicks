from __future__ import annotations

"""Anonymous UFC fight pick-em ledger and lazy settlement."""

import datetime as dt
import os
import sqlite3
import time
from typing import Optional

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

import espn_client as espn


_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "picks.db"
)
_METHODS = ("KO/TKO", "SUB", "DEC")
_CONTRARIAN_K = 1.0
_SCAN_DAYS = 21
_UPCOMING_TTL_SECONDS = 60
_upcoming_cache = {"expires_at": 0.0, "fights": []}


def _conn():
    connection = sqlite3.connect(_DB)
    connection.row_factory = sqlite3.Row
    return connection


def _init_db():
    """Create the UFC ledger once without making an optional feature fatal."""
    try:
        connection = _conn()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ufc_picks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    fight_key TEXT NOT NULL,
                    pick_side TEXT NOT NULL CHECK (pick_side IN ('home','away')),
                    pick_method TEXT CHECK (
                        pick_method IS NULL OR pick_method IN ('KO/TKO','SUB','DEC')
                    ),
                    fighter_name TEXT NOT NULL,
                    opponent_name TEXT NOT NULL,
                    fighter_id TEXT,
                    opponent_id TEXT,
                    card_date TEXT,
                    created_at INTEGER NOT NULL,
                    lock_at INTEGER,
                    settled_at INTEGER,
                    result TEXT,
                    method_result TEXT,
                    points REAL,
                    crowd_share_at_lock REAL,
                    UNIQUE(device_id, fight_key)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ufc_picks_fight ON ufc_picks(fight_key)"
            )
            connection.commit()
        finally:
            connection.close()
    except Exception:
        # A ledger initialization failure must not prevent the sports API from starting.
        pass


_init_db()

router = APIRouter()


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status)


def _device_id(x_device_id: Optional[str]) -> Optional[str]:
    if not x_device_id:
        return None
    device_id = x_device_id.strip()
    return device_id or None


def _iso_to_ms(value) -> Optional[int]:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _compact_fight(game, card_date: str):
    home = game.get("home") or {}
    away = game.get("away") or {}
    fight_key = str(game.get("game_id") or "").strip()
    if not fight_key or not home.get("name") or not away.get("name"):
        return None
    return {
        "fightKey": fight_key,
        "date": game.get("date"),
        "event": game.get("event") or "UFC",
        "cardSegment": game.get("card_segment") or "",
        "state": game.get("state") or "pre",
        "home": {
            "id": str(home.get("id") or ""),
            "name": home.get("name"),
            "record": home.get("record") or "",
        },
        "away": {
            "id": str(away.get("id") or ""),
            "name": away.get("name"),
            "record": away.get("record") or "",
        },
        "lockAt": _iso_to_ms(game.get("date")),
        "_cardDate": card_date,
    }


def _scan_upcoming_fights():
    """Return the first scheduled UFC card found from today through 21 days."""
    now = time.time()
    if now < _upcoming_cache["expires_at"]:
        return _upcoming_cache["fights"]

    first_date = dt.date.today()
    for offset in range(_SCAN_DAYS + 1):
        card_date = (first_date + dt.timedelta(days=offset)).isoformat()
        games = espn.games("ufc", card_date)
        fights = []
        for game in games:
            if game.get("state") != "pre":
                continue
            fight = _compact_fight(game, card_date)
            if fight:
                fights.append(fight)
        if fights:
            fights.sort(key=lambda fight: (fight.get("lockAt") is None, fight.get("lockAt") or 0))
            _upcoming_cache["fights"] = fights
            _upcoming_cache["expires_at"] = now + _UPCOMING_TTL_SECONDS
            return fights

    _upcoming_cache["fights"] = []
    _upcoming_cache["expires_at"] = now + _UPCOMING_TTL_SECONDS
    return []


def _public_fight(fight):
    return {key: value for key, value in fight.items() if not key.startswith("_")}


def _signed_streak(results):
    sequence = [result for result in results if result in ("win", "loss")]
    if not sequence:
        return 0
    first = sequence[0]
    count = 0
    for result in sequence:
        if result != first:
            break
        count += 1
    return count if first == "win" else -count


def _tally(connection, fight_key):
    counts = {"home": 0, "away": 0}
    for row in connection.execute(
        "SELECT pick_side, COUNT(*) AS n FROM ufc_picks WHERE fight_key=? GROUP BY pick_side",
        (fight_key,),
    ).fetchall():
        counts[row["pick_side"]] = row["n"]
    home = counts["home"]
    away = counts["away"]
    return home, away, home + away


def _finished_method(fight) -> Optional[str]:
    """Best-effort normalized method for a finished ESPN competition."""
    winner = next(
        (
            fighter
            for fighter in (fight.get("home") or {}, fight.get("away") or {})
            if fighter.get("winner") is True
        ),
        None,
    )
    fighter_id = str((winner or {}).get("id") or "")
    if not fighter_id:
        return None
    try:
        history = espn.ufc_fight_history(fighter_id, limit=5)
    except Exception:
        return None
    fight_key = str(fight.get("game_id") or "")
    for result in history:
        if str(result.get("fight_id") or "") == fight_key:
            method = result.get("method")
            return method if method in _METHODS else None
    return None


def settle_finished() -> int:
    """Settle open picks from ESPN's finished UFC scoreboard data."""
    settled = 0
    now = int(time.time() * 1000)
    try:
        connection = _conn()
        try:
            open_fights = connection.execute(
                """
                SELECT fight_key, card_date, lock_at
                FROM ufc_picks
                WHERE settled_at IS NULL
                GROUP BY fight_key, card_date, lock_at
                """
            ).fetchall()
            if not open_fights:
                return 0

            scoreboards = {}
            for row in open_fights:
                card_date = row["card_date"]
                if not card_date and row["lock_at"]:
                    card_date = dt.datetime.fromtimestamp(
                        row["lock_at"] / 1000, tz=dt.timezone.utc
                    ).date().isoformat()
                if not card_date:
                    continue
                if card_date not in scoreboards:
                    try:
                        scoreboards[card_date] = espn.games("ufc", card_date)
                    except Exception:
                        scoreboards[card_date] = []

                fight_key = row["fight_key"]
                fight = next(
                    (
                        game
                        for game in scoreboards[card_date]
                        if str(game.get("game_id") or "") == fight_key
                    ),
                    None,
                )
                if not fight or fight.get("state") != "post":
                    continue

                home = fight.get("home") or {}
                away = fight.get("away") or {}
                if home.get("winner") is True:
                    winning_side = "home"
                elif away.get("winner") is True:
                    winning_side = "away"
                else:
                    winning_side = None

                actual_method = _finished_method(fight) if winning_side else None
                count_home, count_away, total = _tally(connection, fight_key)
                shares = {
                    "home": count_home / total if total else None,
                    "away": count_away / total if total else None,
                }
                rows = connection.execute(
                    """
                    SELECT id, pick_side, pick_method
                    FROM ufc_picks
                    WHERE fight_key=? AND settled_at IS NULL
                    """,
                    (fight_key,),
                ).fetchall()
                for pick in rows:
                    if winning_side is None:
                        result = "void"
                        points = None
                        share = None
                        method_result = None
                    else:
                        won = pick["pick_side"] == winning_side
                        result = "win" if won else "loss"
                        share = shares[pick["pick_side"]]
                        points = (
                            1.0 + _CONTRARIAN_K * (1.0 - (share if share is not None else 1.0))
                            if won
                            else 0.0
                        )
                        method_result = None
                        if pick["pick_method"] and actual_method:
                            method_result = (
                                "win" if pick["pick_method"] == actual_method else "loss"
                            )
                    connection.execute(
                        """
                        UPDATE ufc_picks
                        SET settled_at=?, result=?, method_result=?, points=?,
                            crowd_share_at_lock=?
                        WHERE id=?
                        """,
                        (now, result, method_result, points, share, pick["id"]),
                    )
                    settled += 1
            connection.commit()
        finally:
            connection.close()
    except Exception:
        pass
    return settled


@router.get("/api/ufc/upcoming")
async def get_upcoming():
    try:
        fights = [_public_fight(fight) for fight in _scan_upcoming_fights()]
    except Exception:
        return _json({"fights": [], "error": "UFC schedule unavailable"}, status=502)
    return _json({"fights": fights})


@router.post("/api/ufc/picks")
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

    fight_key = str(data.get("fightKey") or "").strip()
    side = data.get("side")
    method = data.get("method")
    if not fight_key:
        return _json({"error": "fightKey required"}, status=400)
    if side not in ("home", "away"):
        return _json({"error": "side must be home or away"}, status=400)
    if method is not None and method not in _METHODS:
        return _json({"error": "method must be KO/TKO, SUB, or DEC"}, status=400)

    try:
        fight = next(
            (item for item in _scan_upcoming_fights() if item["fightKey"] == fight_key),
            None,
        )
    except Exception:
        return _json({"error": "UFC schedule unavailable"}, status=502)
    if not fight:
        return _json({"error": "fight not found or already started"}, status=404)

    now = int(time.time() * 1000)
    lock_at = fight.get("lockAt")
    if fight.get("state") != "pre" or lock_at is None or now >= lock_at:
        return _json({"error": "fight is locked"}, status=409)

    fighter = fight[side]
    opponent = fight["away" if side == "home" else "home"]
    connection = _conn()
    try:
        row = connection.execute(
            "SELECT settled_at FROM ufc_picks WHERE device_id=? AND fight_key=?",
            (device_id, fight_key),
        ).fetchone()
        if row is not None and row["settled_at"] is not None:
            return _json({"error": "already settled"}, status=409)

        connection.execute(
            """
            INSERT OR REPLACE INTO ufc_picks
                (device_id, fight_key, pick_side, pick_method,
                 fighter_name, opponent_name, fighter_id, opponent_id, card_date,
                 created_at, lock_at, settled_at, result, method_result,
                 points, crowd_share_at_lock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
            """,
            (
                device_id,
                fight_key,
                side,
                method,
                fighter["name"],
                opponent["name"],
                fighter.get("id"),
                opponent.get("id"),
                fight.get("_cardDate"),
                now,
                lock_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return _json(
        {
            "fightKey": fight_key,
            "side": side,
            "method": method,
            "fighterName": fighter["name"],
            "opponentName": opponent["name"],
            "lockAt": lock_at,
            "createdAt": now,
        }
    )


@router.delete("/api/ufc/picks")
async def delete_pick(
    fightKey: Optional[str] = Query(None),
    x_device_id: Optional[str] = Header(None),
):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "device id required"}, status=400)
    fight_key = str(fightKey or "").strip()
    if not fight_key:
        return _json({"error": "fightKey required"}, status=400)

    connection = _conn()
    try:
        result = connection.execute(
            """
            DELETE FROM ufc_picks
            WHERE device_id=? AND fight_key=? AND settled_at IS NULL
            """,
            (device_id, fight_key),
        )
        connection.commit()
        deleted = (result.rowcount or 0) > 0
    finally:
        connection.close()
    return _json({"deleted": deleted})


@router.get("/api/ufc/picks/me")
async def get_my_picks(x_device_id: Optional[str] = Header(None)):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "device id required"}, status=400)

    settle_finished()
    connection = _conn()
    try:
        rows = connection.execute(
            """
            SELECT fight_key, pick_side, pick_method, fighter_name, opponent_name,
                   created_at, lock_at, settled_at, result, method_result, points
            FROM ufc_picks
            WHERE device_id=?
            ORDER BY created_at DESC
            """,
            (device_id,),
        ).fetchall()
        picks = [
            {
                "fightKey": row["fight_key"],
                "side": row["pick_side"],
                "method": row["pick_method"],
                "fighterName": row["fighter_name"],
                "opponentName": row["opponent_name"],
                "createdAt": row["created_at"],
                "lockAt": row["lock_at"],
                "settledAt": row["settled_at"],
                "result": row["result"],
                "methodResult": row["method_result"],
                "points": row["points"],
            }
            for row in rows
        ]

        results = [
            row["result"]
            for row in connection.execute(
                """
                SELECT result
                FROM ufc_picks
                WHERE device_id=? AND settled_at IS NOT NULL
                """,
                (device_id,),
            ).fetchall()
        ]
        wins = results.count("win")
        losses = results.count("loss")
        voids = results.count("void")
        sequence = [
            row["result"]
            for row in connection.execute(
                """
                SELECT result
                FROM ufc_picks
                WHERE device_id=? AND settled_at IS NOT NULL
                  AND result IN ('win','loss')
                ORDER BY settled_at DESC
                """,
                (device_id,),
            ).fetchall()
        ]
    finally:
        connection.close()

    return _json(
        {
            "picks": picks,
            "record": {
                "wins": wins,
                "losses": losses,
                "voids": voids,
                "streak": _signed_streak(sequence),
            },
        }
    )


@router.get("/api/ufc/crowd")
async def get_crowd(fightKey: Optional[str] = Query(None)):
    fight_key = str(fightKey or "").strip()
    if not fight_key:
        return _json({"error": "fightKey required"}, status=400)

    connection = _conn()
    try:
        count_home, count_away, total = _tally(connection, fight_key)
    finally:
        connection.close()
    return _json(
        {
            "countHome": count_home,
            "countAway": count_away,
            "total": total,
            "shareHome": count_home / total if total else None,
        }
    )
