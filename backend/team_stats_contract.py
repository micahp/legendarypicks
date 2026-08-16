"""League-specific team aggregate and ESPN extraction helpers.

The aggregate builder is intentionally read-only.  NBA/NHL/NFL are supported
only when a completed ingestion manifest, reciprocal result rows, and complete
paired box-score rows agree.  This prevents a partial capture from being
presented as season-to-date coverage.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

from team_codes import is_canonical


# ncaaf 137 = playing FBS teams. ESPN's group-80 team list publishes 146 ids,
# but nine are all-star/combine sides (team_codes.NON_FRANCHISE) that never play
# a regular-season game; FCS buy-game opponents (Mercer etc.) play real games
# but are not FBS, so their rows count but not toward team coverage.
EXPECTED_TEAMS = {"mlb": 30, "nba": 30, "nhl": 32, "nfl": 32, "mls": 30, "ncaaf": 137}


def _column(key: str, label: str, *, format: str = "number") -> dict[str, str]:
    return {"key": key, "label": label, "format": format}


LEAGUE_CATEGORIES = {
    "mlb": [
        {
            "key": "record",
            "label": "Record & runs",
            "columns": [
                _column("games", "Games"), _column("wins", "Wins"),
                _column("losses", "Losses"), _column("runs_for", "Runs For"),
                _column("runs_against", "Runs Against"),
                _column("run_differential", "Run Differential"),
            ],
        },
    ],
    "nba": [
        {
            "key": "scoring_shooting", "label": "Scoring & shooting",
            "columns": [
                _column("games", "Games"), _column("wins", "Wins"),
                _column("losses", "Losses"), _column("points_per_game", "PTS/G", format="decimal"),
                _column("fg_pct", "FG%", format="percent"),
                _column("three_pct", "3P%", format="percent"),
                _column("ft_pct", "FT%", format="percent"),
            ],
        },
        {
            "key": "rebounding", "label": "Rebounding",
            "columns": [
                _column("games", "Games"),
                _column("rebounds_per_game", "REB/G", format="decimal"),
                _column("off_rebounds_per_game", "OREB/G", format="decimal"),
                _column("def_rebounds_per_game", "DREB/G", format="decimal"),
            ],
        },
        {
            "key": "playmaking", "label": "Playmaking & ball security",
            "columns": [
                _column("games", "Games"),
                _column("assists_per_game", "AST/G", format="decimal"),
                _column("turnovers_per_game", "TOV/G", format="decimal"),
                _column("assist_turnover_ratio", "AST/TOV", format="decimal"),
            ],
        },
        {
            "key": "defense", "label": "Defense",
            "columns": [
                _column("games", "Games"),
                _column("points_allowed_per_game", "Opp PTS/G", format="decimal"),
                _column("steals_per_game", "STL/G", format="decimal"),
                _column("blocks_per_game", "BLK/G", format="decimal"),
            ],
        },
    ],
    "nhl": [
        {
            "key": "scoring_shots", "label": "Scoring & shots",
            "columns": [
                _column("games", "Games"), _column("wins", "Wins"),
                _column("losses", "Losses"), _column("ties", "Ties"),
                _column("goals_per_game", "GF/G", format="decimal"),
                _column("goals_allowed_per_game", "GA/G", format="decimal"),
                _column("shots_per_game", "Shots/G", format="decimal"),
                _column("shooting_pct", "Shooting %", format="percent"),
            ],
        },
        {
            "key": "possession_physical", "label": "Possession & physical play",
            "columns": [
                _column("games", "Games"),
                _column("faceoff_pct", "Faceoff %", format="percent"),
                _column("hits_per_game", "Hits/G", format="decimal"),
                _column("blocked_shots_per_game", "Blocks/G", format="decimal"),
                _column("takeaway_giveaway_ratio", "TA/GA", format="decimal"),
            ],
        },
        {
            "key": "special_teams", "label": "Special teams",
            "columns": [
                _column("games", "Games"),
                _column("powerplay_pct", "Power Play %", format="percent"),
                _column("shorthanded_goals", "SH Goals"),
                _column("penalty_minutes_per_game", "PIM/G", format="decimal"),
            ],
        },
    ],
    "nfl": [
        {
            "key": "offense", "label": "Offense",
            "columns": [
                _column("games", "Games"), _column("wins", "Wins"),
                _column("losses", "Losses"),
                _column("points_per_game", "PTS/G", format="decimal"),
                _column("total_yards_per_game", "YDS/G", format="decimal"),
                _column("passing_yards_per_game", "Pass YDS/G", format="decimal"),
                _column("rushing_yards_per_game", "Rush YDS/G", format="decimal"),
                _column("yards_per_play", "Yards/Play", format="decimal"),
            ],
        },
        {
            "key": "defense", "label": "Defense",
            "columns": [
                _column("games", "Games"),
                _column("points_allowed_per_game", "Opp PTS/G", format="decimal"),
                _column("yards_allowed_per_game", "Opp YDS/G", format="decimal"),
                _column("passing_yards_allowed_per_game", "Opp Pass/G", format="decimal"),
                _column("rushing_yards_allowed_per_game", "Opp Rush/G", format="decimal"),
                _column("takeaways", "Takeaways"),
            ],
        },
        {
            "key": "special_teams", "label": "Special teams",
            "columns": [
                _column("games", "Games"),
                _column("defensive_special_teams_tds", "Def/ST TDs"),
            ],
        },
    ],
    "mls": [
        {
            "key": "record", "label": "Record",
            "columns": [
                _column("games", "Games"), _column("wins", "Wins"),
                _column("losses", "Losses"), _column("ties", "Ties"),
            ],
        },
        {
            "key": "scoring_shooting", "label": "Scoring & shooting",
            "columns": [
                _column("games", "Games"),
                _column("goals_per_game", "GF/G", format="decimal"),
                _column("goals_allowed_per_game", "GA/G", format="decimal"),
                _column("shots_per_game", "Shots/G", format="decimal"),
                _column("blocked_shots_per_game", "Blocks/G", format="decimal"),
            ],
        },
    ],
    "ncaaf": [
        {
            "key": "record", "label": "Record",
            "columns": [
                _column("games", "Games"), _column("wins", "Wins"),
                _column("losses", "Losses"),
            ],
        },
        {
            "key": "offense", "label": "Offense",
            "columns": [
                _column("games", "Games"),
                _column("points_per_game", "PTS/G", format="decimal"),
                _column("total_yards_per_game", "YDS/G", format="decimal"),
                _column("passing_yards_per_game", "Pass YDS/G", format="decimal"),
                _column("rushing_yards_per_game", "Rush YDS/G", format="decimal"),
                _column("first_downs_per_game", "1st Downs/G", format="decimal"),
            ],
        },
        {
            "key": "defense", "label": "Defense",
            "columns": [
                _column("games", "Games"),
                _column("points_allowed_per_game", "Opp PTS/G", format="decimal"),
                _column("yards_allowed_per_game", "Opp YDS/G", format="decimal"),
                _column("turnovers", "Turnovers"),
            ],
        },
    ],
}


STAT_FIELDS = {
    "nba": (
        "fgm_fga", "tpm_tpa", "ftm_fta", "rebounds", "off_rebounds",
        "def_rebounds", "assists", "steals", "blocks", "turnovers",
    ),
    "nhl": (
        "shots", "blocked_shots", "hits", "takeaways", "giveaways",
        "faceoff_pct", "powerplay_goals", "powerplay_opps",
        "shorthanded_goals", "penalty_min",
    ),
    "nfl": (
        "first_downs", "total_offensive_plays", "total_yards",
        "net_passing_yards", "rushing_yards", "turnovers",
        "defensive_special_teams_tds",
    ),
    "mls": (
        # Columns that exist in team_game_stats and the backfill INSERT.
        # Soccer-native stats (shots_on_target, possession_pct, corners...)
        # have no column yet — recorded as a gap, not silently dropped here.
        "shots", "blocked_shots",
    ),
    "ncaaf": (
        # Measured 2026-08-07 against a completed 2025 FBS summary (WIS-ALA):
        # football boxscore team stats publish firstDowns, totalYards,
        # netPassingYards, rushingYards, turnovers — exactly the five columns
        # below that exist in team_game_stats. NFL-only columns that college
        # football does not publish (total_offensive_plays,
        # defensive_special_teams_tds) are NOT mapped here: a missing mapping
        # is a publisher gap, not a silent zero.
        "first_downs", "total_yards", "net_passing_yards", "rushing_yards",
        "turnovers",
    ),
}


ESPN_TO_COLUMN = {
    "nba": {
        "fieldGoalsMade-fieldGoalsAttempted": "fgm_fga",
        "threePointFieldGoalsMade-threePointFieldGoalsAttempted": "tpm_tpa",
        "freeThrowsMade-freeThrowsAttempted": "ftm_fta",
        "totalRebounds": "rebounds", "offensiveRebounds": "off_rebounds",
        "defensiveRebounds": "def_rebounds", "assists": "assists",
        "steals": "steals", "blocks": "blocks", "turnovers": "turnovers",
        "totalTurnovers": "turnovers",
    },
    "nhl": {
        "shotsTotal": "shots", "blockedShots": "blocked_shots", "hits": "hits",
        "takeaways": "takeaways", "giveaways": "giveaways",
        "faceoffPercent": "faceoff_pct", "powerPlayGoals": "powerplay_goals",
        "powerPlayOpportunities": "powerplay_opps",
        "shortHandedGoals": "shorthanded_goals", "penaltyMinutes": "penalty_min",
    },
    "nfl": {
        "firstDowns": "first_downs", "totalOffensivePlays": "total_offensive_plays",
        "totalYards": "total_yards", "netPassingYards": "net_passing_yards",
        "rushingYards": "rushing_yards", "turnovers": "turnovers",
        "defensiveTouchdowns": "defensive_special_teams_tds",
    },
    "mls": {
        # Measured 2026-08-06 (event 726799, MIA 2-2 NYC): soccer /summary
        # boxscore team statistics publish these keys. Mapped to the columns
        # the team_game_stats INSERT actually writes; the soccer-native stats
        # (shotsOnTarget, possessionPct, corners...) have no column yet.
        "totalShots": "shots", "blockedShots": "blocked_shots",
    },
    "ncaaf": {
        # Measured 2026-08-07 (WIS-ALA 2025 FBS): college football publishes
        # the same five football keys the INSERT columns carry. The NFL keys
        # that college football does NOT publish (totalOffensivePlays,
        # defensiveTouchdowns) are deliberately absent — see STAT_FIELDS.
        "firstDowns": "first_downs",
        "totalYards": "total_yards",
        "netPassingYards": "net_passing_yards",
        "rushingYards": "rushing_yards",
        "turnovers": "turnovers",
    },
}


TEXT_FIELDS = {"fgm_fga", "tpm_tpa", "ftm_fta"}


def _number(value: Any) -> float | int | None:
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("%"):
            value = value[:-1].strip()
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def extract_espn_team_stats(league: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized team rows from one ESPN ``/summary`` payload."""
    lg = league.lower()
    mapping = ESPN_TO_COLUMN.get(lg)
    if not mapping:
        return []
    teams = (summary.get("boxscore") or {}).get("teams") or []
    out = []
    for item in teams:
        values: dict[str, Any] = {}
        for stat in item.get("statistics") or []:
            column = mapping.get(stat.get("name"))
            if not column:
                continue
            raw = stat.get("displayValue")
            values[column] = raw if column in TEXT_FIELDS else _number(raw)
        team = item.get("team") or {}
        out.append({
            "team_abbrev": team.get("abbreviation") or "",
            "home_away": item.get("homeAway") or item.get("_homeAway") or "",
            "stats": values,
        })
    return out


