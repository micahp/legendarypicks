"""routers/players.py — players endpoints. Handlers only; shared code lives in _core."""
import json
import math
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *

router = APIRouter()

@router.get("/api/players/search")
def search_players(q: str = Query("", description="Search query")):
    query = str(q or "").strip()
    if len(query) < 2:
        return []
    contains = "%{}%".format(query)
    prefix = "{}%".format(query)
    with closing(_db()) as con:
        rows = con.execute(
            """SELECT p.id, p.name, p.team, p.league,
                      EXISTS(SELECT 1 FROM player_game_logs g WHERE g.player_id=p.id) AS has_logs,
                      EXISTS(SELECT 1 FROM props pr WHERE pr.player_id=p.id) AS has_props,
                      EXISTS(SELECT 1 FROM player_stats s WHERE s.player_id=p.id) AS has_stats
               FROM players p
               WHERE p.name LIKE ? COLLATE NOCASE
                 AND (
                   EXISTS(SELECT 1 FROM player_game_logs g WHERE g.player_id=p.id)
                   OR EXISTS(SELECT 1 FROM props pr WHERE pr.player_id=p.id)
                   OR EXISTS(SELECT 1 FROM player_stats s WHERE s.player_id=p.id)
                 )
               ORDER BY
                 CASE
                   WHEN p.name = ? COLLATE NOCASE THEN 0
                   WHEN p.name LIKE ? COLLATE NOCASE THEN 1
                   ELSE 2
                 END,
                 has_props DESC, has_logs DESC, has_stats DESC,
                 p.name COLLATE NOCASE, p.id
               LIMIT 20""",
            (contains, query, prefix),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "team": r["team"],
            "league": r["league"],
            "coverage": {
                "game_logs": bool(r["has_logs"]),
                "props": bool(r["has_props"]),
                "season_stats": bool(r["has_stats"]),
            },
        }
        for r in rows
    ]


