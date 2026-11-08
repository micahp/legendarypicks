"""Offline database-only narrative relevance research for Legendary Picks.

The default mode is offline and uses the shared development database in
query-only mode. An explicit prospective-capture mode can fetch pregame ESPN
summaries into research artifacts; it never writes to a database.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from contextlib import closing, nullcontext
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
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
PREVIEW_HORIZON_HOURS = 48
NFL_SCHEDULE_TIMEZONE = ZoneInfo("America/New_York")
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
    "Use the compact selected-evidence summary and any shared, dated ESPN matchup "
    "context supplied. The same ESPN context is supplied to every variant. State only "
    "facts directly present in those inputs. For a team_relationship, describe both "
    "supplied measurements and their sample windows. Do not calculate additional stats. "
    "For a team_streak, state only that verified streak. If no eligible evidence is "
    "supplied, return no preview. Do not claim causation, predict an outcome, or describe "
    "a play as decisive. Write one to three clear sentences."
)
COMBINED_SYSTEM = (
    "Use only the compact selected-evidence summary as evidence for a matchup claim. "
    "The shared, dated ESPN matchup context is supplied to every variant; cite its facts "
    "only as directly stated. Do not derive additional averages, margins, trends, or "
    "player statistics from background text. For a team_relationship, combine the offense and opposing-defense "
    "facts into one clear insight: state whether the supplied deltas move in the same "
    "or opposite directions, and explain what that means for this metric. Treat points "
    "or EPA allowed as the defense measure; higher means more allowed, lower means less. "
    "Do not merely repeat the two measurements without explaining their relationship. "
    "For a team_streak, state the verified streak only; do not connect it to the "
    "opponent's record or invent a second trend. If no selected evidence is supplied, "
    "say no verified relationship cleared the evidence gate and add no other facts. "
    "Do not add player statistics. Do not predict an outcome or call either team "
    "favored, stronger, a mismatch, or likely to win; avoid 'favors' and 'should win'. "
    "Do not claim causation or describe a high-EPA or scoring play as game-winning "
    "without sequence evidence. Write one to three clear sentences."
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


def _nfl_kickoff_utc(gameday: Any, gametime: Any) -> datetime | None:
    """Convert nflverse's Eastern-time kickoff field to an aware UTC instant."""
    try:
        local = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None
    return local.replace(tzinfo=NFL_SCHEDULE_TIMEZONE).astimezone(timezone.utc)


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
    amount_off, amount_def = ("more" if off_delta >= 0 else "less",
                              "more" if def_delta >= 0 else "less")
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
    if (off_delta >= 0) == (def_delta >= 0):
        scoring_direction = "higher" if off_delta >= 0 else "lower"
        if league == "nfl":
            relation = (f"The two trends align toward {scoring_direction} EPA: the "
                        f"{offense}'s offense has generated {amount_off} EPA per play, "
                        f"and the {defense} have allowed {amount_def} EPA per play.")
        else:
            relation = (f"The two scoring trends align toward {scoring_direction} totals: "
                        f"the {offense} have scored {amount_off} points, and the "
                        f"{defense} have allowed {amount_def} points.")
    elif league == "nfl":
        relation = (f"The trends pull in different directions: the {offense}'s offense is "
                    f"generating {amount_off} EPA per play, while the {defense} have "
                    f"allowed {amount_def} EPA per play.")
    else:
        relation = (f"The trends pull in different directions: the {offense} are scoring "
                    f"{amount_off} points, while the {defense} have allowed "
                    f"{amount_def} points.")
    return " ".join((a, b, relation))


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
    if cutoff is None:
        raise ResearchAuditError("target selection requires a valid as_of timestamp")
    horizon_end = cutoff + timedelta(hours=PREVIEW_HORIZON_HOURS)
    out = []
    if league == "nfl":
        first_local_date = cutoff.astimezone(NFL_SCHEDULE_TIMEZONE).date().isoformat()
        rows = con.execute(
            "SELECT game_id,season,week,gameday,gametime,away_team,home_team,espn,ingested_at "
            "FROM nfl_schedule WHERE season=? AND game_type='REG' AND gameday>=? "
            "ORDER BY gameday,gametime,game_id", (NFL_SEASON, first_local_date)).fetchall()
        for raw in rows:
            row = dict(raw)
            available = _utc(row.get("ingested_at"))
            start = _nfl_kickoff_utc(row.get("gameday"), row.get("gametime"))
            if (available is None or available > cutoff or start is None
                    or not cutoff < start <= horizon_end):
                continue
            row.update({
                "league": "nfl", "start_utc": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "kickoff_date": str(row["gameday"])[:10],
                "kickoff_time_basis": "nflverse gametime is Eastern; converted with America/New_York",
                "availability_basis": "nfl_schedule.ingested_at_observed_future_schedule",
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
            available = _utc(row.get("ingested_at"))
            start = _utc(row.get("start_utc"))
            if (available is None or available > cutoff or start is None
                    or not cutoff < start <= horizon_end):
                continue
            row.update({
                "league": "nba", "kickoff_date": str(row["game_date"]),
                "kickoff_time_basis": "nba_schedule.start_utc",
                "availability_basis": "nba_schedule.ingested_at_observed_scheduled_game",
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
    record_text = f"{record['wins']}-{record['losses']}"
    if record.get("ties"):
        record_text += f"-{record['ties']}"
    return (f"{name} ({code}): {record_text}, "
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


def _attach_raw_nfl_play_rows(candidate: dict[str, Any],
                              metric_rows: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
    if candidate.get("league") != "nfl" or candidate.get("candidate_type") != "team_relationship":
        return
    evidence = candidate.get("evidence") or {}
    for key in ("offense_recent", "offense_baseline",
                "defense_allowed_recent", "defense_allowed_baseline"):
        side = "defense" if key.startswith("defense") else "offense"
        team = candidate["defense_team"] if side == "defense" else candidate["offense_team"]
        for game in evidence.get(key) or []:
            rows = metric_rows.get((str(game["game_id"]), team), [])
            plays = [row for row in rows if bool(row.get("allowed")) == (side == "defense")]
            game["play_rows"] = [{
                "game_id": str(row["game_id"]), "play_id": str(row["play_id"]),
                "epa": float(row["epa"]), "posteam": row["posteam"],
                "defteam": row["defteam"],
            } for row in plays]


def _close(actual: Any, expected: Any, tolerance: float = 1e-6) -> bool:
    try:
        return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def _recompute_relationship_statistics(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence") or {}
    league = str(candidate.get("league") or "").lower()
    windows = (
        ("offense_recent", "offense_recent"),
        ("offense_baseline", "offense_baseline"),
        ("defense_allowed_recent", "defense_allowed_recent"),
        ("defense_allowed_baseline", "defense_allowed_baseline"),
    )
    mismatches, recomputed, checked_rows = [], {}, 0
    all_game_ids, all_event_ids = set(), set()
    for window_key, value_key in windows:
        rows = evidence.get(window_key) or []
        values = []
        if not rows:
            mismatches.append(f"{window_key}:missing_source_rows")
            continue
        for row in rows:
            game_id = str(row.get("game_id") or "")
            all_game_ids.add(game_id)
            if league == "nfl":
                plays = row.get("play_rows") or []
                play_ids = [str(play.get("play_id")) for play in plays]
                expected_team = (candidate.get("defense_team") if window_key.startswith("defense")
                                 else candidate.get("offense_team"))
                if not plays:
                    mismatches.append(f"{window_key}:{game_id}:raw_play_rows_missing")
                    continue
                if len(plays) < MIN_NFL_PLAYS_PER_GAME:
                    mismatches.append(f"{window_key}:{game_id}:below_minimum_play_count")
                if len(plays) != int(row.get("eligible_plays") or 0):
                    mismatches.append(f"{window_key}:{game_id}:play_count_differs")
                if set(play_ids) != set(map(str, row.get("play_ids") or [])):
                    mismatches.append(f"{window_key}:{game_id}:play_ids_differ")
                if any(
                    str(play.get("game_id")) != game_id or
                    (str(play.get("defteam")) if window_key.startswith("defense") else
                     str(play.get("posteam"))) != str(expected_team)
                    for play in plays
                ):
                    mismatches.append(f"{window_key}:{game_id}:team_or_game_id_differs")
                play_values = [play.get("epa") for play in plays]
                if any(not isinstance(value, (int, float)) for value in play_values):
                    mismatches.append(f"{window_key}:{game_id}:invalid_epa_value")
                    continue
                game_mean = sum(float(value) for value in play_values) / len(play_values)
                if not _close(game_mean, row.get("epa_per_play"), tolerance=0.000006):
                    mismatches.append(f"{window_key}:{game_id}:stored_game_mean_differs")
                all_event_ids.update(f"{game_id}:{play_id}" for play_id in play_ids)
                checked_rows += len(plays)
            else:
                expected_team = (candidate.get("defense_team") if window_key.startswith("defense")
                                 else candidate.get("offense_team"))
                if str(row.get("team")) != str(expected_team):
                    mismatches.append(f"{window_key}:{game_id}:team_differs")
                stat_key = "points_allowed" if window_key.startswith("defense") else "points_for"
                value = row.get(stat_key)
                if not isinstance(value, (int, float)):
                    mismatches.append(f"{window_key}:{game_id}:missing_{stat_key}")
                    continue
                game_mean = float(value)
                event_id = (f"{game_id}:{row.get('team')}:{row.get('points_for')}"
                            f":{row.get('points_allowed')}")
                all_event_ids.add(event_id)
                checked_rows += 1
            values.append(game_mean)
        if not values:
            continue
        computed_value = sum(values) / len(values)
        recomputed[value_key] = computed_value
        if not _close(computed_value, candidate.get(value_key)):
            mismatches.append(f"{value_key}:candidate_summary_differs")
        count_key = (f"defense_{window_key.rsplit('_', 1)[-1]}_games"
                     if window_key.startswith("defense_allowed") else f"{value_key}_games")
        if len(values) != int(candidate.get(count_key) or 0):
            mismatches.append(f"{count_key}:source_row_count_differs")

    if all(key in recomputed for key in (
            "offense_recent", "offense_baseline",
            "defense_allowed_recent", "defense_allowed_baseline")):
        offense_delta = recomputed["offense_recent"] - recomputed["offense_baseline"]
        defense_delta = (recomputed["defense_allowed_recent"] -
                         recomputed["defense_allowed_baseline"])
        recomputed["offense_delta"] = offense_delta
        recomputed["defense_allowed_delta"] = defense_delta
        if not _close(round(offense_delta, 4), candidate.get("offense_delta")):
            mismatches.append("offense_delta:candidate_summary_differs")
        if not _close(round(defense_delta, 4), candidate.get("defense_allowed_delta")):
            mismatches.append("defense_allowed_delta:candidate_summary_differs")
        expected_relationship = (
            "aligned_scoring_pressure" if offense_delta * defense_delta > 0
            else "opposing_recent_trends")
        if candidate.get("relationship_type") != expected_relationship:
            mismatches.append("relationship_type:direction_differs")
    if all_game_ids != set(map(str, candidate.get("supporting_game_ids") or [])):
        mismatches.append("supporting_game_ids:differ")
    if all_event_ids != set(map(str, candidate.get("supporting_event_ids") or [])):
        mismatches.append("supporting_event_ids:differ")
    return {
        "status": "pass" if not mismatches else "fail",
        "method": "raw_nfl_pbp_epa_rows" if league == "nfl" else "schedule_score_rows",
        "checked_source_rows": checked_rows, "recomputed": recomputed,
        "reported": {key: candidate.get(key) for _, key in windows},
        "mismatches": sorted(set(mismatches)),
    }


def _recompute_team_record(record: dict[str, Any]) -> dict[str, Any]:
    rows = record.get("source_game_rows") or record.get("games_detail") or []
    mismatches = []
    results = []
    for row in rows:
        if "for" not in row or "against" not in row:
            mismatches.append("source_row_missing_scores")
            continue
        result = "W" if row["for"] > row["against"] else "L" if row["for"] < row["against"] else "T"
        if row.get("result") != result:
            mismatches.append(f"{row.get('game_id')}:result_differs_from_scores")
        results.append({**row, "result": result})
    if not results:
        mismatches.append("source_rows_missing")
    results.sort(key=lambda row: (str(row.get("date") or row.get("game_date") or ""),
                                  str(row.get("game_id") or "")))
    wins = sum(row["result"] == "W" for row in results)
    losses = sum(row["result"] == "L" for row in results)
    ties = sum(row["result"] == "T" for row in results)
    count = len(results)
    recent = results[-10:]
    last10 = f"{sum(row['result'] == 'W' for row in recent)}-{sum(row['result'] == 'L' for row in recent)}"
    if any(row["result"] == "T" for row in recent):
        last10 += f"-{sum(row['result'] == 'T' for row in recent)}"
    last_result = results[-1]["result"] if results else None
    streak = 0
    for row in reversed(results):
        if row["result"] != last_result:
            break
        streak += 1
    computed = {
        "games": count, "wins": wins, "losses": losses, "ties": ties,
        "win_pct": (wins + 0.5 * ties) / count if count else None,
        "differential": round(sum(row["for"] - row["against"] for row in results) / count, 2)
        if count else 0,
        "last10": last10, "streak_result": last_result, "streak_length": streak,
    }
    for key, value in computed.items():
        matches = _close(record.get(key), value) if isinstance(value, (int, float)) else record.get(key) == value
        if not matches:
            mismatches.append(f"{key}:record_differs")
    row_ids = {str(row.get("game_id")) for row in results}
    if row_ids != set(map(str, record.get("supporting_game_ids") or row_ids)):
        mismatches.append("supporting_game_ids:differ")
    return {"status": "pass" if not mismatches else "fail", "source_rows": count,
            "recomputed": computed, "mismatches": sorted(set(mismatches))}


def _recompute_record_population(records: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    audits = {team: _recompute_team_record(record) for team, record in records.items()}
    ranked = sorted(records, key=lambda team: (
        -float(audits[team]["recomputed"].get("win_pct") or 0),
        -float(audits[team]["recomputed"].get("differential") or 0), team))
    for rank, team in enumerate(ranked, 1):
        audits[team]["recomputed"]["rank"] = rank
        if records[team].get("rank") != rank:
            audits[team]["mismatches"].append("rank:record_differs")
            audits[team]["status"] = "fail"
    return audits


def _recompute_player_form(player: dict[str, Any], league: str) -> dict[str, Any]:
    logs = player.get("source_logs") or []
    mismatches = []
    recomputed = {}
    for key, label in HEADLINE_STATS[league]:
        values = [log.get("stats", {}).get(key) for log in logs
                  if isinstance(log.get("stats", {}).get(key), (int, float))]
        if len(values) >= 3:
            recomputed[label] = values
    if recomputed != (player.get("statistics") or {}):
        mismatches.append("displayed_statistics_differ_from_source_logs")
    source_ids = [log.get("player_game_log_id") for log in logs]
    if source_ids != list(player.get("supporting_log_ids") or []):
        mismatches.append("supporting_log_ids:differ")
    available = [log.get("available_at") for log in logs if log.get("available_at")]
    if available and max(available) != player.get("available_at"):
        mismatches.append("available_at:source_log_max_differs")
    return {"status": "pass" if not mismatches else "fail", "source_rows": len(logs),
            "recomputed": recomputed, "mismatches": mismatches}


def _audit_reconstructed_input(fields: dict[str, Any], league: str) -> dict[str, Any]:
    records = {
        record.get("team"): record.get("independent_recomputation")
        for record in fields.get("record_facts") or [] if record
    }
    players = {
        str(player.get("player_id")): player.get("independent_recomputation")
        for player in fields.get("player_form") or []
    }
    audits = [audit for audit in records.values()] + [audit for audit in players.values()]
    missing = sum(audit is None for audit in audits)
    failed = sum(audit is not None and audit.get("status") != "pass" for audit in audits)
    return {
        "status": "pass" if not missing and not failed else "fail",
        "team_records": records, "player_form": players,
        "checks": len(audits), "missing_audits": missing, "failed_audits": failed,
        "league": league,
    }


def _recompute_streak(candidate: dict[str, Any]) -> dict[str, Any]:
    rows = candidate.get("evidence", {}).get("games") or []
    expected = {"win": "W", "loss": "L", "tie": "T"}.get(
        candidate.get("streak_result"))
    mismatches = []
    if expected is None:
        mismatches.append("streak_result:unknown_value")
    if len(rows) != int(candidate.get("streak_length") or 0):
        mismatches.append("streak_length:source_row_count_differs")
    if not rows or expected is None or any(row.get("result") != expected for row in rows):
        mismatches.append("streak_result:source_rows_differ")
    if {str(row.get("game_id")) for row in rows} != set(
            map(str, candidate.get("supporting_game_ids") or [])):
        mismatches.append("supporting_game_ids:differ")
    return {"status": "pass" if not mismatches else "fail", "source_rows": len(rows),
            "recomputed": {"streak_length": len(rows), "streak_result": expected},
            "mismatches": mismatches}


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
        "streak_result": {"W": "win", "L": "loss", "T": "tie"}[record["streak_result"]],
        "streak_length": record["streak_length"],
        "source_game_date": detail[0]["date"],
            "supporting_game_ids": [str(row["game_id"]) for row in detail],
        "supporting_event_ids": [f"{row['game_id']}:final_result" for row in detail],
        "occurred_at": available, "available_at": available, "verified": True,
        "evidence": {"source_table": "nfl_schedule" if target["league"] == "nfl"
                     else "nba_schedule", "games": detail},
    }


def _candidate_prompt_fact(candidate: dict[str, Any] | None) -> dict[str, Any]:
    """Return only the independently checked summary fields needed for generation."""
    if not candidate:
        return {"selected_evidence_status": "no_eligible_candidate"}
    candidate_type = candidate.get("candidate_type")
    audit_status = (candidate.get("independent_recomputation") or {}).get("status")
    if audit_status != "pass":
        return {"selected_evidence_status": "independent_recomputation_failed",
                "independent_recomputation_status": audit_status}
    if candidate_type == "team_relationship":
        offense_delta = float(candidate["offense_delta"])
        defense_delta = float(candidate["defense_allowed_delta"])
        return {
            "selected_evidence_status": "eligible_and_independently_recomputed",
            "candidate_type": candidate_type,
            "league": candidate.get("league"),
            "metric": candidate.get("metric"),
            "offense": {
                "team": candidate.get("offense_team"),
                "recent_mean": candidate.get("offense_recent"),
                "baseline_mean": candidate.get("offense_baseline"),
                "delta": candidate.get("offense_delta"),
                "recent_games": candidate.get("offense_recent_games"),
                "baseline_games": candidate.get("offense_baseline_games"),
                "delta_direction": "up" if offense_delta > 0 else "down" if offense_delta < 0 else "flat",
            },
            "opposing_defense": {
                "team": candidate.get("defense_team"),
                "measure": "points_allowed_per_game" if candidate.get("league") == "nba"
                    else "epa_allowed_per_scrimmage_play",
                "recent_mean": candidate.get("defense_allowed_recent"),
                "baseline_mean": candidate.get("defense_allowed_baseline"),
                "delta": candidate.get("defense_allowed_delta"),
                "recent_games": candidate.get("defense_recent_games"),
                "baseline_games": candidate.get("defense_baseline_games"),
                "delta_direction": "up" if defense_delta > 0 else "down" if defense_delta < 0 else "flat",
            },
            "delta_directions_align": (offense_delta > 0) == (defense_delta > 0)
                if offense_delta and defense_delta else False,
            "relationship_type": candidate.get("relationship_type"),
            "independent_recomputation_status": audit_status,
        }
    if candidate_type == "team_streak":
        return {
            "selected_evidence_status": "eligible_and_independently_recomputed",
            "candidate_type": candidate_type,
            "league": candidate.get("league"),
            "team": candidate.get("team"),
            "team_name": candidate.get("team_name"),
            "streak_result": candidate.get("streak_result"),
            "streak_length": candidate.get("streak_length"),
            "independent_recomputation_status": audit_status,
        }
    return {"selected_evidence_status": "no_supported_prompt_summary"}


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
    result["independent_recomputation"] = record.get("_independent_recomputation") or \
        _recompute_team_record(record)
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
    result = {"win": "won", "loss": "lost", "tie": "tied"}.get(
        candidate["streak_result"], "played")
    number = {3: "three", 4: "four", 5: "five", 6: "six"}.get(
        int(candidate["streak_length"]), str(candidate["streak_length"]))
    return f"The {team} have {result} {number} straight games."


def _record_sentence(home: dict[str, Any] | None, away: dict[str, Any] | None,
                     names: dict[str, str], home_code: str, away_code: str) -> str | None:
    if not home or not away or abs(home["wins"] - away["wins"]) < 2:
        return None
    away_record = f"{away['wins']}-{away['losses']}"
    home_record = f"{home['wins']}-{home['losses']}"
    if away.get("ties"):
        away_record += f"-{away['ties']}"
    if home.get("ties"):
        home_record += f"-{home['ties']}"
    return (f"The {names.get(away_code, away_code)} are {away_record}; "
            f"the {names.get(home_code, home_code)} are {home_record}.")


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
    is_relationship = selected.get("candidate_type") == "team_relationship"
    max_selected_claims = 3 if is_relationship else 1
    selected_sentences = sentences[:max_selected_claims]
    evidence = selected.get("evidence") or {}
    statistic_recomputation = selected.get("independent_recomputation")
    if not statistic_recomputation:
        statistic_recomputation = (_recompute_relationship_statistics(selected) if is_relationship
                                   else _recompute_streak(selected))
    rows = []
    for index, sentence in enumerate(selected_sentences):
        if is_relationship:
            if index == 0:
                evidence_prefixes = ("offense",)
            elif index == 1:
                evidence_prefixes = ("defense_allowed",)
            else:
                evidence_prefixes = ("offense", "defense_allowed")
            windows = [
                item for prefix in evidence_prefixes
                for suffix in ("recent", "baseline")
                for item in evidence.get(f"{prefix}_{suffix}") or []
            ]
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
        if statistic_recomputation.get("status") != "pass":
            recompute_reason = "independent_statistic_recomputation_failed"
            rejection = f"{rejection};{recompute_reason}" if rejection else recompute_reason
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
            "independent_statistic_recomputation": statistic_recomputation,
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
            home_audit = home.get("_independent_recomputation") or _recompute_team_record(home)
            away_audit = away.get("_independent_recomputation") or _recompute_team_record(away)
            record_audit = {
                "status": "pass" if home_audit["status"] == away_audit["status"] == "pass" else "fail",
                "method": "team_game_score_rows",
                "teams": {target["home_team"]: home_audit, target["away_team"]: away_audit},
            }
            if record_audit["status"] != "pass":
                recompute_reason = "independent_standings_recomputation_failed"
                rejection = f"{rejection};{recompute_reason}" if rejection else recompute_reason
            rows.append({
                "target_game_id": target["target_game_id"], "league": target["league"],
                "variant": variant, "claim_index": len(rows) + 1, "as_of": as_of,
                "category": "standings_record", "candidate_id": "core-current-records",
                "claim_text": sentence, "occurred_at": available_at, "available_at": available_at,
                "supporting_game_ids": game_ids, "supporting_event_ids": event_ids,
                "mechanical_verification": "pass" if not rejection else "fail",
                "rejection_reason": rejection,
                "source_evidence": game_rows,
                "independent_statistic_recomputation": record_audit,
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


def _payload_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _summary_matchup_fields(league: str, payload: dict[str, Any]) -> tuple[dict[str, str], datetime | None, str, bool]:
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    competition = competitions[0] if competitions else {}
    sides = {}
    for row in competition.get("competitors") or []:
        side = row.get("homeAway")
        abbreviation = ((row.get("team") or {}).get("abbreviation") or "").strip()
        if side in ("home", "away") and abbreviation:
            sides[side] = team_codes.normalize(league, abbreviation)
    start = _utc(competition.get("date") or header.get("date"))
    state = str((((competition.get("status") or {}).get("type") or {}).get("state")) or "").lower()
    completed = (((competition.get("status") or {}).get("type") or {}).get("completed")) is True
    return sides, start, state, completed


def _validate_context_snapshot(example: dict[str, Any], snapshot: dict[str, Any],
                               as_of: str) -> None:
    payload = snapshot.get("summary_payload")
    if not isinstance(payload, dict):
        raise ResearchAuditError("ESPN context snapshot has no summary payload")
    if _payload_sha256(payload) != snapshot.get("summary_sha256"):
        raise ResearchAuditError("ESPN context snapshot hash does not match its payload")
    captured_at, cutoff, kickoff = (_utc(snapshot.get("captured_at")), _utc(as_of),
                                    _utc(example.get("kickoff_utc")))
    if captured_at is None or cutoff is None or kickoff is None:
        raise ResearchAuditError("ESPN context snapshot requires captured, cutoff, and kickoff timestamps")
    if captured_at > cutoff or cutoff >= kickoff or captured_at >= kickoff:
        raise ResearchAuditError("ESPN context snapshot is not cutoff-safe and pre-kickoff")
    for field in ("cache_file_mtime", "cache_file_ctime"):
        if snapshot.get(field):
            stamp = _utc(snapshot[field])
            if stamp is None or stamp > cutoff:
                raise ResearchAuditError(f"ESPN context {field} is after the experiment cutoff")
    league = str(example["league"])
    sides, summary_start, state, completed = _summary_matchup_fields(league, payload)
    expected = {"away": example["matchup"]["away"], "home": example["matchup"]["home"]}
    if sides != expected:
        raise ResearchAuditError(f"ESPN context teams do not match target {example['target_game_id']}")
    if summary_start is None or abs((summary_start - kickoff).total_seconds()) > 300:
        raise ResearchAuditError(f"ESPN context kickoff does not match target {example['target_game_id']}")
    header_id = str((payload.get("header") or {}).get("id") or "")
    if not header_id or header_id != str(snapshot.get("espn_event_id")):
        raise ResearchAuditError("ESPN context event id does not match its summary payload")
    if state != "pre" or completed:
        raise ResearchAuditError(f"ESPN context for {example['target_game_id']} is not a pregame summary")


def _context_section(snapshot: dict[str, Any]) -> str:
    lines = snapshot.get("context_lines") or []
    body = "\n".join(lines) if lines else "No matchup-context lines were produced."
    return (
        "Shared pregame ESPN matchup context "
        f"(captured {snapshot['captured_at']}; summary SHA-256 {snapshot['summary_sha256']}):\n"
        + body
    )


def _attach_espn_context_snapshots(outdir: Path,
                                   snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Inject verified snapshot-derived lines identically into each target's three prompts."""
    from research_narrative_event_knowledge import _jsonl_write, _json_write
    import matchup_context

    examples = _read_jsonl(outdir / "examples.jsonl")
    baseline_queue = _read_jsonl(outdir / "baseline_generation_queue.jsonl")
    candidate_queue = _read_jsonl(outdir / "candidate_generation_queue.jsonl")
    manifest_path = outdir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    as_of = manifest["as_of"]
    by_target = {str(row["target_game_id"]): row for row in snapshots}
    target_ids = {str(row["target_game_id"]) for row in examples}
    if set(by_target) != target_ids:
        raise ResearchAuditError("ESPN snapshot set must explicitly cover every target, including missing snapshots")
    queue_by_key = {
        (str(row["target_game_id"]), row["variant"]): row
        for row in baseline_queue + candidate_queue
    }
    verified, unavailable = 0, []
    for example in examples:
        target_id = str(example["target_game_id"])
        snapshot = by_target[target_id]
        if snapshot.get("status") != "captured":
            if snapshot.get("status") != "unavailable":
                raise ResearchAuditError(f"unknown ESPN snapshot status for {target_id}")
            unavailable.append(target_id)
            example["matchup_context_snapshot"] = {
                "status": "unavailable", "reason": snapshot.get("reason"),
            }
            example["baseline_fields"]["matchup_context"] = {
                "status": "unavailable_pre_cutoff_snapshot",
                "reason": snapshot.get("reason"),
            }
            queue_by_key[(target_id, "core_stories_baseline")]["matchup_context_snapshot_status"] = "unavailable"
            for variant, system_prompt in (("event_only", EVENT_ONLY_SYSTEM),
                                           ("combined", COMBINED_SYSTEM)):
                row = queue_by_key[(target_id, variant)]
                row["system_prompt"] = system_prompt
                row["system_prompt_sha256"] = _sha(system_prompt)
                row["matchup_context_snapshot_status"] = "unavailable"
                row["model_call_made"] = False
                for key in ("provider", "model", "model_output_sha256"):
                    row.pop(key, None)
            continue

        _validate_context_snapshot(example, snapshot, as_of)
        records = example.get("baseline_fields", {}).get("record_facts") or []
        current_season = any(int((record or {}).get("games") or 0) > 0 for record in records)
        lines = matchup_context.context_lines(
            example["league"], str(snapshot["espn_event_id"]),
            summary=snapshot["summary_payload"], state="pre",
            current_season=current_season,
        )
        snapshot["context_lines"] = lines
        snapshot["context_lines_function"] = "backend/matchup_context.py::context_lines"
        block = _context_section(snapshot)
        old_baseline_user = example["baseline_user_prompt"]
        baseline_user = old_baseline_user + "\n" + block
        example["baseline_user_prompt_without_espn_context"] = old_baseline_user
        example["baseline_user_prompt"] = baseline_user
        example["matchup_context_snapshot"] = {
            key: snapshot.get(key) for key in (
                "status", "espn_event_id", "captured_at", "summary_sha256",
                "capture_timestamp_basis", "cache_file_mtime", "cache_file_ctime",
                "cache_file_relative_path", "context_lines_function")
        }
        example["matchup_context_snapshot"]["context_line_count"] = len(lines)
        example["baseline_fields"]["matchup_context"] = {
            "status": "captured_pre_kickoff_snapshot",
            "espn_event_id": snapshot["espn_event_id"],
            "captured_at": snapshot["captured_at"],
            "summary_sha256": snapshot["summary_sha256"],
            "capture_timestamp_basis": snapshot.get("capture_timestamp_basis"),
            "context_lines_function": "backend/matchup_context.py::context_lines",
            "context_lines": lines,
        }
        baseline_prompt = queue_by_key[(target_id, "core_stories_baseline")]
        baseline_prompt["user_prompt"] = baseline_user
        baseline_prompt["user_prompt_sha256"] = _sha(baseline_user)

        selected = example.get("selected_candidate")
        summary_json = json.dumps(_candidate_prompt_fact(selected), ensure_ascii=False, sort_keys=True)
        matchup = example["matchup"]
        date_label = _date_label({
            "league": example["league"], "kickoff_date": example["kickoff_date"],
            "start_utc": example["kickoff_utc"],
        })
        event_user = (
            f"Matchup: {matchup['away']} vs {matchup['home']}. Date: {date_label}.\n"
            f"{block}\nVerified selected-evidence summary (JSON):\n{summary_json}"
        )
        combined_user = (
            f"{old_baseline_user}\n{block}\n"
            f"Verified selected-evidence summary (JSON):\n{summary_json}"
        )
        for variant, user_prompt, system_prompt in (
            ("event_only", event_user, EVENT_ONLY_SYSTEM),
            ("combined", combined_user, COMBINED_SYSTEM),
        ):
            row = queue_by_key[(target_id, variant)]
            row["system_prompt"] = system_prompt
            row["system_prompt_sha256"] = _sha(system_prompt)
            row["user_prompt"] = user_prompt
            row["user_prompt_sha256"] = _sha(user_prompt)
            row["matchup_context_snapshot_sha256"] = snapshot["summary_sha256"]
            row["matchup_context_captured_at"] = snapshot["captured_at"]
            row["matchup_context_snapshot_status"] = "verified_pre_cutoff"
            row["model_call_made"] = False
            for key in ("provider", "model", "model_output_sha256"):
                row.pop(key, None)
        baseline_prompt["matchup_context_snapshot_sha256"] = snapshot["summary_sha256"]
        baseline_prompt["matchup_context_captured_at"] = snapshot["captured_at"]
        baseline_prompt["matchup_context_snapshot_status"] = "verified_pre_cutoff"
        baseline_prompt["model_call_made"] = False
        for key in ("provider", "model", "model_output_sha256"):
            baseline_prompt.pop(key, None)
        verified += 1

    snapshot_artifact = [
        {key: value for key, value in row.items() if key != "summary_payload"}
        for row in snapshots
    ]
    _jsonl_write(outdir / "espn_context_snapshots.jsonl", snapshot_artifact)
    _jsonl_write(outdir / "examples.jsonl", examples)
    _jsonl_write(outdir / "baseline_generation_queue.jsonl", baseline_queue)
    _jsonl_write(outdir / "candidate_generation_queue.jsonl", candidate_queue)
    manifest["espn_context_capture"] = {
        "targets_with_verified_pre_cutoff_snapshots": verified,
        "targets_without_verified_snapshots": unavailable,
        "context_lines_function": "backend/matchup_context.py::context_lines",
        "snapshot_artifact": "espn_context_snapshots.jsonl",
        "same_snapshot_supplied_to_all_variants_for_captured_targets": True,
        "all_targets_have_snapshot": not unavailable,
    }
    manifest["limitations"] = [
        item for item in manifest.get("limitations", [])
        if "core_stories matchup_context from ESPN summary is marked unavailable" not in item
        and "No original-generator model output exists in offline mode" not in item
    ]
    if unavailable:
        manifest["limitations"].append(
            f"Cutoff-safe ESPN summary snapshots were unavailable for {len(unavailable)} of "
            f"{len(examples)} targets; those targets retain a reduced-context baseline.")
    manifest["limitations"].append(
        "The full core_stories generator was not invoked; local records and player-form inputs remain reconstructed.")
    manifest["limitations"] = list(dict.fromkeys(manifest["limitations"]))
    _json_write(manifest_path, manifest)
    return manifest["espn_context_capture"]


def _blind_identity_key_path(outdir: Path) -> Path:
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return (cache_root / "legendarypicks" / "research" / outdir.parent.name /
            outdir.name / "blind_identity_key.jsonl")


def _write_private_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_blind_packet(outdir: Path, pairs: list[dict[str, Any]],
                        identity_key_path: Path | None = None) -> dict[str, Any]:
    blind_rows, identity, evidence_rows = [], [], []
    for pair in pairs:
        variants = [
            ("core_stories_baseline", pair.get("baseline_preview"), pair.get("baseline_claims", [])),
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
                        "mechanical_verification", "rejection_reason",
                        "independent_statistic_recomputation") if key in claim
                } for claim in claims],
                "input_evidence": (pair.get("variant_input_evidence") or {}).get(variant, []),
                "evidence_note": "Input evidence is supplied for review; it is not an automatic claim alignment for generated prose.",
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
    private_key = identity_key_path or _blind_identity_key_path(outdir)
    repo_root = Path(__file__).resolve().parents[1]
    if repo_root == private_key.resolve() or repo_root in private_key.resolve().parents:
        raise ResearchAuditError("blind identity key must be stored outside the repository")
    _write_private_jsonl(private_key, identity)
    return {
        "blind_drafts": len(blind_rows),
        "targets_with_candidate_drafts": len({row["blind_target_id"] for row in blind_rows}),
        "baseline_preview_available": any(pair.get("baseline_preview") for pair in pairs),
        "identity_key_storage": "external_owner_only_research_cache",
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
    statistic_audits = []
    pairs = []
    category_coverage = Counter()
    with closing(open_readonly(db_path)) as con:
        nfl_targets = _target_rows(con, "nfl", as_of, nfl_count)
        nba_targets = _target_rows(con, "nba", as_of, nba_count)
        nfl_games, nfl_schedule_rejected = _load_nfl_games(con, as_of)
        nba_games, nba_schedule_rejected = _load_nba_current_games(con, as_of)
        nba_baseline = _load_nba_baseline(con, as_of)
        nfl_records, nba_records = _records(nfl_games), _records(nba_games)
        record_audits = {
            "nfl": _recompute_record_population(nfl_records),
            "nba": _recompute_record_population(nba_records),
        }
        for league_records, audits in ((nfl_records, record_audits["nfl"]),
                                       (nba_records, record_audits["nba"])):
            for team, record in league_records.items():
                record["_independent_recomputation"] = audits[team]
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
                        line["independent_recomputation"] = _recompute_player_form(line, league)
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
                if selected:
                    _attach_raw_nfl_play_rows(selected, nfl_metrics)
                    selected["independent_recomputation"] = (
                        _recompute_relationship_statistics(selected)
                        if selected.get("candidate_type") == "team_relationship"
                        else _recompute_streak(selected))
                prompt_fact = _candidate_prompt_fact(selected)
                evidence_json = json.dumps(prompt_fact, ensure_ascii=False, sort_keys=True)
                event_user = (
                    f"Matchup: {target['away_team']} vs {target['home_team']}. "
                    f"Date: {_date_label(target)}.\nVerified selected-evidence summary (JSON):\n{evidence_json}")
                candidate_queue.append(_prompt_entry(
                    target, "event_only", EVENT_ONLY_SYSTEM, event_user))
                combined_user = baseline_grounding
                combined_user += "\nVerified selected-evidence summary (JSON):\n" + evidence_json
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
                input_audit = _audit_reconstructed_input(baseline_fields, league)
                selected_audit = (selected.get("independent_recomputation") if selected else None)
                target_audit = {
                    "target_game_id": target["target_game_id"], "league": league,
                    "input_evidence": input_audit,
                    "selected_candidate": selected_audit,
                    "status": "pass" if input_audit["status"] == "pass" and
                    (selected_audit is None or selected_audit.get("status") == "pass") else "fail",
                }
                statistic_audits.append(target_audit)
                blind_target_id = f"target-{len(pairs) + 1:03d}"
                example = {
                    "target_game_id": target["target_game_id"], "league": league,
                    "matchup": {"away": target["away_team"], "home": target["home_team"]},
                    "kickoff_date": target["kickoff_date"],
                    "kickoff_time_basis": target["kickoff_time_basis"],
                    "kickoff_utc": target["start_utc"],
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
                    "independent_evidence_audit": target_audit,
                    "independent_human_rating": "pending",
                }
                examples.append(example)
                pairs.append({
                    "target_game_id": target["target_game_id"], "league": league,
                    "matchup": example["matchup"], "as_of": as_of,
                    "kickoff_date": target["kickoff_date"],
                    "blind_target_id": blind_target_id,
                    "baseline_preview": None,
                    "event_only_preview": preview["event_only_preview"],
                    "combined_preview": preview["combined_preview"],
                    "event_claims": event_claims,
                    "combined_claims": combined_claims,
                    "variant_input_evidence": {
                        "core_stories_baseline": baseline_fields,
                        "event_only": selected.get("evidence", {}) if selected else {},
                        "combined": {
                            "baseline_fields": baseline_fields,
                            "selected_candidate": selected or {},
                        },
                    },
                })

    all_prompts = baseline_queue + candidate_queue
    prompt_chars = sum(len(row["system_prompt"]) + len(row["user_prompt"])
                       for row in all_prompts)
    estimated_input_tokens = math.ceil(prompt_chars / 4)
    total_calls = len(all_prompts)
    budget = {
        "model": "deepseek/deepseek-v4.1-flash (repository default)",
        "calls_for_selected_targets_three_variants": total_calls,
        "selected_target_count": len(examples),
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
    _jsonl_write(outdir / "statistic_audit.jsonl", statistic_audits)
    _jsonl_write(outdir / "rejected_facts.jsonl", rejected)
    _jsonl_write(outdir / "baseline_generation_queue.jsonl", baseline_queue)
    _jsonl_write(outdir / "candidate_generation_queue.jsonl", candidate_queue)

    selected_counts = Counter(
        row["selected_candidate"]["candidate_type"]
        for row in examples if row.get("selected_candidate"))
    claim_pass = sum(row["mechanical_verification"] == "pass" for row in claims)
    statistic_pass = sum(row["status"] == "pass" for row in statistic_audits)
    manifest = {
        "objective": "offline deterministic matchup relevance ranking",
        "database": inventory["database"], "database_mode": "mode=ro + query_only",
        "as_of": as_of, "targets": {"nfl": len(nfl_targets), "nba": len(nba_targets)},
        "target_horizon_hours": PREVIEW_HORIZON_HOURS,
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
        "independent_evidence_recomputation": {
            "targets_checked": len(statistic_audits), "targets_passed": statistic_pass,
            "targets_failed": len(statistic_audits) - statistic_pass,
        },
        "external_requests": 0, "model_inference_requests": 0,
        "human_ratings_entered": 0, "independent_human_evaluation": False,
        "inference_budget": budget, "blind_packet": blind_status,
        "limitations": [
            "NFL kickoff timestamps convert nflverse's Eastern gametime to UTC using America/New_York.",
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _espn_summary_archive_path(outdir: Path, snapshot: dict[str, Any],
                               cache_root: str | Path | None = None) -> Path:
    root = Path(cache_root or os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return (root / "legendarypicks" / "research" / outdir.parent.name / outdir.name /
            "espn_summary_snapshots" /
            f"{snapshot['target_game_id']}-{snapshot['summary_sha256']}.json")


def _archive_espn_summary_payload(outdir: Path, snapshot: dict[str, Any],
                                  cache_root: str | Path | None = None) -> Path:
    """Keep the raw prospective summary in the private external research cache."""
    payload = snapshot.get("summary_payload")
    if not isinstance(payload, dict) or _payload_sha256(payload) != snapshot.get("summary_sha256"):
        raise ResearchAuditError("cannot archive an ESPN summary with an invalid payload hash")
    path = _espn_summary_archive_path(outdir, snapshot, cache_root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists():
        if _payload_sha256(json.loads(path.read_text(encoding="utf-8"))) != snapshot["summary_sha256"]:
            raise ResearchAuditError("existing external ESPN summary archive has a hash mismatch")
        return path
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _espn_scoreboard_event(target: dict[str, Any], payload: dict[str, Any]) -> str:
    matches = []
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        sides = {}
        for competitor in competition.get("competitors") or []:
            side = competitor.get("homeAway")
            abbreviation = ((competitor.get("team") or {}).get("abbreviation") or "").strip()
            if side in ("home", "away") and abbreviation:
                sides[side] = team_codes.normalize(target["league"], abbreviation)
        start = _utc(competition.get("date") or event.get("date"))
        kickoff = _utc(target.get("start_utc"))
        if (sides == {"away": target["away_team"], "home": target["home_team"]}
                and start is not None and kickoff is not None
                and abs((start - kickoff).total_seconds()) <= 300):
            event_id = str(event.get("id") or "")
            if event_id:
                matches.append(event_id)
    if len(matches) != 1:
        raise ResearchAuditError(
            f"ESPN scoreboard has {len(matches)} exact event matches for {target['target_game_id']}")
    return matches[0]


def capture_prospective_espn_context(db_path: str, outdir: str | Path,
                                     nfl_count: int = 10, nba_count: int = 10,
                                     now_fn=None, scoreboard_fetch=None,
                                     summary_fetch=None) -> dict[str, Any]:
    """Capture each summary before kickoff, then build all local inputs at the capture cutoff."""
    from research_narrative_event_knowledge import _json_write

    outdir = Path(outdir).resolve()
    if (outdir / "run_manifest.json").exists():
        raise ResearchAuditError("prospective ESPN capture requires a new, empty research output directory")
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    started = _utc(now_fn())
    if started is None:
        raise ResearchAuditError("prospective capture clock returned an invalid timestamp")
    initial_as_of = _timestamp_text(started)
    with closing(open_readonly(db_path)) as con:
        targets = (_target_rows(con, "nfl", initial_as_of, nfl_count) +
                   _target_rows(con, "nba", initial_as_of, nba_count))
    if not targets:
        raise ResearchAuditError("no scheduled targets fall within the 48-hour capture window")
    if any(_utc(row["start_utc"]) is None or _utc(row["start_utc"]) <= started for row in targets):
        raise ResearchAuditError("prospective capture target is not strictly before kickoff")

    import espn_client as espn
    is_live_capture = scoreboard_fetch is None and summary_fetch is None
    if is_live_capture:
        # This standalone research process must perform fresh requests, not silently
        # stamp an older in-memory or disk-cache response as a new capture.
        espn.set_disk_cache("", ttl=0)
        espn._CACHE.clear()
        espn._FETCHER._memory.clear()
        scoreboard_fetch = espn.scoreboard_raw
        summary_fetch = espn.summary
    elif scoreboard_fetch is None or summary_fetch is None:
        raise ResearchAuditError("inject both ESPN fetch functions together for a test capture")

    scoreboard_rows: dict[str, dict[str, Any]] = {}
    snapshots = []
    pacing = espn.batch_pacing() if is_live_capture else nullcontext()
    with pacing:
        for day in sorted({row["kickoff_date"] for row in targets if row["league"] == "nba"}):
            scoreboard = scoreboard_fetch("nba", day)
            captured_at = _utc(now_fn())
            if captured_at is None:
                raise ResearchAuditError("ESPN scoreboard capture clock returned an invalid timestamp")
            scoreboard_rows[day] = {
                "payload": scoreboard, "captured_at": _timestamp_text(captured_at),
                "sha256": _payload_sha256(scoreboard),
            }
        for target in targets:
            if target["league"] == "nfl":
                event_id = str(target.get("espn") or "")
                mapping = {"source": "nfl_schedule.espn"}
            else:
                board = scoreboard_rows[target["kickoff_date"]]
                event_id = _espn_scoreboard_event(target, board["payload"])
                mapping = {
                    "source": "captured_espn_scoreboard",
                    "captured_at": board["captured_at"],
                    "scoreboard_sha256": board["sha256"],
                }
            if not event_id:
                raise ResearchAuditError(f"no ESPN event id is available for {target['target_game_id']}")
            summary = summary_fetch(target["league"], event_id)
            captured_at = _utc(now_fn())
            if captured_at is None:
                raise ResearchAuditError("ESPN summary capture clock returned an invalid timestamp")
            example = {
                "target_game_id": target["target_game_id"], "league": target["league"],
                "matchup": {"away": target["away_team"], "home": target["home_team"]},
                "kickoff_utc": target["start_utc"],
            }
            snapshot = {
                "target_game_id": target["target_game_id"], "league": target["league"],
                "status": "captured", "espn_event_id": event_id,
                "kickoff_utc": target["start_utc"], "captured_at": _timestamp_text(captured_at),
                "capture_timestamp_basis": "UTC clock recorded immediately after fresh ESPN summary response",
                "summary_sha256": _payload_sha256(summary),
                "event_id_mapping": mapping, "summary_payload": summary,
            }
            _validate_context_snapshot(example, snapshot, _timestamp_text(captured_at))
            if is_live_capture:
                snapshot["source_snapshot_archive"] = str(
                    _archive_espn_summary_payload(outdir, snapshot))
            snapshots.append(snapshot)

    cutoff = max(_utc(row["captured_at"]) for row in snapshots)
    if any(_utc(row["kickoff_utc"]) <= cutoff for row in snapshots):
        raise ResearchAuditError("at least one target kickoff passed before all summaries were captured")
    final_as_of = _timestamp_text(cutoff)
    with closing(open_readonly(db_path)) as con:
        refreshed = (_target_rows(con, "nfl", final_as_of, nfl_count) +
                     _target_rows(con, "nba", final_as_of, nba_count))
    if {row["target_game_id"] for row in refreshed} != {row["target_game_id"] for row in targets}:
        raise ResearchAuditError("target set changed while ESPN summaries were being captured; retry with a fresh packet")

    manifest = build_relevance_packet(db_path, outdir, final_as_of, nfl_count, nba_count)
    examples = _read_jsonl(outdir / "examples.jsonl")
    for snapshot in snapshots:
        example = next(row for row in examples if row["target_game_id"] == snapshot["target_game_id"])
        _validate_context_snapshot(example, snapshot, final_as_of)
    _attach_espn_context_snapshots(outdir, snapshots)
    manifest_path = outdir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    capture_metadata = {
        "summary_requests": len(snapshots),
        "scoreboard_requests": len(scoreboard_rows),
        "capture_window_start": initial_as_of,
        "common_cutoff": final_as_of,
    }
    if is_live_capture:
        capture_metadata.update({
            "capture_mode": "prospective_fresh_espn_requests",
            "raw_summary_storage": "private external research cache, mode 0600",
            "summary_archive_directory": str(
                _espn_summary_archive_path(outdir, snapshots[0]).parent),
        })
    else:
        capture_metadata["capture_mode"] = "prospective_injected_test_fetches"
    manifest["espn_context_capture"].update(capture_metadata)
    _json_write(manifest_path, manifest)
    return manifest


def _normalized_draft(text: str) -> str:
    return " ".join(text.casefold().split())


def _openrouter_api_key() -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key.strip()
    for env_path in ("/root/legendarypicks/.env", "/root/.hermes/.env"):
        try:
            with open(env_path, encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("OPENROUTER_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def _openrouter_chat(system: str, user: str, max_tokens: int, model: str) -> str | None:
    key = _openrouter_api_key()
    if not key:
        raise ResearchAuditError("OPENROUTER_API_KEY is not configured")
    import urllib.error
    import urllib.request

    body = {
        "model": model, "temperature": 0.4, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    effort = os.environ.get("LP_LLM_REASONING", "none")
    if effort and effort != "default":
        body["reasoning_effort"] = effort
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "legendarypicks-research/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read())
        return (payload["choices"][0]["message"].get("content") or "").strip() or None
    except urllib.error.HTTPError as exc:
        print(f"OpenRouter research request failed with HTTP {exc.code}.", flush=True)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"OpenRouter research request failed: {type(exc).__name__}.", flush=True)
        return None


def run_three_way_comparison(outdir: str | Path, max_tokens: int = 600,
                             chat_fn=None, provider: str = "openrouter",
                             model: str | None = None) -> dict[str, Any]:
    """Generate matched baseline, event-only, and combined drafts for selected targets."""
    from research_narrative_event_knowledge import _json_write, _jsonl_write

    if provider != "openrouter":
        raise ResearchAuditError("this research run is authorized for the OpenRouter provider only")
    outdir = Path(outdir).resolve()
    examples = _read_jsonl(outdir / "examples.jsonl")
    baseline_queue = _read_jsonl(outdir / "baseline_generation_queue.jsonl")
    candidate_queue = _read_jsonl(outdir / "candidate_generation_queue.jsonl")
    if not examples:
        raise ResearchAuditError("build the cutoff-matched research packet before model generation")

    prompts: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in baseline_queue + candidate_queue:
        prompts[str(row["target_game_id"])][row["variant"]] = row
    required = {"core_stories_baseline", "event_only", "combined"}
    cutoff_values = {row.get("as_of") for row in examples}
    if len(cutoff_values) != 1:
        raise ResearchAuditError("three-way targets must share one as_of cutoff")
    as_of = next(iter(cutoff_values))
    cutoff = _utc(as_of)
    if cutoff is None:
        raise ResearchAuditError("three-way targets have an invalid as_of cutoff")
    targets_with_context_snapshot = 0
    targets_missing_context_snapshot = []
    for example in examples:
        target_id = str(example["target_game_id"])
        target_prompts = prompts.get(target_id, {})
        if set(target_prompts) != required:
            raise ResearchAuditError(f"target {target_id} does not have exactly three prompts")
        kickoff = _utc(example.get("kickoff_utc"))
        if kickoff is None:
            raise ResearchAuditError(f"target {target_id} has no exact kickoff timestamp")
        if not cutoff < kickoff <= cutoff + timedelta(hours=PREVIEW_HORIZON_HOURS):
            raise ResearchAuditError(f"target {target_id} falls outside the production preview horizon")
        if any(row.get("as_of") != as_of for row in target_prompts.values()):
            raise ResearchAuditError(f"target {target_id} prompts do not share the same cutoff")
        if target_prompts["core_stories_baseline"].get("system_prompt_sha256") != _sha(CORE_PREVIEW_SYSTEM):
            raise ResearchAuditError("baseline prompt differs from core_stories.py")
        if (target_prompts["event_only"].get("system_prompt_sha256") ==
                target_prompts["combined"].get("system_prompt_sha256") or
                target_prompts["event_only"].get("user_prompt_sha256") ==
                target_prompts["combined"].get("user_prompt_sha256")):
            raise ResearchAuditError(f"target {target_id} event-only and combined inputs are not distinct")
        snapshot = example.get("matchup_context_snapshot") or {}
        if snapshot.get("status") == "captured":
            captured_at = _utc(snapshot.get("captured_at"))
            snapshot_sha = snapshot.get("summary_sha256")
            if captured_at is None or captured_at > cutoff or cutoff >= kickoff or not snapshot_sha:
                raise ResearchAuditError(f"target {target_id} ESPN context snapshot is not cutoff-safe")
            for variant, prompt in target_prompts.items():
                if (prompt.get("matchup_context_snapshot_status") != "verified_pre_cutoff" or
                        prompt.get("matchup_context_snapshot_sha256") != snapshot_sha or
                        prompt.get("matchup_context_captured_at") != snapshot.get("captured_at") or
                        snapshot_sha not in prompt.get("user_prompt", "")):
                    raise ResearchAuditError(
                        f"target {target_id} does not supply the same ESPN snapshot to {variant}")
            targets_with_context_snapshot += 1
        elif snapshot.get("status") == "unavailable":
            targets_missing_context_snapshot.append(target_id)
            for variant, prompt in target_prompts.items():
                if (prompt.get("matchup_context_snapshot_status") != "unavailable" or
                        prompt.get("matchup_context_snapshot_sha256")):
                    raise ResearchAuditError(
                        f"target {target_id} has inconsistent unavailable ESPN context across variants")
        elif snapshot:
            raise ResearchAuditError(f"target {target_id} has an unknown ESPN snapshot status")

    if chat_fn is None:
        model = model or os.environ.get("LP_LLM_MODEL", "deepseek/deepseek-v4.1-flash")
        chat_fn = lambda system, user, limit: _openrouter_chat(system, user, limit, model)
    model = model or "injected-test-chat"

    comparison_path = outdir / "model_comparison.jsonl"
    prior_rows = _read_jsonl(comparison_path)
    prior_by_target = {str(row["target_game_id"]): row for row in prior_rows}
    results = []
    calls_made = 0
    generation_failed = False
    for example in examples:
            target_id = str(example["target_game_id"])
            target_prompts = prompts[target_id]
            old = prior_by_target.get(target_id, {})
            variants = dict(old.get("variants") or {})
            target_row = {
                "target_game_id": target_id, "league": example["league"],
                "matchup": example["matchup"], "as_of": as_of,
                "kickoff_utc": example["kickoff_utc"], "model": model,
                "provider": provider, "variants": variants,
            }
            for variant in ("core_stories_baseline", "event_only", "combined"):
                prompt = target_prompts[variant]
                cached = variants.get(variant)
                if (cached and cached.get("status") == "generated" and
                        cached.get("system_prompt_sha256") == prompt["system_prompt_sha256"] and
                        cached.get("user_prompt_sha256") == prompt["user_prompt_sha256"]):
                    continue
                calls_made += 1
                output = chat_fn(prompt["system_prompt"], prompt["user_prompt"], max_tokens)
                if not output:
                    variants[variant] = {
                        "status": "failed", "system_prompt_sha256": prompt["system_prompt_sha256"],
                        "user_prompt_sha256": prompt["user_prompt_sha256"],
                        "error": "provider returned no text",
                    }
                    target_row["variants"] = variants
                    prior_by_target[target_id] = target_row
                    generation_failed = True
                    break
                output = str(output).strip()
                variants[variant] = {
                    "status": "generated", "output": output,
                    "output_sha256": _sha(output),
                    "system_prompt_sha256": prompt["system_prompt_sha256"],
                    "user_prompt_sha256": prompt["user_prompt_sha256"],
                    "max_completion_tokens": max_tokens,
                }
                target_row["variants"] = variants
                prior_by_target[target_id] = target_row
            results = [prior_by_target[key] for key in prior_by_target]
            _jsonl_write(comparison_path, results)
            if generation_failed:
                break

    results = [prior_by_target.get(str(example["target_game_id"])) for example in examples]
    if generation_failed or any(not row or any(
            row.get("variants", {}).get(variant, {}).get("status") != "generated"
            for variant in required) for row in results):
        _jsonl_write(comparison_path, [row for row in results if row])
        return {
            "status": "incomplete", "targets": len(examples),
            "model_inference_requests": calls_made, "provider": provider, "model": model,
        }

    distinctness = []
    result_by_target = {str(row["target_game_id"]): row for row in results}
    for row in results:
        drafts = {key: _normalized_draft(value["output"])
                  for key, value in row["variants"].items()}
        unique = len(set(drafts.values()))
        distinctness.append({
            "target_game_id": row["target_game_id"], "league": row["league"],
            "unique_text_count": unique,
            "baseline_matches_event_only": drafts["core_stories_baseline"] == drafts["event_only"],
            "baseline_matches_combined": drafts["core_stories_baseline"] == drafts["combined"],
            "event_only_matches_combined": drafts["event_only"] == drafts["combined"],
        })

    for example in examples:
        generated = result_by_target[str(example["target_game_id"])]["variants"]
        example["baseline_preview"] = generated["core_stories_baseline"]["output"]
        example["event_only_model_preview"] = generated["event_only"]["output"]
        example["combined_model_preview"] = generated["combined"]["output"]
        example["baseline_status"] = "generated_with_core_stories_prompt_and_reconstructed_local_input"
    _jsonl_write(outdir / "examples.jsonl", examples)
    _jsonl_write(outdir / "model_comparison.jsonl", results)
    _jsonl_write(outdir / "three_way_distinctness.jsonl", distinctness)

    for queue in (baseline_queue, candidate_queue):
        for prompt in queue:
            variant = prompt["variant"]
            generated = result_by_target[str(prompt["target_game_id"])]["variants"][variant]
            prompt["model_call_made"] = True
            prompt["provider"] = provider
            prompt["model"] = model
            prompt["model_output_sha256"] = generated["output_sha256"]
    _jsonl_write(outdir / "baseline_generation_queue.jsonl", baseline_queue)
    _jsonl_write(outdir / "candidate_generation_queue.jsonl", candidate_queue)

    claims_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for claim in _read_jsonl(outdir / "claim_audit.jsonl"):
        claims_by_key[(str(claim["target_game_id"]), claim["variant"])].append(claim)
    pairs = []
    for index, example in enumerate(examples, 1):
        target_id = str(example["target_game_id"])
        selected = example.get("selected_candidate") or {}
        baseline_fields = example.get("baseline_fields") or {}
        pairs.append({
            "target_game_id": target_id, "league": example["league"],
            "matchup": example["matchup"], "as_of": as_of,
            "kickoff_date": example["kickoff_date"], "blind_target_id": f"target-{index:03d}",
            "baseline_preview": example["baseline_preview"],
            "event_only_preview": example["event_only_model_preview"],
            "combined_preview": example["combined_model_preview"],
            "baseline_claims": [],
            "event_claims": claims_by_key[(target_id, "event_only")],
            "combined_claims": claims_by_key[(target_id, "combined")],
            "variant_input_evidence": {
                "core_stories_baseline": {
                    "record_facts": baseline_fields.get("record_facts", []),
                    "player_form": baseline_fields.get("player_form", []),
                    "matchup_context": baseline_fields.get("matchup_context"),
                },
                "event_only": {
                    "selected_candidate_id": selected.get("candidate_id"),
                    "supporting_game_ids": selected.get("supporting_game_ids", []),
                    "supporting_event_ids": selected.get("supporting_event_ids", []),
                    "independent_recomputation": selected.get("independent_recomputation"),
                },
                "combined": {
                    "record_facts": baseline_fields.get("record_facts", []),
                    "player_form": baseline_fields.get("player_form", []),
                    "selected_candidate_id": selected.get("candidate_id"),
                    "supporting_game_ids": selected.get("supporting_game_ids", []),
                    "supporting_event_ids": selected.get("supporting_event_ids", []),
                    "independent_recomputation": selected.get("independent_recomputation"),
                },
            },
        })
    blind_status = _write_blind_packet(outdir, pairs)

    manifest_path = outdir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous_requests = int(manifest.get("model_comparison", {}).get("request_count", 0))
    total_requests = previous_requests + calls_made
    manifest["objective"] = "cutoff-matched three-way pregame narrative comparison"
    manifest["external_requests"] = total_requests
    manifest["model_inference_requests"] = total_requests
    manifest["generated_preview_counts"].update({
        "event_only_model_output": len(examples), "combined_model_output": len(examples),
        "core_stories_model_output": len(examples),
    })
    manifest["inference_budget"]["inference_requests_made"] = total_requests
    manifest["inference_budget"]["provider_used"] = provider
    manifest["inference_budget"]["model"] = model
    manifest["blind_packet"] = blind_status
    manifest["limitations"] = [
        item for item in manifest.get("limitations", [])
        if "No original-generator model output exists" not in item
        and "The generated baseline uses reconstructed local records and player form; production ESPN matchup_context was unavailable." not in item
    ]
    manifest["limitations"].append(
        "The full core_stories generator was not invoked; local records and player-form inputs remain reconstructed.")
    if targets_missing_context_snapshot and not manifest.get("espn_context_capture"):
        manifest["limitations"].append(
            "This run has no cutoff-safe ESPN matchup-context snapshots; treat it as a reduced-context comparison.")
    manifest["limitations"] = list(dict.fromkeys(manifest["limitations"]))
    manifest["limitations"].append(
        "Source-statistic audits validate supplied input rows, not the semantic accuracy of model-generated prose.")
    manifest["limitations"] = list(dict.fromkeys(manifest["limitations"]))
    context_family_counts = Counter()
    for example in examples:
        for line in (example.get("baseline_fields", {}).get("matchup_context", {})
                     .get("context_lines", [])):
            if line.startswith("Competition:"):
                family = "header.season phase"
            elif "in this tournament:" in line or line.startswith("BACKGROUND,"):
                family = "standings"
            elif " leaders:" in line:
                family = "leaders"
            elif " — last " in line and "most recent first:" in line:
                family = "lastFiveGames form"
            else:
                family = "other context note"
            context_family_counts[family] += 1

    manifest["model_comparison"] = {
        "status": "completed", "provider": provider, "model": model,
        "targets": len(examples), "variants_per_target": 3,
        "matched_targets_and_cutoff": True,
        "same_espn_snapshot_across_variants": targets_with_context_snapshot == 0 or
            targets_with_context_snapshot + len(targets_missing_context_snapshot) == len(examples),
        "targets_with_cutoff_safe_espn_context": targets_with_context_snapshot,
        "targets_without_cutoff_safe_espn_context": targets_missing_context_snapshot,
        "production_baseline_fidelity": "partial_reconstructed_local_inputs",
        "target_horizon_hours": PREVIEW_HORIZON_HOURS,
        "request_count": total_requests,
        "requests_this_invocation": calls_made,
        "event_only_combined_textually_distinct_targets": sum(
            not row["event_only_matches_combined"] for row in distinctness),
        "targets_with_three_unique_outputs": sum(row["unique_text_count"] == 3
                                                  for row in distinctness),
        "baseline_prompt_source": "backend/core_stories.py::generate_game_story",
        "baseline_context_status": (
            f"cutoff-safe ESPN context shared across {targets_with_context_snapshot} of {len(examples)} targets; "
            "local records and player-form inputs reconstructed"),
        "human_ratings_entered": 0,
        "production_input_comparison": {
            "production_generator_invoked": False,
            "system_prompt_sha256_matches_core_stories": True,
            "research_model_call": {
                "provider": provider, "model": model,
                "max_completion_tokens": max_tokens, "temperature": 0.4,
            },
            "production_model_call": {
                "dispatch": "core_stories._deepseek_chat -> _core._llm_chat",
                "provider_setting": "LP_LLM_PROVIDERS (code default: nous,openrouter)",
                "max_completion_tokens_default": 8000,
            },
            "espn_context": {
                "helper": "matchup_context.context_lines",
                "same_snapshot_and_derived_lines_shared_across_variants": True,
                "targets_with_verified_pre_cutoff_snapshots": targets_with_context_snapshot,
                "targets_without_verified_pre_cutoff_snapshots": targets_missing_context_snapshot,
                "historical_replay_external_espn_requests": 0,
                "context_line_count": sum(context_family_counts.values()),
                "observed_context_line_families": dict(sorted(context_family_counts.items())),
            },
            "input_differences": [
                "The replay rebuilds matchup, date, host, game state, and team records from cutoff-filtered local schedule rows; production generate_game_story uses its runtime game_result, schedule, and standings paths. Replay state is fixed to pre.",
                "Production calls stakes.for_matchup; the reconstructed baseline supplies no stakes lines.",
                "Production prioritizes game-specific prop-board player form, then falls back to player_form.lines. The replay derives player form directly from cutoff-filtered player_game_logs, so its player selection and wording are not guaranteed to match.",
                "Production derives matchup_context current_season from its runtime records_stale check and passes runtime state. The replay infers current_season from reconstructed record rows and supplies state=pre.",
                "The baseline uses the same system prompt hash, but this run called OpenRouter directly with a 600-token completion limit. Production uses the configured _llm_chat provider path and defaults to an 8000-token limit.",
            ],
        },
    }
    _json_write(manifest_path, manifest)
    rejected = _read_jsonl(outdir / "rejected_facts.jsonl")
    inventory = json.loads((outdir / "database_coverage.json").read_text(encoding="utf-8"))
    _write_report(outdir, manifest, examples, rejected, inventory, manifest["inference_budget"])
    return manifest["model_comparison"]


def _write_report(outdir: Path, manifest: dict[str, Any],
                  examples: list[dict[str, Any]], rejected: list[dict[str, Any]],
                  inventory: dict[str, Any], budget: dict[str, Any]) -> None:
    nfl_coverage = inventory["coverage"].get("nfl_pbp", {}).get("current_season_2026", {})
    nba_stat_coverage = inventory["coverage"].get("team_game_stats", {}).get(
        "nba_populated_rows_at_cutoff", 0)
    nba_boxes = inventory["coverage"].get("nba_player_boxes_nbacom", {})
    comparison = manifest.get("model_comparison")
    context_capture = manifest.get("espn_context_capture") or {}
    recomputation = manifest.get("independent_evidence_recomputation", {})
    target_total = sum(manifest.get("targets", {}).values())
    lines = [
        f"# Narrative relevance research — {manifest['as_of'][:10]}", "",
        f"Database: {manifest['database']} (read-only; query_only={inventory['query_only']}).",
        f"Shared cutoff: {manifest['as_of']}. Preview horizon: {PREVIEW_HORIZON_HOURS} hours.",
        f"External model requests: {manifest['model_inference_requests']}.", "",
        "## Result", "",
        f"Prepared {manifest['targets']['nfl']} NFL and {manifest['targets']['nba']} NBA targets. "
        "The three variants share each target and cutoff. NFL kickoff uses the Eastern-time "
        "schedule field converted to UTC; the nflverse schedule dictionary documents that "
        "field's timezone [here](https://nflreadr.nflverse.com/articles/dictionary_schedules.html).",
        "The production core_stories.py file was not changed.",
        "",
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
        f"Independent source-statistic audits: {recomputation.get('targets_passed', 0)} of "
        f"{recomputation.get('targets_checked', 0)} targets passed; "
        f"{recomputation.get('targets_failed', 0)} failed. See statistic_audit.jsonl.",
        f"Rejected candidates retained with reasons and evidence IDs: {len(rejected)}.",
        "- NFL EPA is stated as team efficiency across plays; no play is called game-winning.",
        "- Drive, fourth-down, lead-change, and single-play game-winner categories are quarantined.",
        "- Paired trend candidates need a same-metric offense/defense comparison, at least three "
        "recent and baseline games on both sides, both changes above threshold, recent evidence, "
        "and timestamps before the cutoff.", "",
        "## Three-way generation and review", "",
    ]
    if comparison:
        context_count = comparison.get("targets_with_cutoff_safe_espn_context", 0)
        context_total = comparison.get("targets", len(examples))
        missing_context = comparison.get("targets_without_cutoff_safe_espn_context", [])
        fidelity = comparison.get("production_input_comparison", {})
        missing_matchups = [
            f"{item['matchup']['away']} at {item['matchup']['home']} ({item['target_game_id']})"
            for item in examples if str(item["target_game_id"]) in missing_context
        ]
        if context_count:
            line_families = fidelity.get("espn_context", {}).get(
                "observed_context_line_families", {})
            line_summary = ", ".join(
                f"{family} ({count})" for family, count in line_families.items()) or "none"
            absent_fields = [field for field, family in (
                ("header.season phase", "header.season phase"), ("standings", "standings"))
                if family not in line_families]
            absent_summary = (f" The snapshots produced no {', '.join(absent_fields)} lines."
                              if absent_fields else "")
            context_note = (
                f"The existing matchup_context.context_lines() logic derived shared pregame facts "
                f"from timestamped, hashed ESPN summary snapshots for {context_count} of "
                f"{context_total} targets. The other {len(missing_context)} target(s) have no "
                f"cutoff-safe summary and remain reduced-context: {', '.join(missing_matchups)}. "
                f"For the captured summaries it emitted {line_summary} "
                f"({fidelity.get('espn_context', {}).get('context_line_count', 0)} lines total)."
                + absent_summary
            )
        else:
            context_note = (
                "No cutoff-safe ESPN matchup-context snapshot was supplied. This is a reduced-context "
                "baseline using reconstructed local records and player form, not a faithful production-input replay."
            )
        lines.extend([
            f"Generated {comparison['variants_per_target']} drafts for each of "
            f"{comparison['targets']} targets with {comparison['request_count']} "
            f"{comparison['provider']} requests using {comparison['model']}.",
            "The baseline uses the exact core_stories.py system prompt. " + context_note,
            "Production input fidelity: the replay did not invoke core_stories.generate_game_story. "
            "It rebuilt game state, matchup/date/host, team records, and player form from cutoff-filtered "
            "local rows; it supplied no stakes lines. Production reads runtime game_result/schedule and "
            "standings data, calls stakes.for_matchup, and prioritizes prop-board player form before "
            "player_form.lines. The replay fixes state=pre and infers current_season from reconstructed "
            "records; production derives both through its runtime game and records_stale checks.",
            f"Model path also differs: this run called {fidelity.get('research_model_call', {}).get('provider')} "
            f"directly with a {fidelity.get('research_model_call', {}).get('max_completion_tokens')}-token "
            "completion limit; production dispatches through _core._llm_chat, whose code default is "
            "the LP_LLM_PROVIDERS chain and an 8000-token limit.",
            "The event-only "
            "and combined system and user prompts differ for every target.",
            f"Event-only and combined output text differs for "
            f"{comparison['event_only_combined_textually_distinct_targets']} of "
            f"{comparison['targets']} targets; all three outputs are textually unique for "
            f"{comparison['targets_with_three_unique_outputs']} targets.",
            f"Blind packet: {manifest['blind_packet']['blind_drafts']} drafts across "
            f"{manifest['blind_packet']['targets_with_candidate_drafts']} targets. "
            "No human ratings were entered, so the comparison does not establish a winner.",
        ])
    else:
        if context_capture:
            lines.append(
                f"Cutoff-safe ESPN summaries were captured for "
                f"{context_capture.get('targets_with_verified_pre_cutoff_snapshots', 0)} of "
                f"{target_total} targets. Their derived context is in espn_context_snapshots.jsonl "
                "and is supplied to all three variants. The local records and player-form inputs "
                "remain reconstructed."
            )
        lines.extend([
            f"Prepared {manifest['blind_packet']['blind_drafts']} deterministic candidate "
            "drafts. Model outputs have not been generated.",
        ])
    lines.extend(["", "No automatic or human judgment of generated prose is claimed. The "
                  "row-level statistic audit rechecks input metrics, not semantic use of those "
                  "facts in model text.", "", "## Target drafts", "",
                  "Full text and matched prompt hashes are in examples.jsonl and model_comparison.jsonl.", ""])
    if comparison:
        lines.extend([
            "| League | Matchup | Kickoff UTC | Core baseline | Event-only | Combined |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for item in examples:
            lines.append(
                f"| {item['league'].upper()} | {item['matchup']['away']} at {item['matchup']['home']} "
                f"| {item['kickoff_utc']} | {_report_excerpt(item.get('baseline_preview'))} "
                f"| {_report_excerpt(item.get('event_only_model_preview'))} "
                f"| {_report_excerpt(item.get('combined_model_preview'))} |")
    else:
        lines.extend([
            "| League | Matchup | Kickoff UTC | Event-only draft | Combined draft |",
            "| --- | --- | --- | --- | --- |",
        ])
        for item in examples:
            lines.append(
                f"| {item['league'].upper()} | {item['matchup']['away']} at {item['matchup']['home']} "
                f"| {item['kickoff_utc']} | {_report_excerpt(item.get('event_only_preview'))} "
                f"| {_report_excerpt(item.get('combined_preview'))} |")
    lines.extend(["## Remaining limitations", ""])
    lines.extend(f"- {limitation}" for limitation in manifest["limitations"])
    lines.extend(["", "Row-level artifacts: examples.jsonl, claim_audit.jsonl, statistic_audit.jsonl, "
                  "rejected_facts.jsonl, database_coverage.json, baseline_generation_queue.jsonl, "
                  "candidate_generation_queue.jsonl, model_comparison.jsonl, "
                  "three_way_distinctness.jsonl, espn_context_snapshots.jsonl, and the blind review files.", ""])
    (outdir / "research_report.md").write_text("\n".join(lines), encoding="utf-8")


def _report_excerpt(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "[none]").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DEV_DB))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--nfl-count", type=int, default=10)
    parser.add_argument("--nba-count", type=int, default=10)
    parser.add_argument("--capture-espn-context", action="store_true",
                        help="capture fresh pregame ESPN summaries, then build with their common capture cutoff")
    parser.add_argument("--generate-three-way", action="store_true",
                        help="call the configured OpenRouter model for matched baseline/event/combined prompts")
    parser.add_argument("--max-tokens", type=int, default=600)
    args = parser.parse_args()
    if args.capture_espn_context:
        if args.as_of is not None:
            parser.error("--capture-espn-context chooses its cutoff from the fresh pregame captures; omit --as-of")
        manifest = capture_prospective_espn_context(
            args.db, args.outdir, args.nfl_count, args.nba_count)
    else:
        manifest = build_relevance_packet(
            args.db, args.outdir, args.as_of or AS_OF, args.nfl_count, args.nba_count)
    comparison = (run_three_way_comparison(args.outdir, max_tokens=args.max_tokens)
                  if args.generate_three_way else None)
    if comparison:
        manifest = json.loads((Path(args.outdir) / "run_manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "outdir": str(Path(args.outdir).resolve()), "targets": manifest["targets"],
        "generated_preview_counts": manifest["generated_preview_counts"],
        "external_requests": manifest["external_requests"],
        "model_inference_requests": manifest["model_inference_requests"],
        "three_way_comparison": comparison,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
