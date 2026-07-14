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


# ── Explicit player-leader categories and display contracts ────────
def _metric(key, label, format):
    return {"key": key, "label": label, "format": format}


_LEAGUE_CATEGORIES = {
    "nba": [
        {"key": "scoring", "label": "Scoring", "stats": [
            _metric("pts", "Points", "decimal_1"),
            _metric("fgm", "Field Goals Made", "integer"),
            _metric("fga", "Field Goals Attempted", "integer"),
            _metric("fg3m", "3-Pointers Made", "integer"),
            _metric("fg3a", "3-Pointers Attempted", "integer"),
            _metric("ftm", "Free Throws Made", "integer"),
            _metric("fta", "Free Throws Attempted", "integer"),
        ]},
        {"key": "playmaking", "label": "Playmaking", "stats": [
            _metric("ast", "Assists", "decimal_1"),
            _metric("tov", "Turnovers", "decimal_1"),
        ]},
        {"key": "rebounding", "label": "Rebounding", "stats": [
            _metric("reb", "Rebounds", "decimal_1"),
        ]},
        {"key": "defense", "label": "Defense", "stats": [
            _metric("stl", "Steals", "decimal_1"),
            _metric("blk", "Blocks", "decimal_1"),
        ]},
        {"key": "efficiency", "label": "Efficiency", "stats": [
            _metric("ts_pct", "True Shooting %", "percent_1"),
            _metric("pts", "Points", "decimal_1"),
            _metric("minutes", "Minutes", "decimal_1"),
        ]},
    ],
    "nfl": [
        {"key": "passing", "label": "Passing", "stats": [
            _metric("pass_yds_g", "Pass Yards/Game", "decimal_1"),
            _metric("pass_td", "Pass Touchdowns", "integer"),
            _metric("interceptions", "Interceptions", "integer"),
            _metric("cmp_g", "Completions/Game", "decimal_1"),
            _metric("pass_epa", "Pass EPA", "decimal_1"),
        ]},
        {"key": "rushing", "label": "Rushing", "stats": [
            _metric("rush_yds_g", "Rush Yards/Game", "decimal_1"),
            _metric("carries_g", "Carries/Game", "decimal_1"),
        ]},
        {"key": "receiving", "label": "Receiving", "stats": [
            _metric("rec_yds_g", "Receiving Yards/Game", "decimal_1"),
            _metric("receptions", "Receptions", "integer"),
            _metric("targets", "Targets", "integer"),
        ]},
    ],
    "nhl": [
        {"key": "scoring", "label": "Scoring", "stats": [
            _metric("points_nhl", "Points", "integer"),
            _metric("goals", "Goals", "integer"),
            _metric("assists", "Assists", "integer"),
        ]},
        {"key": "shooting", "label": "Shooting", "stats": [
            _metric("shots", "Shots", "integer"),
            _metric("shooting_pct", "Shooting %", "percent_1"),
        ]},
        {"key": "special_teams", "label": "Special Teams", "stats": [
            _metric("ppg", "Power-Play Goals", "integer"),
            _metric("ppp", "Power-Play Points", "integer"),
            _metric("shg", "Short-Handed Goals", "integer"),
        ]},
        {"key": "possession", "label": "Possession", "stats": [
            _metric("plus_minus", "Plus/Minus", "integer"),
            _metric("pim", "Penalty Minutes", "integer"),
            _metric("faceoff_pct", "Faceoff %", "percent_1"),
        ]},
    ],
    "mlb_batting": [
        {"key": "production", "label": "Production", "stats": [
            _metric("avg", "Batting Average", "decimal_3"),
            _metric("hr", "Home Runs", "integer"),
            _metric("woba", "wOBA", "decimal_3"),
            _metric("xwoba", "xwOBA", "decimal_3"),
        ]},
        {"key": "contact_quality", "label": "Contact Quality", "stats": [
            _metric("xwoba", "xwOBA", "decimal_3"),
            _metric("exit_velo", "Exit Velocity", "decimal_1"),
            _metric("hard_hit_pct", "Hard-Hit %", "percent_1"),
            _metric("barrel_pct", "Barrel %", "percent_1"),
        ]},
        {"key": "discipline", "label": "Discipline", "stats": [
            _metric("k_pct", "Strikeout %", "percent_1"),
            _metric("bb_pct", "Walk %", "percent_1"),
        ]},
    ],
    "mlb_pitching": [
        {"key": "strikeouts", "label": "Strikeouts", "stats": [
            _metric("k_pct", "Strikeout %", "percent_1"),
            _metric("whiff_pct", "Whiff %", "percent_1"),
        ]},
        {"key": "contact_suppression", "label": "Contact Suppression", "stats": [
            _metric("xwoba_against", "xwOBA Against", "decimal_3"),
            _metric("exit_velo_against", "Exit Velocity Against", "decimal_1"),
            _metric("barrel_pct_against", "Barrel % Against", "percent_1"),
        ]},
    ],
}

