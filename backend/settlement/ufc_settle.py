#!/usr/bin/env python3
"""ufc_settle.py — settle UFC props from durable per-fight logs."""
import datetime as dt
import json
import sqlite3
from typing import Optional

from settlement.market_mapping import normalize_market, MARKET_ALIASES
from settlement.grading import _grade_actual


_UFC_NUMERIC_MARKETS = {
    "significant_strikes": "sigStrikesLanded",
    "fight_time": "fight_time",
}

_UFC_METHOD_MARKETS = {
    "win_by_decision": "DEC",
    "win_by_ko": "KO/TKO",
    "knockouts": "KO/TKO",
    "win_by_submission": "SUB",
    "submissions": "SUB",
}


def _ufc_scoreboard_competition(espn, date_text: str, fight_id: str) -> dict:
    """Return the exact fight object from ESPN's card-level UFC scoreboard."""
    path = espn.LEAGUES["ufc"][0]
    wanted = str(fight_id)
    checked = []
    for day in espn.neighbor_dates(date_text):
        checked.append(day)
        date_key = str(day or "").replace("-", "")
        payload = espn._get(
            espn._SITE.format(path=path) + f"/scoreboard?dates={date_key}", ttl=60)
        for event in payload.get("events") or []:
            for competition in event.get("competitions") or []:
                if str(competition.get("id") or "") == wanted:
                    return competition
    raise ValueError(
        f"UFC fight {wanted} absent from scoreboards {', '.join(checked)}")


def _ufc_actual(stats: dict, market: str) -> Optional[float]:
    """Read a supported UFC actual from one durable per-fight log."""
    canonical = normalize_market(market)
    canonical = MARKET_ALIASES.get(canonical, canonical)
    stat_key = _UFC_NUMERIC_MARKETS.get(canonical)
    if stat_key:
        value = stats.get(stat_key)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    wanted_method = _UFC_METHOD_MARKETS.get(canonical)
    if not wanted_method:
        return None
    result = str(stats.get("result") or "").strip().upper()
    method = str(stats.get("method") or "").strip().upper()
    if result == "W":
        if not method:
            return None
        return 1.0 if method == wanted_method else 0.0
    if result in {"L", "D", "NC"}:
        return 0.0
    return None


def _settle_ufc_props(con: sqlite3.Connection, game, props: list) -> dict:
    """Grade UFC props from durable per-fighter, per-fight actuals."""
    logs = con.execute(
        "SELECT player_id, source_player_key, stats FROM player_game_logs "
        "WHERE league='ufc' AND game_id=?",
        (str(game["espn_event_id"]),)).fetchall()
    by_player_id = {}
    by_espn_id = {}
    for row in logs:
        if row["player_id"] is not None:
            by_player_id.setdefault(str(row["player_id"]), []).append(row)
        if row["source_player_key"]:
            by_espn_id.setdefault(str(row["source_player_key"]), []).append(row)

    settled = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    supported = set(_UFC_NUMERIC_MARKETS) | set(_UFC_METHOD_MARKETS)

    for prop in props:
        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        if canonical not in supported:
            unmappable += 1
            continue

        if prop["espn_id"]:
            matches = by_espn_id.get(str(prop["espn_id"]), [])
        else:
            matches = by_player_id.get(str(prop["player_id"]), [])
        if len(matches) != 1:
            pending += 1
            continue

        try:
            stats = json.loads(matches[0]["stats"] or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            errors += 1
            continue
        actual = _ufc_actual(stats, canonical)
        if actual is None:
            pending += 1
            continue
        try:
            if _grade_actual(con, prop, actual, now):
                settled += 1
            else:
                unmappable += 1
        except Exception:
            errors += 1

    con.commit()
    return {"settled": settled, "void": 0, "unmappable": unmappable,
            "pending": pending, "errors": errors}