def _json_stats(raw: Any) -> dict[str, Any] | None:
    """Parse a `team_game_stats.stats` blob, or None when there isn't a usable one.

    None means "fall back to the columns" — an absent, empty or malformed blob
    must not blank out a row whose columns are still populated. Distinguishing
    that from an empty dict matters: {} is a row we migrated and found nothing
    in, which is genuinely no stats.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _table_columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _round(value: float | int | None, places: int = 3):
    return None if value is None else round(value, places)


def _rate(numerator: float, denominator: float):
    return _round(numerator / denominator) if denominator else None


def _made_attempted(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    separator = "-" if "-" in value else "/" if "/" in value else None
    if not separator:
        return None
    try:
        made, attempted = value.split(separator, 1)
        return int(made), int(attempted)
    except (TypeError, ValueError):
        return None


def _base_response(league: str, reason: str | None, season=None, coverage=None, teams=None):
    categories = LEAGUE_CATEGORIES.get(league, [])
    columns = categories[0]["columns"] if categories else []
    return {
        "league": league, "season": season, "supported": reason is None,
        "reason": reason, "categories": categories, "columns": columns,
        "coverage": coverage or {
            "status": "unavailable", "source": "team_game_results+team_game_stats",
            "scope": "reconciled_completed_games", "expected_teams": EXPECTED_TEAMS.get(league),
            "observed_teams": 0, "team_count": 0, "expected_games": None,
            "observed_games": 0, "games": 0, "rows": 0, "paired_games": 0,
            "stats_games": 0, "paired_stat_games": 0, "invalid_games": 0,
            "invalid_stat_games": 0,
            "missing_stat_rows": 0, "invalid_stat_rows": 0,
            "first_game_date": None, "last_game_date": None,
            "season_start": None, "season_end": None,
            "external_schedule_reconciled": False,
        },
        "teams": teams or [],
    }


def _valid_result_pair(rows: list[dict[str, Any]], *, allow_ties: bool = False) -> bool:
    if len(rows) != 2:
        return False
    first, second = rows
    required = ("team", "opponent", "score_for", "score_against", "win")
    if any(row.get(key) is None for row in rows for key in required):
        return False
    first_score = float(first["score_for"])
    second_score = float(second["score_for"])
    result_flags_valid = (
        int(first["win"]) == int(second["win"]) == 0
        if allow_ties and first_score == second_score
        else first_score != second_score
        and sorted((int(first["win"]), int(second["win"]))) == [0, 1]
        and int(first["win"]) == (1 if first_score > second_score else 0)
    )
    return (
        first["team"] == second["opponent"] and second["team"] == first["opponent"]
        and float(first["score_for"]) == float(second["score_against"])
        and float(second["score_for"]) == float(first["score_against"])
        and result_flags_valid
    )


def _aggregate_rows(league: str, results: list[dict[str, Any]], stats: dict[tuple[str, str], dict]):
    totals: dict[str, dict[str, Any]] = {}
    for result in results:
        team = result["team"]
        row = totals.setdefault(
            team, defaultdict(float, team=team, games=0, wins=0, losses=0, ties=0)
        )
        row["games"] += 1
        row["wins"] += int(result["win"])
        tied = float(result["score_for"]) == float(result["score_against"])
        row["ties"] += int(tied)
        row["losses"] += int(not tied and not int(result["win"]))
        row["points_for"] += float(result["score_for"])
        row["points_against"] += float(result["score_against"])
        stat = stats.get((str(result["game_id"]), team), {})
        for key, value in stat.items():
            if key in TEXT_FIELDS:
                parsed = _made_attempted(value)
                if parsed:
                    row[f"{key}_made"] += parsed[0]
                    row[f"{key}_attempted"] += parsed[1]
            elif isinstance(value, (int, float)):
                row[key] += value

        opponent = stats.get((str(result["game_id"]), result["opponent"]), {})
        if league in ("nfl", "ncaaf"):
            row["yards_allowed"] += opponent.get("total_yards", 0)
            row["passing_yards_allowed"] += opponent.get("net_passing_yards", 0)
            row["rushing_yards_allowed"] += opponent.get("rushing_yards", 0)
            if league == "nfl":
                row["takeaways"] += opponent.get("turnovers", 0)

    output = []
    for values in totals.values():
        games = values["games"]
        base = {
            "team": values["team"], "games": games, "wins": values["wins"],
            "losses": values["losses"],
        }
        if league == "mlb":
            base.update({
                "runs_for": int(values["points_for"]),
                "runs_against": int(values["points_against"]),
                "run_differential": int(values["points_for"] - values["points_against"]),
            })
        elif league == "nba":
            base.update({
                "points_per_game": _rate(values["points_for"], games),
                "points_allowed_per_game": _rate(values["points_against"], games),
                "fg_pct": _rate(values["fgm_fga_made"], values["fgm_fga_attempted"]),
                "three_pct": _rate(values["tpm_tpa_made"], values["tpm_tpa_attempted"]),
                "ft_pct": _rate(values["ftm_fta_made"], values["ftm_fta_attempted"]),
                "rebounds_per_game": _rate(values["rebounds"], games),
                "off_rebounds_per_game": _rate(values["off_rebounds"], games),
                "def_rebounds_per_game": _rate(values["def_rebounds"], games),
                "assists_per_game": _rate(values["assists"], games),
                "turnovers_per_game": _rate(values["turnovers"], games),
                "assist_turnover_ratio": _rate(values["assists"], values["turnovers"]),
                "steals_per_game": _rate(values["steals"], games),
                "blocks_per_game": _rate(values["blocks"], games),
            })
        elif league == "nhl":
            base.update({
                "goals_per_game": _rate(values["points_for"], games),
                "goals_allowed_per_game": _rate(values["points_against"], games),
                "shots_per_game": _rate(values["shots"], games),
                "shooting_pct": _rate(values["points_for"], values["shots"]),
                "faceoff_pct": _rate(values["faceoff_pct"], games * 100),
                "hits_per_game": _rate(values["hits"], games),
                "blocked_shots_per_game": _rate(values["blocked_shots"], games),
                "takeaway_giveaway_ratio": _rate(values["takeaways"], values["giveaways"]),
                "powerplay_pct": _rate(values["powerplay_goals"], values["powerplay_opps"]),
                "shorthanded_goals": int(values["shorthanded_goals"]),
                "penalty_minutes_per_game": _rate(values["penalty_min"], games),
            })
        elif league == "nfl":
            base.update({
                "ties": values["ties"],
                "points_per_game": _rate(values["points_for"], games),
                "total_yards_per_game": _rate(values["total_yards"], games),
                "passing_yards_per_game": _rate(values["net_passing_yards"], games),
                "rushing_yards_per_game": _rate(values["rushing_yards"], games),
                "yards_per_play": _rate(values["total_yards"], values["total_offensive_plays"]),
                "points_allowed_per_game": _rate(values["points_against"], games),
                "yards_allowed_per_game": _rate(values["yards_allowed"], games),
                "passing_yards_allowed_per_game": _rate(values["passing_yards_allowed"], games),
                "rushing_yards_allowed_per_game": _rate(values["rushing_yards_allowed"], games),
                "takeaways": int(values["takeaways"]),
                "defensive_special_teams_tds": int(values["defensive_special_teams_tds"]),
            })
        elif league == "mls":
            base.update({
                "ties": values["ties"],
                "goals_per_game": _rate(values["points_for"], games),
                "goals_allowed_per_game": _rate(values["points_against"], games),
                "shots_per_game": _rate(values["shots"], games),
                "blocked_shots_per_game": _rate(values["blocked_shots"], games),
            })
        elif league == "ncaaf":
            base.update({
                "points_per_game": _rate(values["points_for"], games),
                "total_yards_per_game": _rate(values["total_yards"], games),
                "passing_yards_per_game": _rate(values["net_passing_yards"], games),
                "rushing_yards_per_game": _rate(values["rushing_yards"], games),
                "first_downs_per_game": _rate(values["first_downs"], games),
                "points_allowed_per_game": _rate(values["points_against"], games),
                "yards_allowed_per_game": _rate(values["yards_allowed"], games),
                "turnovers": int(values["turnovers"]),
            })
        output.append(base)
    if league == "mlb":
        return sorted(output, key=lambda row: (-row["run_differential"], -row["runs_for"], row["team"]))
    return sorted(output, key=lambda row: (-row["wins"], row["losses"], row["team"]))


def build_team_aggregates(connection, league: str) -> dict[str, Any]:
    """Build a truthful season aggregate response from an existing connection."""
    lg = league.lower()
    if lg not in EXPECTED_TEAMS:
        return _base_response(lg, "unsupported_league")
    result_columns = _table_columns(connection, "team_game_results")
    required_results = {"league", "game_id", "team", "game_date", "opponent", "score_for", "score_against", "win"}
    if not required_results.issubset(result_columns):
        return _base_response(lg, "coverage_table_unavailable")
    manifest = None
    season_start = season_end = None
    if lg == "mlb":
        season_row = connection.execute(
            "SELECT MAX(CAST(substr(game_date,1,4) AS INTEGER)) FROM team_game_results "
            "WHERE league=? AND game_date GLOB '[0-9][0-9][0-9][0-9]-*'", (lg,),
        ).fetchone()
        season = season_row[0] if season_row else None
        if season is None:
            return _base_response(lg, "no_measured_coverage")
        result_query = (
            "SELECT game_id,team,game_date,opponent,score_for,score_against,win "
            "FROM team_game_results WHERE league=? AND substr(game_date,1,4)=? "
            "ORDER BY game_date,game_id,team"
        )
        result_params = (lg, str(season))
    else:
        required_manifest = {
            "league", "season", "season_start", "season_end", "status",
            "expected_teams", "fetched_teams", "expected_games", "fetched_games",
            "source", "completed_at",
        }
        if not required_manifest.issubset(_table_columns(connection, "team_stats_coverage")):
            return _base_response(lg, "season_bounds_unavailable")
        manifest_row = connection.execute(
            "SELECT * FROM team_stats_coverage WHERE league=? "
            "ORDER BY season DESC, completed_at DESC LIMIT 1", (lg,),
        ).fetchone()
        if not manifest_row:
            return _base_response(lg, "season_bounds_unavailable")
        manifest = dict(manifest_row)
        season = manifest.get("season")
        season_start = manifest.get("season_start")
        season_end = manifest.get("season_end")
        try:
            parsed_start = date.fromisoformat(season_start)
            parsed_end = date.fromisoformat(season_end)
            valid_bounds = parsed_start <= parsed_end and season is not None
        except (TypeError, ValueError):
            valid_bounds = False
        if not valid_bounds:
            return _base_response(lg, "invalid_season_bounds", season=season)
        result_query = (
            "SELECT game_id,team,game_date,opponent,score_for,score_against,win "
            "FROM team_game_results WHERE league=? AND game_date BETWEEN ? AND ? "
            "ORDER BY game_date,game_id,team"
        )
        result_params = (lg, season_start, season_end)

    result_rows = [dict(row) for row in connection.execute(result_query, result_params)]
    games: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in result_rows:
        games[str(row["game_id"])].append(row)
    paired_games = sum(
        _valid_result_pair(rows, allow_ties=lg in ("nfl", "mls", "wc"))
        for rows in games.values()
    )
    invalid_games = len(games) - paired_games
    if lg == "ncaaf":
        teams = sorted({row["team"] for row in result_rows
                        if row.get("team") and is_canonical("ncaaf", row["team"])})
    else:
        teams = sorted({row["team"] for row in result_rows if row.get("team")})
    dates = [row["game_date"] for row in result_rows if row.get("game_date")]

    stats: dict[tuple[str, str], dict[str, Any]] = {}
    missing_stat_rows = invalid_stat_rows = stats_games = paired_stat_games = 0
    invalid_stat_games = 0
    required_stats = STAT_FIELDS.get(lg, ())
    stats_columns = _table_columns(connection, "team_game_stats") if lg != "mlb" else set()
    if lg != "mlb" and {
        "league", "game_id", "team_abbrev", "home_away", "captured_at", *required_stats,
    }.issubset(stats_columns):
        game_ids = list(games)
        if game_ids:
            placeholders = ",".join("?" for _ in game_ids)
            # `stats` is the JSON home for per-game stats (see team_stats_json).
            # Selected only when the database actually has the column, so code
            # newer than its database keeps working — the migration is additive
            # and a DB may legitimately be behind.
            has_blob = "stats" in stats_columns
            selected = ",".join(
                ("game_id", "team_abbrev", "home_away", "captured_at", *required_stats)
                + (("stats",) if has_blob else ())
            )
            rows = connection.execute(
                f"SELECT {selected} FROM team_game_stats WHERE league=? AND game_id IN ({placeholders}) "
                "ORDER BY captured_at", (lg, *game_ids),
            )
            for row in rows:
                item = dict(row)
                blob = _json_stats(item.pop("stats", None))
                # Blob first, columns second, and only for keys this league
                # declares. A blob missing a key means that stat was absent, so
                # the column value must not be resurrected under it — that is how
                # a stale column silently outlives the value it used to hold.
                if blob is not None:
                    for key in required_stats:
                        item[key] = blob.get(key)
                stats[(str(item.pop("game_id")), item.pop("team_abbrev"))] = item
        stat_game_teams: dict[str, set[str]] = defaultdict(set)
        stat_game_sides: dict[str, set[str]] = defaultdict(set)
        for game_id, team in stats:
            stat_game_teams[game_id].add(team)
            stat_game_sides[game_id].add(stats[(game_id, team)].get("home_away"))
        stats_games = len(stat_game_teams)
        paired_stat_games = sum(
            len(teams_for_game) == 2 and stat_game_sides[game_id] == {"home", "away"}
            for game_id, teams_for_game in stat_game_teams.items()
        )
        invalid_stat_games = stats_games - paired_stat_games
        for result in result_rows:
            stat = stats.get((str(result["game_id"]), result["team"]))
            if stat is None:
                missing_stat_rows += 1
            elif any(stat.get(field) is None for field in required_stats):
                invalid_stat_rows += 1
    elif lg != "mlb":
        missing_stat_rows = len(result_rows)

    # `in_progress` counts as reconciled: it means every published game through the
    # row's `checked_through` is present and paired — the same evidence `complete`
    # carries, over a season that has not ended yet. MLB short-circuits this today,
    # so leaving it out would not break anything now and would quietly demote the
    # next league that goes in progress.
    reconciled = lg == "mlb" or bool(
        manifest and manifest["status"] in ("complete", "in_progress")
        and manifest["expected_teams"] == manifest["fetched_teams"] == EXPECTED_TEAMS[lg]
        and manifest["expected_games"] == manifest["fetched_games"] == len(games)
    )
    expected_games = manifest["expected_games"] if manifest else None
    supported = (
        len(teams) == EXPECTED_TEAMS[lg] and bool(result_rows) and invalid_games == 0
        and reconciled and (lg == "mlb" or (missing_stat_rows == 0 and invalid_stat_rows == 0))
        and (lg == "mlb" or invalid_stat_games == 0)
    )
    coverage = {
        "status": "measured" if supported else "incomplete",
        "source": "team_game_results" if lg == "mlb" else "espn_team_schedules+espn_boxscores",
        "scope": "captured_completed_games" if lg == "mlb" else "reconciled_completed_games",
        "expected_teams": EXPECTED_TEAMS[lg], "observed_teams": len(teams), "team_count": len(teams),
        "expected_games": expected_games, "observed_games": len(games), "games": len(games),
        "rows": len(result_rows),
        "paired_games": paired_games, "stats_games": stats_games,
        "paired_stat_games": paired_stat_games, "invalid_games": invalid_games,
        "invalid_stat_games": invalid_stat_games,
        "missing_stat_rows": missing_stat_rows, "invalid_stat_rows": invalid_stat_rows,
        "first_game_date": min(dates) if dates else None,
        "last_game_date": max(dates) if dates else None,
        "season_start": season_start, "season_end": season_end,
        "external_schedule_reconciled": bool(reconciled) if lg != "mlb" else False,
    }
    if not supported:
        if invalid_games:
            reason = "invalid_game_pairs"
        elif len(teams) != EXPECTED_TEAMS[lg]:
            reason = "incomplete_team_coverage"
        elif not reconciled:
            reason = "schedule_not_reconciled"
        elif missing_stat_rows:
            reason = "missing_team_stats"
        elif invalid_stat_games:
            reason = "invalid_stat_pairs"
        else:
            reason = "incomplete_stat_fields"
        return _base_response(lg, reason, season, coverage)
    agg_rows = (result_rows if lg != "ncaaf" else
                [r for r in result_rows
                 if r.get("team") and is_canonical("ncaaf", r["team"])])
    return _base_response(lg, None, season, coverage, _aggregate_rows(lg, agg_rows, stats))
