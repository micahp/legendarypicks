#!/usr/bin/env python3
"""ufc_settle.py — settle UFC props from durable per-fight logs."""
import datetime as dt
import json
import sqlite3
from typing import Optional

from settlement.market_mapping import normalize_market, MARKET_ALIASES
from settlement.grading import _grade_actual
from core_markets import ufc_actual


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

_UFC_FINISH_MARKETS = {"finishes"}


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
    """Compatibility wrapper around the shared published result/method contract."""
    canonical = normalize_market(market)
    canonical = MARKET_ALIASES.get(canonical, canonical)
    return ufc_actual(stats, canonical)


def _ufcstats_game_is_final(
    con: sqlite3.Connection, game_id: int, date_text: str
) -> bool:
    """Prove finality from completed UFCStats profile rows when available.

    UFCStats fighter profiles contain completed bouts only.  Requiring one
    unambiguous, result-bearing row on the exact game date for every fighter
    carrying a numeric prop lets settlement stay source-complete when ESPN's
    scoreboard is unavailable.  Method-only cards still use the legacy
    scoreboard finality path until their fighters enter this ingest scope.
    """
    has_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='player_game_logs_ufcstats'"
    ).fetchone() is not None
    if not has_table:
        return False
    player_ids = [
        int(row[0])
        for row in con.execute(
            """SELECT DISTINCT player_id FROM props
                 WHERE game_id=?
                   AND market IN ('significant_strikes','fight_time')
                 ORDER BY player_id""",
            (game_id,),
        ).fetchall()
    ]
    if not player_ids:
        return False
    for player_id in player_ids:
        rows = con.execute(
            """SELECT stats FROM player_game_logs_ufcstats
                 WHERE league='ufc' AND player_id=?
                   AND date(game_date) BETWEEN date(?,'-1 day') AND date(?,'+1 day')""",
            (player_id, str(date_text or "")[:10], str(date_text or "")[:10]),
        ).fetchall()
        if len(rows) != 1:
            return False
        try:
            stats = json.loads(rows[0][0] or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if str(stats.get("result") or "").upper() not in {"W", "L", "D", "NC"}:
            return False
        if not str(stats.get("method") or "").strip():
            return False
    return True


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

    # UFCStats uses its own fighter and fight ids, so its rows stay in a
    # provider-specific table and resolve through the canonical player id plus
    # the published fight date. A fighter cannot have two UFC bouts on one day;
    # more than one row remains pending rather than guessing.
    ufcstats_by_player = {}
    has_ufcstats = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='player_game_logs_ufcstats'"
    ).fetchone() is not None
    if has_ufcstats:
        for row in con.execute(
            """SELECT player_id,source_player_key,stats
                 FROM player_game_logs_ufcstats
                WHERE league='ufc'
                  AND date(game_date) BETWEEN date(?,'-1 day') AND date(?,'+1 day')""",
            (str(game["date"] or "")[:10], str(game["date"] or "")[:10]),
        ).fetchall():
            ufcstats_by_player.setdefault(str(row["player_id"]), []).append(row)

    settled = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    supported = (
        set(_UFC_NUMERIC_MARKETS)
        | set(_UFC_METHOD_MARKETS)
        | _UFC_FINISH_MARKETS
    )

    for prop in props:
        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        if canonical not in supported:
            unmappable += 1
            continue

        source_matches = ufcstats_by_player.get(str(prop["player_id"]), [])
        if len(source_matches) == 1:
            matches = source_matches
        elif len(source_matches) > 1:
            pending += 1
            continue
        elif prop["espn_id"]:
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
