"""stats — players router stats layer."""
import json
import math
import sqlite3
import time
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from league_offering import offered_leagues, sql_league_filter
from league_stats import LEADERBOARD_LEAGUES, canonical_population_sql
from nfl_rankings import nfl_player_rank_context
from nfl_stat_derivations import with_derived as _with_derived
from nfl_news import (ROTOWIRE_LABEL, load_news_feed, load_player_news_page, load_sleeper_crosswalk, merge_player_news, resolve_rotowire_id)
from . import router
from .search import _reg_season_game_filter  # noqa: E402


def __db_pkg(*args, **kwargs):
    """Resolve `routers.players._db` at call time (tests patch the package attr)."""
    from routers.players import _db as _pkg
    return _pkg(*args, **kwargs)

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
    with closing(__db_pkg()) as con:
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
        with closing(__db_pkg()) as con:
            con.row_factory = sqlite3.Row
            reg_filter, _ = _reg_season_game_filter(con, lg)
            rows = con.execute(
                "SELECT player_id, stats, game_date, game_no FROM player_game_logs "
                f"WHERE league=? AND season=? AND player_id IN ({placeholders}) {reg_filter}",
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
    if lg not in LEADERBOARD_LEAGUES:
        return JSONResponse({"error": f"Unsupported league: {league}"}, 404)

    if lg == "mlb":
        stat_type = (type or "batting").lower()
        if stat_type not in ("batting", "pitching"):
            raise HTTPException(400, "type must be batting or pitching for MLB")
        definition_key = f"mlb_{stat_type}"
        canonical_type = stat_type
    else:
        if type is not None:
            raise HTTPException(400, "type is only supported for MLB leaders")
        stat_type = None
        canonical_type = "season"
        definition_key = lg

    definitions = _LEAGUE_CATEGORIES[definition_key]
    # `games` is a column on every leaders table but belongs to no stat category,
    # so it is sortable without being offerable as a category metric. Sorting the
    # visible 25 rows in the browser is not an option here: those rows are the top
    # 25 for the CURRENT stat, so a client-side re-sort would answer "who played
    # most among the scoring leaders" while looking like "who played most".
    _EXTRA_SORT_KEYS = {"games"}
    category_defs = {item["key"]: item for item in definitions}
    approved_stats = {
        metric["key"] for item in definitions for metric in item["stats"]
    }
    if category is not None and category not in category_defs:
        raise HTTPException(400, f"Unknown category {category!r} for {definition_key}")
    if stat is not None and stat not in approved_stats | _EXTRA_SORT_KEYS:
        raise HTTPException(400, f"Unknown stat {stat!r} for {definition_key}")
    if category is not None and stat is not None and stat not in _EXTRA_SORT_KEYS:
        category_stats = {metric["key"] for metric in category_defs[category]["stats"]}
        if stat not in category_stats:
            raise HTTPException(400, f"Stat {stat!r} does not belong to category {category!r}")

    with closing(__db_pkg()) as con:
        con.row_factory = sqlite3.Row
        db_cols = {row[1] for row in con.execute("PRAGMA table_info(player_stats)").fetchall()}
        ownership_where, ownership_params = canonical_population_sql(
            lg, canonical_type, alias="ps"
        )
        season_where = f"ps.league=? AND {ownership_where}"
        season_params = [lg]
        season_params.extend(ownership_params)
        available_seasons = [
            row["season"] for row in con.execute(
                f"""SELECT DISTINCT ps.season AS season
                    FROM player_stats ps
                    WHERE {season_where}
                    ORDER BY ps.season DESC""",
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

        population_where = f"ps.league=? AND ps.season=? AND {ownership_where}"
        population_params = [lg, season]
        population_params.extend(ownership_params)

        # `player_id IS NOT NULL` is load-bearing. This asks whether one PLAYER owns
        # two canonical rows; SQL's GROUP BY puts every NULL in one group, so without
        # it the question silently becomes "are there two rows the spine has not
        # matched yet", which is a different thing and not an emergency. It fired on
        # prod 2026-08-03: NHL had 21 unmatched fringe skaters (CJ Suess, 2 games) and
        # ZERO real duplicates, and the whole league's leaders went 503.
        duplicate = con.execute(
            f"""SELECT ps.player_id
                FROM player_stats ps
                WHERE {population_where} AND ps.player_id IS NOT NULL
                GROUP BY ps.player_id
                HAVING COUNT(*)>1
                LIMIT 1""",
            population_params,
        ).fetchone()
        if duplicate is not None:
            raise HTTPException(
                503,
                "canonical player stats contain duplicate ownership for "
                f"{lg} season {season}; rebuild required",
            )
        # This guard exists for the 2026-07 MLB corruption, where a stats row carried
        # ANOTHER PLAYER's name (Statcast's `player_name` is the pitcher's). It used to
        # assert raw string equality against `players.name`, and that ruler is wrong:
        # `player_stats` is a row about a SEASON and carries the name and team the player
        # had THAT season, while `players` is the CURRENT index. A transfer or a change in
        # how the publisher writes a name makes the two legitimately differ.
        #
        # Measured 2026-08-17 on picks.dev.db: 18 NCAAF rows tripped it and ZERO were
        # corrupt. All 18 of dev's `players` rows matched ESPN's current listing exactly
        # (AJ Green Jr.|WMU, DJ Lagway|BAY, ...) against 2025 stats rows reading AJ
        # Green|ARK. 11 of the 18 differed only by accents, punctuation or a suffix. The
        # whole league's leaderboard 503'd on correct data — the same false-positive shape
        # the duplicate check above already carries a note about.
        #
        # So ask the question the guard actually means: does this row's name belong to a
        # DIFFERENT person in this league? A formatting or transfer drift does not; the
        # MLB pitcher case does, because the pitcher is himself a player in the index.
        candidates = con.execute(
            f"""SELECT ps.player_id, ps.player_name, p.name
                FROM player_stats ps
                JOIN players p
                  ON p.id=ps.player_id AND p.league=ps.league
                WHERE {population_where}
                  AND ps.player_name!=p.name""",
            population_params,
        ).fetchall()
        def _surname(value: str) -> str:
            parts = _normalize_name(value).split()
            return parts[-1] if parts else ""

        for cand in candidates:
            stats_name, index_name = cand["player_name"], cand["name"]
            if _normalize_name(stats_name) == _normalize_name(index_name):
                continue  # accents, punctuation, a suffix — the same person, written twice
            if _surname(stats_name) and _surname(stats_name) == _surname(index_name):
                # Same surname, different given name: every one of these measured on
                # 2026-08-17 was a nickname against a legal name — Bam/Braylon McReynolds,
                # Charlie/Charles Miska, Jake/Jacob Newell, Ray Ray/Nathaniel Joseph. The
                # publisher writes one form in a season row and another in the index.
                continue
            # A different surname is the corruption signal: the MLB rows carried the
            # PITCHER's name, and a fabricated name fails here too.
            raise HTTPException(
                503,
                "canonical player stats disagree with the player index for "
                f"{lg} season {season}; rebuild required",
            )

        available_keys = set()
        for key in approved_stats:
            if key not in db_cols:
                continue
            count = con.execute(
                f"""SELECT COUNT(ps.{key})
                    FROM player_stats ps
                    WHERE {population_where}""",
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
        if stat is not None and stat not in available_keys | _EXTRA_SORT_KEYS:
            raise HTTPException(400, f"Stat {stat!r} is unavailable for season {season}")
        if category is not None:
            if category not in available_categories:
                raise HTTPException(400, f"Category {category!r} is unavailable for season {season}")
            selected_category = category
        elif stat is not None and stat not in _EXTRA_SORT_KEYS:
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

        select_cols = [
            "ps.player_id",
            "p.name AS player_name",
            "COALESCE(p.team, ps.team) AS team",
            "ps.games",
        ] + [f"ps.{key} AS {key}" for key in ordered_metric_keys]
        select_str = ", ".join(select_cols)
        params = list(population_params)
        where = f"WHERE {population_where}"
        # Default min_games for MLB to filter cup-of-coffee players
        effective_min = min_games
        if effective_min == 0 and lg == "mlb":
            effective_min = 30 if stat_type == "batting" else 10
        if effective_min > 0:
            where += " AND ps.games >= ?"
            params.append(effective_min)

        rows = con.execute(
            f"""SELECT {select_str}
                FROM player_stats ps
                JOIN players p
                  ON p.id=ps.player_id AND p.league=ps.league
                {where}
                  AND ps.{sort_stat} IS NOT NULL
                ORDER BY ps.{sort_stat} DESC, p.name ASC
                LIMIT ?""",
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
    # NCAAF holds SEASON TOTALS, not per-game rates — ingest_ncaaf_season_stats.py
    # sums CFBD's per-game rows (see league_stats.py:195). So these are the raw
    # columns, deliberately not the `_g` keys the NFL block uses: no *_g column is
    # populated for ncaaf, and naming one here would silently drop the category
    # (the availability loop below skips any key missing from db_cols).
    # Every metric listed is non-NULL on both databases as of 2026-08-17.
    "ncaaf": [
        {"key": "passing", "label": "Passing", "stats": [
            _metric("pass_yds", "Pass Yards", "integer"),
            _metric("pass_td", "Pass Touchdowns", "integer"),
            _metric("att", "Pass Attempts", "integer"),
            _metric("intc", "Interceptions", "integer"),
        ]},
        {"key": "rushing", "label": "Rushing", "stats": [
            _metric("rush_yds", "Rush Yards", "integer"),
            _metric("rush_td", "Rush Touchdowns", "integer"),
        ]},
        {"key": "receiving", "label": "Receiving", "stats": [
            _metric("rec_yds", "Receiving Yards", "integer"),
            _metric("rec", "Receptions", "integer"),
            _metric("rec_td", "Receiving Touchdowns", "integer"),
        ]},
    ],
    "mls": [
        {"key": "scoring", "label": "Scoring", "stats": [
            _metric("goals", "Goals", "integer"),
            _metric("assists", "Assists", "integer"),
        ]},
        {"key": "shooting", "label": "Shooting", "stats": [
            _metric("shots", "Shots", "integer"),
            _metric("sot", "Shots on Target", "integer"),
        ]},
    ],
}

_LEAGUE_DEFAULTS = {
    "nba": ("scoring", "pts"),
    "nfl": ("passing", "pass_yds_g"),
    "nhl": ("scoring", "points_nhl"),
    "mlb_batting": ("production", "avg"),
    "mlb_pitching": ("strikeouts", "k_pct"),
    "ncaaf": ("passing", "pass_yds"),
    "mls": ("scoring", "goals"),
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
    "mls": {
        "scoring": {"metric": _metric("goals", "Goals/Game", "decimal_1"), "raw_keys": ("goals",)},
        "shooting": {"metric": _metric("shots", "Shots/Game", "decimal_1"), "raw_keys": ("shots",)},
    },
}

_COMPARISON_BASE = {
    "recent_label": "Last 5",
    "baseline_label": "Earlier season",
    "recent_games": 5,
    "min_baseline_games": 5,
    "status": "display_only",
}

_DST_POSITIONS = ("DEF", "DST", "D/ST")

# The two positions nflverse's `fantasy_points` does not cover, so the only honest
# source for their weekly score is the scorer's. See
# `ingest_nfl_published_fantasy.py` -- 446 of 544 D/ST team-weeks disagreed with the
# number this project used to compute for itself.
_PUBLISHED_FANTASY_POSITIONS = ("PK", "K", "DEF", "DST", "D/ST")

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
