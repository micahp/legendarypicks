#!/usr/bin/env python3
"""settle_game.py — top-level driver: grade all unsettled props for one game."""
import datetime as dt
import sqlite3

from settlement.market_mapping import resolve_market, resolve_compound_market
from settlement.boxscore_extract import _find_player_stat, _find_player_compound_stat
import sys

from settlement.mlb_api import _fetch_mlb_gamepk, _fetch_mlb_final
from settlement.mlb_settle import _settle_mlb_props
from settlement.ufc_settle import (
    _settle_ufc_props,
    _ufc_scoreboard_competition,
    _ufcstats_game_is_final,
)
from settlement.mls_settle import _settle_mls_props
from settlement.tennis_settle import _settle_tennis_props, _tennis_snapshot
from settlement.wc_settle import _settle_wc_props

# The soccer competitions that grade off the roster-stat surface.
_SOCCER_LEAGUES = ("mls", "lcup", "ligamx")


def _unsettled_count(con: sqlite3.Connection, game_id: int) -> int:
    """Count the props an early-return leaves open.

    Every normal settler accounts for each input as settled, pending, or
    unmappable.  The finality/link/source guards must preserve that denominator
    too; returning ``pending=0`` for a game with no snapshot made hundreds of
    real props disappear from the batch summary.
    """
    return int(con.execute("""
        SELECT COUNT(*)
        FROM props p
        LEFT JOIN prop_results pr ON pr.prop_id=p.id
        WHERE p.game_id=? AND pr.prop_id IS NULL
    """, (game_id,)).fetchone()[0])


def _pending_result(con: sqlite3.Connection, game_id: int, *, msg: str = "",
                    error_msg: str = "", errors: int = 0) -> dict:
    result = {"settled": 0, "void": 0, "unmappable": 0,
              "pending": _unsettled_count(con, game_id), "errors": errors}
    if msg:
        result["msg"] = msg
    if error_msg:
        result["error_msg"] = error_msg
    return result


