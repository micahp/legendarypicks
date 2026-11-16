"""Settle NBA props from the latest published SportsDataverse boxscore release."""
import datetime as dt
import sqlite3
from typing import Optional

import nba_sportsdataverse
from settlement.market_mapping import resolve_market


def settle_from_sportsdataverse(con: sqlite3.Connection, game_id: int,
                                espn_event_id: str, props) -> Optional[dict]:
    """Settle only when the event is present in a complete active release.

    A missing player row in a published game stays pending. Only an explicit
    source DNP is voided; no absent line is turned into zero.
    """
    source_game = nba_sportsdataverse.current_source_game(con, espn_event_id)
    if source_game is None:
        return None

    settled = void = unmappable = pending = errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for prop in props:
        row = nba_sportsdataverse.current_player_line(
            con, prop["player_id"], espn_event_id
        ) if prop["player_id"] is not None else None
        if row is None:
            pending += 1
            continue

        if row["appearance_status"] == "dnp":
            actual = None
            hit = None
            outcome = "void"
        elif row["appearance_status"] != "played":
            pending += 1
            continue
        else:
            if resolve_market("nba", prop["market"]) is None:
                unmappable += 1
                continue
            actual = nba_sportsdataverse.value_for_market(row["stats"], prop["market"])
            if actual is None:
                pending += 1
                continue
            side = str(prop["side"] or "").lower()
            if side == "over":
                hit = 1 if actual > prop["line"] else (0 if actual < prop["line"] else None)
            elif side == "under":
                hit = 1 if actual < prop["line"] else (0 if actual > prop["line"] else None)
            else:
                unmappable += 1
                continue
            outcome = "settled"

        try:
            con.execute(
                "INSERT INTO prop_results(prop_id,actual_value,hit,settled_at) VALUES(?,?,?,?)",
                (prop["id"], actual, hit, now),
            )
            if outcome == "void":
                void += 1
            else:
                settled += 1
        except sqlite3.IntegrityError:
            errors += 1

    con.commit()
    return {
        "settled": settled,
        "void": void,
        "unmappable": unmappable,
        "pending": pending,
        "errors": errors,
        "msg": "game {}: SportsDataverse NBA Stats boxscore".format(game_id),
    }
