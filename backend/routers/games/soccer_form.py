"""Read recent soccer form from the stored FotMob publisher history.

This endpoint is deliberately read-only. The Props page must never turn a UI
click into an ESPN scrape or an opportunistic database write. FotMob history is
published by the guarded league ingest; missing coverage stays explicit.
"""
import json
import sqlite3
from contextlib import closing

from fastapi import APIRouter, HTTPException

from _core import _db

router = APIRouter()


def _form_leagues(player_league):
    if player_league == "ligamx":
        return ("ligamx", "lcup")
    if player_league == "mls":
        return ("mls", "lcup")
    if player_league == "lcup":
        return ("lcup",)
    return ()


def _match(row):
    try:
        stats = json.loads(row["stats"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(500, "stored FotMob form is malformed") from exc
    if not isinstance(stats, dict):
        raise HTTPException(500, "stored FotMob form is malformed")
    home = None
    if row["home_away"] == "home":
        home = True
    elif row["home_away"] == "away":
        home = False
    opponent = row["opponent"] or "Opponent unavailable"
    matchup = opponent if home is None else (f"vs {opponent}" if home else f"@ {opponent}")
    return {
        "date": row["game_date"], "event_id": row["game_id"],
        "matchup": matchup, "home": home,
        "minutes": stats.get("minutes"), "goals": stats.get("goals"),
        "assists": stats.get("assists"), "shots": stats.get("shots"),
        "shots_on_target": stats.get("shots_on_target"),
        "tackles": stats.get("tackles"), "clearances": stats.get("clearances"),
        "crosses": stats.get("crosses"),
        # FotMob's stored `passes` is not relabelled as pass attempts.
        "passes_attempted": stats.get("passes_attempted"),
        "fouls_committed": stats.get("fouls_committed"),
    }


@router.get("/api/soccer/player/{player_id}/form")
def soccer_player_form(player_id: int, limit: int = 5):
    limit = max(1, min(int(limit), 10))
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        player = con.execute(
            "SELECT id,name,team,league FROM players WHERE id=?", (player_id,)
        ).fetchone()
        if not player:
            raise HTTPException(404, "player not found")
        leagues = _form_leagues(str(player["league"] or ""))
        if not leagues:
            return {
                "player_id": player_id, "player": player["name"],
                "team": player["team"], "league": player["league"],
                "source": "fotmob", "matches": [], "stored": 0,
                "note": f"FotMob form is not available for {player['league'] or 'this league'}",
            }
        placeholders = ",".join("?" for _ in leagues)
        try:
            rows = con.execute(
                "SELECT game_date,game_id,opponent,home_away,stats "
                "FROM player_game_logs_fotmob "
                f"WHERE player_id=? AND league IN ({placeholders}) "
                "ORDER BY game_date DESC,id DESC LIMIT ?",
                (player_id, *leagues, limit),
            ).fetchall()
        except sqlite3.Error as exc:
            raise HTTPException(503, "FotMob form history is unavailable") from exc

    return {
        "player_id": player_id, "player": player["name"],
        "team": player["team"], "league": player["league"],
        "source": "fotmob", "matches": [_match(row) for row in rows],
        "stored": 0,
        "note": None if rows else "No completed FotMob matches are stored for this player",
    }
