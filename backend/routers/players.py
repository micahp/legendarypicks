"""routers/players.py — players endpoints. Handlers only; shared code lives in _core."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *

router = APIRouter()

@router.get("/api/players/search")
def search_players(q: str = Query("", description="Search query")):
    if not q or len(q) < 2:
        return []
    with closing(_db()) as con:
        rows = con.execute(
            "SELECT DISTINCT id, name, team, league FROM players WHERE name LIKE ? LIMIT 20",
            (f"%{q}%",)
        ).fetchall()
    return [{"id": r["id"], "name": r["name"], "team": r["team"], "league": r["league"]} for r in rows]


@router.get("/api/player/{player_id}")
def player_profile(player_id: int):
    """Aggregate for the player page: header + recent game logs + per-stat
    projections + current props on this player. (Advanced metrics stay at
    /api/player/{id}/stats; this is the page-level rollup.)"""
    import json as _json
    with closing(_db()) as con:
        p = con.execute("SELECT id, name, team, league, position FROM players WHERE id=?", (player_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Player not found")
        league = p["league"]
        srow = con.execute(
            "SELECT season FROM player_game_logs WHERE player_id=? ORDER BY season DESC LIMIT 1",
            (player_id,)).fetchone()
        season = srow["season"] if srow else None
        logs = []
        if season is not None:
            logs = con.execute(
                """SELECT stats, game_date, opponent, home_away, game_no
                   FROM player_game_logs WHERE player_id=? AND season=?
                   ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC LIMIT 25""",
                (player_id, season)).fetchall()
        props = con.execute(
            """SELECT market, side, line, MAX(captured_at) ca FROM props
               WHERE player_id=? GROUP BY market, side ORDER BY ca DESC LIMIT 30""",
            (player_id,)).fetchall()

    series, recent = {}, []
    for r in logs:
        s = _json.loads(r["stats"])
        recent.append({"date": r["game_date"], "opponent": r["opponent"],
                       "home": (r["home_away"] == "home") if r["home_away"] else None, "stats": s})
        for k, v in s.items():
            if isinstance(v, (int, float)):
                series.setdefault(k, []).append(v)
    projections = {}
    for k, vals in series.items():
        pr = proj_mod.project_stat(vals)
        if pr:
            projections[k] = pr

    return {
        "id": p["id"], "name": p["name"], "team": p["team"], "league": league,
        "position": p["position"], "season": season, "games": len(logs),
        "recent_games": recent[:15],
        "projections": projections,
        "props": [{"market": _base_market(x["market"]), "side": x["side"], "line": x["line"]} for x in props],
    }


@router.get("/api/player/{player_id}/matchups")
def player_matchups(player_id: int):
    """Player-vs-opponent splits from per-game logs (Matchups tab). Groups the
    player's games by opponent → games count + per-stat averages."""
    import json as _json
    with closing(_db()) as con:
        p = con.execute("SELECT id, name, league FROM players WHERE id=?", (player_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Player not found")
        srow = con.execute(
            "SELECT season FROM player_game_logs WHERE player_id=? ORDER BY season DESC LIMIT 1",
            (player_id,)).fetchone()
        season = srow["season"] if srow else None
        rows = []
        if season is not None:
            rows = con.execute(
                "SELECT opponent, stats FROM player_game_logs WHERE player_id=? AND season=? AND opponent IS NOT NULL",
                (player_id, season)).fetchall()

    by_opp: dict = {}
    for r in rows:
        opp = r["opponent"]
        d = by_opp.setdefault(opp, {"games": 0, "sums": {}})
        d["games"] += 1
        for k, v in _json.loads(r["stats"]).items():
            if isinstance(v, (int, float)):
                d["sums"][k] = d["sums"].get(k, 0) + v
    matchups = [
        {"opponent": opp, "games": d["games"],
         "avg": {k: round(v / d["games"], 2) for k, v in d["sums"].items()}}
        for opp, d in by_opp.items()
    ]
    matchups.sort(key=lambda x: -x["games"])
    return {"player_id": player_id, "name": p["name"], "league": p["league"],
            "season": season, "matchups": matchups}


@router.get("/api/projections/player/{player_id}")
def player_projections(player_id: int,
                       season: Optional[int] = Query(None),
                       line: Optional[float] = Query(None),
                       market: Optional[str] = Query(None)):
    """Per-stat projections (recency-weighted EV + floor/median/ceiling) for a
    player, derived from player_game_logs. Pass ?line=&market= for P(over)."""
    import json as _json
    with closing(_db()) as con:
        prow = con.execute("SELECT id, name, league, team FROM players WHERE id=?", (player_id,)).fetchone()
        if not prow:
            raise HTTPException(404, "Player not found")
        if season is None:
            srow = con.execute(
                "SELECT season FROM player_game_logs WHERE player_id=? ORDER BY season DESC LIMIT 1",
                (player_id,)).fetchone()
            season = srow["season"] if srow else None
        params = [player_id]
        q = "SELECT stats FROM player_game_logs WHERE player_id=?"
        if season is not None:
            q += " AND season=?"; params.append(season)
        # most-recent-first; game_date is NULL for NFL (week-keyed) → fall back to week
        q += " ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC"
        rows = con.execute(q, params).fetchall()

    base = {"player_id": player_id, "name": prow["name"], "league": prow["league"],
            "team": prow["team"], "season": season, "games": len(rows)}
    if not rows:
        return {**base, "projections": {}}

    series: dict = {}
    for r in rows:
        for k, v in _json.loads(r["stats"]).items():
            if isinstance(v, (int, float)):
                series.setdefault(k, []).append(v)

    projections = {}
    for k, vals in series.items():
        pr = proj_mod.project_stat(vals)
        if not pr:
            continue
        if line is not None and (market is None or market == k):
            pr["prob_over"] = proj_mod.prob_over(vals, line)
        projections[k] = pr
    return {**base, "projections": projections}


@router.get("/api/player/{player_id}/stats")
def player_stats(player_id: int,
                 league: str = Query("mlb"),
                 statcast_id: Optional[int] = Query(None)):
    """Return advanced stats for a player. MLB uses Statcast via pybaseball."""
    from datetime import datetime as dt2, timedelta

    if league not in ("mlb", "nfl", "nba", "nhl"):
        return {"player_id": player_id, "stats": None,
                "message": f"Advanced stats not yet available for {league}"}

    # Look up player name
    with closing(_db()) as con:
        row = con.execute("SELECT name FROM players WHERE id=?", (player_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Player not found")
    player_name = row["name"]

    import time
    now = time.time()  # passed to helpers for cache keying (was undefined → 500 on every call)

    result = {"player_id": player_id, "player_name": player_name, "league": league}

    # ── MLB: Statcast via pybaseball ──────────────────────────────
    if league == "mlb":
        result.update(_get_mlb_stats(player_name, player_id, statcast_id, now))

    # ── NFL: nflverse via nfl_data_py ─────────────────────────────
    elif league == "nfl":
        result.update(_get_nfl_stats(player_name, player_id, now))

    # ── NBA: nba_api (stats.nba.com) ──────────────────────────────
    elif league == "nba":
        result.update(_get_nba_stats(player_name, player_id, now))

    # ── NHL: api-web.nhle.com ─────────────────────────────────────
    elif league == "nhl":
        result.update(_get_nhl_stats(player_name, player_id, now))

    return result

