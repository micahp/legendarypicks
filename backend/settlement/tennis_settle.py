#!/usr/bin/env python3
"""Settle player-attributed tennis markets from durable scoreboard snapshots."""
import datetime as dt
import json
import re
import sqlite3
import unicodedata

from settlement.grading import _grade_actual


def _player_key(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in folded.lower()
                   if ch.isalnum() and not unicodedata.combining(ch))


def _same_player(left: str, right: str) -> bool:
    left_key = _player_key(left)
    right_key = _player_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    return (min(len(left_key), len(right_key)) >= 7
            and (left_key.startswith(right_key) or right_key.startswith(left_key)))


def _tennis_snapshot(con: sqlite3.Connection, league: str, event_id: str):
    row = con.execute(
        "SELECT state, payload FROM scoreboard_snapshots "
        "WHERE league=? AND game_id=? ORDER BY fetched_at DESC LIMIT 1",
        (league, str(event_id)),
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {"state": row["state"], "payload": payload}


def _required_set_wins(props) -> int:
    """Infer best-of-three/five from the publisher's exact-score ladder."""
    for prop in props:
        match = re.fullmatch(r"set_betting___(\d+)_(\d+)", prop["market"] or "")
        if match and int(match.group(1)) >= 3:
            return 3
    return 2


def _settle_tennis_props(con: sqlite3.Connection, props, snapshot: dict) -> dict:
    """Grade the four tennis markets emitted by ``_parse_tennis_props``.

    A completed snapshot must publish a full winning set count.  A retirement,
    walkover, partial score, missing player, or ambiguous player identity remains
    pending; none is converted into a guessed loss or a void row.
    """
    payload = snapshot.get("payload") or {}
    home = payload.get("home") or {}
    away = payload.get("away") or {}
    home_sets = home.get("sets")
    away_sets = away.get("sets")
    required = _required_set_wins(props)
    try:
        home_wins = int(home.get("score"))
        away_wins = int(away.get("score"))
    except (TypeError, ValueError):
        home_wins = away_wins = -1

    complete = (
        snapshot.get("state") == "post"
        and isinstance(home_sets, list) and isinstance(away_sets, list)
        and len(home_sets) == len(away_sets) and len(home_sets) >= required
        and max(home_wins, away_wins) == required
        and min(home_wins, away_wins) >= 0
    )
    if not complete:
        return {"settled": 0, "void": 0, "unmappable": 0,
                "pending": len(props), "errors": 0}

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    counts = {"settled": 0, "void": 0, "unmappable": 0,
              "pending": 0, "errors": 0}
    for prop in props:
        player_name = prop["player_name"] or ""
        is_home = _same_player(player_name, home.get("name") or "")
        is_away = _same_player(player_name, away.get("name") or "")
        if is_home == is_away:
            counts["pending"] += 1
            continue

        player_sets = home_sets if is_home else away_sets
        player_wins = home_wins if is_home else away_wins
        opponent_wins = away_wins if is_home else home_wins
        market = prop["market"] or ""
        actual = None
        if market == "match_winner":
            actual = float(player_wins > opponent_wins)
        elif market == "total_games":
            try:
                actual = float(sum(float(value) for value in player_sets))
            except (TypeError, ValueError):
                counts["pending"] += 1
                continue
        elif market == "win_a_set":
            actual = float(player_wins >= 1)
        else:
            score = re.fullmatch(r"set_betting___(\d+)_(\d+)", market)
            if score:
                actual = float(
                    player_wins == int(score.group(1))
                    and opponent_wins == int(score.group(2))
                )

        if actual is None:
            counts["unmappable"] += 1
            continue
        try:
            if _grade_actual(con, prop, actual, now):
                counts["settled"] += 1
            else:
                counts["unmappable"] += 1
        except sqlite3.Error:
            counts["errors"] += 1

    con.commit()
    return counts
