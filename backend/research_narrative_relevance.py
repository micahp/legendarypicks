"""Offline database-only narrative relevance research for Legendary Picks.

The module has no ESPN client, publisher collector, or model-provider imports.
It reads the shared development database in query-only mode and writes research
artifacts only.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

import team_codes
from research_narrative_event_knowledge import (
    DEFAULT_DEV_DB, ResearchAuditError, _backfilled_postgame_cutoff,
    _player_log_available_at, _schedule_available_at, open_readonly,
)

AS_OF = "2026-11-01T09:00:00Z"
NFL_SEASON, NBA_SEASON, NBA_BASELINE_SEASON = 2026, 2027, 2025
MIN_RECENT_GAMES = 3
MIN_BASELINE_GAMES = 3
MIN_NFL_PLAYS_PER_GAME = 15
QUARANTINED_CATEGORIES = {
    "fourth_down_attempts", "fourth_down_conversion", "drive_outcome",
    "drive_outcomes", "scoring_drive", "decisive_drive", "final_lead_change",
    "lead_change", "clutch_event", "single_play_game_winner", "game_winning_play",
}

# Exact preview system prompt assembled by core_stories.generate_game_story.
CORE_PREVIEW_SYSTEM = (
    "You are a sharp sports writer. Set up this matchup using ONLY the facts given. "
    "Lead priority: (1) what's at stake in this game, (2) a player or team on a clear "
    "hot or cold run, (3) record/quality context, including where these two clubs "
    "sit in the competition. Name the players the facts name. A fact marked "
    "BACKGROUND is true of every game in the competition — it is scenery, not the "
    "story, and belongs in this card only if this game is what changed it. Be "
    "specific with numbers, but NEVER state the same stat twice in different units, "
    "and never pad — if the facts are thin, one sharp sentence beats four generic "
    "ones. 1-4 sentences. Do NOT invent injuries, trades, lineup news, or a host "
    "city/venue — only the Host fact (if given) says who is playing at home; never "
    "assume it from a team's usual city. No clichés, no hype, plain confident tone."
)
EVENT_ONLY_SYSTEM = (
    "Use only dated, verified evidence supplied. Explain a matchup relationship only "
    "when both sides measure the same thing and evidence shows a meaningful connection. "
    "Describe trends and sample windows; do not claim causation, prediction, or a "
    "decisive play. If no relationship clears the evidence gates, use one relevant "
    "team streak or return no preview. Write one to three clear sentences."
)
COMBINED_SYSTEM = (
    "Use only dated, verified evidence supplied. Prefer one matchup relationship "
    "supported by both teams' recent and baseline data; add at most one distinct "
    "standings or player fact only when it materially helps explain this matchup. "
    "Do not force a connection, repeat a category, claim causation, or describe a "
    "high-EPA or scoring play as game-winning without sequence evidence. Write one "
    "to three clear sentences."
)
HEADLINE_STATS = {
    "nba": [("PTS", "points"), ("REB", "rebounds"), ("AST", "assists")],
    "nfl": [("fpts_ppr", "PPR points"), ("rush_yds", "rush yards"),
            ("rec_yds", "rec yards")],
}


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _availability(game_date: Any, ingested_at: Any, player: bool = False) -> tuple[str, str]:
    return (_player_log_available_at(game_date, ingested_at) if player
            else _schedule_available_at(game_date, ingested_at))


def _count_if_table(con: sqlite3.Connection, table: str) -> dict[str, Any]:
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        return {"exists": False, "rows": 0}
    count = int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    result: dict[str, Any] = {"exists": True, "rows": count}
    columns = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
    if "game_id" in columns:
        result["games"] = int(con.execute(
            f'SELECT COUNT(DISTINCT game_id) FROM "{table}"').fetchone()[0])
    if "game_date" in columns:
        result["game_date_range"] = [
            con.execute(f'SELECT MIN(game_date) FROM "{table}"').fetchone()[0],
            con.execute(f'SELECT MAX(game_date) FROM "{table}"').fetchone()[0],
        ]
    return result


def run_local_inventory(db_path: str, as_of: str) -> dict[str, Any]:
    """Coverage inventory via local SQL only; there is no network code path."""
    with closing(open_readonly(db_path)) as con:
        coverage = {table: _count_if_table(con, table) for table in (
            "nfl_pbp", "nfl_schedule", "team_game_results", "player_game_logs",
            "team_game_stats", "nba_schedule", "nba_sportsdataverse_games",
            "nba_player_boxes_nbacom")}
        if coverage["nfl_pbp"]["exists"]:
            cols = {row[1] for row in con.execute('PRAGMA table_info("nfl_pbp")')}
            if {"game_id", "play_id"} <= cols:
                r = con.execute("SELECT COUNT(*) plays,COUNT(DISTINCT game_id) games FROM nfl_pbp").fetchone()
                coverage["nfl_pbp"]["all_seasons"] = {"plays": int(r[0]), "games": int(r[1])}
            if {"season", "game_id", "play_id"} <= cols:
                r = con.execute("SELECT COUNT(*) plays,COUNT(DISTINCT game_id) games "
                                "FROM nfl_pbp WHERE season=?", (NFL_SEASON,)).fetchone()
                coverage["nfl_pbp"]["current_season_2026"] = {
                    "plays": int(r[0]), "games": int(r[1])}
        if coverage["team_game_stats"]["exists"]:
            coverage["team_game_stats"]["by_league_source"] = [
                dict(row) for row in con.execute(
                    "SELECT league,source,COUNT(*) rows,COUNT(DISTINCT game_id) games "
                    "FROM team_game_stats GROUP BY league,source ORDER BY league,source")]
            stats_columns = {row[1] for row in con.execute(
                'PRAGMA table_info("team_game_stats")')}
            populated_columns = sorted(stats_columns & {
                "fgm_fga", "rebounds", "assists", "turnovers", "total_yards", "total_offensive_plays"})
            predicate = " OR ".join(f'"{column}" IS NOT NULL' for column in populated_columns) or "0"
            coverage["team_game_stats"]["nba_populated_rows_at_cutoff"] = int(
                con.execute("SELECT COUNT(*) FROM team_game_stats WHERE league='nba' "
                            f"AND captured_at<=? AND ({predicate})", (as_of,)).fetchone()[0])
            sdv = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                              "AND name='nba_sportsdataverse_games'").fetchone()
            sdv_columns = ({row[1] for row in con.execute(
                'PRAGMA table_info("nba_sportsdataverse_games")')} if sdv else set())
            if "espn_event_id" in sdv_columns:
                coverage["team_game_stats"]["nba_local_crosswalk_seasons"] = [
                    dict(row) for row in con.execute(
                        "SELECT s.season,s.game_type,COUNT(DISTINCT t.game_id) games,COUNT(*) rows "
                        "FROM team_game_stats t JOIN nba_sportsdataverse_games s "
                        "ON s.espn_event_id=t.game_id WHERE t.league='nba' AND t.captured_at<=? "
                        "GROUP BY s.season,s.game_type ORDER BY s.season,s.game_type", (as_of,))]
        if coverage["player_game_logs"]["exists"]:
            coverage["player_game_logs"]["by_league_season_at_cutoff"] = [
                dict(row) for row in con.execute(
                    "SELECT league,season,COUNT(*) rows,COUNT(DISTINCT game_id) games,"
                    "MIN(game_date) first_game,MAX(game_date) last_game,MAX(ingested_at) latest_capture "
                    "FROM player_game_logs WHERE ingested_at<=? GROUP BY league,season "
                    "ORDER BY league,season", (as_of,))]
        coverage["nba_event_level_tables"] = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "(lower(name) LIKE '%nba%pbp%' OR lower(name) LIKE '%nba%play_by_play%' "
            "OR lower(name) LIKE '%nba%timeline%' OR lower(name) LIKE '%nba%play_event%') "
            "ORDER BY name")]
        if coverage["nba_player_boxes_nbacom"]["exists"]:
            box_columns = {row[1] for row in con.execute(
                'PRAGMA table_info("nba_player_boxes_nbacom")')}
            if "ingested_at" in box_columns:
                coverage["nba_player_boxes_nbacom"]["latest_capture"] = con.execute(
                    "SELECT MAX(ingested_at) FROM nba_player_boxes_nbacom WHERE ingested_at<=?",
                    (as_of,)).fetchone()[0]
        return {
            "database": str(Path(db_path).resolve()), "as_of": as_of,
            "query_only": int(con.execute("PRAGMA query_only").fetchone()[0]),
            "external_requests": 0, "coverage": coverage,
            "method": "SQLite mode=ro and PRAGMA query_only=ON; local tables only",
        }


def claim_cutoff_rejection(fact: dict[str, Any], target: dict[str, Any],
                           as_of: str) -> str | None:
    cutoff = _utc(as_of)
    kickoff = _utc(target.get("start_utc"))
    if cutoff is None:
        return "invalid_as_of_timestamp"
    if kickoff and cutoff > kickoff:
        return "as_of_after_kickoff"
    if not kickoff:
        target_day = _as_date(target.get("kickoff_date") or target.get("game_date"))
        if target_day is None or cutoff.date() >= target_day:
            return "kickoff_not_proven_after_as_of"
    category = str(fact.get("category") or "").lower()
    if category in QUARANTINED_CATEGORIES:
        return f"quarantined_category:{category}"
    if not fact.get("verified"):
        return "unverified_fact"
    if not fact.get("supporting_game_ids") or not fact.get("supporting_event_ids"):
        return "missing_source_row_ids"
    occurred, available = _utc(fact.get("occurred_at")), _utc(fact.get("available_at"))
    if occurred is None or available is None:
        return "missing_occurrence_or_availability_timestamp"
    if occurred > cutoff:
        return "occurred_after_cutoff"
    if available > cutoff:
        return "not_available_at_cutoff"
    if kickoff and occurred >= kickoff:
        return "occurred_at_or_after_kickoff"
    return None


def _threshold(metric: str, candidate: dict[str, Any]) -> float:
    if candidate.get("minimum_effect") is not None:
        return float(candidate["minimum_effect"])
    return 0.08 if metric == "epa_per_scrimmage_play" else 6.0


def build_matchup_relationship(target: dict[str, Any], candidate: dict[str, Any],
                               as_of: str) -> dict[str, Any]:
    """Score a paired offense/defense trend without inferring an outcome."""
    result = dict(candidate)
    result.setdefault("candidate_type", "team_relationship")
    result.setdefault("category", "team_relationship")
    reasons = []
    rejection = claim_cutoff_rejection(result, target, as_of)
    if rejection:
        reasons.append(rejection)
    league = str(target.get("league") or "").lower()
    participants = {team_codes.normalize(league, target.get("home_team")),
                    team_codes.normalize(league, target.get("away_team"))}
    offense = team_codes.normalize(league, result.get("offense_team"))
    defense = team_codes.normalize(league, result.get("defense_team"))
    if offense not in participants or defense not in participants or offense == defense:
        reasons.append("facts_not_linked_to_both_matchup_teams")
    if result.get("metric") != result.get("defense_metric", result.get("metric")):
        reasons.append("facts_do_not_measure_the_same_metric_relationship")
    metric = str(result.get("metric") or "")
    threshold = _threshold(metric, result)
    try:
        offense_delta = float(result["offense_recent"]) - float(result["offense_baseline"])
        defense_delta = (float(result["defense_allowed_recent"]) -
                         float(result["defense_allowed_baseline"]))
    except (KeyError, TypeError, ValueError):
        offense_delta = defense_delta = 0.0
        reasons.append("missing_recent_or_baseline_metric")
    try:
        samples = [int(result[key]) for key in (
            "offense_recent_games", "offense_baseline_games",
            "defense_recent_games", "defense_baseline_games")]
    except (KeyError, TypeError, ValueError):
        samples = [0, 0, 0, 0]
    if min(samples) < MIN_RECENT_GAMES:
        reasons.append("minimum_sample_not_met_for_recent_and_baseline_windows")
    if abs(offense_delta) < threshold:
        reasons.append("offensive_change_below_meaningful_effect_threshold")
    if abs(defense_delta) < threshold:
        reasons.append("opposing_defensive_change_below_meaningful_effect_threshold")
    try:
        age = int(result.get("max_recent_age_days", 999))
    except (TypeError, ValueError):
        age = 999
    if age > (21 if league == "nfl" else 14):
        reasons.append("recent_window_too_old")
    if result.get("source_category") in QUARANTINED_CATEGORIES or result.get(
            "candidate_type") in {"single_play", "game_winning_play",
                                  "drive_outcome", "fourth_down_attempt"}:
        reasons.append("quarantined_event_semantics")

    recency = max(0.0, min(10.0, 10.0 - age / 3.0))
    effect_size = min(10.0, (abs(offense_delta) + abs(defense_delta)) /
                       max(2 * threshold, 1e-9) * 5)
    baseline = min(10.0, (samples[1] + samples[3]) * 1.0)
    quality_coverage = int(result.get("opponent_quality_coverage") or 0)
    quality_value = float(result.get("recent_opponent_win_pct") or 0)
    components = {
        "recency": round(recency, 3),
        "effect_size": round(effect_size, 3),
        "matchup_relevance": 10 if not any("facts_not_linked" in r or "same_metric" in r
                                           for r in reasons) else 0,
        "baseline_coverage": round(baseline, 3),
        "opponent_quality": 2 if quality_coverage >= 2 and quality_value >= 0.55 else 0,
        "relationship_strength": 10 if abs(offense_delta) >= threshold and
        abs(defense_delta) >= threshold else 0,
        "isolated_player_penalty": 0, "low_sample_penalty": 0 if min(samples) >= 3 else 10,
        "repetition_penalty": 0,
    }
    score = (0.20 * components["recency"] +
             0.25 * components["effect_size"] +
             0.20 * components["matchup_relevance"] +
             0.15 * components["baseline_coverage"] +
             0.05 * components["opponent_quality"] +
             0.15 * components["relationship_strength"] -
             components["low_sample_penalty"])
    result.update({
        "offense_delta": round(offense_delta, 4),
        "defense_allowed_delta": round(defense_delta, 4),
        "minimum_effect": threshold,
        "relationship_type": "aligned_scoring_pressure" if offense_delta * defense_delta > 0
        else "opposing_recent_trends",
        "score_components": components, "selection_score": round(max(0.0, score), 3),
        "eligible": not reasons, "rejection_reasons": reasons,
    })
    return result


def rank_matchup_candidates(target: dict[str, Any], candidates: list[dict[str, Any]],
                            as_of: str) -> list[dict[str, Any]]:
    ranked = []
    for candidate in candidates:
        kind = candidate.get("candidate_type")
        if kind == "team_relationship":
            item = build_matchup_relationship(target, candidate, as_of)
        else:
            item = dict(candidate)
            reasons = []
            rejection = claim_cutoff_rejection(item, target, as_of)
            if rejection:
                reasons.append(rejection)
            if kind in {"player_outlier", "player_form"}:
                reasons.append("isolated_player_fact_lacks_opposing_team_matchup_evidence")
                item["score_components"] = {
                    "recency": 5.0, "effect_size": 4.0,
                    "matchup_relevance": 0.0, "baseline_coverage": 5.0,
                    "opponent_quality": 0.0, "relationship_strength": 0.0,
                    "isolated_player_penalty": 4.0, "low_sample_penalty": 0.0,
                    "repetition_penalty": 0.0,
                }
                item["selection_score"] = 0.0
            elif kind == "team_streak":
                length = int(item.get("streak_length") or 0)
                if length < 3:
                    reasons.append("streak_below_three_games")
                item["score_components"] = {
                    "recency": 8, "effect_size": min(8, length),
                    "matchup_relevance": 4, "baseline_coverage": 6,
                    "opponent_quality": 0, "relationship_strength": 2,
                    "isolated_player_penalty": 0, "low_sample_penalty": 0,
                    "repetition_penalty": 0,
                }
                item["selection_score"] = round(3 + min(3, length / 2), 3)
            else:
                reasons.append("candidate_type_not_enabled_for_preview_selection")
            item.update({"eligible": not reasons, "rejection_reasons": reasons})
        ranked.append(item)
    ranked.sort(key=lambda row: (
        not row.get("eligible"), -float(row.get("selection_score") or 0),
        str(row.get("candidate_id") or "")))
    seen_categories = set()
    for item in ranked:
        if not item.get("eligible"):
            continue
        category = item.get("candidate_type")
        components = item.setdefault("score_components", {})
        penalty = 1.5 if category in seen_categories else 0.0
        components["repetition_penalty"] = penalty
        if penalty:
            item["selection_score"] = round(max(0.0, item["selection_score"] - penalty), 3)
        seen_categories.add(category)
    return ranked


def render_relationship_preview(target: dict[str, Any], candidate: dict[str, Any],
                                team_names: dict[str, str] | None = None) -> str:
    if not candidate.get("eligible"):
        return ""
    names = team_names or {}
    offense = names.get(str(candidate["offense_team"]).upper(), candidate["offense_team"])
    defense = names.get(str(candidate["defense_team"]).upper(), candidate["defense_team"])
    league = str(target.get("league") or "").lower()
    off_value = float(candidate["offense_recent"])
    off_base = float(candidate["offense_baseline"])
    def_value = float(candidate["defense_allowed_recent"])
    def_base = float(candidate["defense_allowed_baseline"])
    off_delta = float(candidate["offense_delta"])
    def_delta = float(candidate["defense_allowed_delta"])
    direction_off, direction_def = ("up" if off_delta >= 0 else "down",
                                    "up" if def_delta >= 0 else "down")
    if league == "nfl":
        a = (f"The {offense}' offense has averaged {off_value:.2f} EPA per scrimmage play "
             f"over its last {candidate.get('offense_recent_games', 3)} games, "
             f"{direction_off} {abs(off_delta):.2f} from the previous "
             f"{candidate.get('offense_baseline_games', 3)}.")
        b = (f"The {defense} have allowed {def_value:.2f} EPA per opposing scrimmage play "
             f"over their last {candidate.get('defense_recent_games', 3)} games, "
             f"{direction_def} {abs(def_delta):.2f} from their previous "
             f"{candidate.get('defense_baseline_games', 3)}.")
    else:
        a = (f"The {offense} have averaged {off_value:.1f} points over their last "
             f"{candidate.get('offense_recent_games', 3)} games, {direction_off} "
             f"{abs(off_delta):.1f} from their 2025-26 regular-season average of {off_base:.1f}.")
        b = (f"The {defense} have allowed {def_value:.1f} points over their last "
             f"{candidate.get('defense_recent_games', 3)} games, {direction_def} "
             f"{abs(def_delta):.1f} from their 2025-26 average of {def_base:.1f}.")
    return " ".join((a, b))


def _records(games: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for game in games:
        home, away = game["home_team"], game["away_team"]
        hs, aws = int(game["home_score"]), int(game["away_score"])
        by_team[home].append({"game_id": str(game["game_id"]), "date": str(game["game_date"])[:10],
                              "opponent": away, "for": hs, "against": aws,
                              "result": "W" if hs > aws else "L" if hs < aws else "T",
                              "available_at": game["available_at"],
                              "availability_basis": game["availability_basis"]})
        by_team[away].append({"game_id": str(game["game_id"]), "date": str(game["game_date"])[:10],
                              "opponent": home, "for": aws, "against": hs,
                              "result": "W" if aws > hs else "L" if aws < hs else "T",
                              "available_at": game["available_at"],
                              "availability_basis": game["availability_basis"]})
    records = {}
    for team, detail in by_team.items():
        detail.sort(key=lambda row: (row["date"], row["game_id"]))
        wins = sum(row["result"] == "W" for row in detail)
        losses = sum(row["result"] == "L" for row in detail)
        ties = sum(row["result"] == "T" for row in detail)
        n = len(detail)
        recent = detail[-10:]
        last10 = f"{sum(r['result']=='W' for r in recent)}-{sum(r['result']=='L' for r in recent)}"
        if any(r["result"] == "T" for r in recent):
            last10 += f"-{sum(r['result']=='T' for r in recent)}"
        last_result = detail[-1]["result"]
        streak = 0
        for row in reversed(detail):
            if row["result"] != last_result:
                break
            streak += 1
        records[team] = {
            "team": team, "games": n, "wins": wins, "losses": losses, "ties": ties,
            "win_pct": (wins + 0.5 * ties) / n if n else None,
            "differential": round(sum(r["for"] - r["against"] for r in detail) / n, 2) if n else 0,
            "last10": last10, "streak_result": last_result, "streak_length": streak,
            "games_detail": detail,
        }
    ranked = sorted(records.values(), key=lambda row: (
        -(row["win_pct"] or 0), -row["differential"], row["team"]))
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
    return records


def _load_nfl_games(con: sqlite3.Connection, as_of: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = con.execute(
        "SELECT game_id,season,game_type,week,gameday,away_team,home_team,away_score,home_score,"
        "ingested_at,espn FROM nfl_schedule WHERE season=? AND game_type='REG' "
        "ORDER BY gameday,week,game_id", (NFL_SEASON,)).fetchall()
    cutoff = _utc(as_of)
    games, rejected = [], Counter()
    for raw in rows:
        row = dict(raw)
        if row["away_score"] is None or row["home_score"] is None:
            continue
        available, basis = _schedule_available_at(row["gameday"], row["ingested_at"])
        if not _utc(available) or _utc(available) > cutoff:
            rejected["schedule_capture_after_cutoff"] += 1
            continue
        row.update({
            "game_date": str(row["gameday"])[:10], "available_at": available,
            "availability_basis": basis,
            "away_team": team_codes.normalize("nfl", row["away_team"]),
            "home_team": team_codes.normalize("nfl", row["home_team"]),
        })
        games.append(row)
    return games, dict(rejected)


def _load_nba_current_games(con: sqlite3.Connection, as_of: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = con.execute(
        "SELECT game_id,season,season_type,game_date,start_utc,away_team,home_team,away_score,"
        "home_score,status,ingested_at,espn,sub_label FROM nba_schedule WHERE season=? "
        "AND season_type='REG' ORDER BY start_utc,game_id", (NBA_SEASON,)).fetchall()
    cutoff = _utc(as_of)
    games, rejected = [], Counter()
    for raw in rows:
        row = dict(raw)
        if row["away_score"] is None or row["home_score"] is None or int(row["status"] or 0) != 3:
            continue
        available, basis = _schedule_available_at(row["game_date"], row["ingested_at"])
        if not _utc(available) or _utc(available) > cutoff:
            rejected["schedule_capture_after_cutoff"] += 1
            continue
        row.update({
            "available_at": available, "availability_basis": basis,
            "away_team": team_codes.normalize("nba", row["away_team"]),
            "home_team": team_codes.normalize("nba", row["home_team"]),
        })
        games.append(row)
    return games, dict(rejected)


def _load_nba_baseline(con: sqlite3.Connection, as_of: str) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT source_game_id,season,game_type,game_date,home,away,home_score,away_score,"
        "espn_event_id,ingested_at FROM nba_sportsdataverse_games WHERE season=? AND game_type='REG' "
        "ORDER BY game_date,source_game_id", (NBA_BASELINE_SEASON,)).fetchall()
    cutoff = _utc(as_of)
    games = []
    for raw in rows:
        row = dict(raw)
        available = _backfilled_postgame_cutoff(row["game_date"])
        if _utc(available) > cutoff:
            continue
        row.update({
            "game_id": str(row["source_game_id"]), "available_at": available,
            "availability_basis": "nba_sportsdataverse_backfill_game_date_plus_one_day_12_utc",
            "away_team": team_codes.normalize("nba", row["away"]),
            "home_team": team_codes.normalize("nba", row["home"]),
        })
        games.append(row)
    return games


def _target_rows(con: sqlite3.Connection, league: str, as_of: str, count: int) -> list[dict[str, Any]]:
    cutoff = _utc(as_of)
    out = []
    if league == "nfl":
        rows = con.execute(
            "SELECT game_id,season,week,gameday,gametime,away_team,home_team,espn,ingested_at "
            "FROM nfl_schedule WHERE season=? AND game_type='REG' AND gameday>? "
            "ORDER BY gameday,week,game_id", (NFL_SEASON, cutoff.date().isoformat())).fetchall()
        for raw in rows:
            row = dict(raw)
            captured = _utc(row["ingested_at"])
            available = captured.isoformat(timespec="seconds").replace("+00:00", "Z") if captured else None
            basis = "nfl_schedule.ingested_at_observed_future_schedule"
            start_bound = f"{row['gameday']}T00:00:00Z"
            if _utc(available) and _utc(available) <= cutoff and _utc(start_bound) > cutoff:
                row.update({
                    "league": "nfl", "start_utc": start_bound,
                    "kickoff_date": str(row["gameday"])[:10],
                    "kickoff_time_basis": "nfl_schedule gametime is local and has no timezone; UTC is a conservative date lower bound",
                    "availability_basis": basis,
                    "away_team": team_codes.normalize("nfl", row["away_team"]),
                    "home_team": team_codes.normalize("nfl", row["home_team"]),
                    "as_of": as_of, "target_game_id": str(row["game_id"]),
                })
                out.append(row)
            if len(out) >= count:
                break
    else:
        rows = con.execute(
            "SELECT game_id,season,season_type,game_date,start_utc,away_team,home_team,"
            "status_text,espn,ingested_at FROM nba_schedule WHERE season=? AND season_type='REG' "
            "AND status=1 AND start_utc>? ORDER BY start_utc,game_id", (NBA_SEASON, as_of)).fetchall()
        for raw in rows:
            row = dict(raw)
            captured = _utc(row["ingested_at"])
            available = captured.isoformat(timespec="seconds").replace("+00:00", "Z") if captured else None
            basis = "nba_schedule.ingested_at_observed_scheduled_game"
            if _utc(available) and _utc(available) <= cutoff:
                row.update({
                    "league": "nba", "kickoff_date": str(row["game_date"]),
                    "kickoff_time_basis": "nba_schedule.start_utc",
                    "availability_basis": basis,
                    "away_team": team_codes.normalize("nba", row["away_team"]),
                    "home_team": team_codes.normalize("nba", row["home_team"]),
                    "as_of": as_of, "target_game_id": str(row["game_id"]),
                })
                out.append(row)
            if len(out) >= count:
                break
    return out[:count]


def _team_names(con: sqlite3.Connection, league: str) -> dict[str, str]:
    if league == "nfl":
        rows = con.execute("SELECT team,team_name FROM nfl_teams WHERE season=?", (NFL_SEASON,)).fetchall()
    else:
        rows = con.execute("SELECT team,team_name FROM nba_teams WHERE season=?", (NBA_SEASON,)).fetchall()
    return {team_codes.normalize(league, row[0]): row[1] or row[0] for row in rows}


def _team_record_line(code: str, record: dict[str, Any] | None, names: dict[str, str]) -> str:
    name = names.get(code, code)
    if not record or not record.get("games"):
        return f"{name} ({code}): no games played yet this season (no record to cite)."
    win_pct = f"{record['win_pct']:.3f}".lstrip("0")
    return (f"{name} ({code}): {record['wins']}-{record['losses']}, "
            f"{win_pct} winning percentage, streak {record['streak_result']}{record['streak_length']}, "
            f"last-10 {record['last10']}, run differential {record['differential']}, "
            f"quality rank #{record['rank']} of {len(names)}")


def _player_form(con: sqlite3.Connection, league: str, team: str, as_of: str) -> list[dict[str, Any]]:
    """Reconstruct player_form.lines over only records available at the cutoff."""
    season = con.execute(
        "SELECT MAX(season) FROM player_game_logs WHERE league=? AND ingested_at<=?",
        (league, as_of)).fetchone()[0]
    if season is None:
        return []
    rows = con.execute(
        "SELECT l.id,l.player_id,p.name,l.stats,l.game_id,l.game_date,l.game_no,l.team,l.ingested_at "
        "FROM player_game_logs l LEFT JOIN players p ON p.id=l.player_id "
        "WHERE l.league=? AND l.season=? AND l.team=? AND l.ingested_at<=? "
        "ORDER BY COALESCE(l.game_date,'') DESC,CAST(l.game_no AS INTEGER) DESC",
        (league, season, team, as_of)).fetchall()
    buckets = {}
    for row in rows:
        bucket = buckets.setdefault(row["player_id"], {"name": row["name"], "logs": []})
        if len(bucket["logs"]) >= 5:
            continue
        try:
            stats = json.loads(row["stats"])
        except (TypeError, json.JSONDecodeError):
            stats = {}
        available, basis = _player_log_available_at(row["game_date"], row["ingested_at"])
        bucket["logs"].append({
            "id": int(row["id"]), "game_date": row["game_date"], "game_no": row["game_no"],
            "game_id": row["game_id"],
            "available_at": available, "availability_basis": basis, "stats": stats,
        })
    primary = HEADLINE_STATS[league][0][0]
    ranked = []
    for player_id, info in buckets.items():
        vals = [r["stats"].get(primary) for r in info["logs"]
                if isinstance(r["stats"].get(primary), (int, float))]
        if len(vals) >= 3 and info["name"]:
            ranked.append((sum(vals) / len(vals), str(player_id), player_id, info))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    result = []
    for _avg, _sort_id, player_id, info in ranked[:3]:
        parts, stats_used = [], {}
        for key, label in HEADLINE_STATS[league]:
            vals = [r["stats"].get(key) for r in info["logs"]
                    if isinstance(r["stats"].get(key), (int, float))]
            if len(vals) >= 3:
                parts.append(f"{label} [" + ", ".join(f"{v:g}" for v in vals) + "]")
                stats_used[label] = vals
        if not parts:
            continue
        line = (f"{info['name']} ({team}, {season} logs, last {len(info['logs'])} games, "
                "most recent first): " + "; ".join(parts) + ".")
        result.append({
            "player_id": int(player_id), "name": info["name"], "team": team,
            "season": int(season), "line": line,
            "supporting_log_ids": [r["id"] for r in info["logs"]],
            "supporting_game_ids": [str(r["game_id"]) for r in info["logs"] if r["game_id"]],
            "supporting_game_dates": [r["game_date"] for r in info["logs"]],
            "source_logs": [{
                "player_game_log_id": r["id"], "game_id": r["game_id"],
                "game_date": r["game_date"], "available_at": r["available_at"],
                "availability_basis": r["availability_basis"], "stats": r["stats"],
            } for r in info["logs"]],
            "available_at": max(r["available_at"] for r in info["logs"]),
            "availability_basis": sorted({r["availability_basis"] for r in info["logs"]}),
            "statistics": stats_used,
        })
    return result


def _nfl_play_metrics(con: sqlite3.Connection) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    rows = con.execute(
        "SELECT game_id,play_id,game_date,posteam,defteam,play_type,epa FROM nfl_pbp "
        "WHERE season=? AND play_type IN ('run','pass') AND epa IS NOT NULL "
        "AND posteam IS NOT NULL AND defteam IS NOT NULL ORDER BY game_id,play_id",
        (NFL_SEASON,)).fetchall()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        offense = team_codes.normalize("nfl", row["posteam"])
        defense = team_codes.normalize("nfl", row["defteam"])
        event = {
            "game_id": str(row["game_id"]), "play_id": str(row["play_id"]),
            "game_date": str(row["game_date"])[:10], "epa": float(row["epa"]),
            "posteam": offense, "defteam": defense,
        }
        grouped[(event["game_id"], offense)].append(event)
        grouped[(event["game_id"], defense)].append({**event, "allowed": True})
    return grouped, len(rows)


def _window_summary(team: str, history: list[dict[str, Any]],
                    metric_rows: dict[tuple[str, str], list[dict[str, Any]]],
                    side: str) -> dict[str, Any] | None:
    usable = []
    for game in history:
        rows = [r for r in metric_rows.get((str(game["game_id"]), team), [])
                if bool(r.get("allowed")) == (side == "defense")]
        if len(rows) >= MIN_NFL_PLAYS_PER_GAME:
            usable.append({"game": game, "plays": rows,
                           "mean": sum(r["epa"] for r in rows) / len(rows)})
    usable.sort(key=lambda row: (row["game"]["game_date"], str(row["game"]["game_id"])),
                reverse=True)
    if len(usable) < MIN_RECENT_GAMES + MIN_BASELINE_GAMES:
        return None
    recent, baseline = usable[:3], usable[3:]
    return {
        "recent": sum(r["mean"] for r in recent) / 3,
        "baseline": sum(r["mean"] for r in baseline) / len(baseline),
        "recent_games": len(recent), "baseline_games": len(baseline),
        "recent_plays": sum(len(r["plays"]) for r in recent),
        "baseline_plays": sum(len(r["plays"]) for r in baseline),
        "recent_rows": recent, "baseline_rows": baseline,
        "latest_date": recent[0]["game"]["game_date"],
    }


def _window_evidence(window: list[dict[str, Any]], team: str) -> list[dict[str, Any]]:
    return [{
        "game_id": str(item["game"]["game_id"]),
        "game_date": item["game"]["game_date"], "team": team,
        "available_at": item["game"]["available_at"],
        "availability_basis": item["game"]["availability_basis"],
        "epa_per_play": round(item["mean"], 5), "eligible_plays": len(item["plays"]),
        "play_ids": [str(row["play_id"]) for row in item["plays"]],
    } for item in window]


def _opponent_quality(team: str, recent_rows: list[dict[str, Any]],
                      games: list[dict[str, Any]]) -> tuple[float | None, int, list[dict[str, Any]]]:
    refs = []
    for item in recent_rows:
        game = item["game"]
        opponent = game["away_team"] if game["home_team"] == team else game["home_team"]
        prior = [row for row in games if row["game_date"] < game["game_date"] and
                 opponent in (row["home_team"], row["away_team"])]
        wins = losses = ties = 0
        for row in prior:
            own = row["home_score"] if row["home_team"] == opponent else row["away_score"]
            other = row["away_score"] if row["home_team"] == opponent else row["home_score"]
            if own > other: wins += 1
            elif own < other: losses += 1
            else: ties += 1
        n = wins + losses + ties
        if n:
            refs.append({
                "source_game_id": str(game["game_id"]), "opponent": opponent,
                "prior_games": n, "prior_record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
                "prior_win_pct": round((wins + 0.5 * ties) / n, 3),
                "prior_game_ids": [str(r["game_id"]) for r in prior],
                "prior_game_rows": [{
                    "game_id": str(r["game_id"]), "game_date": r["game_date"],
                    "home_team": r["home_team"], "away_team": r["away_team"],
                    "home_score": r["home_score"], "away_score": r["away_score"],
                    "available_at": r["available_at"],
                } for r in prior],
            })
    mean = sum(r["prior_win_pct"] for r in refs) / len(refs) if refs else None
    return mean, len(refs), refs


def _nfl_relationship_candidates(target: dict[str, Any], games: list[dict[str, Any]],
                                 metrics: dict[tuple[str, str], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates = []
    for offense, defense in ((target["away_team"], target["home_team"]),
                             (target["home_team"], target["away_team"])):
        off_games = sorted((g for g in games if offense in (g["home_team"], g["away_team"])),
                           key=lambda g: (g["game_date"], g["game_id"]), reverse=True)
        def_games = sorted((g for g in games if defense in (g["home_team"], g["away_team"])),
                           key=lambda g: (g["game_date"], g["game_id"]), reverse=True)
        off = _window_summary(offense, off_games, metrics, "offense")
        deff = _window_summary(defense, def_games, metrics, "defense")
        if not off or not deff:
            continue
        oq, oc, oq_rows = _opponent_quality(offense, off["recent_rows"], games)
        dq, dc, dq_rows = _opponent_quality(defense, deff["recent_rows"], games)
        quality = [v for v in (oq, dq) if v is not None]
        windows = (off["recent_rows"], off["baseline_rows"],
                   deff["recent_rows"], deff["baseline_rows"])
        game_ids = sorted({str(row["game"]["game_id"]) for w in windows for row in w})
        event_ids = sorted({f"{p['game_id']}:{p['play_id']}"
                            for w in windows for item in w for p in item["plays"]})
        available = max(_backfilled_postgame_cutoff(g["game_date"])
                        for g in games if str(g["game_id"]) in game_ids)
        latest_dates = [off["latest_date"], deff["latest_date"]]
        age = max((date.fromisoformat(target["as_of"][:10]) -
                   date.fromisoformat(day)).days for day in latest_dates)
        candidates.append({
            "candidate_id": f"nfl-epa:{offense}:{defense}",
            "candidate_type": "team_relationship", "category": "team_relationship",
            "league": "nfl", "metric": "epa_per_scrimmage_play",
            "defense_metric": "epa_per_scrimmage_play",
            "offense_team": offense, "defense_team": defense,
            "offense_recent": off["recent"], "offense_baseline": off["baseline"],
            "defense_allowed_recent": deff["recent"],
            "defense_allowed_baseline": deff["baseline"],
            "offense_recent_games": off["recent_games"],
            "offense_baseline_games": off["baseline_games"],
            "defense_recent_games": deff["recent_games"],
            "defense_baseline_games": deff["baseline_games"],
            "offense_recent_n": off["recent_plays"],
            "offense_baseline_n": off["baseline_plays"],
            "defense_recent_n": deff["recent_plays"],
            "defense_baseline_n": deff["baseline_plays"],
            "max_recent_age_days": age,
            "opponent_quality_coverage": min(oc, dc),
            "recent_opponent_win_pct": sum(quality) / len(quality) if quality else None,
            "supporting_game_ids": game_ids, "supporting_event_ids": event_ids,
            "occurred_at": available, "available_at": available, "verified": True,
            "evidence": {
                "source_table": "nfl_pbp",
                "metric_definition": "unweighted mean of per-game EPA/play for run/pass plays with non-null EPA; three latest usable games versus the previous three",
                "minimum_plays_per_game": MIN_NFL_PLAYS_PER_GAME,
                "offense_recent": _window_evidence(off["recent_rows"], offense),
                "offense_baseline": _window_evidence(off["baseline_rows"], offense),
                "defense_allowed_recent": _window_evidence(deff["recent_rows"], defense),
                "defense_allowed_baseline": _window_evidence(deff["baseline_rows"], defense),
                "offense_opponent_quality": oq_rows,
                "defense_opponent_quality": dq_rows,
            },
        })
    return candidates


def _nba_relationship_candidates(target: dict[str, Any], recent_games: list[dict[str, Any]],
                                 baseline_games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def summarize(team: str, games: list[dict[str, Any]]) -> tuple[float, float, list[dict[str, Any]]]:
        rows = []
        for game in games:
            if team == game["home_team"]:
                own, allowed, opponent = int(game["home_score"]), int(game["away_score"]), game["away_team"]
            elif team == game["away_team"]:
                own, allowed, opponent = int(game["away_score"]), int(game["home_score"]), game["home_team"]
            else:
                continue
            rows.append({
                "game_id": str(game.get("game_id") or game.get("source_game_id")),
                "date": str(game["game_date"]), "team": team, "opponent": opponent,
                "points_for": own, "points_allowed": allowed,
                "available_at": game["available_at"],
                "availability_basis": game["availability_basis"],
            })
        return ((sum(r["points_for"] for r in rows) / len(rows),
                 sum(r["points_allowed"] for r in rows) / len(rows), rows)
                if rows else (0.0, 0.0, []))

    candidates = []
    for offense, defense in ((target["away_team"], target["home_team"]),
                             (target["home_team"], target["away_team"])):
        off_recent_games = sorted(
            (g for g in recent_games if offense in (g["home_team"], g["away_team"])),
            key=lambda g: (g["start_utc"], g["game_id"]), reverse=True)[:3]
        def_recent_games = sorted(
            (g for g in recent_games if defense in (g["home_team"], g["away_team"])),
            key=lambda g: (g["start_utc"], g["game_id"]), reverse=True)[:3]
        off_base_games = [g for g in baseline_games if offense in (g["home_team"], g["away_team"])]
        def_base_games = [g for g in baseline_games if defense in (g["home_team"], g["away_team"])]
        if min(len(off_recent_games), len(def_recent_games),
               len(off_base_games), len(def_base_games)) < 3:
            continue
        off_r, _off_ar, off_r_rows = summarize(offense, off_recent_games)
        off_b, _off_ab, off_b_rows = summarize(offense, off_base_games)
        _def_r, def_r, def_r_rows = summarize(defense, def_recent_games)
        _def_b, def_b, def_b_rows = summarize(defense, def_base_games)
        all_rows = off_r_rows + off_b_rows + def_r_rows + def_b_rows
        ids = sorted({r["game_id"] for r in all_rows})
        event_ids = sorted({f"{r['game_id']}:{r['team']}:{r['points_for']}:{r['points_allowed']}"
                            for r in all_rows})
        available = max(r["available_at"] for r in all_rows)
        recent_dates = [r["date"] for r in off_r_rows + def_r_rows]
        age = max((date.fromisoformat(target["as_of"][:10]) -
                   date.fromisoformat(day)).days for day in recent_dates)
        off_quality, off_quality_coverage, off_quality_rows = _opponent_quality(
            offense, [{"game": game} for game in off_recent_games], recent_games)
        def_quality, def_quality_coverage, def_quality_rows = _opponent_quality(
            defense, [{"game": game} for game in def_recent_games], recent_games)
        quality_values = [value for value in (off_quality, def_quality) if value is not None]
        candidates.append({
            "candidate_id": f"nba-points:{offense}:{defense}",
            "candidate_type": "team_relationship", "category": "team_relationship",
            "league": "nba", "metric": "points_per_game",
            "defense_metric": "points_per_game",
            "offense_team": offense, "defense_team": defense,
            "offense_recent": off_r, "offense_baseline": off_b,
            "defense_allowed_recent": def_r, "defense_allowed_baseline": def_b,
            "offense_recent_games": len(off_r_rows),
            "offense_baseline_games": len(off_b_rows),
            "defense_recent_games": len(def_r_rows),
            "defense_baseline_games": len(def_b_rows),
            "offense_recent_n": len(off_r_rows), "offense_baseline_n": len(off_b_rows),
            "defense_recent_n": len(def_r_rows), "defense_baseline_n": len(def_b_rows),
            "minimum_effect": 6.0, "max_recent_age_days": age,
            "opponent_quality_coverage": min(off_quality_coverage, def_quality_coverage),
            "recent_opponent_win_pct": (sum(quality_values) / len(quality_values)
                                        if quality_values else None),
            "supporting_game_ids": ids, "supporting_event_ids": event_ids,
            "occurred_at": available, "available_at": available, "verified": True,
            "evidence": {
                "source_tables": ["nba_schedule", "nba_sportsdataverse_games"],
                "metric_definition": "mean points scored/allowed per completed regular-season game; current last three versus 2025-26 regular-season baseline",
                "offense_recent": off_r_rows, "offense_baseline": off_b_rows,
                "defense_allowed_recent": def_r_rows,
                "defense_allowed_baseline": def_b_rows,
                "offense_opponent_quality": off_quality_rows,
                "defense_opponent_quality": def_quality_rows,
            },
        })
    return candidates


def _target_streak(target: dict[str, Any], team: str, records: dict[str, dict[str, Any]],
                   names: dict[str, str]) -> dict[str, Any] | None:
    record = records.get(team)
    if not record or int(record.get("streak_length") or 0) < 3:
        return None
    detail = []
    for game in reversed(record["games_detail"]):
        if game["result"] != record["streak_result"]:
            break
        detail.append(game)
    if not detail:
        return None
    available = max(row["available_at"] for row in detail)
    return {
        "candidate_id": f"streak:{team}:{record['streak_result']}{record['streak_length']}",
        "candidate_type": "team_streak", "category": "recent_streak",
        "league": target["league"], "team": team, "team_name": names.get(team, team),
        "streak_result": "win" if record["streak_result"] == "W" else "loss",
        "streak_length": record["streak_length"],
        "source_game_date": detail[0]["date"],
            "supporting_game_ids": [str(row["game_id"]) for row in detail],
        "supporting_event_ids": [f"{row['game_id']}:final_result" for row in detail],
        "occurred_at": available, "available_at": available, "verified": True,
        "evidence": {"source_table": "nfl_schedule" if target["league"] == "nfl"
                     else "nba_schedule", "games": detail},
    }


def _team_record_evidence(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    result = {key: record[key] for key in (
        "team", "games", "wins", "losses", "ties", "win_pct", "differential",
        "last10", "streak_result", "streak_length", "rank")}
    result["supporting_game_ids"] = [str(item["game_id"]) for item in record["games_detail"]]
    result["supporting_event_ids"] = [f"{item['game_id']}:final_result" for item in record["games_detail"]]
    result["available_at"] = max(item["available_at"] for item in record["games_detail"])
    result["source_game_rows"] = record["games_detail"]
    return result


def _core_grounding(target: dict[str, Any], records: dict[str, dict[str, Any]],
                    names: dict[str, str], player_lines: dict[str, list[dict[str, Any]]]
                    ) -> tuple[str, dict[str, Any]]:
    away, home = target["away_team"], target["home_team"]
    if target["league"] == "nfl":
        game_date = date.fromisoformat(target["kickoff_date"])
    else:
        game_date = _utc(target["start_utc"]).astimezone(ZoneInfo("America/New_York")).date()
    date_label = game_date.strftime("%A %b %-d, %Y")
    grounding = (
        f"Matchup: {away} vs {home}. Game state: pre. Date: {date_label}.\n"
        f"{_team_record_line(away, records.get(away), names)}\n"
        f"{_team_record_line(home, records.get(home), names)}\n"
        f"Host: {home} — this game is played at {home}'s home venue."
    )
    player_rows = player_lines.get(away, []) + player_lines.get(home, [])
    if player_rows:
        grounding += "\nRecent player form (each value is dated; newest first):\n"
        grounding += "\n".join(item["line"] for item in player_rows)
    fields = {
        "matchup": {"away_team": away, "home_team": home},
        "game_state": "pre", "date": date_label, "host": home,
        "record_facts": [_team_record_evidence(records.get(away)),
                         _team_record_evidence(records.get(home))],
        "stakes": {"lines": [],
                   "status": "no certain playoff/division clinch or elimination fact at this early-season cutoff"},
        "player_form": player_rows,
        "matchup_context": {
            "status": "unavailable_offline",
            "reason": "core_stories gets this from espn.summary; this audit made no ESPN request and did not establish a local event crosswalk",
        },
    }
    return grounding, fields


def _date_label(target: dict[str, Any]) -> str:
    if target["league"] == "nfl":
        d = date.fromisoformat(target["kickoff_date"])
    else:
        d = _utc(target["start_utc"]).astimezone(ZoneInfo("America/New_York")).date()
    return d.strftime("%A %b %-d, %Y")


def _streak_preview(candidate: dict[str, Any], names: dict[str, str]) -> str:
    team = names.get(candidate["team"], candidate["team"])
    result = "won" if candidate["streak_result"] == "win" else "lost"
    number = {3: "three", 4: "four", 5: "five", 6: "six"}.get(
        int(candidate["streak_length"]), str(candidate["streak_length"]))
    return f"The {team} have {result} {number} straight games."


def _record_sentence(home: dict[str, Any] | None, away: dict[str, Any] | None,
                     names: dict[str, str], home_code: str, away_code: str) -> str | None:
    if not home or not away or abs(home["wins"] - away["wins"]) < 2:
        return None
    return (f"The {names.get(away_code, away_code)} are {away['wins']}-{away['losses']}; "
            f"the {names.get(home_code, home_code)} are {home['wins']}-{home['losses']}.")


def _candidate_grounding(target: dict[str, Any], selected: dict[str, Any] | None,
                         names: dict[str, str]) -> str:
    prefix = (f"Matchup: {target['away_team']} vs {target['home_team']}. "
              f"Date: {_date_label(target)}.\n")
    if selected is None:
        return prefix + "No verified matchup relationship cleared the relevance threshold."
    if selected["candidate_type"] == "team_relationship":
        return prefix + render_relationship_preview(target, selected, names)
    return prefix + _streak_preview(selected, names)


def _claim_rows(target: dict[str, Any], selected: dict[str, Any] | None,
                preview: str, as_of: str, variant: str,
                records: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if not selected:
        return []
    sentences = [part.strip() for part in preview.split(". ") if part.strip()]
    sentences = [part if part.endswith(".") else part + "." for part in sentences]
    max_selected_claims = 2 if selected.get("candidate_type") == "team_relationship" else 1
    selected_sentences = sentences[:max_selected_claims]
    evidence = selected.get("evidence") or {}
    rows = []
    for index, sentence in enumerate(selected_sentences):
        if selected.get("candidate_type") == "team_relationship":
            side = ("offense" if index == 0 else "defense")
            evidence_prefix = "offense" if side == "offense" else "defense_allowed"
            windows = (evidence.get(f"{evidence_prefix}_recent") or []) + (
                evidence.get(f"{evidence_prefix}_baseline") or [])
            game_ids = sorted({str(item["game_id"]) for item in windows})
            event_ids = []
            for item in windows:
                if item.get("play_ids"):
                    event_ids.extend(f"{item['game_id']}:{play_id}" for play_id in item["play_ids"])
                else:
                    event_ids.append(f"{item['game_id']}:{item.get('team')}:{item.get('points_for')}:{item.get('points_allowed')}")
            available_values = [item.get("available_at") for item in windows if item.get("available_at")]
            claim_evidence = windows
        else:
            game_ids = list(selected.get("supporting_game_ids") or [])
            event_ids = list(selected.get("supporting_event_ids") or [])
            evidence_games = evidence.get("games") or []
            available_values = [item.get("available_at") for item in evidence_games
                                if item.get("available_at")]
            claim_evidence = evidence_games
        available_at = max(available_values) if available_values else selected.get("available_at")
        fact = {
            "category": selected.get("category"), "verified": selected.get("verified"),
            "occurred_at": available_at, "available_at": available_at,
            "supporting_game_ids": game_ids, "supporting_event_ids": event_ids,
        }
        rejection = claim_cutoff_rejection(fact, target, as_of)
        rows.append({
            "target_game_id": target["target_game_id"], "league": target["league"],
            "variant": variant, "claim_index": index + 1, "as_of": as_of,
            "category": selected.get("category"),
            "candidate_id": selected.get("candidate_id"), "claim_text": sentence,
            "occurred_at": available_at, "available_at": available_at,
            "supporting_game_ids": game_ids,
            "supporting_event_ids": sorted(set(event_ids)),
            "mechanical_verification": "pass" if not rejection else "fail",
            "rejection_reason": rejection, "selection_score": selected.get("selection_score"),
            "score_components": selected.get("score_components"),
            "source_evidence": claim_evidence,
        })
    if variant == "combined" and records:
        home, away = records.get(target["home_team"]), records.get(target["away_team"])
        if (home and away and len(sentences) > max_selected_claims):
            game_rows = home["games_detail"] + away["games_detail"]
            game_ids = sorted({str(item["game_id"]) for item in game_rows})
            event_ids = [f"{game_id}:final_result" for game_id in game_ids]
            available_at = max(item["available_at"] for item in game_rows)
            fact = {"category": "standings_record", "verified": True,
                    "occurred_at": available_at, "available_at": available_at,
                    "supporting_game_ids": game_ids, "supporting_event_ids": event_ids}
            rejection = claim_cutoff_rejection(fact, target, as_of)
            sentence = sentences[-1] if len(sentences) > max_selected_claims else ""
            rows.append({
                "target_game_id": target["target_game_id"], "league": target["league"],
                "variant": variant, "claim_index": len(rows) + 1, "as_of": as_of,
                "category": "standings_record", "candidate_id": "core-current-records",
                "claim_text": sentence, "occurred_at": available_at, "available_at": available_at,
                "supporting_game_ids": game_ids, "supporting_event_ids": event_ids,
                "mechanical_verification": "pass" if not rejection else "fail",
                "rejection_reason": rejection,
                "source_evidence": game_rows,
            })
    return rows


def _preview_for_target(target: dict[str, Any], candidates: list[dict[str, Any]],
                        names: dict[str, str], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ranked = rank_matchup_candidates(target, candidates, target["as_of"])
    selected = next((row for row in ranked if row.get("eligible") and
                     row.get("candidate_type") == "team_relationship"), None)
    if selected is None:
        selected = next((row for row in ranked if row.get("eligible") and
                         row.get("candidate_type") == "team_streak"), None)
    event_preview = ""
    if selected:
        event_preview = (render_relationship_preview(target, selected, names)
                         if selected["candidate_type"] == "team_relationship"
                         else _streak_preview(selected, names))
    core_addition = (_record_sentence(records.get(target["home_team"]),
                                      records.get(target["away_team"]), names,
                                      target["home_team"], target["away_team"])
                     if selected and selected["candidate_type"] == "team_relationship" else None)
    return {
        "ranked_candidates": ranked, "selected": selected,
        "event_only_preview": event_preview,
        "combined_preview": " ".join(x for x in (event_preview, core_addition) if x),
        "combined_added_core_fact": core_addition,
        "rejected_candidates": [row for row in ranked if not row.get("eligible")],
        "event_only_grounding": _candidate_grounding(target, selected, names),
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_entry(target: dict[str, Any], variant: str, system: str,
                  user: str) -> dict[str, Any]:
    return {
        "target_game_id": target["target_game_id"], "league": target["league"],
        "variant": variant, "as_of": target["as_of"],
        "system_prompt": system, "user_prompt": user,
        "system_prompt_sha256": _sha(system), "user_prompt_sha256": _sha(user),
        "model_call_made": False,
    }


def _write_blind_packet(outdir: Path, pairs: list[dict[str, Any]]) -> dict[str, Any]:
    blind_rows, identity, evidence_rows = [], [], []
    for pair in pairs:
        variants = [
            ("event_only", pair["event_only_preview"], pair.get("event_claims", [])),
            ("combined", pair["combined_preview"], pair.get("combined_claims", [])),
        ]
        variants = [(name, text, claims) for name, text, claims in variants if text]
        secrets.SystemRandom().shuffle(variants)
        for order, (variant, preview, claims) in enumerate(variants, 1):
            blind_id = f"blind-{secrets.token_hex(8)}"
            blind_rows.append({
                "blind_id": blind_id, "blind_target_id": pair["blind_target_id"],
                "league": pair["league"], "preview": preview, "variant_order": order,
            })
            evidence_rows.append({
                "blind_id": blind_id, "blind_target_id": pair["blind_target_id"],
                "league": pair["league"], "matchup": pair["matchup"],
                "as_of": pair["as_of"], "kickoff_date": pair["kickoff_date"],
                "claim_evidence": [{
                    key: claim[key] for key in (
                        "category", "claim_index", "claim_text", "occurred_at", "available_at",
                        "supporting_game_ids", "supporting_event_ids", "source_evidence",
                        "mechanical_verification", "rejection_reason") if key in claim
                } for claim in claims],
            })
            identity.append({
                "blind_id": blind_id, "variant": variant,
                "target_game_id": pair["target_game_id"],
                "blind_target_id": pair["blind_target_id"],
            })
    secrets.SystemRandom().shuffle(blind_rows)
    from research_narrative_event_knowledge import _jsonl_write
    _jsonl_write(outdir / "blind_review_packet.jsonl", blind_rows)
    _jsonl_write(outdir / "blind_evidence.jsonl", evidence_rows)
    with (outdir / "blind_rating_template.csv").open("w", newline="", encoding="utf-8") as fh:
        fields = ("blind_id", "blind_target_id", "league", "factual_accuracy_1_to_5",
                  "relevance_1_to_5", "specificity_1_to_5", "readability_1_to_5",
                  "unsupported_claims", "notes")
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in blind_rows:
            writer.writerow({"blind_id": row["blind_id"],
                             "blind_target_id": row["blind_target_id"],
                             "league": row["league"]})
    private_key = outdir.parent / "blind_identity_key.jsonl"
    _jsonl_write(private_key, identity)
    return {
        "blind_drafts": len(blind_rows),
        "targets_with_candidate_drafts": len({row["blind_target_id"] for row in blind_rows}),
        "baseline_preview_available": False,
        "baseline_reason": "core_stories output requires model inference; offline mode preserved its exact system prompt and reconstructed input",
        "identity_key_path": str(private_key),
    }


def build_relevance_packet(db_path: str, outdir: str | Path, as_of: str = AS_OF,
                           nfl_count: int = 10, nba_count: int = 10) -> dict[str, Any]:
    """Create cutoff-safe local inputs, candidate drafts, claims, and review files."""
    from research_narrative_event_knowledge import _json_write, _jsonl_write

    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    inventory = run_local_inventory(db_path, as_of)
    if inventory["query_only"] != 1:
        raise ResearchAuditError("database connection is not query-only")

    examples, claims, rejected, baseline_queue, candidate_queue = [], [], [], [], []
    pairs = []
    category_coverage = Counter()
    with closing(open_readonly(db_path)) as con:
        nfl_targets = _target_rows(con, "nfl", as_of, nfl_count)
        nba_targets = _target_rows(con, "nba", as_of, nba_count)
        nfl_games, nfl_schedule_rejected = _load_nfl_games(con, as_of)
        nba_games, nba_schedule_rejected = _load_nba_current_games(con, as_of)
        nba_baseline = _load_nba_baseline(con, as_of)
        nfl_records, nba_records = _records(nfl_games), _records(nba_games)
        nfl_names, nba_names = _team_names(con, "nfl"), _team_names(con, "nba")
        nfl_metrics, nfl_eligible_plays = _nfl_play_metrics(con)

        for league, targets, names, records in (
                ("nfl", nfl_targets, nfl_names, nfl_records),
                ("nba", nba_targets, nba_names, nba_records)):
            for target in targets:
                target["as_of"] = as_of
                if league == "nfl":
                    raw_candidates = _nfl_relationship_candidates(
                        target, nfl_games, nfl_metrics)
                    source_games = nfl_games
                else:
                    raw_candidates = _nba_relationship_candidates(
                        target, nba_games, nba_baseline)
                    source_games = nba_games
                for team in (target["away_team"], target["home_team"]):
                    streak = _target_streak(target, team, records, names)
                    if streak:
                        raw_candidates.append(streak)
                player_lines = {
                    team: _player_form(con, league, team, as_of)
                    for team in (target["away_team"], target["home_team"])
                }
                for team, lines in player_lines.items():
                    for line in lines:
                        raw_candidates.append({
                            "candidate_id": f"player-form:{line['player_id']}",
                            "candidate_type": "player_form", "category": "player_form",
                            "league": league, "team": team, "verified": True,
                            "supporting_game_ids": line["supporting_game_ids"],
                            "supporting_event_ids": [str(i) for i in line["supporting_log_ids"]],
                            "occurred_at": line["available_at"],
                            "available_at": line["available_at"], "evidence": line,
                        })
                preview = _preview_for_target(target, raw_candidates, names, records)
                for row in raw_candidates:
                    category_coverage[str(row.get("candidate_type"))] += 1
                if preview["selected"]:
                    category_coverage[f"selected:{preview['selected']['candidate_type']}"] += 1
                else:
                    category_coverage["selected:none"] += 1

                baseline_grounding, baseline_fields = _core_grounding(
                    target, records, names, player_lines)
                baseline_queue.append(_prompt_entry(
                    target, "core_stories_baseline", CORE_PREVIEW_SYSTEM, baseline_grounding))

                selected = preview["selected"]
                evidence_json = json.dumps(selected or {}, ensure_ascii=False, sort_keys=True)
                event_user = (
                    f"Matchup: {target['away_team']} vs {target['home_team']}. "
                    f"Date: {_date_label(target)}.\nVerified selected evidence (JSON):\n{evidence_json}")
                candidate_queue.append(_prompt_entry(
                    target, "event_only", EVENT_ONLY_SYSTEM, event_user))
                combined_user = baseline_grounding
                if selected:
                    combined_user += "\nVerified selected matchup evidence (JSON):\n" + evidence_json
                candidate_queue.append(_prompt_entry(
                    target, "combined", COMBINED_SYSTEM, combined_user))

                event_claims = _claim_rows(
                    target, selected, preview["event_only_preview"], as_of, "event_only")
                combined_claims = _claim_rows(
                    target, selected, preview["combined_preview"], as_of, "combined", records)
                target_claims = event_claims + combined_claims
                claims.extend(target_claims)
                for fact in preview["rejected_candidates"]:
                    rejected.append({
                        "target_game_id": target["target_game_id"], "league": league,
                        "candidate_id": fact.get("candidate_id"),
                        "candidate_type": fact.get("candidate_type"),
                        "category": fact.get("category"),
                        "rejection_reasons": fact.get("rejection_reasons"),
                        "selection_score": fact.get("selection_score"),
                        "score_components": fact.get("score_components"),
                        "supporting_game_ids": fact.get("supporting_game_ids"),
                        "supporting_event_ids": fact.get("supporting_event_ids"),
                        "evidence": fact.get("evidence"),
                    })
                for lines in player_lines.values():
                    for line in lines:
                        rejected.append({
                            "target_game_id": target["target_game_id"], "league": league,
                            "candidate_id": f"player-form:{line['player_id']}",
                            "candidate_type": "player_form", "category": "player_form",
                            "rejection_reasons": [
                                "isolated_player_stat_no_opposing_defense_measure"],
                            "supporting_game_ids": line["supporting_game_ids"],
                            "supporting_event_ids": [str(i) for i in line["supporting_log_ids"]],
                            "evidence": line,
                        })
                record_evidence = {
                    team: _team_record_evidence(records.get(team))
                    for team in (target["away_team"], target["home_team"])
                }
                blind_target_id = f"target-{len(pairs) + 1:03d}"
                example = {
                    "target_game_id": target["target_game_id"], "league": league,
                    "matchup": {"away": target["away_team"], "home": target["home_team"]},
                    "kickoff_date": target["kickoff_date"],
                    "kickoff_time_basis": target["kickoff_time_basis"],
                    "kickoff_utc_or_conservative_lower_bound": target["start_utc"],
                    "schedule_row_available_at": target["availability_basis"],
                    "as_of": as_of,
                    "baseline_system_prompt": CORE_PREVIEW_SYSTEM,
                    "baseline_system_prompt_sha256": _sha(CORE_PREVIEW_SYSTEM),
                    "baseline_user_prompt": baseline_grounding,
                    "baseline_fields": baseline_fields,
                    "baseline_preview": None,
                    "baseline_status": "prompt_and_local_evidence_reconstructed; model_not_called",
                    "event_only_preview": preview["event_only_preview"],
                    "combined_preview": preview["combined_preview"],
                    "combined_added_core_fact": preview["combined_added_core_fact"],
                    "selected_candidate": selected,
                    "ranked_candidates": preview["ranked_candidates"],
                    "team_record_evidence": record_evidence,
                    "player_form_input_lines": player_lines,
                    "mechanical_claims": target_claims,
                    "independent_human_rating": "pending",
                }
                examples.append(example)
                pairs.append({
                    "target_game_id": target["target_game_id"], "league": league,
                    "matchup": example["matchup"], "as_of": as_of,
                    "kickoff_date": target["kickoff_date"],
                    "blind_target_id": blind_target_id,
                    "event_only_preview": preview["event_only_preview"],
                    "combined_preview": preview["combined_preview"],
                    "event_claims": event_claims,
                    "combined_claims": combined_claims,
                })

    all_prompts = baseline_queue + candidate_queue
    prompt_chars = sum(len(row["system_prompt"]) + len(row["user_prompt"])
                       for row in all_prompts)
    estimated_input_tokens = math.ceil(prompt_chars / 4)
    total_calls = len(all_prompts)
    budget = {
        "model": "deepseek/deepseek-v4.1-flash (repository default; not reverified online)",
        "calls_for_10_nfl_plus_10_nba_three_variants": total_calls,
        "per_target_calls": 3,
        "max_completion_tokens_per_call_for_opt_in": 600,
        "max_completion_tokens_total": total_calls * 600,
        "estimated_input_tokens_characters_divided_by_4": estimated_input_tokens,
        "estimated_openrouter_model_token_cost_usd_at_repo_noted_rates": round(
            estimated_input_tokens * 0.15 / 1_000_000 +
            total_calls * 600 * 0.60 / 1_000_000, 6),
        "provider_call_fee_range_usd": {
            "nous_0.00005_per_call": round(total_calls * 0.00005, 6),
            "openrouter_0.0002_per_call": round(total_calls * 0.0002, 6),
        },
        "pricing_note": "backend/_core.py comments dated 2026-09-10 list these provider call fees and model token rates; how they combine is unspecified. Planning estimate only.",
        "inference_requests_made": 0,
    }
    blind_status = _write_blind_packet(outdir, pairs)
    _json_write(outdir / "database_coverage.json", inventory)
    _jsonl_write(outdir / "examples.jsonl", examples)
    _jsonl_write(outdir / "claim_audit.jsonl", claims)
    _jsonl_write(outdir / "rejected_facts.jsonl", rejected)
    _jsonl_write(outdir / "baseline_generation_queue.jsonl", baseline_queue)
    _jsonl_write(outdir / "candidate_generation_queue.jsonl", candidate_queue)

    selected_counts = Counter(
        row["selected_candidate"]["candidate_type"]
        for row in examples if row.get("selected_candidate"))
    claim_pass = sum(row["mechanical_verification"] == "pass" for row in claims)
    manifest = {
        "objective": "offline deterministic matchup relevance ranking",
        "database": inventory["database"], "database_mode": "mode=ro + query_only",
        "as_of": as_of, "targets": {"nfl": len(nfl_targets), "nba": len(nba_targets)},
        "core_stories_source": "backend/core_stories.py::generate_game_story",
        "core_system_prompt_sha256": _sha(CORE_PREVIEW_SYSTEM),
        "core_stories_unchanged": True,
        "nfl_schedule_completed_games_at_cutoff": len(nfl_games),
        "nfl_schedule_rejections": nfl_schedule_rejected,
        "nfl_pbp_run_pass_plays_with_epa": nfl_eligible_plays,
        "nba_recent_completed_games_at_cutoff": len(nba_games),
        "nba_schedule_rejections": nba_schedule_rejected,
        "nba_previous_season_regular_games_at_cutoff": len(nba_baseline),
        "selected_category_counts": dict(selected_counts),
        "candidate_input_category_counts": dict(category_coverage),
        "generated_preview_counts": {
            "event_only": sum(bool(row["event_only_preview"]) for row in examples),
            "combined": sum(bool(row["combined_preview"]) for row in examples),
            "core_stories_model_output": 0,
        },
        "mechanical_claims": {
            "total": len(claims), "passed": claim_pass, "failed": len(claims) - claim_pass,
        },
        "external_requests": 0, "model_inference_requests": 0,
        "human_ratings_entered": 0, "independent_human_evaluation": False,
        "inference_budget": budget, "blind_packet": blind_status,
        "limitations": [
            "NFL schedule has local gametime without a timezone; its UTC game-date lower bound is sufficient to prove the shared cutoff precedes the target date, but is not the kickoff instant.",
            "Upcoming NBA schedule rows have no stored ESPN event crosswalk; no ESPN or publisher request was made.",
            "NBA team_game_stats has no populated current-season stat rows; this ranking uses local NBA schedule scores and prior-season nba_sportsdataverse_games scores.",
            "core_stories matchup_context from ESPN summary is marked unavailable in baseline manifests.",
            "No original-generator model output exists in offline mode, so there is no fair baseline rating or improvement claim.",
            "Ranking weights are deterministic heuristics and have not been trained or independently human-validated.",
            "Fourth-down and drive classifications remain quarantined in their separate correctness workstream.",
        ],
    }
    _json_write(outdir / "run_manifest.json", manifest)
    _write_report(outdir, manifest, examples, rejected, inventory, budget)
    return manifest


def _write_report(outdir: Path, manifest: dict[str, Any],
                  examples: list[dict[str, Any]], rejected: list[dict[str, Any]],
                  inventory: dict[str, Any], budget: dict[str, Any]) -> None:
    nfl_coverage = inventory["coverage"].get("nfl_pbp", {}).get("current_season_2026", {})
    nba_stat_coverage = inventory["coverage"].get("team_game_stats", {}).get(
        "nba_populated_rows_at_cutoff", 0)
    nba_boxes = inventory["coverage"].get("nba_player_boxes_nbacom", {})
    lines = [
        "# Narrative relevance research — 2026-11-01", "",
        f"Database: {manifest['database']} (read-only; query_only={inventory['query_only']}).",
        f"Shared cutoff: {manifest['as_of']}. External requests: 0. Model calls: 0.", "",
        "## Result", "",
        f"Prepared {manifest['targets']['nfl']} NFL and {manifest['targets']['nba']} NBA targets. "
        "Event-only and combined outputs are deterministic research drafts. The exact "
        "core_stories system prompt and its reconstructable local inputs are saved for a "
        "later opt-in model comparison.",
        "The production core_stories.py file was not changed.",
        "The core prompt's local team record and player-form fields are reconstructed at "
        "the shared cutoff. matchup_context is explicitly marked unavailable because the "
        "production path reads it from ESPN summary. NFL target timestamps use a game-date "
        "UTC lower bound because the local schedule has no timezone for gametime.", "",
        "## Local coverage", "",
        f"- NFL PBP: {inventory['coverage'].get('nfl_pbp', {}).get('all_seasons', {}).get('plays', 0):,} plays "
        f"across {inventory['coverage'].get('nfl_pbp', {}).get('all_seasons', {}).get('games', 0):,} games "
        f"(2010–2026); the 2026 partition has {nfl_coverage.get('plays', 0):,} plays across "
        f"{nfl_coverage.get('games', 0):,} games. The trend extractor selected "
        f"{manifest['nfl_pbp_run_pass_plays_with_epa']:,} run/pass plays with non-null EPA.",
        f"- NFL final regular-season games available at cutoff: "
        f"{manifest['nfl_schedule_completed_games_at_cutoff']}.",
        f"- NBA current-season completed regular games: "
        f"{manifest['nba_recent_completed_games_at_cutoff']}.",
        f"- NBA previous-season regular-season baseline games: "
        f"{manifest['nba_previous_season_regular_games_at_cutoff']}.",
        f"- NBA team_game_stats: {nba_stat_coverage:,} populated rows joined to the 2025 regular season/Cup; "
        "no populated current-season team-game rows were found. Current scoring trends use schedule results.",
        f"- NBA player-box rows: {nba_boxes.get('rows', 0):,} across {nba_boxes.get('games', 0):,} games; "
        f"latest capture at cutoff: {nba_boxes.get('latest_capture')}. The local schema audit found no "
        f"NBA event-level play-by-play table (matching tables: "
        f"{inventory['coverage'].get('nba_event_level_tables', [])}).",
        "- Player-game-log lines are reconstructed as core input with actual capture timestamps "
        "for near-game snapshots. Isolated player lines are retained as rejected candidates.", "",
        "## Selection", "",
        f"Selected candidates: {json.dumps(manifest['selected_category_counts'], sort_keys=True)}.",
        f"Candidate inputs: {json.dumps(manifest['candidate_input_category_counts'], sort_keys=True)}.",
        f"Claim-level cutoff checks: {manifest['mechanical_claims']['passed']} passed, "
        f"{manifest['mechanical_claims']['failed']} failed, "
        f"{manifest['mechanical_claims']['total']} total.",
        f"Rejected candidates retained with reasons and evidence IDs: {len(rejected)}.",
        "- NFL EPA is stated as team efficiency across plays; no play is called game-winning.",
        "- Drive, fourth-down, lead-change, and single-play game-winner categories are quarantined.",
        "- Paired trend candidates need a same-metric offense/defense comparison, at least three "
        "recent and baseline games on both sides, both changes above threshold, recent evidence, "
        "and timestamps before the cutoff.", "",
        "## Human review status", "",
        f"The blind packet contains {manifest['blind_packet']['blind_drafts']} deterministic "
        f"candidate drafts across {manifest['blind_packet']['targets_with_candidate_drafts']} "
        "targets. Original-generator output is absent because no model call was made. "
        "No independent human ratings were entered; no improvement claim is supported.", "",
        "## Opt-in inference budget", "",
        f"Three variants for 20 targets require {budget['calls_for_10_nfl_plus_10_nba_three_variants']} "
        f"calls. Proposed completion cap: {budget['max_completion_tokens_per_call_for_opt_in']} "
        f"tokens per call; estimated prompt input {budget['estimated_input_tokens_characters_divided_by_4']:,} "
        "tokens by characters divided by four. At repository-noted model token rates the estimate "
        f"is USD {budget['estimated_openrouter_model_token_cost_usd_at_repo_noted_rates']:.6f}. "
        f"Provider call fees are separately listed: Nous USD "
        f"{budget['provider_call_fee_range_usd']['nous_0.00005_per_call']:.6f}; OpenRouter USD "
        f"{budget['provider_call_fee_range_usd']['openrouter_0.0002_per_call']:.6f}. "
        "The repository does not specify whether these schedules combine; rates were not reverified.", "",
        "## Example drafts", "",
    ]
    for item in examples:
        lines.extend([
            f"### {item['league'].upper()} · {item['matchup']['away']} at "
            f"{item['matchup']['home']} · {item['kickoff_date']}", "",
            f"Event-only: {item['event_only_preview'] or '[no eligible preview]'}",
            f"Combined: {item['combined_preview'] or '[no eligible preview]'}",
            "Core baseline output: not generated offline; prompt and local evidence are in examples.jsonl.",
            "",
        ])
    lines.extend(["## Remaining limitations", ""])
    lines.extend(f"- {limitation}" for limitation in manifest["limitations"])
    lines.extend(["", "Row-level artifacts: examples.jsonl, claim_audit.jsonl, "
                  "rejected_facts.jsonl, database_coverage.json, baseline_generation_queue.jsonl, "
                  "candidate_generation_queue.jsonl, and the blind review files.", ""])
    (outdir / "research_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DEV_DB))
    parser.add_argument("--as-of", default=AS_OF)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--nfl-count", type=int, default=10)
    parser.add_argument("--nba-count", type=int, default=10)
    args = parser.parse_args()
    manifest = build_relevance_packet(
        args.db, args.outdir, args.as_of, args.nfl_count, args.nba_count)
    print(json.dumps({
        "outdir": str(Path(args.outdir).resolve()), "targets": manifest["targets"],
        "generated_preview_counts": manifest["generated_preview_counts"],
        "external_requests": manifest["external_requests"],
        "model_inference_requests": manifest["model_inference_requests"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