def _void_cancelled_game(con: sqlite3.Connection, game_id: int) -> dict:
    """Persist one terminal NULL result per open prop on a sourced cancellation."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    prop_ids = [row[0] for row in con.execute(
        "SELECT p.id FROM props p LEFT JOIN prop_results pr ON pr.prop_id=p.id "
        "WHERE p.game_id=? AND pr.prop_id IS NULL", (game_id,))]
    con.executemany(
        "INSERT INTO prop_results(prop_id,actual_value,hit,settled_at) "
        "VALUES (?,NULL,NULL,?)",
        ((prop_id, now) for prop_id in prop_ids),
    )
    con.commit()
    return {"settled": 0, "void": len(prop_ids), "unmappable": 0,
            "pending": 0, "errors": 0,
            "msg": f"game {game_id}: publisher-confirmed cancellation"}


def settle_game(con: sqlite3.Connection, game_id: int) -> dict:
    """Settle all unsettled props for one prop_games row."""
    import espn_client as espn

    game_columns = {row[1] for row in con.execute("PRAGMA table_info(prop_games)")}
    cancellation = ("cancelled_at, cancel_reason, cancel_source"
                    if "cancelled_at" in game_columns
                    else "NULL AS cancelled_at, NULL AS cancel_reason, NULL AS cancel_source")
    game = con.execute(
        "SELECT id, league, home, away, date, espn_event_id, final_home, final_away, "
        f"start_time, {cancellation} FROM prop_games WHERE id=?",
        (game_id,)
    ).fetchone()
    if not game:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1, "error_msg": "game not found"}

    if game["cancelled_at"] and game["cancel_source"]:
        return _void_cancelled_game(con, game_id)

    league = game["league"]
    espn_event_id = game["espn_event_id"]
    if not espn_event_id and league != "mlb":
        return _pending_result(
            con, game_id,
            msg=f"game {game_id}: no durable publisher event link")
    if not espn_event_id:
        if game["final_home"] is None:
            # Through the PACKAGE, at call time. These were module-level names
            # on the pre-split settlement.py and the finality tests replace them
            # with stubs; against the copies this module bound at import, the
            # stubs are ignored and the test asserts against the live MLB Stats
            # API instead of its own fixture.
            _pkg = sys.modules["settlement"]
            pk = getattr(_pkg, "_fetch_mlb_gamepk", _fetch_mlb_gamepk)(
                game["date"], game["home"], game["away"],
                start_time=game["start_time"])
            final = getattr(_pkg, "_fetch_mlb_final", _fetch_mlb_final)(pk) if pk else None
            if not final:
                return _pending_result(
                    con, game_id,
                    msg=f"game {game_id}: not final yet (no ESPN link; MLB "
                        f"gamePk={pk or 'unresolved'})")
            con.execute("UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                        (final[0], final[1], game_id))
            con.commit()
            game = dict(game, final_home=final[0], final_away=final[1])

    # Tennis settlement is DB-first. The scoreboard ingest already persists the
    # per-player set scores and completion state needed by every tennis market we
    # accept; issuing one summary/boxscore request per prop_game would add fan-out
    # and the generic team-sport parser cannot identify tennis athletes anyway.
    if league in ("atp", "wta"):
        snapshot = _tennis_snapshot(con, league, espn_event_id)
        if not snapshot:
            return _pending_result(
                con, game_id,
                msg=f"game {game_id}: no durable tennis scoreboard snapshot")
        if snapshot["state"] != "post":
            return _pending_result(
                con, game_id,
                msg=f"game {game_id}: tennis snapshot is "
                    f"{snapshot['state'] or 'unknown'}")
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id,
                   pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 0, "msg": f"game {game_id}: no unsettled props"}
        return _settle_tennis_props(con, props, snapshot)

    # World Cup player logs are written only from publisher-completed matches.
    # They are the durable source for the four player markets we ingest, so no
    # per-game network request or generic team boxscore interpretation is needed.
    if league == "wc":
        published = con.execute(
            "SELECT 1 FROM player_game_logs WHERE league='wc' AND game_id=? LIMIT 1",
            (str(espn_event_id),),
        ).fetchone()
        if not published:
            return _pending_result(
                con, game_id,
                msg=f"game {game_id}: no completed World Cup player logs")
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id,
                   pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 0, "msg": f"game {game_id}: no unsettled props"}
        return _settle_wc_props(con, espn_event_id, props)

    # ── Is the game actually over? ──────────────────────────────────────────────
    ufcstats_final = (
        league == "ufc"
        and _ufcstats_game_is_final(con, game_id, game["date"])
    )
    if game["final_home"] is None and not ufcstats_final:
        try:
            if league == "ufc":
                competition = _ufc_scoreboard_competition(
                    espn, game["date"], espn_event_id)
                status_type = ((competition.get("status") or {}).get("type") or {})
                result = {
                    "state": status_type.get("state"),
                    "completed": status_type.get("completed") is True,
                }
            else:
                result = espn.game_result(league, espn_event_id)
            if not result.get("completed"):
                return _pending_result(
                    con, game_id,
                    msg=f"game {game_id}: not final yet (state={result['state']}, "
                        f"completed={result.get('completed')})")
            if league != "ufc":
                con.execute(
                    "UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                    (result.get("home_score"), result.get("away_score"), game_id))
                con.commit()
        except Exception as e:
            return _pending_result(
                con, game_id, errors=1,
                error_msg=f"game {game_id}: ESPN pull failed: {e}")

    # ── MLB: use MLB Stats API for accurate TB/doubles/strikeouts ──
    if league == "mlb":
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id, pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                    "msg": f"game {game_id}: no unsettled props"}
        import settlement
        result = settlement._settle_mlb_props(con, game, props)
        result.setdefault("errors", 0)
        return result

    if league == "ufc":
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id,
                   pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 0, "msg": f"game {game_id}: no unsettled props"}
        return _settle_ufc_props(con, game, props)

    # Every soccer competition grades from durable per-appearance rows.  A live
    # summary is retained only as a lazy fallback for first-goal ordering when
    # the stored first_goal field cannot answer that event market.
    if league in _SOCCER_LEAGUES:
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id,
                   pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 0, "msg": f"game {game_id}: no unsettled props"}
        return _settle_mls_props(
            con,
            game,
            props,
            summary_loader=lambda: espn.summary(league, espn_event_id),
        )

    # Pull boxscore
    try:
        box = espn.boxscore(league, espn_event_id)
    except Exception as e:
        return _pending_result(
            con, game_id, errors=1,
            error_msg=f"game {game_id}: boxscore pull failed: {e}")

    if not box:
        return _pending_result(
            con, game_id, errors=1,
            error_msg=f"game {game_id}: empty boxscore returned")

    # Find unsettled props for this game
    props = con.execute("""
        SELECT p.id, p.market, p.line, p.side, p.player_id, pl.name as player_name, pl.team as player_team,
               pl.espn_id as espn_id
        FROM props p
        JOIN players pl ON pl.id = p.player_id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE p.game_id = ? AND pr.prop_id IS NULL
    """, (game_id,)).fetchall()

    settled = 0
    void = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    for prop in props:
        mapping = resolve_market(league, prop["market"])
        if mapping is None:
            unmappable += 1
            continue

        category, stat_key = mapping

        # Handle compound stats
        if category is None:
            components = resolve_compound_market(league, prop["market"])
            if not components:
                unmappable += 1
                continue
            actual = _find_player_compound_stat(
                box, prop["player_name"], prop["player_team"],
                [component[0] for component in components],
                [component[1] for component in components],
                espn_id=prop["espn_id"], missing_as_zero=league == "ncaaf")
        else:
            actual = _find_player_stat(
                box, prop["player_name"], prop["player_team"],
                category, stat_key, espn_id=prop["espn_id"])

        if actual is None:
            pending += 1
            continue

        line = prop["line"]
        side = (prop["side"] or "").lower()
        if side == "over":
            hit = 1 if actual > line else (0 if actual < line else None)
        elif side == "under":
            hit = 1 if actual < line else (0 if actual > line else None)
        else:
            unmappable += 1
            continue

        try:
            con.execute(
                "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) VALUES (?,?,?,?)",
                (prop["id"], actual, hit, now))
            settled += 1
        except Exception as e:
            errors += 1

    con.commit()
    return {"settled": settled, "void": void, "unmappable": unmappable,
            "pending": pending, "errors": errors}
