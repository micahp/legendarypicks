"""direct — Bovada scraper direct layer."""
import re
import json
import os
import sys
import collections
import datetime as dt
import unicodedata
import urllib.request

import datetime as dt
import re
import unicodedata
from .config import _MINTED_PLAYERS  # noqa: E402
import espn_client as espn  # noqa: E402
from link_prop_games import link_prop_game, apply_start_time  # noqa: E402
from espn_client.scoreboard import _slate_day  # noqa: E402

def _wc_event_date(prop: dict, fallback: str, league: str) -> str:
    """The local slate day Bovada's startTime falls on, per `_slate_day`.

    This returned the UTC date until 2026-08-19, and that is the whole of the
    two-convention problem in `prop_games.date`. A 9:30pm Central kickoff is
    02:30Z the NEXT day, so the board filed tonight's late games under tomorrow
    while the scoreboard, which buckets by the local day, correctly said
    tonight. ESPN settles it: it returns event 761739 at 2026-08-20T02:30Z on
    its **Aug 19** board, so the local day is the publisher's own convention.

    The cost of the old value is not just a wrong date. It is that half the
    codebase grew a +/-1 day window to survive it -- `link_prop_games` searches
    neighbour slates, `settlement/mlb_api` tries three days, `ingest_underdog_props`
    matches `BETWEEN date-1 AND date+1`. Every one of those is compensation for
    this line.

    `league` is required rather than defaulted because `_slate_day` is not one
    rule: tennis buckets by UTC on purpose, everything else by America/New_York.
    A default would silently give one of them the wrong answer.
    """
    try:
        stamp = float(prop.get("start_time"))
        if stamp > 10_000_000_000:
            stamp /= 1000
        moment = dt.datetime.fromtimestamp(stamp, dt.timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return fallback
    return _slate_day(league, moment.isoformat().replace("+00:00", "Z")) or fallback

def _event_start_iso(prop: dict):
    """Full UTC kickoff datetime (ISO) from Bovada startTime, so the slate can show a game time and
    not just a date. None when the stamp is missing/unparseable."""
    try:
        stamp = float(prop.get("start_time"))
        if stamp > 10_000_000_000:
            stamp /= 1000
        return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None

def _wc_direct_ingest(all_props: list, today: str):
    """Direct DB insert for WC props — bypasses ingest API since WC players
    don't exist in the players table yet (Phase 1: name-match only).
    Creates player rows as needed."""
    import sqlite3, os as _os
    DB = _os.environ.get("LP_DB_PATH") or _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "data", "picks.db")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ingested = 0
    espn_by_date = {}

    try:
        by_game = {}
        for p in all_props:
            game_date = _wc_event_date(p, today, "wc")
            gkey = (game_date, p["game_desc"])
            if gkey not in by_game:
                by_game[gkey] = {
                    "date": game_date,
                    "home": p["home_team"],
                    "away": p["away_team"],
                    "props": []
                }
            by_game[gkey]["props"].append(p)

        for gkey, batch in by_game.items():
            print(f"  {batch['away']} @ {batch['home']}: {len(batch['props'])} props")
            game_start = _event_start_iso(batch["props"][0]) if batch["props"] else None
            cur = con.execute(
                "SELECT id,league,date,home,away,espn_event_id,start_time FROM prop_games "
                "WHERE league=? AND date=? AND home=? AND away=?",
                ("wc", batch["date"], batch["home"], batch["away"]))
            game_row = cur.fetchone()
            if game_row:
                game_id = game_row["id"]
                apply_start_time(con, game_id, game_start, game_row["start_time"],
                                 label="%s @ %s" % (batch["away"], batch["home"]))
            else:
                cur = con.execute(
                    "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
                    ("wc", batch["date"], batch["home"], batch["away"], "", game_start))
                game_id = cur.lastrowid
                game_row = con.execute(
                    "SELECT id,league,date,home,away,espn_event_id,start_time FROM prop_games WHERE id=?",
                    (game_id,)).fetchone()

            if not game_row["espn_event_id"]:
                if batch["date"] not in espn_by_date:
                    try:
                        espn_by_date[batch["date"]] = espn.games("wc", batch["date"])
                    except Exception as exc:
                        print(f"    ESPN schedule unavailable for {batch['date']}: {exc}")
                        espn_by_date[batch["date"]] = []
                espn_id = link_prop_game(con, game_row, espn_by_date[batch["date"]])
                if espn_id:
                    con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (espn_id, game_id))
                    print(f"    linked ESPN event {espn_id}")
                else:
                    print("    WARNING: unresolved ESPN event; props retained for next retry")

            for p in batch["props"]:
                pname = p["player_name"]
                pteam = p.get("team", "")
                pl = con.execute(
                    "SELECT id FROM players WHERE name=? AND league=?",
                    (pname, "wc")).fetchone()
                if pl:
                    player_id = pl["id"]
                else:
                    # Minting a `players` row out of a sportsbook display name, with no
                    # publisher id behind it. This is the shape that put 531 shadow players
                    # into prod MLS: rows with no espn_id, no game logs and props attached,
                    # duplicating athletes the spine already held, so prop -> player ->
                    # game_log never joined for any of them.
                    #
                    # It stays for `wc` because the World Cup spine is genuinely built this
                    # way (Phase 1, name-match only) and there is no ESPN id to resolve
                    # against. What changed is that it is COUNTED. A mint used to be
                    # indistinguishable from a match in the run output, which is why nobody
                    # noticed 531 of them.
                    cur = con.execute(
                        "INSERT INTO players(name, team, league) VALUES(?,?,?)",
                        (pname, pteam if pteam else None, "wc"))
                    player_id = cur.lastrowid
                    _MINTED_PLAYERS.append(("wc", pname))

                odds_val = p.get("odds")
                line_val = p.get("line") or 0
                side = p.get("side", "over")
                market = p.get("market", "")

                odds_int = None
                if odds_val is not None:
                    try:
                        odds_int = int(odds_val)
                    except (ValueError, TypeError):
                        if str(odds_val).upper() == "EVEN":
                            odds_int = 100
                existing = con.execute(
                    "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? "
                    "AND line=? AND side=? AND source='bovada'",
                    (game_id, player_id, market, line_val, side)).fetchone()
                if existing:
                    if odds_int is None:
                        con.execute("UPDATE props SET captured_at=? WHERE id=?", (now, existing["id"]))
                    else:
                        con.execute(
                            "UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
                            (now, odds_int, now, existing["id"]))
                elif odds_int is not None:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now, odds_int, now))
                else:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) VALUES(?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now))
                ingested += 1

        con.commit()
    finally:
        con.close()
    return ingested

