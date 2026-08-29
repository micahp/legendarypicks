#!/usr/bin/env python3
"""Settle World Cup player markets from durable completed-match logs."""
import datetime as dt
import json
import sqlite3

from settlement.grading import _grade_actual
from settlement.market_mapping import normalize_market


_WC_LOG_MARKETS = {
    "goals": "goals",
    "assists": "assists",
    "shots": "shots",
    "shots_on_target": "sot",
    "shots_on_goal": "sot",
}


def _wc_actual(con: sqlite3.Connection, event_id: str, player_id: int,
               market: str):
    """Return ``(actual, reason)``; actual is numeric only on unique evidence."""
    stat_key = _WC_LOG_MARKETS.get(normalize_market(market))
    if not stat_key:
        return None, "unmappable_market"
    rows = con.execute(
        "SELECT stats FROM player_game_logs "
        "WHERE league='wc' AND game_id=? AND player_id=?",
        (str(event_id), player_id),
    ).fetchall()
    if not rows:
        return None, "no_player_log"
    if len(rows) != 1:
        return None, "ambiguous_player_log"
    try:
        stats = json.loads(rows[0]["stats"] if hasattr(rows[0], "keys") else rows[0][0])
        if stats.get("did_not_play") == 1:
            return None, "did_not_play"
        value = stats.get(stat_key)
        return (float(value), "") if value is not None else (None, "missing_stat")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, "invalid_stats"


def _settle_wc_props(con: sqlite3.Connection, event_id: str, props,
                     overwrite: bool = False) -> dict:
    counts = {"settled": 0, "void": 0, "unmappable": 0,
              "pending": 0, "errors": 0}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for prop in props:
        actual, reason = _wc_actual(
            con, event_id, prop["player_id"], prop["market"])
        if actual is None:
            if reason == "unmappable_market":
                counts["unmappable"] += 1
            elif reason == "did_not_play":
                try:
                    con.execute(
                        "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) "
                        "VALUES (?,NULL,NULL,?)",
                        (prop["id"], now))
                    counts["void"] += 1
                except sqlite3.Error:
                    counts["errors"] += 1
            else:
                counts["pending"] += 1
            continue
        try:
            if _grade_actual(con, prop, actual, now, overwrite=overwrite):
                counts["settled"] += 1
            else:
                counts["unmappable"] += 1
        except sqlite3.Error:
            counts["errors"] += 1
    con.commit()
    return counts