_LEAGUE_DEFAULTS = {
    "nba": ("scoring", "pts"),
    "nfl": ("passing", "pass_yds_g"),
    "nhl": ("scoring", "points_nhl"),
    "mlb_batting": ("production", "avg"),
    "mlb_pitching": ("strikeouts", "k_pct"),
}


def _empty_leaders(lg, season, stat_type):
    return {
        "league": lg,
        "season": season,
        "stat": None,
        "stat_type": stat_type,
        "category": None,
        "categories": [],
        "columns": [],
        "leaders": [],
    }


def _format_leader_value(value, format):
    if value is None:
        return None
    if format == "integer":
        return int(value)
    if format == "decimal_3":
        return round(float(value), 3)
    if format in ("decimal_1", "percent_1"):
        return round(float(value), 1)
    if format == "time":
        return str(value)
    raise ValueError(f"Unsupported leader format: {format}")


@router.get("/api/{league}/leaders")
def league_leaders(league: str,
                   stat: Optional[str] = Query(None),
                   category: Optional[str] = Query(None),
                   type: Optional[str] = Query(None),
                   min_games: int = Query(0, ge=0),
                   limit: int = Query(25, ge=1, le=100)):
    """Player leaderboard for a league from the player_stats table.
    ?category=scoring — metric group (default: league-appropriate)
    ?stat=pts — sort column within/inferred from the category
    ?type=batting|pitching — MLB only, picks the stat_type to filter
    ?min_games=N — minimum games played (default: 0 for all, 10 for MLB batting)
    """
    lg = league.lower()
    if lg not in ("nba", "nfl", "nhl", "mlb"):
        return JSONResponse({"error": f"Unsupported league: {league}"}, 404)

    if lg == "mlb":
        stat_type = (type or "batting").lower()
        if stat_type not in ("batting", "pitching"):
            raise HTTPException(400, "type must be batting or pitching for MLB")
        definition_key = f"mlb_{stat_type}"
    else:
        if type is not None:
            raise HTTPException(400, "type is only supported for MLB leaders")
        stat_type = None
        definition_key = lg

    definitions = _LEAGUE_CATEGORIES[definition_key]
    category_defs = {item["key"]: item for item in definitions}
    approved_stats = {
        metric["key"] for item in definitions for metric in item["stats"]
    }
    if category is not None and category not in category_defs:
        raise HTTPException(400, f"Unknown category {category!r} for {definition_key}")
    if stat is not None and stat not in approved_stats:
        raise HTTPException(400, f"Unknown stat {stat!r} for {definition_key}")
    if category is not None and stat is not None:
        category_stats = {metric["key"] for metric in category_defs[category]["stats"]}
        if stat not in category_stats:
            raise HTTPException(400, f"Stat {stat!r} does not belong to category {category!r}")

    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        db_cols = {row[1] for row in con.execute("PRAGMA table_info(player_stats)").fetchall()}
        season_where = "league=?"
        season_params = [lg]
        if stat_type is not None:
            season_where += " AND stat_type=?"
            season_params.append(stat_type)
        srow = con.execute(
            f"SELECT season FROM player_stats WHERE {season_where} "
            "ORDER BY season DESC LIMIT 1",
            season_params,
        ).fetchone()
        season = srow["season"] if srow else None
        if season is None:
            return _empty_leaders(lg, None, stat_type)

        population_where = "league=? AND season=?"
        population_params = [lg, season]
        if stat_type is not None:
            population_where += " AND stat_type=?"
            population_params.append(stat_type)

        available_keys = set()
        for key in approved_stats:
            if key not in db_cols:
                continue
            count = con.execute(
                f"SELECT COUNT({key}) FROM player_stats WHERE {population_where}",
                population_params,
            ).fetchone()[0]
            if count > 0:
                available_keys.add(key)

        categories = []
        for item in definitions:
            metrics = [dict(metric) for metric in item["stats"] if metric["key"] in available_keys]
            if metrics:
                categories.append({"key": item["key"], "label": item["label"], "stats": metrics})
        if not categories:
            normalized_season = season if isinstance(season, int) else str(season)
            return _empty_leaders(lg, normalized_season, stat_type)

        available_categories = {item["key"]: item for item in categories}
        if stat is not None and stat not in available_keys:
            raise HTTPException(400, f"Stat {stat!r} is unavailable for season {season}")
        if category is not None:
            if category not in available_categories:
                raise HTTPException(400, f"Category {category!r} is unavailable for season {season}")
            selected_category = category
        elif stat is not None:
            selected_category = next(
                item["key"] for item in definitions
                if any(metric["key"] == stat for metric in item["stats"])
            )
        else:
            default_category, _default_stat = _LEAGUE_DEFAULTS[definition_key]
            selected_category = (
                default_category if default_category in available_categories else categories[0]["key"]
            )

        columns = available_categories[selected_category]["stats"]
        if stat is not None:
            sort_stat = stat
        elif category is not None:
            sort_stat = columns[0]["key"]
        else:
            _default_category, default_stat = _LEAGUE_DEFAULTS[definition_key]
            sort_stat = default_stat if (
                selected_category == _default_category and default_stat in available_keys
            ) else columns[0]["key"]

        metric_metadata = {}
        ordered_metric_keys = []
        for item in categories:
            for metric in item["stats"]:
                metric_metadata.setdefault(metric["key"], metric)
                if metric["key"] not in ordered_metric_keys:
                    ordered_metric_keys.append(metric["key"])

        select_cols = ["player_id", "player_name", "team", "games"] + ordered_metric_keys
        select_str = ", ".join(select_cols)
        params = list(population_params)
        where = f"WHERE {population_where}"
        # Default min_games for MLB to filter cup-of-coffee players
        effective_min = min_games
        if effective_min == 0 and lg == "mlb":
            effective_min = 30 if stat_type == "batting" else 10
        if effective_min > 0:
            where += " AND games >= ?"
            params.append(effective_min)

        rows = con.execute(
            f"SELECT {select_str} FROM player_stats {where} "
            f"AND {sort_stat} IS NOT NULL ORDER BY {sort_stat} DESC, player_name ASC LIMIT ?",
            params + [limit]
        ).fetchall()

    leaders = []
    for r in rows:
        entry = {"player_id": r["player_id"], "name": r["player_name"],
                 "team": r["team"] or "", "games": r["games"]}
        for key in ordered_metric_keys:
            entry[key] = _format_leader_value(r[key], metric_metadata[key]["format"])
        leaders.append(entry)

    return {"league": lg, "season": season if isinstance(season, int) else str(season),
            "stat": sort_stat, "stat_type": stat_type,
            "category": selected_category, "categories": categories,
            "columns": columns, "leaders": leaders}
