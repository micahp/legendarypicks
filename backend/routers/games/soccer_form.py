"""Lazy per-athlete soccer form, read-through into player_game_logs.

The same shape as `/api/ufc/fighter/{id}/form`: nothing is ingested up front, a
click pays for a live read, and the shared Fetcher's cache makes the next click
free.

It also WRITES what it read. The prop chart draws from `player_game_logs`, and
Liga MX has no season ingest, so those players charted three Leagues Cup games
against an MLS player's forty-two. Every click now leaves its five matches
behind, so the chart fills in from ordinary use instead of waiting for a
backfill window. That is deliberately opportunistic: it covers the players
somebody actually looked at, in the order somebody looked at them.

Costs 1 + 2N ESPN requests on a cold click (eventlog, then statistics and event
per match), which is why it is a click and not a page load.
"""
import json
import sqlite3
from contextlib import closing

from fastapi import APIRouter, HTTPException

import espn_client as espn
from _core import _db

router = APIRouter()

# Only Liga MX for now. The client function is league-agnostic, but every league
# added here is a promise that its athletes carry an espn_id and that its season
# key is right, and neither is free.
_FORM_LEAGUES = {"ligamx": 2026}

# What we store from a form read. Absent values stay ABSENT -- a stat the
# publisher did not send must not be written as 0, because 0 tackles is a real
# result and afterwards the two are indistinguishable.
_STORED = ("goals", "assists", "shots", "shots_on_target", "tackles",
           "clearances", "crosses", "passes_attempted", "passes",
           "fouls_committed", "saves", "minutes")


def _persist(con, player_id, athlete_id, league, season, matches):
    """Write the matches we just read, without overwriting a richer row.

    INSERT OR IGNORE on the ingest's own uniqueness (league, source_player_key,
    season, game_no) so a row written by `ingest_soccer_logs` always wins: that
    path knows the game_type and the team codes, and this one is a read-through
    that happens to have the same numbers.
    """
    written = 0
    for match in matches:
        event_id = match.get("event_id")
        if not event_id:
            continue
        stats = {key: match[key] for key in _STORED
                 if match.get(key) is not None}
        if not stats:
            continue
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO player_game_logs"
                "(player_id, league, season, game_no, game_id, game_date,"
                " stats, source, source_player_key)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (player_id, league, season, event_id, event_id,
                 match.get("date"), json.dumps(stats), "espn-core",
                 str(athlete_id)))
            written += cur.rowcount or 0
        except sqlite3.Error:
            # A read is still a good read if the write loses a race.
            continue
    if written:
        con.commit()
    return written


@router.get("/api/soccer/player/{player_id}/form")
def soccer_player_form(player_id: int, limit: int = 5):
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        player = con.execute(
            "SELECT id, name, team, league, espn_id FROM players WHERE id=?",
            (player_id,)).fetchone()
        if not player:
            raise HTTPException(404, "player not found")
        league = str(player["league"] or "")
        if league not in _FORM_LEAGUES:
            # Not an error. A Leagues Cup card mixes MLS and Liga MX players and
            # asks the same question of both; the MLS ones already have a season
            # in player_game_logs and chart from it. Returning 400 here would
            # render a failure on a row that is simply served another way.
            return {"player_id": player_id, "player": player["name"],
                    "team": player["team"], "league": league,
                    "source": "espn-core", "matches": [], "stored": 0,
                    "note": f"form is not wired for {league or 'this league'}"}
        athlete_id = str(player["espn_id"] or "")
        if not athlete_id:
            # Never guess an athlete by name here. An ambiguous key does not
            # raise, it silently returns somebody else's season.
            return {"player_id": player_id, "player": player["name"],
                    "team": player["team"], "league": league,
                    "source": "espn-core", "matches": [], "stored": 0,
                    "note": "no espn_id on this player"}

        season = _FORM_LEAGUES[league]
        try:
            matches = espn.soccer_athlete_form(
                league, athlete_id, season, limit=max(1, min(int(limit), 10)))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, "ESPN form unavailable") from exc

        stored = _persist(con, player_id, athlete_id, league, season, matches)

    return {"player_id": player_id, "player": player["name"],
            "team": player["team"], "league": league, "espn_id": athlete_id,
            "source": "espn-core", "matches": matches, "stored": stored}
