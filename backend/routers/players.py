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


# ── Per-league stat columns for the leaders endpoint ─────────
_LEAGUE_STATS = {
    "nba": ["pts", "reb", "ast", "stl", "blk", "tov", "fg3m", "minutes", "ts_pct", "fgm", "fga", "ftm", "fta"],
    "nfl": ["pass_yds_g", "pass_td", "interceptions", "cmp_g", "rush_yds_g", "receptions", "rec_yds_g", "targets", "fantasy_pts_g", "fantasy_ppr_g"],
    "nhl": ["goals", "assists", "points_nhl", "shots", "shooting_pct", "plus_minus", "pim", "ppg", "ppp", "shg"],
    "mlb_batting": ["avg", "hr", "k_pct", "bb_pct", "woba", "xwoba", "exit_velo", "hard_hit_pct"],
    "mlb_pitching": ["k_pct", "whiff_pct", "xwoba_against", "exit_velo_against", "barrel_pct_against"],
}
_LEAGUE_DEFAULT_STAT = {"nba": "pts", "nfl": "fantasy_pts_g", "nhl": "points_nhl",
                        "mlb_batting": "avg", "mlb_pitching": "k_pct"}

# Human-readable stat labels (camelCase/snake_case → display)
def _stat_label(k: str) -> str:
    return k.replace("_g", "/G").replace("_pct", "%").replace("_nhl", "").replace("_", " ").upper()


@router.get("/api/{league}/leaders")
def league_leaders(league: str,
                   stat: Optional[str] = Query(None),
                   type: Optional[str] = Query(None),
                   min_games: int = Query(0, ge=0),
                   limit: int = Query(25, ge=1, le=100)):
    """Player leaderboard for a league from the player_stats table.
    ?stat=pts — sort column (default: league-appropriate)
    ?type=batting|pitching — MLB only, picks the stat_type to filter
    ?min_games=N — minimum games played (default: 0 for all, 10 for MLB batting)
    """
    lg = league.lower()
    if lg not in ("nba", "nfl", "nhl", "mlb"):
        return JSONResponse({"error": f"Unsupported league: {league}"}, 404)

    with closing(_db()) as con:
        # Find the current/latest season
        srow = con.execute(
            "SELECT season FROM player_stats WHERE league=? ORDER BY season DESC LIMIT 1",
            (lg,)).fetchone()
        season = srow["season"] if srow else None
        if season is None:
            return {"league": lg, "season": None, "stat": stat, "leaders": []}

        stat_type = None
        stat_set = _LEAGUE_STATS.get(lg, [])
        if lg == "mlb":
            # MLB: filter by stat_type=batting (default) or pitching
            stat_type = (type or "batting").lower()
            if stat_type not in ("batting", "pitching"):
                stat_type = "batting"
            stat_set = _LEAGUE_STATS.get(f"mlb_{stat_type}", stat_set)

        # Resolve the sort stat
        default_key = f"mlb_{stat_type}" if lg == "mlb" and stat_type else lg
        sort_stat = stat or _LEAGUE_DEFAULT_STAT.get(default_key, stat_set[0] if stat_set else "games")
        if sort_stat not in stat_set:
            stat_set = list(stat_set) + [sort_stat]  # allow ad-hoc stat if it exists in DB

        # Build SELECT: only columns that exist and are in the stat set
        # Always include player_id, player_name, team, games
        cols = ["player_id", "player_name", "team", "games"] + [c for c in stat_set if c != sort_stat or c in stat_set]
        # Put sort_stat first in stat columns for readability
        stat_cols = [sort_stat] + [c for c in stat_set if c != sort_stat]

        # Validate columns exist in DB (the table is wide and mixed)
        db_cols = set()
        try:
            db_cols = {r[1] for r in con.execute("PRAGMA table_info(player_stats)").fetchall()}
        except Exception:
            pass
        valid_stat_cols = [c for c in stat_cols if c in db_cols]
        valid_extra = [c for c in cols if c in db_cols]

        select_cols = [c for c in valid_extra if c not in valid_stat_cols] + valid_stat_cols
        select_str = ", ".join(select_cols)
        order_col = sort_stat if sort_stat in db_cols else "games"

        params = [lg, season]
        where = "WHERE league=? AND season=?"
        if lg == "mlb" and stat_type:
            where += " AND stat_type=?"
            params.append(stat_type)
        # Default min_games for MLB to filter cup-of-coffee players
        effective_min = min_games
        if effective_min == 0 and lg == "mlb":
            effective_min = 30 if stat_type == "batting" else 10
        if effective_min > 0:
            where += " AND games >= ?"
            params.append(effective_min)

        rows = con.execute(
            f"SELECT {select_str} FROM player_stats {where} "
            f"AND {order_col} IS NOT NULL ORDER BY {order_col} DESC LIMIT ?",
            params + [limit]
        ).fetchall()

    leaders = []
    for r in rows:
        entry = {"player_id": r["player_id"], "name": r["player_name"],
                 "team": r["team"] or "", "games": r["games"]}
        for c in valid_stat_cols:
            v = r[c]
            entry[c] = round(float(v), 1) if v is not None else None
        leaders.append(entry)

    return {"league": lg, "season": season if isinstance(season, int) else str(season),
            "stat": sort_stat, "stat_type": stat_type, "leaders": leaders}

