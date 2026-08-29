#!/usr/bin/env python3
"""settle_game.py — top-level driver: grade all unsettled props for one game."""
import datetime as dt
import sqlite3

from settlement.market_mapping import resolve_market
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

# The soccer competitions that grade off the roster-stat surface.
_SOCCER_LEAGUES = ("mls", "lcup", "ligamx")


def settle_game(con: sqlite3.Connection, game_id: int) -> dict:
    """Settle all unsettled props for one prop_games row."""
    import espn_client as espn

    game = con.execute(
        "SELECT id, league, home, away, date, espn_event_id, final_home, final_away, "
        "start_time FROM prop_games WHERE id=?",
        (game_id,)
    ).fetchone()
    if not game:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1, "error_msg": "game not found"}

    league = game["league"]
    espn_event_id = game["espn_event_id"]
    if not espn_event_id and league != "mlb":
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                "msg": f"game {game_id}: no espn_event_id, cannot pull boxscore"}
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
                return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                        "msg": f"game {game_id}: not final yet (no ESPN link; MLB "
                               f"gamePk={pk or 'unresolved'})"}
            con.execute("UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                        (final[0], final[1], game_id))
            con.commit()
            game = dict(game, final_home=final[0], final_away=final[1])

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
                return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                        "msg": f"game {game_id}: not final yet (state={result['state']}, "
                               f"completed={result.get('completed')})"}
            if league != "ufc":
                con.execute(
                    "UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                    (result.get("home_score"), result.get("away_score"), game_id))
                con.commit()
        except Exception as e:
            return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
                    "error_msg": f"game {game_id}: ESPN pull failed: {e}"}

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

    # Every soccer competition grades off the same published surface. Dispatching
    # on `mls` alone meant a Leagues Cup fixture fell through to the boxscore
    # path below, which soccer summaries do not populate -- `boxscore` carries
    # only `teams` for these events, the per-player stats live under `rosters`.
    if league in _SOCCER_LEAGUES:
        try:
            summary = espn.summary(league, espn_event_id)
        except Exception as e:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 1,
                    "error_msg": f"game {game_id}: {league} summary pull failed: {e}"}
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
        return _settle_mls_props(con, props, summary)

    # Pull boxscore
    try:
        box = espn.boxscore(league, espn_event_id)
    except Exception as e:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
                "error_msg": f"game {game_id}: boxscore pull failed: {e}"}

    if not box:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
                "error_msg": f"game {game_id}: empty boxscore returned"}

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
        if category is None and stat_key is None:
            if "hits_runs_rbis" in prop["market"]:
                actual = _find_player_compound_stat(
                    box, prop["player_name"], prop["player_team"],
                    ["batting", "batting", "batting"], ["H", "R", "RBI"],
                    espn_id=prop["espn_id"])
            else:
                unmappable += 1
                continue
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