def _normalize_identity_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value.lower())).strip()

def _resolve_ufc_player_for_bovada(con, player_name: str) -> int:
    """Use a reviewed alias before creating a Bovada-only UFC player row."""
    exact = con.execute(
        "SELECT id FROM players WHERE name=? AND league='ufc' ORDER BY id", (player_name,)
    ).fetchall()
    if len(exact) == 1:
        return exact[0]["id"]
    if len(exact) > 1:
        raise RuntimeError("ambiguous UFC canonical name from Bovada: {}".format(player_name))
    aliases = con.execute(
        "SELECT DISTINCT p.id FROM name_alias na JOIN players p ON p.id=na.player_id "
        "WHERE p.league='ufc' AND na.alias_norm=? ORDER BY p.id",
        (_normalize_identity_name(player_name),),
    ).fetchall()
    if len(aliases) == 1:
        return aliases[0]["id"]
    if len(aliases) > 1:
        raise RuntimeError("ambiguous UFC reviewed alias from Bovada: {}".format(player_name))
    # Same mint, same accounting: a fighter Bovada names that no canonical row and no
    # reviewed alias matches becomes a new row, and the run says so.
    _MINTED_PLAYERS.append(("ufc", player_name))
    return con.execute(
        "INSERT INTO players(name, team, league) VALUES(?,?,?)",
        (player_name, None, "ufc"),
    ).lastrowid

def _find_existing_ufc_game_for_players(con, game_date: str, player_ids: set):
    """Find one canonical fight by its resolved fighters when display names changed."""
    if len(player_ids) != 2:
        return None
    candidates = con.execute(
        "SELECT pg.id,pg.start_time FROM prop_games pg JOIN props pr ON pr.game_id=pg.id "
        "WHERE pg.league='ufc' AND pg.date=? AND pr.player_id IN (?,?) "
        "GROUP BY pg.id HAVING COUNT(DISTINCT pr.player_id)=2",
        (game_date, *sorted(player_ids)),
    ).fetchall()
    if len(candidates) > 1:
        raise RuntimeError("ambiguous UFC canonical game for Bovada fighter ids")
    return candidates[0] if candidates else None

def _ufc_direct_ingest(all_props: list, today: str) -> int:
    """Direct DB insert for UFC method-of-victory props — fighters are created as players (league
    'ufc') as needed, like WC. Game home/away = the two fighters; start_time stored. No ESPN linking."""
    import sqlite3, os as _os
    DB = _os.environ.get("LP_DB_PATH") or _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ingested = 0
    try:
        by_game = {}
        for p in all_props:
            gdate = _wc_event_date(p, today, "ufc")
            gkey = (gdate, p["game_desc"])
            if gkey not in by_game:
                by_game[gkey] = {"date": gdate, "home": p["home_team"], "away": p["away_team"], "props": []}
            by_game[gkey]["props"].append(p)

        for batch in by_game.values():
            game_start = _event_start_iso(batch["props"][0]) if batch["props"] else None
            resolved_props = [
                (p, _resolve_ufc_player_for_bovada(con, p["player_name"]))
                for p in batch["props"]
            ]
            row = con.execute(
                "SELECT id,start_time FROM prop_games WHERE league=? AND date=? AND home=? AND away=?",
                ("ufc", batch["date"], batch["home"], batch["away"])).fetchone()
            if not row:
                row = _find_existing_ufc_game_for_players(
                    con, batch["date"], {player_id for _, player_id in resolved_props}
                )
            if row:
                game_id = row["id"]
                apply_start_time(con, game_id, game_start, row["start_time"],
                                 label="%s @ %s" % (batch["away"], batch["home"]))
            else:
                game_id = con.execute(
                    "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
                    ("ufc", batch["date"], batch["home"], batch["away"], "", game_start)).lastrowid
            print(f"  {batch['away']} vs {batch['home']}: {len(batch['props'])} props")
            for p, player_id in resolved_props:
                line_val = p.get("line") or 0
                side = p.get("side", "over")
                market = p.get("market", "")
                odds_int = None
                if p.get("odds") is not None:
                    try:
                        odds_int = int(p["odds"])
                    except (ValueError, TypeError):
                        odds_int = 100 if str(p["odds"]).upper() == "EVEN" else None
                existing = con.execute(
                    "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? AND line=? AND side=? AND source='bovada'",
                    (game_id, player_id, market, line_val, side)).fetchone()
                if existing:
                    if odds_int is None:
                        con.execute("UPDATE props SET captured_at=? WHERE id=?", (now, existing["id"]))
                    else:
                        con.execute("UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
                                    (now, odds_int, now, existing["id"]))
                elif odds_int is not None:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now, odds_int, now))
                else:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) VALUES(?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now))
                ingested += 1
        con.commit()
    finally:
        con.close()
    return ingested