def _season_stats_for_profile(player_id: int, player_name: str, league: str):
    """Reuse the DB-backed advanced-stat readers for the page-level profile."""
    getter = {
        "mlb": lambda: _get_mlb_stats(player_name, player_id, None, time.time()),
        "nfl": lambda: _get_nfl_stats(player_name, player_id, time.time()),
        "nba": lambda: _get_nba_stats(player_name, player_id, time.time()),
        "nhl": lambda: _get_nhl_stats(player_name, player_id, time.time()),
    }.get(str(league or "").lower())
    if getter is None:
        return None
    result = getter()
    if not isinstance(result, dict):
        return None
    has_stats = (
        bool(result.get("stats"))
        or bool(result.get("batting"))
        or bool(result.get("pitching"))
    )
    return result if has_stats else None


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
        # Required for the allowlist below to be correct, not cosmetic: 2024 rows
        # carry legacy nflverse keys (`receptions`), 2025 rows canonical pbp keys
        # (`rec`), and no season mixes the two. A player whose most recent season
        # is 2024 would miss _NFL_PROJECTION_STATS entirely and lose every
        # projection. Applied to the game logs too so the game-log table can key
        # off canonical names alone. /api/projections/player/{id} normalizes the
        # same way.
        if league == "nfl":
            s = {_NFL_KEY_NORMALIZE.get(k, k): v for k, v in s.items()}
        recent.append({"date": r["game_date"], "opponent": r["opponent"],
                       "home": (r["home_away"] == "home") if r["home_away"] else None,
                       # NFL rows are week-keyed with a NULL game_date, so the
                       # week is the only thing that identifies the game.
                       "game_no": r["game_no"], "stats": s})
        for k, v in s.items():
            if isinstance(v, (int, float)):
                series.setdefault(k, []).append(v)
    projections = {}
    for k, vals in series.items():
        # NFL blobs carry snap-count and NGS fields alongside production stats.
        # Projecting a cushion or a special-teams snap % is meaningless, and for
        # an offensive player those rows are all zeros — 17-20 rows of them,
        # burying everything below. Usage belongs on the usage trend, not here.
        if league == "nfl" and k not in _NFL_PROJECTION_STATS:
            continue
        pr = proj_mod.project_stat(vals)
        if not pr:
            continue
        # A stat the player has never recorded projects to zero across the board:
        # every passing field for a receiver, every defensive field for anyone on
        # offense. Nothing to say, so say nothing.
        if league == "nfl" and not pr.get("season_avg") and not pr.get("projection"):
            continue
        projections[k] = pr

    season_stats = _season_stats_for_profile(p["id"], p["name"], league)
    return {
        "id": p["id"], "name": p["name"], "team": p["team"], "league": league,
        "position": p["position"], "season": season, "games": len(logs),
        "recent_games": recent[:15],
        "projections": projections,
        "props": [{"market": _base_market(x["market"]), "side": x["side"], "line": x["line"]} for x in props],
        "season_stats": season_stats,
        "coverage": {
            "game_logs": bool(logs),
            "props": bool(props),
            "season_stats": season_stats is not None,
        },
        "data_status": "ready" if (logs or props or season_stats) else "unavailable",
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


# Legacy (2024 nflverse) → canonical (2025 pbp) stat key normalization.
# The two ingest pipelines use different key names; projections must be
# key-consistent regardless of which season is auto-selected.
_NFL_KEY_NORMALIZE = {
    "passing_yards":    "pass_yds",
    "passing_tds":      "pass_td",
    "completions":      "cmp",
    "attempts":         "att",
    "interceptions":    "intc",
    "rushing_yards":    "rush_yds",
    "rushing_tds":      "rush_td",
    "receiving_yards":  "rec_yds",
    "receiving_tds":    "rec_td",
    "receptions":       "rec",
    "fantasy_points":   "fpts",
    "fantasy_points_ppr": "fpts_ppr",
    # carries, targets: same key in both pipelines
}

# Production stats worth projecting on the player page, in canonical (post-
# normalize) key names. Everything else an NFL blob carries — off_pct/off_snaps,
# def_pct/def_snaps, st_pct/st_snaps, and the NGS fields adot/air_yds_share/
# cushion/separation/yac_above_exp/cpoe/pass_epa — is usage or context, shown on
# the usage trend rather than projected here.
_NFL_PROJECTION_STATS = {
    "pass_yds", "pass_td", "intc", "cmp", "att",
    "rush_yds", "rush_td", "carries",
    "rec", "rec_yds", "rec_td", "targets",
    "fpts", "fpts_ppr",
}


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
                # Normalize legacy (2024 nflverse) keys → canonical (2025 pbp) keys
                k = _NFL_KEY_NORMALIZE.get(k, k)
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

_CHANGE_METRICS = {
    "mlb": {
        "production": {"metric": _metric("hr_g", "HR/Game", "decimal_1"), "raw_keys": ("HR",)},
        "discipline": {"metric": _metric("k_pct", "K%", "percent_1"), "rate": {"numerators": ["K"], "denominators": ["PA"], "pct": True}},
    },
    "nba": {
        "scoring": {"metric": _metric("pts", "Points/Game", "decimal_1"), "raw_keys": ("PTS",)},
        "playmaking": {"metric": _metric("ast", "Assists/Game", "decimal_1"), "raw_keys": ("AST",)},
        "rebounding": {"metric": _metric("reb", "Rebounds/Game", "decimal_1"), "raw_keys": ("REB",)},
        "defense": {"metric": _metric("stl", "Steals/Game", "decimal_1"), "raw_keys": ("STL",)},
        "efficiency": {"metric": _metric("ts_pct", "True Shooting %", "percent_1"), "ts": True},
    },
    "nfl": {
        "passing": {"metric": _metric("pass_yds_g", "Pass Yards/Game", "decimal_1"), "raw_keys": ("pass_yds", "passing_yards")},
        "rushing": {"metric": _metric("rush_yds_g", "Rush Yards/Game", "decimal_1"), "raw_keys": ("rush_yds", "rushing_yards")},
        "receiving": {"metric": _metric("rec_yds_g", "Receiving Yards/Game", "decimal_1"), "raw_keys": ("rec_yds", "receiving_yards")},
    },
    "nhl": {
        "scoring": {"metric": _metric("points_nhl", "Points/Game", "decimal_1"), "raw_keys": ("points",)},
        "shooting": {"metric": _metric("shots", "Shots/Game", "decimal_1"), "raw_keys": ("shots",)},
        "special_teams": {"metric": _metric("ppp", "Power-Play Points/Game", "decimal_1"), "raw_keys": ("powerPlayPoints",)},
        "possession": {"metric": _metric("plus_minus", "Plus/Minus per Game", "decimal_1"), "raw_keys": ("plusMinus",)},
    },
}

_COMPARISON_BASE = {
    "recent_label": "Last 5",
    "baseline_label": "Earlier season",
    "recent_games": 5,
    "min_baseline_games": 5,
    "status": "display_only",
}


def _empty_leaders(lg, season, stat_type, available_seasons=None):
    return {
        "league": lg,
        "season": season,
        "available_seasons": available_seasons or [],
        "stat": None,
        "stat_type": stat_type,
        "category": None,
        "categories": [],
        "columns": [],
        "leaders": [],
        "change_metric": None,
        "comparison": None,
        "changes": [],
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


def _numeric_stat(stats, keys):
    for key in keys:
        if key not in stats:
            continue
        value = stats[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        return value if math.isfinite(value) else None
    return None


def _parse_log_stats(raw):
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _window_value(logs, definition):
    if definition.get("ts"):
        totals = {"PTS": 0.0, "FGA": 0.0, "FTA": 0.0}
        valid = 0
        for log in logs:
            stats = _parse_log_stats(log["stats"])
            if stats is None:
                continue
            values = {key: _numeric_stat(stats, (key,)) for key in totals}
            if any(value is None for value in values.values()):
                continue
            valid += 1
            for key, value in values.items():
                totals[key] += value
        denominator = 2 * (totals["FGA"] + 0.44 * totals["FTA"])
        return (100 * totals["PTS"] / denominator if denominator > 0 else None), valid

    rate_def = definition.get("rate")
    if rate_def:
        numer_keys = rate_def["numerators"]
        denom_keys = rate_def["denominators"]
        all_keys = numer_keys + denom_keys
        totals = {k: 0.0 for k in all_keys}
        valid = 0
        for log in logs:
            stats = _parse_log_stats(log["stats"])
            if stats is None:
                continue
            values = {key: _numeric_stat(stats, (key,)) for key in totals}
            if any(value is None for value in values.values()):
                continue
            valid += 1
            for key, value in values.items():
                totals[key] += value
        num_total = sum(totals[k] for k in numer_keys)
        denom_total = sum(totals[k] for k in denom_keys)
        if denom_total == 0:
            return None, valid
        result = num_total / denom_total
        if rate_def.get("pct"):
            result *= 100
        return result, valid

    values = []
    for log in logs:
        stats = _parse_log_stats(log["stats"])
        if stats is None:
            continue
        value = _numeric_stat(stats, definition["raw_keys"])
        if value is not None:
            values.append(value)
    return (sum(values) / len(values) if values else None), len(values)


def _log_order(row):
    game_date = row["game_date"] or ""
    try:
        game_no = int(row["game_no"])
    except (TypeError, ValueError):
        game_no = -1
    return (1, game_date, game_no) if game_date else (0, "", game_no)


def _change_evidence(lg, selected_category, season, leaders):
    definition = _CHANGE_METRICS.get(lg, {}).get(selected_category)
    if definition is None:
        return None, None, []

    change_metric = dict(definition["metric"])
    eligible = [leader for leader in leaders if leader.get("player_id") is not None]
    comparison = {
        **_COMPARISON_BASE,
        "eligible_leaders": len(eligible),
        "qualified_leaders": 0,
    }
    if not eligible:
        return change_metric, comparison, []

    leader_by_id = {}
    for leader in eligible:
        leader_by_id.setdefault(leader["player_id"], leader)
    player_ids = list(leader_by_id)
    placeholders = ",".join("?" for _ in player_ids)
    try:
        with closing(_db()) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT player_id, stats, game_date, game_no FROM player_game_logs "
                f"WHERE league=? AND season=? AND player_id IN ({placeholders})",
                [lg, season] + player_ids,
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: player_game_logs" in str(exc).lower():
            return change_metric, comparison, []
        raise

    logs_by_player = {player_id: [] for player_id in player_ids}
    for row in rows:
        if row["player_id"] in logs_by_player:
            logs_by_player[row["player_id"]].append(row)

    candidates = []
    for player_id, leader in leader_by_id.items():
        logs = sorted(logs_by_player[player_id], key=_log_order)
        if len(logs) < 10:
            continue
        baseline_logs, recent_logs = logs[:-5], logs[-5:]
        recent_value, recent_games = _window_value(recent_logs, definition)
        baseline_value, baseline_games = _window_value(baseline_logs, definition)
        if (
            recent_value is None or baseline_value is None
            or recent_games != 5 or baseline_games < 5
        ):
            continue
        delta = recent_value - baseline_value
        tolerance = 0.05
        direction = "rising" if delta > tolerance else "falling" if delta < -tolerance else "flat"
        candidates.append({
            "player_id": player_id,
            "name": leader["name"],
            "team": leader["team"],
            "metric": dict(change_metric),
            "recent_value": _format_leader_value(recent_value, change_metric["format"]),
            "baseline_value": _format_leader_value(baseline_value, change_metric["format"]),
            "delta": _format_leader_value(delta, change_metric["format"]),
            "direction": direction,
            "recent_games": recent_games,
            "baseline_games": baseline_games,
            "_delta": delta,
        })

    comparison["qualified_leaders"] = len(candidates)
    candidates.sort(key=lambda item: (-abs(item["_delta"]), item["name"]))
    changes = []
    for candidate in candidates[:3]:
        candidate.pop("_delta")
        changes.append(candidate)
    return change_metric, comparison, changes


@router.get("/api/{league}/leaders")
def league_leaders(league: str,
                   stat: Optional[str] = Query(None),
                   category: Optional[str] = Query(None),
                   type: Optional[str] = Query(None),
                   season: Optional[int] = Query(None),
                   min_games: int = Query(0, ge=0),
                   limit: int = Query(25, ge=1, le=100)):
    """Player leaderboard for a league from the player_stats table.
    ?category=scoring — metric group (default: league-appropriate)
    ?stat=pts — sort column within/inferred from the category
    ?type=batting|pitching — MLB only, picks the stat_type to filter
    ?season=2024 — defaults to the latest season with data (never hardcoded — a new
    season's rows just become the new MAX() the day an ingest job starts writing them,
    same day it appears in `available_seasons` below, no code change required)
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
        available_seasons = [
            row["season"] for row in con.execute(
                f"SELECT DISTINCT season FROM player_stats WHERE {season_where} "
                "ORDER BY season DESC",
                season_params,
            ).fetchall()
        ]
        if not available_seasons:
            return _empty_leaders(lg, None, stat_type)
        if season is not None:
            if season not in available_seasons:
                raise HTTPException(400, f"season {season} has no data for {lg}"
                                     f"{f' ({stat_type})' if stat_type else ''}; "
                                     f"available: {available_seasons}")
        else:
            season = available_seasons[0]

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
            return _empty_leaders(lg, normalized_season, stat_type, available_seasons)

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

    change_metric, comparison, changes = _change_evidence(
        lg, selected_category, season, leaders
    )
    return {"league": lg, "season": season if isinstance(season, int) else str(season),
            "available_seasons": available_seasons,
            "stat": sort_stat, "stat_type": stat_type,
            "category": selected_category, "categories": categories,
            "columns": columns, "leaders": leaders,
            "change_metric": change_metric, "comparison": comparison,
            "changes": changes}
