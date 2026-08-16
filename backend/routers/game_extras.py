"""routers/game_extras.py — game_extras endpoints. Handlers only; shared code lives in _core."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *

router = APIRouter()

@router.get("/api/game/{league}/{game_id}/props")
def game_props(league: str, game_id: str):
    """Props for an ESPN game (linked via prop_games.espn_event_id), grouped by
    player — the Game page's betting view. Each player's props expand to a chart.

    Once a game is settled each prop also carries how it LANDED: the actual value and
    whether it hit. That is the half of the product a reader could not see before — the
    board showed what was offered and then went quiet, so the one page where we could show
    that our lines were worth reading showed nothing after the final whistle.

    `settled_lines` counts distinct (player, market, line) — NOT settled rows, and there is
    deliberately no hit count. We store both sides of most lines: for game 401816457, 35 of
    51 lines are held as both over and under, so exactly 35 hit and 35 missed by
    construction. A "33 of 81 hit" headline built on that measures our storage layout, not
    our judgement, and putting it on the page would be claiming a track record we have not
    earned. We do not publish a side, so we cannot report a record. What we CAN report, and
    what is genuinely ours, is where the line was and where the number landed.

    Unsettled props carry result: null. An unsettled prop is not a miss, and a page that
    cannot tell the two apart would be claiming a loss we never took.

    Nameless players are excluded. Not cosmetic: one MLB row (id 28987, no name, no team, no
    external id) is a bucket the Bovada parser filled whenever it could not attribute a
    market — 3,729 props belonging to Cooper Pratt, Raynel Delgado, Kahlil Watson and others
    on a single fake identity. The parser no longer produces them; a row with no name is by
    definition a prop we cannot say is anyone's, and serving it would attribute a stranger's
    line to a player page."""
    with closing(_db()) as con:
        rows = con.execute(
            """SELECT pl.id AS player_id, pl.name, pl.team, p.market, p.line, p.side,
                      MAX(p.captured_at) ca, r.actual_value, r.hit, r.settled_at
               FROM props p
               JOIN prop_games g ON g.id = p.game_id
               JOIN players pl ON pl.id = p.player_id
               LEFT JOIN prop_results r ON r.prop_id = p.id
               WHERE g.espn_event_id = ? AND TRIM(COALESCE(pl.name, '')) <> ''
               GROUP BY pl.id, p.market, p.side
               ORDER BY pl.name""",
            (str(game_id),)).fetchall()
    players: dict = {}
    # Keyed by (player, market, line) — the same identity `settled_lines` counts, so the
    # count and the leader set can never disagree about what a settled line is.
    settled: dict = {}
    for r in rows:
        d = players.setdefault(r["player_id"], {"player_id": r["player_id"], "name": r["name"],
                                                "team": r["team"], "props": []})
        market = _base_market(r["market"])
        result = None
        if r["settled_at"] is not None and r["hit"] is not None:
            # `cashed` is the side the number actually landed on, derived from this row's
            # own side and verdict — so a line stored on one side only still says which way
            # it went, and the page never has to infer it from a missing sibling.
            cashed = r["side"] if r["hit"] else _other_side(r["side"])
            result = {"actual": r["actual_value"], "hit": bool(r["hit"]),
                      "settled_at": r["settled_at"], "cashed": cashed}
            key = (r["player_id"], market, r["line"])
            if key not in settled:
                # Both stored sides of a line carry the same actual and the same line, so
                # whichever row arrives first yields the same margin and the same `cashed`.
                try:
                    margin = abs(float(r["actual_value"]) - float(r["line"]))
                except (TypeError, ValueError):
                    margin = 0.0
                settled[key] = {
                    "player_id": r["player_id"], "name": r["name"], "team": r["team"],
                    "market": market, "line": r["line"], "actual": r["actual_value"],
                    "cashed": cashed, "margin": margin}
        d["props"].append({"market": market, "line": r["line"],
                           "side": r["side"], "result": result})

    # "What decided it" — the settled lines that finished furthest from their own number,
    # in either direction. Not a record: we hold both sides of most lines, so which side
    # cashed is a fact about the game rather than a call of ours (see the docstring).
    leaders = sorted(settled.values(), key=lambda x: x["margin"], reverse=True)[:3]

    return {"league": league, "game_id": str(game_id), "players": list(players.values()),
            "settled_lines": len(settled), "leaders": leaders}


def _other_side(side):
    return {"over": "under", "under": "over"}.get((side or "").lower(), side)


@router.get("/api/game/{league}/{game_id}/story")
def game_story(league: str, game_id: str, refresh: bool = Query(False)):
    """AI matchup blurb (DeepSeek V4 Pro), grounded ONLY in our records/streaks/form.
    Cached per game. Generation logic lives in _core.generate_game_story so the
    pregenerate_game_stories job can warm the cache when a game is first discovered,
    instead of paying the latency on the first user view."""
    return generate_game_story(league, game_id, refresh)


@router.get("/api/game/{league}/{game_id}/edge")
def game_edge(league: str, game_id: str):
    """Projected stat lines for players in an NBA game (no Bovada props for NBA).
    Queries player_game_logs for this game's participants, computes per-stat
    projections from their recent logs, returns top projected lines."""
    lg = league.lower()
    if lg != "nba":
        return {"league": lg, "game_id": str(game_id), "players": []}

    import json as _json
    with closing(_db()) as con:
        rows = con.execute(
            """SELECT DISTINCT pl.id AS player_id, pl.name, pl.team
               FROM player_game_logs l
               JOIN players pl ON pl.id = l.player_id
               WHERE l.league='nba' AND l.game_id=?""",
            (str(game_id),)).fetchall()

    if not rows:
        return {"league": lg, "game_id": str(game_id), "players": []}

    stat_keys = ["PTS", "REB", "AST", "PRA", "3PM", "STL", "BLK", "TO"]
    players_out = []

    with closing(_db()) as con:
        for r in rows:
            pid = r["player_id"]
            logs = con.execute(
                """SELECT stats FROM player_game_logs
                   WHERE player_id=? AND league='nba'
                   ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC
                   LIMIT 20""",
                (pid,)).fetchall()
            if not logs:
                continue

            series: dict = {}
            for lr in logs:
                for k, v in _json.loads(lr["stats"]).items():
                    if isinstance(v, (int, float)) and k in stat_keys:
                        series.setdefault(k, []).append(v)

            props = []
            for sk in stat_keys:
                vals = series.get(sk)
                if vals and len(vals) >= 5:
                    avg = round(sum(vals) / len(vals), 1)
                    props.append({"market": sk.lower(), "line": avg, "side": "proj"})

            if props:
                players_out.append({
                    "player_id": pid, "name": r["name"], "team": r["team"],
                    "props": props[:5]
                })

    return {"league": lg, "game_id": str(game_id), "players": players_out}

