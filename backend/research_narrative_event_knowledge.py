"""Run the bounded, read-only narrative-event research audit.

All database reads use SQLite mode=ro. Network mode retains allowlisted publisher
article metadata only; game statistics come from the local database. News bodies,
descriptions, and play text are discarded and never written to an artifact.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import time
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import narrative_event_knowledge as nek
import team_codes


NFL_WEEKS = (4, 5, 6, 7)
NFL_QUOTAS = {4: 13, 5: 13, 6: 12, 7: 12}
NBA_SEASON = 2027  # current schedule season used for upcoming pregame targets
NBA_EVENT_SEASON = 2026  # latest completed regular season available for the 100-game audit
NBA_REGULAR_GAMES = 50
NBA_ARTICLE_SAMPLE = 100
ARTIFACT_ROOT = (Path(__file__).resolve().parents[1] / "docs" / "research" /
                 "narrative-event-knowledge-2026-10-31")
DEFAULT_DEV_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
DISALLOWED_ARTIFACT_KEYS = {"body", "story", "text", "description", "content", "articlebody"}
# This stays closed until the full local fourth-down attempt population reconciles
# with zero unresolved or contradictory possession/series transitions.
PUBLISH_NFL_FOURTH_DOWN_FACTS = False
PLAYER_STAT_LABELS = {
    "PTS": "points", "REB": "rebounds", "AST": "assists", "STL": "steals",
    "BLK": "blocks", "TO": "turnovers", "MIN": "minutes",
    "3PM": "three-pointers", "FGM": "field goals", "FGA": "field goal attempts",
    "FTM": "free throws", "FTA": "free throw attempts",
    "PRA": "combined points, rebounds, and assists",
    "fpts_ppr": "PPR fantasy points", "targets": "targets", "carries": "carries",
}


class ResearchAuditError(RuntimeError):
    pass


def utc_now() -> str:
    return nek.iso_utc(datetime.now(timezone.utc))


def _utc_db(value: Any) -> str | None:
    if value is None:
        return None
    parsed = nek.parse_utc(value)
    if parsed:
        return nek.iso_utc(parsed)
    # SQLite datetime('now') values in this repository are UTC but omit an offset.
    try:
        naive = datetime.fromisoformat(str(value).replace(" ", "T"))
    except (TypeError, ValueError):
        return None
    if naive.tzinfo is None:
        naive = naive.replace(tzinfo=timezone.utc)
    return nek.iso_utc(naive)


def _json_write(path: Path, value: Any) -> None:
    _assert_metadata_only(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _jsonl_write(path: Path, rows: list[dict[str, Any]]) -> None:
    _assert_metadata_only(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _jsonl_read(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _network_spend_summary(path: Path) -> dict[str, Any]:
    request_counts = Counter()
    status_counts: dict[str, Counter] = defaultdict(Counter)
    if not path.is_file():
        return {"request_counts_by_host": {}, "status_counts_by_host": {}}
    for row in _jsonl_read(path):
        host = str(row.get("host") or "unknown")
        request_counts[host] += 1
        status_counts[host][str(row.get("status") or "unknown")] += 1
    return {"request_counts_by_host": dict(request_counts),
            "status_counts_by_host": {host: dict(counts)
                                      for host, counts in status_counts.items()}}


def _assert_metadata_only(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).replace("_", "").lower() in DISALLOWED_ARTIFACT_KEYS:
                raise ResearchAuditError(f"refusing article/play text field at {path}.{key}")
            _assert_metadata_only(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_metadata_only(child, f"{path}[{index}]")


def open_readonly(path: str | Path) -> sqlite3.Connection:
    db = Path(path).expanduser().resolve()
    if db.name == "picks.db":
        raise ResearchAuditError("refusing the production-named picks.db; pass the dev database explicitly")
    if not db.is_file():
        raise ResearchAuditError(f"database does not exist: {db}")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        con.close()
        raise ResearchAuditError("SQLite did not enter query-only mode")
    return con


def _backfilled_postgame_cutoff(game_date: str) -> str:
    """Conservative chronological boundary for backfilled game-derived facts.

    This is an as-of convention, not a claim about the database ingest time or an
    observed publication timestamp. It deliberately makes same-day replay ineligible.
    """
    try:
        day = datetime.strptime(str(game_date)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ResearchAuditError(f"invalid source game date: {game_date!r}") from exc
    return nek.iso_utc(datetime.combine(day + timedelta(days=1),
                                       datetime.min.time().replace(hour=12), timezone.utc))


def _player_log_available_at(game_date: Any, ingested_at: Any) -> tuple[str, str]:
    """Use near-game snapshots; use chronology for later bulk backfills.

    A player-log capture within two days of its game is a useful observed
    availability timestamp. A later bulk import says when the row was copied,
    not when the game information first became knowable, so replay uses the
    conservative postgame boundary instead.
    """
    try:
        day = datetime.strptime(str(game_date)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ResearchAuditError(f"invalid player-log game date: {game_date!r}") from exc
    captured = _utc_db(ingested_at)
    if captured:
        captured_at = nek.parse_utc(captured)
        game_day_start = datetime.combine(day, datetime.min.time(), timezone.utc)
        if captured_at and game_day_start <= captured_at <= game_day_start + timedelta(days=2):
            return captured, "player_game_logs.ingested_at_near_game_date"
    return (_backfilled_postgame_cutoff(game_date),
            "player_game_logs_game_date_plus_one_day_12_utc_conservative")


def _schedule_available_at(game_date: Any, ingested_at: Any) -> tuple[str, str]:
    """Use near-game schedule capture timestamps; treat later bulk loads as backfills."""
    try:
        day = datetime.strptime(str(game_date)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ResearchAuditError(f"invalid schedule game date: {game_date!r}") from exc
    captured = _utc_db(ingested_at)
    if captured:
        captured_at = nek.parse_utc(captured)
        game_day_start = datetime.combine(day, datetime.min.time(), timezone.utc)
        if captured_at and game_day_start <= captured_at <= game_day_start + timedelta(days=2):
            return captured, "schedule.ingested_at_near_game_date"
    return (_backfilled_postgame_cutoff(game_date),
            "schedule_game_date_plus_one_day_12_utc_conservative")


def _local_fact(*, league: str, game_id: str, event_id: str, category: str,
                team: str | None, opponent: str | None, game_date: str,
                occurred_at: str, available_at: str, evidence_ids: list[str],
                calculation: dict[str, Any], source: str,
                relevant_teams: list[str] | None = None) -> dict[str, Any]:
    fact = {
        "schema_version": nek.SCHEMA_VERSION, "league": league,
        "game_id": str(game_id), "event_id": str(event_id),
        "category": category, "source": source, "team": team,
        "source_game_date": str(game_date)[:10],
        "source_game_opponent": opponent,
        "occurred_at": occurred_at, "available_at": available_at,
        "supporting_game_ids": [str(game_id)],
        "supporting_event_ids": sorted(set(map(str, evidence_ids))),
        "calculation": calculation, "verified": True,
    }
    if relevant_teams:
        fact["relevant_teams"] = sorted({str(t).upper() for t in relevant_teams})
    return fact


def _play_id(value: Any) -> str:
    try:
        numeric = float(value)
        return str(int(numeric)) if numeric.is_integer() else str(value)
    except (TypeError, ValueError):
        return str(value)


_NFL_NEXT_SCRIMMAGE_TYPES = {"run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike"}


def _classify_nfl_fourth_down_attempt(plays: list[dict[str, Any]], index: int) -> dict[str, str]:
    """Classify a fourth-down scrimmage attempt from football state transitions, never EPA success."""
    play = plays[index]
    offense = str(play.get("posteam") or "").upper()
    defense = str(play.get("defteam") or "").upper()
    if play.get("down") != 4 or play.get("play_type") not in {"run", "pass"}:
        return {"outcome": "unresolved", "reason": "not_a_fourth_down_scrimmage_attempt"}
    if play.get("touchdown") == 1:
        return {"outcome": "converted", "reason": "touchdown"}

    result = str(play.get("series_result") or "")
    next_play = next((row for row in plays[index + 1:]
                      if row.get("play_type") in _NFL_NEXT_SCRIMMAGE_TYPES and
                      row.get("posteam")), None)
    next_team = str(next_play.get("posteam") or "").upper() if next_play else ""
    same_team_next_series = bool(
        next_play and next_team == offense and next_play.get("down") == 1 and
        (play.get("series") is None or next_play.get("series") is None or
         float(next_play["series"]) > float(play["series"]))
    )
    opponent_next = bool(next_play and next_team and next_team != offense)
    gained_line = (play.get("ydstogo") is not None and play.get("yards_gained") is not None and
                   float(play["yards_gained"]) >= float(play["ydstogo"]))
    defensive_penalty = (play.get("penalty") == 1 and
                         str(play.get("penalty_team") or "").upper() == defense)

    if result == "First down":
        if opponent_next:
            return {"outcome": "unresolved", "reason": "first_down_conflicts_with_next_possession"}
        if not same_team_next_series:
            return {"outcome": "unresolved", "reason": "first_down_conflicts_with_next_series"}
        if defensive_penalty:
            return {"outcome": "converted", "reason": "defensive_penalty"}
        return {"outcome": "converted", "reason": "series_first_down"}

    if result in {"Turnover", "Turnover on downs"}:
        if next_play and not opponent_next:
            return {"outcome": "unresolved", "reason": "turnover_result_conflicts_with_next_possession"}
        return {"outcome": "failed", "reason": "series_turnover" if result == "Turnover"
                else "turnover_on_downs"}

    if same_team_next_series:
        if defensive_penalty:
            return {"outcome": "converted", "reason": "defensive_penalty"}
        if gained_line:
            return {"outcome": "converted", "reason": "yards_to_go_and_series_transition"}
        return {"outcome": "unresolved", "reason": "series_transition_without_gain_or_penalty_evidence"}
    if opponent_next:
        return {"outcome": "failed", "reason": "opponent_next_possession"}
    if play.get("interception") == 1 or play.get("fumble_lost") == 1:
        return {"outcome": "failed", "reason": "turnover_event"}
    return {"outcome": "unresolved", "reason": "insufficient_terminal_or_sequence_evidence"}


def _audit_nfl_fourth_down(plays: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = [index for index, play in enumerate(plays)
                if play.get("down") == 4 and play.get("play_type") in {"run", "pass"}]
    classifications = [_classify_nfl_fourth_down_attempt(plays, index) for index in attempts]
    counts = Counter(row["outcome"] for row in classifications)
    reasons = Counter(row["reason"] for row in classifications)
    unresolved_reasons = Counter(row["reason"] for row in classifications
                                 if row["outcome"] == "unresolved")
    complete = bool(attempts) and counts["unresolved"] == 0
    return {
        "attempts": len(attempts), "converted": counts["converted"],
        "failed": counts["failed"], "unresolved": counts["unresolved"],
        "classification_complete": complete,
        "reconciliation_status": "sequence_reconciled" if complete else "incomplete",
        "reason_counts": dict(sorted(reasons.items())),
        "unresolved_reason_counts": dict(sorted(unresolved_reasons.items())),
        "evidence_fields": ["down", "ydstogo", "yards_gained", "series", "series_result",
                            "posteam", "play_type", "touchdown", "penalty", "penalty_team",
                            "interception", "fumble_lost"],
        "success_epa_used": False,
    }


def _derive_local_nfl_game(con: sqlite3.Connection, game: dict[str, Any]
                            ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Summarize one game from Legendary Picks' own nfl_pbp and nfl_schedule rows."""
    game_id = str(game.get("source_game_id") or game["game_id"])
    schedule = con.execute(
        """SELECT game_id,season,week,gameday,away_team,home_team,away_score,home_score,espn
           FROM nfl_schedule WHERE game_id=?""", (game_id,)).fetchone()
    if not schedule:
        return [], {"league": "nfl", "game_id": game_id, "status": "missing_local_schedule"}, ""
    rows = [dict(row) for row in con.execute(
        """SELECT play_id,posteam,defteam,drive,series,series_result,down,ydstogo,
                  yards_gained,pass_attempt,rush_attempt,success,interception,fumble_lost,
                  touchdown,two_point_attempt,play_type,penalty,penalty_team,qtr,
                  game_seconds_remaining
           FROM nfl_pbp WHERE game_id=? ORDER BY play_id""", (game_id,))]
    if not rows:
        return [], {"league": "nfl", "game_id": game_id, "status": "missing_local_pbp"}, ""

    game_date = str(schedule["gameday"] or game.get("game_date") or "")[:10]
    postgame_at = _backfilled_postgame_cutoff(game_date)
    home, away = str(schedule["home_team"]).upper(), str(schedule["away_team"]).upper()
    participants = [home, away]
    opponent = {home: away, away: home}
    plays = [{**row, "_event_id": f"{game_id}:{_play_id(row['play_id'])}"} for row in rows]

    drives: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for play in plays:
        if play.get("drive") is not None:
            drives[str(play["drive"])].append(play)
    drive_audit_counts: Counter = Counter()
    drive_sequence_conflicts = 0
    ordered_drives = sorted(drives.items(), key=lambda item: min(
        float(row["play_id"]) for row in item[1]))
    for index, (_, drive_plays) in enumerate(ordered_drives):
        scrimmage = [row for row in drive_plays
                     if row.get("play_type") in _NFL_NEXT_SCRIMMAGE_TYPES]
        terminal = scrimmage[-1] if scrimmage else None
        owner = next((str(row.get("posteam") or "").upper() for row in scrimmage
                      if row.get("posteam")), "")
        next_owner = ""
        if index + 1 < len(ordered_drives):
            next_plays = sorted(ordered_drives[index + 1][1], key=lambda row: float(row["play_id"]))
            next_owner = next((str(row.get("posteam") or "").upper() for row in next_plays
                               if row.get("play_type") in _NFL_NEXT_SCRIMMAGE_TYPES and row.get("posteam")), "")
        result = str(terminal.get("series_result") or "") if terminal else ""
        if terminal and terminal.get("touchdown") == 1 and result == "Opp touchdown":
            classification = "defensive_touchdown_candidate"
        elif terminal and terminal.get("touchdown") == 1:
            classification = "offensive_touchdown_candidate"
        elif terminal and result == "Punt" and terminal.get("play_type") == "punt" and next_owner and next_owner != owner:
            classification = "punt_candidate"
        elif terminal and result == "Turnover on downs" and next_owner and next_owner != owner:
            classification = "turnover_on_downs_candidate"
        elif terminal and result == "Turnover" and next_owner and next_owner != owner:
            classification = "turnover_candidate"
        elif terminal and result == "Field goal" and terminal.get("play_type") == "field_goal":
            classification = "field_goal_made_candidate"
        elif terminal and result == "Missed field goal" and terminal.get("play_type") == "field_goal":
            classification = "field_goal_missed_candidate"
        elif terminal and result == "End of half":
            classification = "period_end_candidate"
        elif terminal and result == "Safety":
            classification = "safety_candidate"
        else:
            classification = "unknown"
            if result in {"Punt", "Turnover", "Turnover on downs"}:
                drive_sequence_conflicts += 1
        drive_audit_counts[classification] += 1

    facts: list[dict[str, Any]] = []
    turnover_plays = [play for play in plays if play.get("interception") == 1 or
                      play.get("fumble_lost") == 1]

    fourth_down_audit = _audit_nfl_fourth_down(plays)
    if PUBLISH_NFL_FOURTH_DOWN_FACTS and fourth_down_audit["classification_complete"]:
        fourth_down_teams: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for index, play in enumerate(plays):
            if play.get("down") == 4 and play.get("play_type") in {"run", "pass"}:
                team = str(play.get("posteam") or "").upper()
                if team in participants:
                    fourth_down_teams[team].append({
                        **play, "_classification": _classify_nfl_fourth_down_attempt(plays, index)})
        for team, attempts in fourth_down_teams.items():
            facts.append(_local_fact(
                league="nfl", game_id=game_id, event_id=f"{game_id}:fourth-down:{team}",
                category="fourth_down_attempts", team=team, opponent=opponent[team],
                game_date=game_date, occurred_at=postgame_at, available_at=postgame_at,
                evidence_ids=[play["_event_id"] for play in attempts],
                calculation={"attempts": len(attempts),
                             "converted": sum(play["_classification"]["outcome"] == "converted"
                                              for play in attempts),
                             "failed": sum(play["_classification"]["outcome"] == "failed"
                                           for play in attempts),
                             "unresolved": 0,
                             "attempt_definition": "fourth_down_pass_or_rush",
                             "conversion_basis": "series_result_and_possession_transition"},
                source="repository:nfl_pbp", relevant_teams=[team]))

    snap_rows = con.execute(
        """SELECT id,player_id,team,off_snaps,off_pct,def_snaps,def_pct,st_snaps,st_pct
           FROM nfl_snap_counts WHERE season=? AND week=? AND team IN (?,?)
           ORDER BY team,player_id""",
        (schedule["season"], schedule["week"],
         away, home)).fetchall()
    for row in snap_rows:
        if row["player_id"] is None:
            continue
        off_pct = float(row["off_pct"] or 0)
        def_pct = float(row["def_pct"] or 0)
        st_pct = float(row["st_pct"] or 0)
        if max(off_pct, def_pct, st_pct) < 0.9:
            continue
        team = str(row["team"]).upper()
        player_id = str(row["player_id"])
        facts.append(_local_fact(
            league="nfl", game_id=game_id, event_id=f"{game_id}:snap:{player_id}",
            category="snap_workload", team=team, opponent=opponent[team],
            game_date=game_date, occurred_at=postgame_at, available_at=postgame_at,
            evidence_ids=[f"nfl_snap_counts:{row['id']}:player:{player_id}"],
            calculation={"player_id": player_id, "off_snaps": row["off_snaps"],
                         "off_pct": row["off_pct"], "def_snaps": row["def_snaps"],
                         "def_pct": row["def_pct"], "st_snaps": row["st_snaps"],
                         "st_pct": row["st_pct"], "high_share_threshold": 0.9,
                         "source_table_key": "season_week_team_player_id"},
            source="repository:nfl_snap_counts", relevant_teams=[team]))

    scoring_trace = []
    for play in plays:
        result = str(play.get("series_result") or "")
        if (play.get("touchdown") == 1 or play.get("two_point_attempt") == 1 or
                play.get("play_type") in {"field_goal", "extra_point"} or result == "Safety"):
            scoring_trace.append({
                "play_id": play["_event_id"], "qtr": play.get("qtr"),
                "game_seconds_remaining": play.get("game_seconds_remaining"),
                "posteam": play.get("posteam"), "defteam": play.get("defteam"),
                "play_type": play.get("play_type"), "series_result": result or None,
                "touchdown": play.get("touchdown"),
                "two_point_attempt": play.get("two_point_attempt"),
                "epa_success_flag_not_scoring_result": play.get("success"),
            })

    stats_reconciliation = {}
    espn_id = str(schedule["espn"] or "")
    if espn_id:
        stats_rows = con.execute(
            """SELECT team_abbrev,turnovers,captured_at FROM team_game_stats
               WHERE league='nfl' AND game_id=?
               ORDER BY team_abbrev,captured_at""", (espn_id,)).fetchall()
        pbp_turnovers = Counter(team_codes.normalize("nfl", str(play["posteam"]))
                                for play in turnover_plays if play.get("posteam"))
        for row in stats_rows:
            team = str(row["team_abbrev"] or "").upper()
            if team:
                canonical_team = team_codes.normalize("nfl", team)
                stats_reconciliation[canonical_team] = {
                    "pbp_giveaways": pbp_turnovers[canonical_team], "team_game_stats_turnovers": row["turnovers"],
                    "captured_at": row["captured_at"],
                    "matches": (int(row["turnovers"]) == pbp_turnovers[team]
                                if row["turnovers"] is not None else None),
                }
    team_results = {}
    if espn_id:
        for row in con.execute(
                """SELECT team,score_for,score_against FROM team_game_results
                   WHERE league='nfl' AND game_id=?""", (espn_id,)):
            team_results[str(row["team"]).upper()] = (row["score_for"], row["score_against"])
    team_results_match = (len(team_results) == 2 and
                          team_results.get(home) == (schedule["home_score"], schedule["away_score"]) and
                          team_results.get(away) == (schedule["away_score"], schedule["home_score"]))
    canonical_participants = {team_codes.normalize("nfl", team) for team in participants}
    turnover_snapshot_matches = (len(stats_reconciliation) == 2 and
                                 set(stats_reconciliation) == canonical_participants and
                                 all(item.get("matches") is True
                                     for item in stats_reconciliation.values()))
    turnover_available_at = max(
        [postgame_at, *(value for item in stats_reconciliation.values()
                        for value in [_utc_db(item.get("captured_at"))] if value)])
    turnover_facts_emitted = False
    if turnover_plays and turnover_snapshot_matches:
        by_offense = Counter(str(play["posteam"]).upper() for play in turnover_plays
                             if play.get("posteam"))
        facts.append(_local_fact(
            league="nfl", game_id=game_id, event_id=f"{game_id}:turnovers",
            category="turnover_events", team=None, opponent=None, game_date=game_date,
            occurred_at=postgame_at, available_at=turnover_available_at,
            evidence_ids=[play["_event_id"] for play in turnover_plays],
            calculation={"total_giveaways": len(turnover_plays), "giveaways_by_team": dict(sorted(by_offense.items())),
                         "interceptions": sum(play.get("interception") == 1 for play in turnover_plays),
                         "lost_fumbles": sum(play.get("fumble_lost") == 1 for play in turnover_plays),
                         "game_teams": participants,
                         "independent_team_box_reconciliation": "matched",
                         "source_fields": ["interception", "fumble_lost"]},
            source="repository:nfl_pbp+team_game_stats", relevant_teams=participants))
        turnover_facts_emitted = True
    audit = {
        "league": "nfl", "game_id": game_id, "status": "local_pbp_processed",
        "source": "nfl_pbp", "play_count": len(plays), "drive_count": len(drives),
        "candidate_drive_terminal_count": sum(drive_audit_counts.values()),
        "turnover_count": len(turnover_plays),
        "turnover_reconciliation": stats_reconciliation or {"status": "no_matching_team_game_stats_snapshot"},
        "turnover_snapshot_matches": turnover_snapshot_matches,
        "turnover_narrative_fact_emitted": turnover_facts_emitted,
        "fourth_down_audit": fourth_down_audit,
        "scoring_reconciliation": {
            "status": "incomplete_missing_scoring_result_fields",
            "scheduled_home_score": schedule["home_score"],
            "scheduled_away_score": schedule["away_score"],
            "scoring_trace": scoring_trace,
            "missing_local_fields": ["field_goal_result", "extra_point_result",
                                     "two_point_conv_result", "posteam_score_post",
                                     "defteam_score_post"],
            "success_field_used_as_scoring_result": False,
            "narrative_facts_emitted": 0,
        },
        "drive_outcome_audit": {
            "drive_count": sum(drive_audit_counts.values()),
            "candidate_terminal_counts": dict(sorted(drive_audit_counts.items())),
            "sequence_transition_conflicts": drive_sequence_conflicts,
            "independently_reconciled_count": 0,
            "narrative_facts_emitted": 0,
            "status": "unverified_quarantined",
            "reason": "nfl_pbp.series_result is a series label and the database has no general drive reconstruction table or per-play score snapshots",
        },
        "team_game_results_reconciliation": {
            "status": ("matched" if team_results_match else
                       "unavailable" if len(team_results) != 2 else "mismatch"),
            "team_rows": len(team_results),
            "matches_schedule": team_results_match if team_results else None,
            "source_ingested_at_used_for_availability": False,
        },
        "availability_basis": "backfilled_game_date_plus_one_day_12_utc_conservative",
        "available_at_is_ingestion_time": False,
    }
    return facts, audit, postgame_at


def _derive_local_nba_game(con: sqlite3.Connection, game: dict[str, Any]
                            ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Use local captured team box-score fields; never substitute publisher timelines."""
    source_game_id = str(game.get("source_game_id") or game.get("game_id") or "")
    event_id = str(game.get("espn_event_id") or "")
    try:
        home, away = _nba_code(str(game["home"])), _nba_code(str(game["away"]))
    except (KeyError, ValueError, TypeError):
        home = _nba_code(str(game.get("home_team") or ""))
        away = _nba_code(str(game.get("away_team") or ""))
    game_date = str(game.get("game_date") or "")[:10]
    occurred_at = _backfilled_postgame_cutoff(game_date)
    stats = con.execute(
        """SELECT game_id,captured_at,team_abbrev,turnovers,rebounds,assists,steals,blocks,
                  fouls,fg_pct,tp_pct,ft_pct,largest_lead,lead_changes
           FROM team_game_stats WHERE league='nba' AND game_id=? ORDER BY team_abbrev""",
        (event_id,)).fetchall()
    opponent = {home: away, away: home}
    facts = []
    for row in stats:
        if not row["team_abbrev"]:
            continue
        team = _nba_code(str(row["team_abbrev"]))
        captured_at = _utc_db(row["captured_at"])
        if team not in opponent or not captured_at:
            continue
        calculation = {key: row[key] for key in
                       ("turnovers", "rebounds", "assists", "steals", "blocks", "fouls",
                        "fg_pct", "tp_pct", "ft_pct", "largest_lead", "lead_changes")
                       if row[key] is not None}
        if not calculation:
            continue
        fact = _local_fact(
            league="nba", game_id=source_game_id,
            event_id=f"{source_game_id}:team-box:{team}", category="team_box_summary",
            team=team, opponent=opponent[team], game_date=game_date,
            occurred_at=occurred_at, available_at=captured_at,
            evidence_ids=[f"{event_id}:team-box:{team}:{key}" for key in sorted(calculation)],
            calculation={**calculation, "snapshot_captured_at": captured_at,
                         "source_fields": sorted(calculation)},
            source="repository:team_game_stats", relevant_teams=[team])
        facts.append(fact)
    scoring_rows = con.execute(
        """SELECT COUNT(*) rows,COUNT(DISTINCT play_id) plays,MIN(captured_at) first_capture,
                  MAX(captured_at) last_capture FROM scoring_plays
           WHERE league='nba' AND game_id=?""", (event_id,)).fetchone()
    audit = {
        "league": "nba", "game_id": source_game_id, "espn_event_id": event_id,
        "status": "local_team_box_only" if stats else "missing_local_team_game_stats",
        "source": "team_game_stats", "team_box_rows": len(stats),
        "team_box_fields_present": sorted({key for fact in facts for key in fact["calculation"]
                                           if key not in {"snapshot_captured_at", "source_fields"}}),
        "play_by_play_rows": int(scoring_rows["rows"] or 0),
        "play_by_play_game_coverage": "scoring_plays_partial" if scoring_rows["rows"] else "none",
        "scoring_play_capture_window": [scoring_rows["first_capture"], scoring_rows["last_capture"]],
        "availability_basis": "team_game_stats.captured_at",
        "available_at_is_ingestion_time": False,
    }
    return facts, audit, occurred_at


def load_local_narrative_events(con: sqlite3.Connection, games: list[dict[str, Any]]) -> dict[str, Any]:
    """Load event facts from local LP tables only; this function performs no HTTP calls."""
    facts: list[dict[str, Any]] = []
    audits = []
    postgame_by_game = {}
    for game in games:
        if game.get("league") == "nfl":
            derived, audit, postgame_at = _derive_local_nfl_game(con, game)
        elif game.get("league") == "nba":
            derived, audit, postgame_at = _derive_local_nba_game(con, game)
        else:
            continue
        facts.extend(derived)
        audits.append(audit)
        if postgame_at:
            postgame_by_game[str(game.get("espn_event_id") or game.get("source_game_id") or
                                 game.get("game_id"))] = postgame_at
    return {"facts": facts, "rows": audits, "postgame_at": postgame_by_game,
            "source": "legendarypicks_dev_database"}


def _nba_play_by_play_tables(table_names: list[str]) -> list[str]:
    return [name for name in table_names
            if re.search(r"(^|_)(pbp|play|plays|play_by_play)(_|$)", name.lower())]


def local_database_coverage(con: sqlite3.Connection) -> dict[str, Any]:
    """Inventory local event-source coverage and missing play-level fields."""
    def one(sql: str, params: tuple = ()) -> dict[str, Any]:
        row = con.execute(sql, params).fetchone()
        return dict(row) if isinstance(row, sqlite3.Row) else dict(zip(
            [column[0] for column in con.execute(sql, params).description], row))

    nfl_pbp_fields = [row[1] for row in con.execute("PRAGMA table_info(nfl_pbp)")]
    drive_tables = [row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND lower(name) LIKE '%drive%' ORDER BY name")]
    nba_event_tables = [row[0] for row in con.execute(
        """SELECT name FROM sqlite_master WHERE type='table'
           AND (lower(name) LIKE '%nba%' OR lower(name) LIKE '%basketball%') ORDER BY name""")]
    nba_play_tables = _nba_play_by_play_tables(nba_event_tables)
    return {
        "database_mode": "read_only_query_only",
        "nfl": {
            "nfl_pbp": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                MIN(game_date) AS first_game_date,MAX(game_date) AS last_game_date,
                SUM(drive IS NOT NULL) AS rows_with_drive,SUM(down IS NOT NULL) AS rows_with_down,
                SUM(series_result IS NOT NULL) AS rows_with_series_result,
                SUM(success IS NOT NULL) AS rows_with_success,
                SUM(interception=1) AS interceptions,SUM(fumble_lost=1) AS lost_fumbles,
                SUM(down=4) AS fourth_down_rows,SUM(touchdown=1) AS touchdown_rows
                FROM nfl_pbp"""),
            "nfl_pbp_fields": nfl_pbp_fields,
            "nfl_pbp_missing_event_fields": [field for field in (
                "field_goal_result", "extra_point_result", "two_point_conv_result",
                "posteam_score_post", "defteam_score_post", "fixed_drive_result",
            ) if field not in nfl_pbp_fields],
            "drive_reconstruction_tables": drive_tables,
            "per_play_capture_timestamp": "missing",
            "score_snapshot_fields": "missing",
            "schedule": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                SUM(away_score IS NOT NULL AND home_score IS NOT NULL) AS completed_games,
                MIN(gameday) AS first_game_date,MAX(gameday) AS last_game_date
                FROM nfl_schedule"""),
            "team_game_results": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                MIN(game_date) AS first_game_date,MAX(game_date) AS last_game_date,
                MIN(ingested_at) AS min_ingested_at,MAX(ingested_at) AS max_ingested_at
                FROM team_game_results WHERE league='nfl'"""),
            "player_game_logs": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                SUM(player_id IS NOT NULL) AS rows_with_player_id,
                SUM(team IS NOT NULL) AS rows_with_team,
                SUM(stats IS NOT NULL AND stats!='{}') AS rows_with_stats_json,
                MIN(game_date) AS first_game_date,MAX(game_date) AS last_game_date,
                MIN(ingested_at) AS min_ingested_at,MAX(ingested_at) AS max_ingested_at
                FROM player_game_logs WHERE league='nfl'"""),
            "nfl_snap_counts": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT player_id) AS players,
                MIN(season) AS first_season,MAX(season) AS last_season,
                COUNT(DISTINCT season||':'||week||':'||team) AS team_weeks,
                SUM(player_id IS NOT NULL) AS rows_with_player_id
                FROM nfl_snap_counts"""),
            "team_game_stats": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                SUM(captured_at IS NOT NULL) AS rows_with_capture_time,
                MIN(captured_at) AS first_capture,MAX(captured_at) AS last_capture
                FROM team_game_stats WHERE league='nfl'"""),
        },
        "nba": {
            "nba_sportsdataverse_games": one("""SELECT COUNT(*) AS rows,
                COUNT(DISTINCT source_game_id) AS games,
                SUM(home_score IS NOT NULL AND away_score IS NOT NULL) AS completed_games,
                MIN(game_date) AS first_game_date,MAX(game_date) AS last_game_date,
                MIN(ingested_at) AS min_ingested_at,MAX(ingested_at) AS max_ingested_at
                FROM nba_sportsdataverse_games"""),
            "nba_schedule": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                SUM(away_score IS NOT NULL AND home_score IS NOT NULL) AS scored_games,
                MIN(game_date) AS first_game_date,MAX(game_date) AS last_game_date
                FROM nba_schedule"""),
            "team_game_stats": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                SUM(captured_at IS NOT NULL) AS rows_with_capture_time,
                SUM(turnovers IS NOT NULL) AS rows_with_turnovers,
                SUM(rebounds IS NOT NULL) AS rows_with_rebounds,
                SUM(assists IS NOT NULL) AS rows_with_assists,
                SUM(steals IS NOT NULL) AS rows_with_steals,
                SUM(blocks IS NOT NULL) AS rows_with_blocks,
                SUM(fouls IS NOT NULL) AS rows_with_fouls,
                SUM(fg_pct IS NOT NULL) AS rows_with_fg_pct,
                SUM(tp_pct IS NOT NULL) AS rows_with_tp_pct,
                SUM(ft_pct IS NOT NULL) AS rows_with_ft_pct,
                SUM(largest_lead IS NOT NULL) AS rows_with_largest_lead,
                SUM(lead_changes IS NOT NULL) AS rows_with_lead_changes,
                MIN(captured_at) AS first_capture,MAX(captured_at) AS last_capture
                FROM team_game_stats WHERE league='nba'"""),
            "player_game_logs": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                SUM(player_id IS NOT NULL) AS rows_with_player_id,
                SUM(team IS NOT NULL) AS rows_with_team,
                SUM(stats IS NOT NULL AND stats!='{}') AS rows_with_stats_json,
                MIN(game_date) AS first_game_date,MAX(game_date) AS last_game_date,
                MIN(ingested_at) AS min_ingested_at,MAX(ingested_at) AS max_ingested_at
                FROM player_game_logs WHERE league='nba'"""),
            "scoring_plays": one("""SELECT COUNT(*) AS rows,COUNT(DISTINCT game_id) AS games,
                SUM(captured_at IS NOT NULL) AS rows_with_capture_time,
                MIN(captured_at) AS first_capture,MAX(captured_at) AS last_capture,
                MIN(period) AS first_period,MAX(period) AS last_period
                FROM scoring_plays WHERE league='nba'"""),
            "play_by_play_named_tables": nba_play_tables,
            "complete_play_by_play_tables_confirmed": [],
            "complete_play_by_play_status": "not_stored_locally; scoring_plays contains scoring events only",
            "scoring_plays_missing_fields": ["non_scoring possessions", "defensive events",
                                             "rebounds/turnovers between scores", "complete event sequence"],
        },
    }


def _spread_pick(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count >= len(rows):
        return rows[:]
    if count <= 0 or not rows:
        return []
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[i] for i in indices]


def _nba_code(value: str) -> str:
    return team_codes.normalize("nba", value)


def build_samples(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (50 NFL PBP sample, 50 NBA PBP + 100 NBA article sample)."""
    nfl_rows = [dict(row) for row in con.execute(
        """SELECT s.game_id AS source_game_id, CAST(s.espn AS TEXT) AS espn_event_id,
                  s.season, s.week, s.gameday AS game_date, s.away_team, s.home_team,
                  s.away_score, s.home_score
           FROM nfl_schedule s
           WHERE s.season=2026 AND s.game_type='REG' AND s.week BETWEEN 4 AND 7
             AND s.away_score IS NOT NULL AND s.home_score IS NOT NULL
             AND EXISTS (SELECT 1 FROM nfl_pbp p WHERE p.game_id=s.game_id)
           ORDER BY s.week, s.gameday, s.game_id""")]
    nfl_sample = []
    for week, quota in NFL_QUOTAS.items():
        selected = _spread_pick([r for r in nfl_rows if int(r["week"]) == week], quota)
        if len(selected) != quota:
            raise ResearchAuditError(f"NFL week {week}: expected {quota} PBP games, found {len(selected)}")
        nfl_sample.extend(selected)
    if len(nfl_sample) != 50:
        raise ResearchAuditError("NFL local schedule/PBP sample does not contain 50 games")
    for row in nfl_sample:
        row.update({"league": "nfl", "sample_role": "four_week_event_sample",
                    "season_phase": "regular", "game_page_id": row["espn_event_id"]})

    nba_population = [dict(row) for row in con.execute(
        """SELECT source_game_id,season,source_season AS season_year,espn_event_id,
                  game_date,home,away,home_score,away_score,game_type
           FROM nba_sportsdataverse_games
           WHERE source_season=? AND game_type='REG'
             AND home_score IS NOT NULL AND away_score IS NOT NULL
           ORDER BY game_date,source_game_id""", (NBA_EVENT_SEASON,))]
    if len(nba_population) < NBA_ARTICLE_SAMPLE:
        raise ResearchAuditError(
            f"NBA completed regular-season population has {len(nba_population)} games; need 100")
    nba_meta = []
    for row in _spread_pick(nba_population, NBA_ARTICLE_SAMPLE):
        event_id = str(row.get("espn_event_id") or "")
        row.update({"league": "nba", "game_id": event_id or str(row["source_game_id"]),
                    "source_game_id": str(row["source_game_id"]),
                    "game_page_id": str(row["source_game_id"]),
                    "espn_event_id": event_id or None,
                    "home_team": _nba_code(row["home"]), "away_team": _nba_code(row["away"]),
                    "start_utc": None, "season": NBA_EVENT_SEASON,
                    "season_phase": "regular", "sample_role": "article_coverage_sample"})
        nba_meta.append(row)
    nba_pbp_sample = [dict(row) for row in _spread_pick(nba_meta, NBA_REGULAR_GAMES)]
    for row in nba_pbp_sample:
        row["sample_role"] = "event_sample"
    if len(nba_meta) != NBA_ARTICLE_SAMPLE:
        raise ResearchAuditError(
            f"NBA article sample produced {len(nba_meta)} games; expected {NBA_ARTICLE_SAMPLE}")
    return nfl_sample, (nba_pbp_sample, nba_meta)


def _clean_metadata(value: Any, max_chars: int = 500) -> str | None:
    if isinstance(value, dict):
        for key in ("displayName", "name", "text", "title", "value"):
            if value.get(key) is not None:
                return _clean_metadata(value[key], max_chars)
        return None
    if isinstance(value, list):
        items = [_clean_metadata(item, max_chars) for item in value]
        return ", ".join(item for item in items if item)[:max_chars] or None
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:max_chars] or None


def _origin_class(publisher: str | None, byline: str | None, credit: str | None) -> str:
    signal = " ".join(str(v or "") for v in (publisher, byline, credit)).lower()
    if "data skrive" in signal or "sportradar" in signal or "automated" in signal:
        return "computer_assisted_disclosed"
    if re.search(r"\b(ap|associated press)\b", signal):
        return "ap_origin"
    return "unknown_origin"


_HEADLINE_THEMES = {
    "comeback": re.compile(r"\b(comeback|came back|rall(?:y|ied)|erase[sd]? .*deficit|trailed)\b", re.I),
    "clutch_execution": re.compile(r"\b(last.second|game.winning|walk.off|buzzer.beater|late.winner)\b", re.I),
    "fourth_down_strategy": re.compile(r"\b(fourth.down|4th.down|go.for.it)\b", re.I),
    "turnovers": re.compile(r"\b(turnover|interception|fumble|takeaway)s?\b", re.I),
    "defense": re.compile(r"\b(defen[cs]e|defensive|sack|shutout|pressure)\b", re.I),
    "player_outlier": re.compile(r"\b(record|career.high|scores? \d+|scores? .*points|three touchdowns)\b", re.I),
    "scoring_run": re.compile(r"\b(consecutive points|scoring run|points in a row|straight possessions)\b", re.I),
    "injury": re.compile(r"\b(injur(?:y|ed)|hurt|questionable|out for)\b", re.I),
}
_THEME_EVENT_CATEGORIES = {
    "comeback": {"comeback"},
    "clutch_execution": {"final_lead_change", "clutch_events", "late_scoring_drive"},
    "fourth_down_strategy": {"fourth_down_attempts"},
    "turnovers": {"turnover_events"},
    # A generic late-game event may be an offensive score. Require an explicit
    # defensive result before treating it as evidence for a defensive headline.
    "defense": {"defensive_stop", "defensive_takeaway"},
    "player_outlier": {"player_outlier"},
    "scoring_run": {"scoring_run"},
    "injury": set(),
}


def headline_theme_candidates(headline: str | None) -> list[str]:
    if not headline:
        return []
    return sorted(theme for theme, pattern in _HEADLINE_THEMES.items() if pattern.search(headline))


def _duplicate_key(row: dict[str, Any]) -> str | None:
    title = re.sub(r"[^a-z0-9]+", " ", str(row.get("headline") or "").lower()).strip()
    published = str(row.get("published_at") or "")[:10]
    if not title or not published:
        return None
    return f"{published}:{title}"


def _safe_url(url: Any) -> str | None:
    if not url:
        return None
    parts = urlsplit(str(url))
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


def _article_metadata(*, league: str, game_id: str, game_date: str,
                      game_end: str | None, home_team: str, away_team: str,
                      publisher: str, headline: str | None, byline: str | None,
                      credit: str | None, published_at: str | None, url: str | None,
                      article_type: str | None, status: str,
                      sample_role: str, season_phase: str,
                      coverage_scope: str = "single_game") -> dict[str, Any]:
    pub = publisher or "unknown"
    clean_url = _safe_url(url)
    published = _utc_db(published_at) if published_at else None
    final_whistle = nek.parse_utc(game_end)
    published_dt = nek.parse_utc(published)
    delay = int((published_dt - final_whistle).total_seconds()) if final_whistle and published_dt else None
    return {
        "league": league,
        "game_id": str(game_id),
        "game_date": str(game_date),
        "home_team": home_team,
        "away_team": away_team,
        "publisher": pub,
        "headline": _clean_metadata(headline),
        "byline": _clean_metadata(byline, 250),
        "source_credit": _clean_metadata(credit, 250),
        "published_at": published,
        "url": clean_url,
        "article_type": _clean_metadata(article_type, 120),
        "origin_class": _origin_class(pub, byline, credit),
        "headline_theme_candidates": headline_theme_candidates(headline),
        "publication_delay_seconds_from_final_whistle": delay,
        "status": status,
        "coverage_scope": coverage_scope,
        "sample_role": sample_role,
        "season_phase": season_phase,
        "duplicate_key": _duplicate_key({"headline": headline, "published_at": published}),
    }


class _MetaHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            value = attrs.get("content")
            if key and value and key in {"og:title", "article:published_time", "datepublished"}:
                self.meta[key] = value[:500]
        if tag == "link" and (attrs.get("rel") or "").lower() == "canonical":
            self.canonical = attrs.get("href")


def nba_com_game_metadata(page_html: str, game: dict[str, Any]) -> dict[str, Any]:
    """Parse only story header metadata from NBA.com's embedded game JSON."""
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page_html, re.S | re.I)
    pageprops: dict[str, Any] = {}
    if match:
        try:
            payload = json.loads(match.group(1))
            pageprops = (((payload.get("props") or {}).get("pageProps")) or {})
        except (json.JSONDecodeError, AttributeError, TypeError):
            pageprops = {}
    story = pageprops.get("story") or {}
    header = story.get("header") or {}
    game_info = pageprops.get("game") or {}
    recap = game_info.get("gameRecap") or pageprops.get("gameRecap") or {}
    headline = _clean_metadata(header.get("headline") or recap.get("title"))
    byline = _clean_metadata(story.get("byline"), 250)
    credit = _clean_metadata(story.get("bytitle") or story.get("source"), 250)
    published = _clean_metadata(story.get("date"), 100)
    article_type = _clean_metadata(story.get("storyType") or recap.get("slug"), 120)
    url = recap.get("permalink") or f"https://www.nba.com/game/{game['game_page_id']}"
    state = "found" if headline else "no_story_metadata"
    result = _article_metadata(
        league="nba", game_id=str(game.get("espn_event_id") or game["game_page_id"]),
        game_date=game["game_date"],
        game_end=None, home_team=game["home_team"], away_team=game["away_team"],
        publisher="nba.com", headline=headline, byline=byline, credit=credit,
        published_at=published, url=url, article_type=article_type, status=state,
        sample_role=game["sample_role"], season_phase=game["season_phase"])
    result["publisher_game_id"] = str(game["game_page_id"])
    result["espn_event_id"] = game.get("espn_event_id")
    result["source_discovery"] = "nba.com_game_summary"
    return result


def espn_summary_metadata(payload: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Read allowlisted fields from the summary's article object; discard its story field."""
    article = payload.get("article") or {}
    if isinstance(article, list):
        article = article[0] if article else {}
    links = article.get("links") or {}
    if isinstance(links, dict):
        web = links.get("web") or {}
        url = web.get("href") if isinstance(web, dict) else None
    else:
        url = None
    result = _article_metadata(
        league="nfl", game_id=str(game["espn_event_id"]), game_date=game["game_date"],
        game_end=None, home_team=game["home_team"], away_team=game["away_team"],
        publisher=_clean_metadata(article.get("source"), 120) or "espn",
        headline=article.get("headline"), byline=article.get("byline"),
        credit=article.get("source"), published_at=article.get("published"), url=url,
        article_type=article.get("type"), status="found" if article.get("headline") else "no_article",
        sample_role=game["sample_role"], season_phase=game["season_phase"])
    result["source_discovery"] = "espn_nfl_summary"
    return result


def normalize_summary_timeline(payload: dict[str, Any], game: dict[str, Any],
                               captured_at: str) -> tuple[list[dict[str, Any]], str, str]:
    """Keep score/time/event IDs from ESPN summaries and discard narrative text."""
    league = str(game["league"]).lower()
    if league == "nba":
        raw_items = payload.get("plays") or []
        scope = "full_play_by_play"
    elif league == "nfl":
        raw_items = payload.get("scoringPlays") or []
        scope = "scoring_plays_only"
    else:
        raise ResearchAuditError(f"unsupported ESPN summary timeline league: {league}")
    if not raw_items:
        raise nek.NarrativeDataError(f"ESPN summary has no {scope} rows")

    competitions = (((payload.get("header") or {}).get("competitions")) or [])
    kickoff = nek.parse_utc((competitions[0].get("date") if competitions else None)
                            or game.get("start_utc"))
    if kickoff is None:
        raise nek.NarrativeDataError("ESPN summary lacks a timezone-aware scheduled start")
    source_time_basis = "scheduled_kickoff_plus_game_clock_estimate"

    def field(value: Any, *keys: str) -> Any:
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return value
        return value

    normalized_input = []
    for item in raw_items:
        period_value = field(item.get("period"), "number")
        clock_value = field(item.get("clock"), "displayValue")
        if clock_value is None:
            clock_value = field(item.get("clock"), "value")
        period = nek._optional_int(period_value, "period")
        clock_seconds = nek._clock_seconds(clock_value)
        if not period or clock_seconds is None:
            continue
        if league == "nfl":
            period_length, overtime_length, regulation_periods = 900, 600, 4
        else:
            period_length, overtime_length, regulation_periods = 720, 300, 4
        if period <= regulation_periods:
            elapsed = (period - 1) * period_length + (period_length - clock_seconds)
        else:
            elapsed = (regulation_periods * period_length +
                       (period - regulation_periods - 1) * overtime_length +
                       (overtime_length - clock_seconds))
        # ESPN wallclock timestamps can disagree with the authoritative game-clock order.
        # Use a monotonic scheduled-start + period-clock estimate for both leagues.
        wallclock = nek.iso_utc(kickoff + timedelta(seconds=elapsed))
        team = item.get("team") or {}
        if isinstance(team, dict):
            team = {"abbreviation": team.get("abbreviation") or team.get("displayName")}
        type_value = item.get("type") or {}
        type_label = field(type_value, "text")
        drive = item.get("drive") or {}
        drive_id = field(drive, "id")
        normalized_input.append({
            "id": item.get("id"), "period": {"number": period},
            "clock": {"displayValue": clock_value}, "wallclock": wallclock,
            "homeScore": item.get("homeScore"), "awayScore": item.get("awayScore"),
            "team": team, "type": {"text": type_label},
            "scoringPlay": bool(item.get("scoringPlay", league == "nfl")),
            "scoreValue": item.get("scoreValue"), "drive": {"id": drive_id} if drive_id else {},
            "start": item.get("start"), "isTurnover": bool(item.get("isTurnover")),
            "participants": [{"athlete": {"id": p.get("athlete", {}).get("id")}}
                             for p in item.get("participants") or []
                             if isinstance(p, dict) and isinstance(p.get("athlete"), dict)],
        })
    plays = nek.normalize_espn_plays(normalized_input, league=league,
                                    game_id=str(game["espn_event_id"]),
                                    captured_at=captured_at)
    if league == "nba":
        for play in plays:
            if play.get("team"):
                try:
                    play["team"] = _nba_code(play["team"])
                except ValueError:
                    play["team"] = None
    return plays, scope, source_time_basis


def nfl_week_metadata(page_html: str, week: int) -> dict[str, Any]:
    parser = _MetaHTML()
    parser.feed(page_html)
    return {
        "league": "nfl", "week": int(week), "publisher": "nfl.com",
        "source_discovery": "nfl.com_what_we_learned",
        "headline": parser.meta.get("og:title"),
        "published_at": _utc_db(parser.meta.get("article:published_time") or
                                 parser.meta.get("datepublished")),
        "url": _safe_url(parser.canonical) or
               f"https://www.nfl.com/news/2026-nfl-season-week-{week}-what-we-learned-from-sunday-s-games",
        "status": "found" if parser.meta.get("og:title") else "page_metadata_missing",
        "coverage_scope": "weekly_rollup",
        "article_body_retained": False,
    }


def _fetcher(paced_http, *, min_interval: float, budget: int, user_agent: str | None = None):
    headers = {"User-Agent": user_agent} if user_agent else None
    return paced_http.Fetcher(min_interval=min_interval, retry_waits=(), headers=headers,
                              timeout=30, cache_dir="", cache_ttl=0,
                              host_budget=budget, on_exhausted="sleep")


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "code", None)


def collect_nfl_espn_articles(games: list[dict[str, Any]], *,
                              include_scoreboards: bool = True) -> dict[str, Any]:
    import paced_http
    fetch = _fetcher(paced_http, min_interval=3.0, budget=52,
                     user_agent="curl/8.5.0")
    rows = []
    calls = 0
    refused = False
    start_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    nba_end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y%m%d")
    nfl_end = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y%m%d")
    scoreboards = {"nba": [], "nfl": []}
    if include_scoreboards:
        for league, sport, end_date in (("nba", "basketball", nba_end), ("nfl", "football", nfl_end)):
            scoreboard_url = (f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
                              f"?dates={start_date}-{end_date}&limit=100")
            try:
                calls += 1
                scoreboards[league] = _scoreboard_games(fetch.json(scoreboard_url, ttl=0), league)
            except Exception as exc:
                if _status_code(exc) in {403, 429}:
                    refused = True
                    break
    for index, game in enumerate(games, start=1):
        if refused:
            rows.append({"league": "nfl", "game_id": game["espn_event_id"],
                         "status": "not_requested_after_host_refusal"})
            continue
        url = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
               f"?event={game['espn_event_id']}")
        try:
            calls += 1
            payload = fetch.json(url, ttl=0)
            rows.append(espn_summary_metadata(payload, game))
        except Exception as exc:
            rows.append({"league": "nfl", "game_id": game["espn_event_id"],
                         "publisher": "espn", "status": "fetch_error",
                         "http_status": _status_code(exc), "error_class": type(exc).__name__})
            if _status_code(exc) in {403, 429}:
                refused = True
        if index % 10 == 0:
            print(f"ESPN NFL article metadata: {index}/{len(games)} games; {calls} requests",
                  flush=True)
    return {"rows": rows, "nba_scoreboard_games": scoreboards["nba"],
            "nfl_scoreboard_games": scoreboards["nfl"],
            "requests": calls, "host": "site.api.espn.com"}


def _scoreboard_games(payload: dict[str, Any], league: str) -> list[dict[str, Any]]:
    out = []
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        teams = {}
        for row in comp.get("competitors") or []:
            side = row.get("homeAway")
            team = row.get("team") or {}
            if side in {"home", "away"} and team.get("abbreviation"):
                teams[side] = team["abbreviation"]
        if len(teams) == 2:
            out.append({"league": league, "event_id": str(event.get("id")),
                        "date": event.get("date"), "home_team": teams["home"],
                        "away_team": teams["away"]})
    return out


def collect_nba_pages(games: list[dict[str, Any]]) -> dict[str, Any]:
    import paced_http
    fetch = _fetcher(paced_http, min_interval=2.0, budget=100,
                     user_agent="Mozilla/5.0 (compatible; LPResearch/1.0)")
    rows = []
    calls = 0
    refused = False
    for index, game in enumerate(games, start=1):
        if refused:
            rows.append({"league": "nba", "game_id": game["game_page_id"],
                         "status": "not_requested_after_host_refusal"})
            continue
        url = f"https://www.nba.com/game/{game['game_page_id']}"
        try:
            calls += 1
            page_html = fetch.text(url, ttl=0)
            # Only known article header fields are copied out; the HTML and its full
            # story JSON are discarded immediately after this call returns.
            rows.append(nba_com_game_metadata(page_html, game))
            del page_html
        except Exception as exc:
            rows.append({"league": "nba", "game_id": game["game_page_id"],
                         "publisher": "nba.com", "status": "fetch_error",
                         "http_status": _status_code(exc), "error_class": type(exc).__name__})
            if _status_code(exc) in {403, 429}:
                refused = True
        if index % 10 == 0:
            print(f"NBA.com metadata: {index}/{len(games)} games; {calls} requests", flush=True)
    return {"rows": rows, "requests": calls, "host": "www.nba.com"}


def collect_nfl_weeklies(weeks: tuple[int, ...] = NFL_WEEKS) -> dict[str, Any]:
    import paced_http
    fetch = _fetcher(paced_http, min_interval=2.0, budget=10,
                     user_agent="Mozilla/5.0 (compatible; LPResearch/1.0)")
    rows = []
    calls = 0
    refused = False
    for week in weeks:
        if refused:
            rows.append({"league": "nfl", "week": week, "publisher": "nfl.com",
                         "status": "not_requested_after_host_refusal",
                         "coverage_scope": "weekly_rollup"})
            continue
        url = (f"https://www.nfl.com/news/2026-nfl-season-week-{week}-"
               "what-we-learned-from-sunday-s-games")
        try:
            calls += 1
            page_html = fetch.text(url, ttl=0)
            rows.append(nfl_week_metadata(page_html, week))
            del page_html
        except Exception as exc:
            rows.append({"league": "nfl", "week": week, "publisher": "nfl.com",
                         "status": "fetch_error", "http_status": _status_code(exc),
                         "error_class": type(exc).__name__, "coverage_scope": "weekly_rollup"})
            if _status_code(exc) in {403, 429}:
                refused = True
    return {"rows": rows, "requests": calls, "host": "www.nfl.com"}


def _db_story_audit(con: sqlite3.Connection, games: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for league in ("nfl", "nba"):
        cols = [row[1] for row in con.execute("PRAGMA table_info(game_story)")]
        indexes = [tuple(row) for row in con.execute("PRAGMA index_list(game_story)")]
        counts = [tuple(row) for row in con.execute(
            "SELECT league, COUNT(*), SUM(has_stakes=1), SUM(deterministic=1) "
            "FROM game_story WHERE league=? GROUP BY league", (league,))]
        result[league] = {"columns": cols, "indexes": indexes, "current_counts": counts}
    current = []
    for game in games:
        story = con.execute(
            "SELECT generated_at,has_form,has_stakes,deterministic FROM game_story "
            "WHERE league=? AND game_id=?", (game["league"], str(game["espn_event_id"]))).fetchone()
        current.append({"league": game["league"], "game_id": str(game["espn_event_id"]),
                        "generated_at": story[0] if story else None,
                        "has_form": story[1] if story else None,
                        "has_stakes": story[2] if story else None,
                        "deterministic": story[3] if story else None,
                        "stored_version_count": 1 if story else 0,
                        "prior_preview_recoverable": False if story else None})
    news_counts = [tuple(row) for row in con.execute(
        "SELECT league,source,COUNT(*),COUNT(DISTINCT url) FROM news_items "
        "WHERE league IN ('nfl','nba') AND lower(source) LIKE '%espn%' "
        "GROUP BY league,source ORDER BY league,source")]
    result["sample_story_rows"] = current
    result["espn_news_metadata_counts"] = news_counts
    return result


def _story_versions_for_targets(con, targets: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    out = []
    asof = nek.parse_utc(as_of)
    for target in targets:
        if not target.get("espn_event_id"):
            continue
        row = con.execute("SELECT story,generated_at FROM game_story WHERE league=? AND game_id=?",
                          (target["league"], str(target["espn_event_id"]))).fetchone()
        if not row:
            continue
        generated = nek.parse_utc(_utc_db(row["generated_at"]))
        kickoff = nek.parse_utc(target["start_utc"])
        if not generated or not kickoff or not asof or generated > asof or generated >= kickoff:
            continue
        out.append({"target_game_id": str(target["espn_event_id"]),
                    "league": target["league"], "story_kind": "pregame_preview",
                    "generator": "existing_game_story_cache", "generated_at": _utc_db(row["generated_at"]),
                    "preview": str(row["story"] or ""), "source_event_ids": [],
                    "evidence_provenance_status": "unavailable_existing_story_has_no_source_manifest"})
    return out


def _sample_game_story_versions(con, games, first_plays, last_plays) -> list[dict[str, Any]]:
    """Snapshot the one currently stored version with a timing-derived kind label."""
    out = []
    for game in games:
        game_id = str(game["espn_event_id"])
        row = con.execute("SELECT story,generated_at FROM game_story WHERE league=? AND game_id=?",
                          (game["league"], game_id)).fetchone()
        if not row:
            continue
        generated = nek.parse_utc(_utc_db(row["generated_at"]))
        start = nek.parse_utc(first_plays.get(game_id))
        end = nek.parse_utc(last_plays.get(game_id))
        if generated and start and generated < start:
            kind = "pregame_preview"
        elif generated and end and generated >= end:
            kind = "postgame_recap"
        else:
            kind = "timing_unknown_or_during_game"
        out.append({"target_game_id": game_id, "league": game["league"],
                    "story_kind": kind, "generator": "existing_game_story_cache",
                    "generated_at": _utc_db(row["generated_at"]),
                    "preview": str(row["story"] or ""), "source_event_ids": [],
                    "source_game_ids": [str(game.get("source_game_id") or game_id)],
                    "version_status": "only_current_row_recoverable"})
    return out


def _env_value(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    for path in ("/root/legendarypicks/.env", "/root/.hermes/.env"):
        try:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or default
        except OSError:
            continue
    return default


def _configured_inference_providers():
    """Mirror the repo's configured `_llm_chat` provider order without importing `_core`.

    `_core` calls `_init_db()` at import time; this research script must not initialize
    or write an application database just to use its model settings.
    """
    configured = (_env_value("LP_LLM_PROVIDERS", "nous,openrouter") or "nous,openrouter")
    model = _env_value("LP_LLM_MODEL", "deepseek/deepseek-v4.1-flash")
    providers = []
    for provider in (part.strip() for part in configured.split(",")):
        if provider == "nous":
            key = (_env_value("NOUS_PORTAL_KEY") or _env_value("NOUS_API_KEY"))
            if key:
                base = _env_value("NOUS_BASE_URL", "https://inference-api.nousresearch.com/v1")
                providers.append((provider, str(base).rstrip("/") + "/chat/completions", key))
        elif provider == "openrouter":
            key = _env_value("OPENROUTER_API_KEY")
            if key:
                providers.append((provider, "https://openrouter.ai/api/v1/chat/completions", key))
        elif provider == "deepseek":
            key = _env_value("DEEPSEEK_API_KEY")
            if key:
                providers.append((provider, "https://api.deepseek.com/v1/chat/completions", key))
    return model, providers


def _grounded_llm_preview(target: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the configured DeepSeek model to phrase a supplied, already-filtered fact set."""
    model, providers = _configured_inference_providers()
    if not providers:
        return {"status": "no_configured_provider", "preview": None, "cited_event_ids": []}
    system = (
        "Write a concise pregame sports preview from the supplied verified facts only. "
        "Use one or two sentences. Do not predict a winner, add statistics, infer injuries, "
        "or describe any game outcome beyond what a fact explicitly states. If the facts do "
        "not support a useful sentence, return an empty preview. Return JSON with exactly "
        "two keys: preview (string) and cited_event_ids (array of supplied event_id values)."
    )
    payload_facts = [{"event_id": f["event_id"], "category": f["category"], "team": f.get("team"),
                      "source_game_date": f.get("source_game_date"),
                      "source_game_opponent": f.get("source_game_opponent"),
                      "occurred_at": f["occurred_at"], "available_at": f["available_at"],
                      "calculation": f["calculation"],
                      "supporting_game_ids": f["supporting_game_ids"],
                      "supporting_event_ids": f["supporting_event_ids"]} for f in facts]
    user = json.dumps({"league": target["league"], "home_team": target["home_team"],
                       "away_team": target["away_team"], "facts": payload_facts},
                      ensure_ascii=False, sort_keys=True)
    body = json.dumps({"model": model, "temperature": 0.4, "max_tokens": 600,
                       "reasoning_effort": "none",
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode("utf-8")
    tried = []
    for provider, endpoint, key in providers:
        req = urllib.request.Request(
            endpoint, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "User-Agent": "legendarypicks-research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            content = str(response_data["choices"][0]["message"].get("content") or "").strip()
        except urllib.error.HTTPError as exc:
            tried.append({"provider": provider, "status": int(exc.code)})
            if exc.code in {401, 402, 403}:
                continue
            continue
        except Exception as exc:
            tried.append({"provider": provider, "error_class": type(exc).__name__})
            continue
        try:
            decoded = json.loads(content)
            preview = str(decoded.get("preview") or "").strip()
            cited = decoded.get("cited_event_ids") or []
            allowed = {str(f["event_id"]) for f in facts}
            if not isinstance(cited, list) or not set(map(str, cited)).issubset(allowed):
                return {"status": "invalid_citation_ids", "preview": None,
                        "cited_event_ids": [], "provider": provider, "model": model}
            return {"status": "ok" if preview else "empty_preview", "preview": preview or None,
                    "cited_event_ids": sorted(set(map(str, cited))),
                    "provider": provider, "model": model}
        except (json.JSONDecodeError, AttributeError, TypeError):
            return {"status": "invalid_json", "preview": None, "cited_event_ids": [],
                    "provider": provider, "model": model}
    return {"status": "providers_failed", "preview": None, "cited_event_ids": [],
            "provider_attempts": tried, "model": model}


def _unsupported_numbers(preview: str | None, facts: list[dict[str, Any]]) -> list[str]:
    if not preview:
        return []
    allowed: set[str] = set()
    def gather(value):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            allowed.add(str(int(value)) if float(value).is_integer() else str(value))
            for precision in (1, 2):
                rounded = f"{float(value):.{precision}f}".rstrip("0").rstrip(".")
                allowed.add(rounded)
        elif isinstance(value, dict):
            for child in value.values(): gather(child)
        elif isinstance(value, list):
            for child in value: gather(child)
    for fact in facts:
        gather(fact.get("calculation", {}))
        source_date = str(fact.get("source_game_date") or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", source_date):
            allowed.update((str(int(source_date[8:10])), source_date[:4]))
    found = re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])", preview)
    return sorted(set(token for token in found if token not in allowed))


def _trigram_overlap(left: str | None, right: str | None) -> float:
    def grams(text):
        tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        return {tuple(tokens[i:i + 3]) for i in range(max(0, len(tokens) - 2))}
    a, b = grams(left), grams(right)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def _future_nfl_targets(con: sqlite3.Connection, as_of: str, count: int = 12) -> list[dict[str, Any]]:
    date_cutoff = as_of[:10]
    out = []
    for row in con.execute(
            """SELECT CAST(espn AS TEXT) espn_event_id,game_id AS source_game_id,
                      game_id,season,gameday,away_team,home_team
               FROM nfl_schedule WHERE season=2026 AND game_type='REG' AND gameday>?
                 AND espn IS NOT NULL ORDER BY gameday,week,game_id LIMIT ?""",
            (date_cutoff, count)):
        item = dict(row)
        item.update({"league": "nfl", "game_date": item["gameday"],
                     "start_utc": f"{item['gameday']}T00:00:00Z"})
        out.append(item)
    return out


def _future_nba_targets(con: sqlite3.Connection, as_of: str, count: int = 12) -> list[dict[str, Any]]:
    out = []
    for row in con.execute(
            """SELECT game_id,season,CAST(espn AS TEXT) AS espn_event_id,
                      game_date,start_utc,away_team,home_team
               FROM nba_schedule WHERE season=? AND season_type='REG' AND status=1
                 AND start_utc>? ORDER BY start_utc,game_id LIMIT ?""",
            (NBA_SEASON, as_of, count)):
        item = dict(row)
        item.update({"league": "nba", "game_page_id": str(item["game_id"]),
                     "source_game_id": str(item["game_id"]),
                     "sample_role": "pregame_target",
                     "season_phase": "regular"})
        item["home_team"], item["away_team"] = (
            _nba_code(item["home_team"]), _nba_code(item["away_team"]))
        out.append(item)
    return out


def _recent_local_nba_event_games(con: sqlite3.Connection, as_of: str,
                                 days: int = 28, limit: int = 120) -> list[dict[str, Any]]:
    """Use recent completed NBA schedule rows and existing player-log game IDs for local facts."""
    cutoff = nek.parse_utc(as_of)
    if cutoff is None:
        raise ResearchAuditError("NBA event sample as_of must be timezone-aware")
    start_date = (cutoff - timedelta(days=days)).date().isoformat()
    games = []
    rows = con.execute(
        """SELECT game_id,season,game_date,start_utc,home_team,away_team,
                  home_score,away_score,CAST(espn AS TEXT) AS espn_event_id
           FROM nba_schedule WHERE season=? AND season_type='REG' AND status=3
             AND home_score IS NOT NULL AND away_score IS NOT NULL
             AND game_date>=? AND start_utc<?
           ORDER BY start_utc DESC,game_id DESC LIMIT ?""",
        (NBA_SEASON, start_date, nek.iso_utc(cutoff), int(limit)))
    for row in rows:
        game = dict(row)
        event_id = str(game.get("espn_event_id") or "")
        if not event_id:
            matches = [str(r[0]) for r in con.execute(
                """SELECT DISTINCT game_id FROM player_game_logs WHERE league='nba'
                   AND game_date=? AND ((team=? AND opponent=?) OR (team=? AND opponent=?))""",
                (game["game_date"], game["home_team"], game["away_team"],
                 game["away_team"], game["home_team"]))]
            if len(matches) != 1:
                continue
            event_id = matches[0]
        game.update({"league": "nba", "source_game_id": str(game["game_id"]),
                     "game_id": str(game["game_id"]), "espn_event_id": event_id,
                     "game_page_id": str(game["game_id"]),
                     "home": _nba_code(game["home_team"]),
                     "away": _nba_code(game["away_team"]),
                     "home_team": _nba_code(game["home_team"]),
                     "away_team": _nba_code(game["away_team"]),
                     "sample_role": "recent_local_event_sample",
                     "season_phase": "regular", "game_type": "REG"})
        games.append(game)
    return games


def _recent_team_streak_facts(con: sqlite3.Connection, target: dict[str, Any],
                              as_of: str) -> list[dict[str, Any]]:
    """Derive only three-plus game win/loss streaks from completed local schedule rows."""
    league = str(target.get("league") or "").lower()
    cutoff = nek.parse_utc(as_of)
    kickoff = nek.parse_utc(target.get("start_utc"))
    if league not in {"nfl", "nba"} or cutoff is None or kickoff is None:
        return []
    if league == "nfl":
        sql = """SELECT game_id,gameday AS game_date,home_team,away_team,
                        home_score,away_score,ingested_at,NULL AS start_utc
                 FROM nfl_schedule WHERE season=? AND game_type='REG'
                   AND gameday<? AND away_score IS NOT NULL AND home_score IS NOT NULL
                   AND (home_team=? OR away_team=?)
                 ORDER BY gameday DESC,week DESC,game_id DESC LIMIT 4"""
        params = (int(target.get("season") or 2026), kickoff.date().isoformat(),)
    else:
        sql = """SELECT game_id,game_date,home_team,away_team,home_score,away_score,
                        ingested_at,start_utc
                 FROM nba_schedule WHERE season=? AND season_type='REG' AND status=3
                   AND start_utc<? AND away_score IS NOT NULL AND home_score IS NOT NULL
                   AND (home_team=? OR away_team=?)
                 ORDER BY start_utc DESC,game_id DESC LIMIT 4"""
        params = (int(target.get("season") or NBA_SEASON), nek.iso_utc(kickoff))

    facts = []
    for raw_team in (target.get("home_team"), target.get("away_team")):
        team = _nba_code(str(raw_team)) if league == "nba" else str(raw_team).upper()
        rows = [dict(row) for row in con.execute(sql, (*params, team, team))]
        available_rows = []
        for row in rows:
            available_at, basis = _schedule_available_at(row["game_date"], row["ingested_at"])
            if nek.parse_utc(available_at) and nek.parse_utc(available_at) <= cutoff:
                row["available_at"], row["availability_basis"] = available_at, basis
                available_rows.append(row)
        if len(available_rows) < 3:
            continue
        outcomes = []
        for row in available_rows:
            own = row["home_score"] if str(row["home_team"]).upper() == team else row["away_score"]
            other = row["away_score"] if str(row["home_team"]).upper() == team else row["home_score"]
            outcomes.append("win" if own > other else "loss" if own < other else "tie")
        outcome = outcomes[0]
        if outcome == "tie":
            continue
        streak = 0
        for value in outcomes:
            if value != outcome:
                break
            streak += 1
        if streak < 3:
            continue
        supporting_rows = available_rows[:streak]
        latest = supporting_rows[0]
        latest_opponent = (latest["away_team"] if str(latest["home_team"]).upper() == team
                           else latest["home_team"])
        game_date = str(latest["game_date"])[:10]
        occurred_at = (str(latest.get("start_utc") or f"{game_date}T00:00:00Z"))
        occurred_at = nek.iso_utc(nek.parse_utc(occurred_at)) if nek.parse_utc(occurred_at) else (
            f"{game_date}T00:00:00Z")
        available_at = max(row["available_at"] for row in supporting_rows)
        game_ids = [str(row["game_id"]) for row in supporting_rows]
        event_ids = [f"{gid}:team-result:{team}" for gid in game_ids]
        fact = _local_fact(
            league=league, game_id=game_ids[0], event_id=event_ids[0],
            category="recent_streak", team=team, opponent=str(latest_opponent).upper(),
            game_date=game_date, occurred_at=occurred_at, available_at=available_at,
            evidence_ids=event_ids,
            calculation={"streak_length": streak, "streak_result": outcome,
                         "supporting_results": outcomes[:streak],
                         "availability_bases": sorted({row["availability_basis"]
                                                        for row in supporting_rows})},
            source=f"repository:{'nfl_schedule' if league == 'nfl' else 'nba_schedule'}",
            relevant_teams=[team])
        fact["supporting_game_ids"] = sorted(set(game_ids))
        facts.append(fact)
    return facts


def _attach_nba_event_ids(targets: list[dict[str, Any]],
                         scoreboard: list[dict[str, Any]]) -> None:
    for target in targets:
        if target.get("league") != "nba":
            continue
        expected_teams = frozenset((_nba_code(target["home_team"]), _nba_code(target["away_team"])))
        start = nek.parse_utc(target.get("start_utc"))
        matches = []
        for row in scoreboard:
            try:
                pair = frozenset((_nba_code(row["home_team"]), _nba_code(row["away_team"])))
            except (ValueError, TypeError):
                continue
            event_time = nek.parse_utc(row.get("date"))
            if not start or not event_time or pair != expected_teams:
                continue
            # The scoreboard and local schedule normally agree exactly; allow a
            # two-minute publisher rounding difference, never a name-only join.
            if abs((event_time - start).total_seconds()) <= 120:
                matches.append(row)
        if len(matches) == 1:
            target["espn_event_id"] = matches[0]["event_id"]
            target["event_crosswalk_status"] = "unique_team_and_start_time"
        else:
            target["event_crosswalk_status"] = "ambiguous_or_unmatched"


def _attach_nfl_start_times(targets: list[dict[str, Any]], scoreboard: list[dict[str, Any]]) -> None:
    by_id = {str(row.get("event_id")): row for row in scoreboard if row.get("event_id")}
    for target in targets:
        row = by_id.get(str(target.get("espn_event_id")))
        start = nek.parse_utc(row.get("date")) if row else None
        if start:
            target["start_utc"] = nek.iso_utc(start)
            target["event_crosswalk_status"] = "schedule_espn_id_verified"
        else:
            target["event_crosswalk_status"] = "schedule_id_only_date_boundary"


def _standings_events(con: sqlite3.Connection, game: dict[str, Any], end_at: str,
                      available_at: str) -> list[dict[str, Any]]:
    """Record-only standings delta; no ranks, clinches, or tie-break claims."""
    league = game["league"]
    if league == "nfl":
        rows = [dict(r) for r in con.execute(
            """SELECT game_id,gameday,home_team,away_team,home_score,away_score
               FROM nfl_schedule WHERE season=? AND game_type='REG'
                 AND away_score IS NOT NULL AND home_score IS NOT NULL AND gameday<=?""",
            (int(game["season"]), game["game_date"]))]
        current_id = str(game["source_game_id"])
        id_key = "game_id"
        date_key = "gameday"
    else:
        rows = [dict(r) for r in con.execute(
            """SELECT source_game_id AS game_id,game_date,home AS home_team,away AS away_team,
                      home_score,away_score
               FROM nba_sportsdataverse_games WHERE source_season=? AND game_type='REG'
                 AND home_score IS NOT NULL AND away_score IS NOT NULL AND game_date<=?""",
            (int(game.get("season_year") or game["season"]), game["game_date"]))]
        current_id = str(game["source_game_id"])
        id_key = "game_id"
        date_key = "game_date"
    prior = [r for r in rows if str(r[id_key]) != current_id and str(r[date_key]) < game["game_date"]]
    selected = [r for r in rows if str(r[id_key]) == current_id]
    if len(selected) != 1:
        return []
    current = selected[0]
    facts = []
    for team, score_for, score_against in (
            (current["home_team"], current["home_score"], current["away_score"]),
            (current["away_team"], current["away_score"], current["home_score"])):
        prior_record = {"wins": 0, "losses": 0, "ties": 0}
        support_games = [str(current_id)]
        for row in prior:
            if team not in (row["home_team"], row["away_team"]):
                continue
            own = row["home_score"] if row["home_team"] == team else row["away_score"]
            opp = row["away_score"] if row["home_team"] == team else row["home_score"]
            prior_record["wins" if own > opp else "losses" if own < opp else "ties"] += 1
            support_games.append(str(row[id_key]))
        outcome = "win" if score_for > score_against else "loss" if score_for < score_against else "tie"
        post = dict(prior_record)
        post[{"win": "wins", "loss": "losses", "tie": "ties"}[outcome]] += 1
        canonical_game_id = str(game.get("source_game_id") or game.get("game_id") or
                                game["espn_event_id"])
        opponent = current["away_team"] if current["home_team"] == team else current["home_team"]
        event_id = f"{canonical_game_id}:standings:{team}"
        facts.append({
            "schema_version": nek.SCHEMA_VERSION, "league": league,
            "game_id": canonical_game_id, "event_id": event_id,
            "category": "standings_record", "source": f"repository:{league}_schedule",
            "team": str(team), "source_game_date": str(game["game_date"])[:10],
            "source_game_opponent": str(opponent),
            "occurred_at": end_at, "available_at": available_at,
            "supporting_game_ids": sorted(set(support_games)),
            "supporting_event_ids": sorted(set(support_games)),
            "calculation": {"record_before": prior_record, "game_outcome": outcome,
                            "record_after": post,
                            "previous_games_same_calendar_date_excluded": True,
                            "claim_scope": "win_loss_record_only"},
            "verified": True,
        })
    return facts


def _player_log_rows(con: sqlite3.Connection, games: list[dict[str, Any]],
                     first_plays: dict[str, str]):
    logs_by_game = defaultdict(list)
    all_players = set()
    for game in games:
        if game["league"] == "nba":
            db_game_id = str(game["espn_event_id"])
        else:
            db_game_id = str(game["source_game_id"])
        rows = list(con.execute(
            """SELECT id,player_id,league,season,game_type,game_id,game_date,team,
                      stats,source,source_player_key,ingested_at
               FROM player_game_logs WHERE league=? AND game_id=?""",
            (game["league"], db_game_id)))
        for row in rows:
            if row["player_id"] is None:
                continue
            item = dict(row)
            item["log_id"] = str(item.pop("id"))
            item["available_at"], item["availability_basis"] = _player_log_available_at(
                item.get("game_date"), item.get("ingested_at"))
            item["stats"] = json.loads(item["stats"] or "{}")
            item["player_id"] = str(item["player_id"])
            item["game_start"] = first_plays.get(str(game["espn_event_id"])) or (
                f"{str(item.get('game_date'))[:10]}T00:00:00Z")
            item["game_type"] = item.get("game_type") or "REG"
            item["canonical_game_id"] = str(game.get("source_game_id") or game.get("game_id") or db_game_id)
            logs_by_game[db_game_id].append(item)
            all_players.add(item["player_id"])
    # Pull history by canonical ID; retain only allowlisted stats and required times.
    histories = []
    player_ids = sorted(all_players)
    for start in range(0, len(player_ids), 400):
        batch = player_ids[start:start + 400]
        marks = ",".join("?" for _ in batch)
        if not batch:
            continue
        for row in con.execute(
                f"""SELECT l.id,l.player_id,l.league,l.game_type,l.game_id,l.game_date,
                           l.team,l.stats,l.source,l.source_player_key,l.ingested_at,
                           COALESCE(s.source_game_id,n.game_id,l.game_id) AS canonical_game_id
                    FROM player_game_logs l
                    LEFT JOIN nba_sportsdataverse_games s
                      ON l.league='nba' AND s.espn_event_id=l.game_id
                    LEFT JOIN nba_schedule n
                      ON l.league='nba' AND (CAST(n.espn AS TEXT)=l.game_id OR
                           (n.game_date=l.game_date AND
                            ((n.home_team=l.team AND n.away_team=l.opponent) OR
                             (n.away_team=l.team AND n.home_team=l.opponent))))
                    WHERE l.player_id IN ({marks}) AND l.league IN ('nfl','nba')""",
                batch):
            item = dict(row)
            item["log_id"] = str(item.pop("id"))
            item["available_at"], item["availability_basis"] = _player_log_available_at(
                item.get("game_date"), item.get("ingested_at"))
            item["stats"] = json.loads(item["stats"] or "{}")
            item["player_id"] = str(item["player_id"])
            # player_game_logs has no capture timestamp; ignore ingested_at and use the
            # chronological game-date boundary with existing schedule/game-ID crosswalks.
            date = str(item.get("game_date") or "")[:10]
            item["game_start"] = f"{date}T00:00:00Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None
            item["game_type"] = item.get("game_type") or "REG"
            histories.append(item)
    history_by_log_id = {row["log_id"]: row for row in histories}
    for game in games:
        db_game_id = str(game["espn_event_id"] if game["league"] == "nba" else game["source_game_id"])
        game_date = str(game.get("game_date") or game.get("gameday") or "")[:10]
        first = first_plays.get(str(game["espn_event_id"])) or f"{game_date}T00:00:00Z"
        for target in logs_by_game.get(db_game_id, []):
            target["game_start"] = first
            if target["log_id"] in history_by_log_id:
                history_by_log_id[target["log_id"]]["game_start"] = first
    return logs_by_game, histories


def _add_player_facts(games, first_plays, whistles, con) -> list[dict[str, Any]]:
    log_games, histories = _player_log_rows(con, games, first_plays)
    histories_by_player = defaultdict(list)
    for history in histories:
        histories_by_player[history["player_id"]].append(history)
    facts = []
    for game in games:
        db_game_id = str(game["espn_event_id"] if game["league"] == "nba" else game["source_game_id"])
        target_logs = log_games.get(db_game_id, [])
        if not target_logs:
            continue
        first_play = first_plays.get(str(game["espn_event_id"])) or (
            f"{str(game.get('game_date') or game.get('gameday'))[:10]}T00:00:00Z")
        captured_after_game = max((row["available_at"] for row in target_logs
                                   if row.get("available_at")), default=None)
        last_play = whistles.get(str(game["espn_event_id"])) or captured_after_game or _backfilled_postgame_cutoff(
            game.get("game_date") or game.get("gameday"))
        if not first_play or not last_play:
            continue
        available = max((row.get("available_at") for row in target_logs if row.get("available_at")),
                        default=None)
        if not available:
            continue
        # Player logs use repository game ids (NFL-native; NBA ESPN ids joined through the
        # existing SportsDataVerse/schedule crosswalk). Keep the fact id canonical.
        for row in target_logs:
            row["game_id"] = db_game_id
        target_player_ids = {row["player_id"] for row in target_logs}
        target_histories = [history for player_id in target_player_ids
                            for history in histories_by_player.get(player_id, [])]
        event_facts = nek.derive_player_outliers(
            league=game["league"], target_game_id=db_game_id,
            fact_game_id=str(game.get("source_game_id") or game.get("game_id") or db_game_id),
            target_start=first_play, target_end=last_play, target_available_at=available,
            logs=target_histories)
        for fact in event_facts:
            fact["source_game_date"] = str(game.get("game_date") or game.get("gameday"))[:10]
            fact["source_game_opponent"] = str(game["away_team"] if fact.get("team") == game["home_team"]
                                                else game["home_team"])
            fact["availability_basis"] = sorted({row.get("availability_basis") for row in target_logs
                                                  if row.get("availability_basis")})
        facts.extend(event_facts)
    return facts


def _select_preview_facts(target: dict[str, Any], context: list[dict[str, Any]],
                          player_names: dict[str, str]) -> list[dict[str, Any]]:
    """Keep recent, high-signal evidence; avoid weak outliers and repeated categories."""
    league = str(target.get("league") or "").lower()
    team_set = {canonical for key in ("home_team", "away_team")
                if (canonical := nek._canonical_team(league, target.get(key)))}
    kickoff = nek.parse_utc(target.get("start_utc"))
    max_age_days = 28 if league == "nfl" else 21
    eligible = []
    for fact in context:
        if not fact.get("verified"):
            continue
        date_text = str(fact.get("source_game_date") or "")[:10]
        try:
            source_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            continue
        if kickoff:
            age = (kickoff.date() - source_date).days
            if age < 0 or age > max_age_days:
                continue
        team = nek._canonical_team(league, fact.get("team"))
        calculation = fact.get("calculation") or {}
        category = fact.get("category")
        if category == "comeback":
            minimum = 10 if league == "nfl" else 15
            if team not in team_set or float(calculation.get("largest_deficit_overcome") or 0) < minimum:
                continue
        elif category == "turnover_events":
            by_team = calculation.get("giveaways_by_team") or {}
            if not any(nek._canonical_team(league, t) in team_set and int(n or 0) >= 3
                       for t, n in by_team.items()):
                continue
        elif category == "team_box_summary":
            if team not in team_set or int(calculation.get("turnovers") or 0) < 20:
                continue
        elif category == "scoring_run":
            if team not in team_set or int(calculation.get("points") or 0) < 15:
                continue
        elif category == "recent_streak":
            if team not in team_set or int(calculation.get("streak_length") or 0) < 3:
                continue
        elif category == "player_outlier":
            stat = str(calculation.get("stat") or "")
            player_id = str(calculation.get("player_id") or "")
            try:
                value = float(calculation.get("value"))
                z_score = float(calculation.get("z_score"))
                prior_games = int(calculation.get("prior_games"))
            except (TypeError, ValueError):
                continue
            if (team not in team_set or not player_names.get(player_id) or
                    prior_games < 8 or z_score < 2.5 or stat == "fpts_ppr"):
                continue
            minimum_values = {
                "nba": {"PTS": 25, "REB": 12, "AST": 10, "PRA": 40},
                "nfl": {"targets": 8, "carries": 10},
            }
            if value < minimum_values.get(league, {}).get(stat, float("inf")):
                continue
        else:
            # Lead-change events, raw standings, snap shares, and unvalidated
            # fourth-down/drive/scoring summaries do not explain matchup relevance.
            continue
        recency = (kickoff.date() - source_date).days if kickoff else 0
        score = {"comeback": 5, "recent_streak": 5, "turnover_events": 4, "team_box_summary": 4,
                 "scoring_run": 3, "player_outlier": 3}.get(category, 0)
        eligible.append((score, -recency, str(fact.get("event_id") or ""), fact))

    eligible.sort(key=lambda item: (-item[0], -item[1], item[2]))
    selected = []
    categories = set()
    player_added = False
    team_added = False
    for _, _, _, fact in eligible:
        category = fact.get("category")
        if category in categories:
            continue
        is_player = category == "player_outlier"
        if is_player and player_added:
            continue
        if not is_player and team_added:
            continue
        selected.append(fact)
        categories.add(category)
        player_added |= is_player
        team_added |= not is_player
        if len(selected) == 2:
            break
    return selected


def _team_display_names(con: sqlite3.Connection, targets: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, str]]:
    names: dict[tuple[str, int], dict[str, str]] = {}
    seasons = {(str(target["league"]), int(target.get("season") or
                (NBA_SEASON if target["league"] == "nba" else 2026))) for target in targets}
    for league, season in seasons:
        table = "nfl_teams" if league == "nfl" else "nba_teams"
        team_season = season if league == "nfl" else season - 1
        league_names = {}
        for row in con.execute(
                f"SELECT team,team_name FROM {table} WHERE season=? AND team_name IS NOT NULL",
                (team_season,)):
            code = str(row["team"]).upper()
            canonical = team_codes.normalize(league, code)
            league_names[code] = str(row["team_name"])
            league_names[canonical] = str(row["team_name"])
            for alias, target in team_codes.ALIASES.get(league, {}).items():
                if target == canonical:
                    league_names[alias] = str(row["team_name"])
        names[(league, season)] = league_names
    return names


def _render_deterministic_preview(target: dict[str, Any], context: list[dict[str, Any]],
                                  player_names: dict[str, str],
                                  team_display_names: dict[str, str] | None = None) -> str:
    display_names = {str(code).upper(): str(name) for code, name in
                     (team_display_names or {}).items()}
    team_names = {}
    for key in ("home_team", "away_team"):
        code = str(target[key]).upper()
        canonical = nek._canonical_team(str(target.get("league") or "").lower(), code)
        if canonical:
            team_names[canonical] = display_names.get(code, display_names.get(canonical, code))
    team_set = set(team_names)
    parts = []
    rendered_player_games = set()
    for fact in _select_preview_facts(target, context, player_names):
        team = nek._canonical_team(str(target.get("league") or "").lower(), fact.get("team"))
        date = fact.get("source_game_date")
        opponent = fact.get("source_game_opponent")
        if date:
            try:
                game_date = datetime.strptime(str(date)[:10], "%Y-%m-%d").strftime("%b %-d")
            except ValueError:
                game_date = str(date)[:10]
            opponent_name = display_names.get(str(opponent).upper(), opponent) if opponent else None
            opponent_ref = (f" against the {opponent_name}" if opponent_name and
                            str(opponent).upper() in display_names else
                            f" against {opponent_name}" if opponent_name else "")
            game_ref = f"in its {game_date} game" + opponent_ref
            player_game_ref = f"in the {game_date} game" + opponent_ref
        else:
            # A source game date/opponent is required to make chronological claims.
            game_ref = None
            player_game_ref = None
            opponent_ref = ""
        if fact["category"] == "comeback":
            amount = fact["calculation"]["largest_deficit_overcome"]
            if game_ref:
                parts.append(f"The {team_names.get(team, team)} erased a {amount}-point deficit {game_ref}.")
        elif fact["category"] == "recent_streak" and game_ref:
            c = fact["calculation"]
            count = int(c["streak_length"])
            count_label = {3: "three", 4: "four", 5: "five", 6: "six"}.get(count, str(count))
            opponent_name = display_names.get(str(opponent).upper(), opponent) if opponent else ""
            opponent_ref = (f"the {opponent_name}" if opponent_name and
                            str(opponent).upper() in display_names else opponent_name)
            if c.get("streak_result") == "win":
                detail = f", most recently beating {opponent_ref} on {game_date}" if opponent_ref else ""
                parts.append(f"The {team_names.get(team, team)} have won {count_label} straight games{detail}.")
            elif c.get("streak_result") == "loss":
                detail = f", most recently falling to {opponent_ref} on {game_date}" if opponent_ref else ""
                parts.append(f"The {team_names.get(team, team)} have lost {count_label} straight games{detail}.")
        elif fact["category"] == "final_lead_change" and fact["calculation"].get("play_type"):
            if not game_ref:
                continue
            play_type = str(fact["calculation"]["play_type"])
            play_type = re.sub(r"\s*[-–]\s*\d+\s+of\s+\d+.*$", "", play_type, flags=re.I)
            play_type = re.sub(r"\b3\s*(?:[- ]\s*)?(?:pt|point)\b", "three-point", play_type, flags=re.I)
            play_type = re.sub(r"\b\d+\b", "", play_type)
            play_type = re.sub(r"\s+good\b", "", play_type, flags=re.I)
            play_type = re.sub(r"\s+", " ", play_type).strip(" -").lower()
            if play_type:
                parts.append(f"The {team_names.get(team, team)} took the lead on a {play_type} {game_ref}.")
        elif fact["category"] == "fourth_down_attempts":
            if not game_ref:
                continue
            c = fact["calculation"]
            team_label = team_names.get(team, team or "The team")
            parts.append(f"{team_label} converted {c['converted']} of {c['attempts']} fourth-down attempts {game_ref}.")
        elif fact["category"] == "turnover_events" and game_ref:
            by_team = fact["calculation"].get("giveaways_by_team") or {}
            significant = [
                (team_names.get(nek._canonical_team(
                    str(target.get("league") or "").lower(), code), str(code)), int(count))
                for code, count in by_team.items()
                if nek._canonical_team(str(target.get("league") or "").lower(), code)
                in team_set and int(count or 0) >= 3
            ]
            if significant:
                label, count = sorted(significant, key=lambda row: (-row[1], row[0]))[0]
                parts.append(f"The {label} gave the ball away {count} times in the {game_date} game.")
        elif fact["category"] == "drive_summary" and game_ref:
            outcomes = fact["calculation"].get("terminal_results", {})
            scoring_drives = sum(outcomes.get(key, 0) for key in ("Touchdown", "Field goal"))
            if scoring_drives:
                parts.append(f"The {team_names.get(team, team)} scored on {scoring_drives} of its {fact['calculation']['drive_count']} drives {game_ref}.")
        elif fact["category"] == "scoring_summary" and game_ref:
            c = fact["calculation"]
            details = []
            if c.get("touchdowns"):
                details.append(f"{c['touchdowns']} touchdowns")
            if c.get("field_goals"):
                details.append(f"{c['field_goals']} field goals")
            if details:
                parts.append(f"The {team_names.get(team, team)} scored {c['scheduled_points']} points ({' and '.join(details)}) {game_ref}.")
        elif fact["category"] == "team_box_summary" and game_ref:
            turnovers = fact["calculation"].get("turnovers")
            if turnovers is not None and int(turnovers) >= 20:
                parts.append(f"The {team_names.get(team, team)} committed {turnovers} turnovers {game_ref}.")
        elif fact["category"] == "snap_workload" and game_ref:
            c = fact["calculation"]
            player_game_key = (str(c["player_id"]), str(date))
            if player_game_key in rendered_player_games:
                continue
            rendered_player_games.add(player_game_key)
            name = player_names.get(str(c["player_id"]), f"Player {c['player_id']}")
            if float(c.get("off_pct") or 0) >= 0.9:
                parts.append(f"{name} played {float(c['off_pct'])*100:.0f}% of the offensive snaps {player_game_ref}.")
            elif float(c.get("def_pct") or 0) >= 0.9:
                parts.append(f"{name} played {float(c['def_pct'])*100:.0f}% of the defensive snaps {player_game_ref}.")
        elif fact["category"] == "standings_record" and game_ref:
            record = fact["calculation"].get("record_after", {})
            parts.append(f"The {team_names.get(team, team)} were {record.get('wins', 0)}-{record.get('losses', 0)} after its {game_date} game" +
                         (f" against {opponent}" if opponent else "") + ".")
        elif fact["category"] == "player_outlier":
            if not game_ref:
                continue
            c = fact["calculation"]
            player_game_key = (str(c["player_id"]), str(date))
            if player_game_key in rendered_player_games:
                continue
            rendered_player_games.add(player_game_key)
            name = player_names.get(str(c["player_id"]))
            if not name:
                continue
            stat = PLAYER_STAT_LABELS.get(str(c["stat"]), str(c["stat"]))
            value = f"{float(c['value']):.1f}".rstrip("0").rstrip(".")
            average = f"{float(c['prior_mean']):.1f}".rstrip("0").rstrip(".")
            if c["stat"] == "targets":
                performance = f"{name} drew {value} targets"
            elif c["stat"] == "carries":
                performance = f"{name} had {value} carries"
            elif c["stat"] == "PTS":
                performance = f"{name} scored {value} points"
            elif c["stat"] == "PRA":
                performance = f"{name} recorded {value} combined points, rebounds, and assists"
            else:
                performance = f"{name} recorded {value} {stat}"
            historical_team = display_names.get(str(team).upper(), team)
            historical_team_ref = (f"for the {historical_team}"
                                   if str(team).upper() in display_names else
                                   f"for {historical_team}")
            parts.append(
                f"{performance} {historical_team_ref}{opponent_ref} on {game_date}; the prior "
                f"{c['prior_games']}-game average was {average} {stat}.")
        elif fact["category"] == "scoring_run" and fact["calculation"]["meets_highlight_threshold"]:
            if game_ref:
                parts.append(f"The {team_names.get(team, team)} had a {fact['calculation']['points']}-point scoring run {game_ref}.")
    return " ".join(parts[:3])


def _local_news_metadata_audit(con: sqlite3.Connection) -> dict[str, Any]:
    # `body` is intentionally absent from this projection.
    rows = [dict(row) for row in con.execute(
        "SELECT league,source,headline,url,published FROM news_items "
        "WHERE league IN ('nfl','nba') AND lower(source) LIKE '%espn%'")]
    out = {}
    for league in ("nfl", "nba"):
        subset = [r for r in rows if r["league"] == league]
        unique_keys = {_duplicate_key({"headline": r["headline"], "published_at": r["published"]})
                       for r in subset}
        out[league] = {"rows": len(subset), "unique_urls": len({r["url"] for r in subset}),
                       "distinct_headline_date_keys": sum(1 for key in unique_keys if key),
                       "sources": dict(Counter(r["source"] for r in subset))}
    return out


def _article_detector_comparison(metadata: list[dict[str, Any]], facts: list[dict[str, Any]],
                                 validated_games: set[tuple[str, str]],
                                 game_id_crosswalk: dict[tuple[str, str], str] | None = None
                                 ) -> list[dict[str, Any]]:
    game_id_crosswalk = game_id_crosswalk or {}
    by_game = defaultdict(set)
    for fact in facts:
        by_game[(fact["league"], str(fact["game_id"]))].add(fact["category"])
    out = []
    for row in metadata:
        if (row.get("coverage_scope", "single_game") != "single_game" or
                row.get("status") != "found" or not row.get("game_id")):
            continue
        canonical_game_id = game_id_crosswalk.get(
            (row["league"], str(row["game_id"])), str(row["game_id"]))
        if (row["league"], canonical_game_id) not in validated_games:
            continue
        cats = by_game[(row["league"], canonical_game_id)]
        labels = row.get("headline_theme_candidates") or []
        hits, misses = [], []
        for label in labels:
            (hits if cats.intersection(_THEME_EVENT_CATEGORIES.get(label, set())) else misses).append(label)
        out.append({"league": row["league"], "game_id": str(row["game_id"]),
                    "canonical_game_id": canonical_game_id,
                    "publisher": row["publisher"], "origin_class": row["origin_class"],
                    "headline_theme_candidates": labels,
                    "detected_by_event_facts": hits,
                    "not_detected_by_event_facts": misses,
                    "detected_categories": sorted(cats),
                    "annotation_source": "headline_metadata_only"})
    return out


def _duplicate_audit(metadata: list[dict[str, Any]]) -> dict[str, Any]:
    groups = defaultdict(list)
    url_groups = defaultdict(list)
    for row in metadata:
        if row.get("status") != "found":
            continue
        key = row.get("duplicate_key") or _duplicate_key(row)
        if key:
            groups[key].append({"league": row.get("league"), "game_id": row.get("game_id"),
                                "publisher": row.get("publisher"), "url": row.get("url")})
        url = _safe_url(row.get("url"))
        if url:
            url_groups[url].append({"league": row.get("league"), "game_id": row.get("game_id"),
                                    "publisher": row.get("publisher"), "url": url})
    duplicates = [items for items in groups.values() if len(items) > 1]
    url_duplicates = [items for items in url_groups.values() if len(items) > 1]
    return {"articles_found": sum(1 for row in metadata if row.get("status") == "found"),
            "headline_date_comparable_articles": sum(len(group) for group in groups.values()),
            "unique_headline_date_keys": len(groups), "duplicate_groups": duplicates,
            "duplicate_article_copies": sum(len(group) - 1 for group in duplicates),
            "unique_urls": len(url_groups), "url_duplicate_groups": url_duplicates,
            "url_duplicate_copies": sum(len(group) - 1 for group in url_duplicates)}


def _report(*, story_audit, local_news, local_db_coverage, samples, publisher_rows, event_facts,
            article_checks, duplicate_audit, requests, capture_at, llm_status="not_run",
            blind_comparison_count=0, paired_targets_by_league=None,
            single_variant_targets_by_league=None, numeric_evidence_stats=None) -> str:
    nba_rows = [row for row in publisher_rows if row.get("source_discovery") == "nba.com_game_summary"]
    nfl_espn = [row for row in publisher_rows if row.get("source_discovery") == "espn_nfl_summary"]
    nfl_weekly = [row for row in publisher_rows if row.get("publisher") == "nfl.com"]
    event_counts = Counter((f["league"], f["category"]) for f in event_facts)
    validated = Counter((row["league"], row["status"]) for row in requests.get("pbp_rows", []))
    nba_found = sum(row.get("status") == "found" for row in nba_rows)
    nba_ap = sum(row.get("status") == "found" and row.get("origin_class") == "ap_origin"
                 for row in nba_rows)
    nfl_found = sum(row.get("status") == "found" for row in nfl_espn)
    nfl_ap = sum(row.get("status") == "found" and row.get("origin_class") == "ap_origin"
                 for row in nfl_espn)
    matched = sum(bool(row["detected_by_event_facts"]) for row in article_checks)
    labels = sum(len(row["headline_theme_candidates"]) for row in article_checks)
    hits = sum(len(row["detected_by_event_facts"]) for row in article_checks)
    delay_count = sum(row.get("publication_delay_seconds_from_final_whistle") is not None
                      for row in publisher_rows)
    local_rows = requests.get("pbp_rows", [])
    nfl_local = [row for row in local_rows if row.get("league") == "nfl"]
    nba_local = [row for row in local_rows if row.get("league") == "nba"]
    nfl_validated = sum(row.get("status") == "local_pbp_processed" for row in nfl_local)
    nba_validated = sum(row.get("status") == "local_team_box_only" for row in nba_local)
    validated_count = nfl_validated + nba_validated
    nfl_score_matched = sum(row.get("scoring_reconciliation", {}).get("status") == "matched"
                            for row in nfl_local)
    nfl_team_result_matched = sum(row.get("team_game_results_reconciliation", {}).get("status") == "matched"
                                  for row in nfl_local)
    nfl_team_result_available = sum(row.get("team_game_results_reconciliation", {}).get("status")
                                    != "unavailable" for row in nfl_local)
    nfl_team_result_mismatched = sum(row.get("team_game_results_reconciliation", {}).get("status")
                                     == "mismatch" for row in nfl_local)
    nfl_turnover_rows = [item for row in nfl_local
                         for item in row.get("turnover_reconciliation", {}).values()
                         if isinstance(item, dict) and item.get("matches") is not None]
    nba_sample_stats_rows = sum(row.get("team_box_rows", 0) for row in nba_local)
    nba_sample_play_games = sum(row.get("play_by_play_rows", 0) > 0 for row in nba_local)
    lines = [
        "# Narrative event knowledge: research audit",
        "",
        f"**Captured:** {capture_at}",
        "**Mode:** research only; no application database writes; publisher bodies and play descriptions were not retained.",
        "",
        "## Samples",
        "",
        f"- NFL event sample: {len(samples['nfl'])} completed regular-season games, weeks 4–7, stratified 13/13/12/12.",
        f"- NBA event sample: {len(samples['nba_pbp'])} completed regular-season games from the 2025–26 season, selected as an even subset of the article sample.",
        f"- NBA article sample: {len(samples['nba_metadata'])} completed regular-season games, selected evenly across the 1,230-game 2025–26 regular-season data population; the 50-game event sample is nested inside it.",
        "",
        "## Current storage and collector audit",
        "",
        "- `game_story` has a `(league, game_id)` key and no story-kind/version column. The generator deletes and replaces that row, so a stored postgame row cannot recover an earlier preview. When a current row exists, its saved text is only one version; the database cannot tell whether a preview was ever generated before the recap.",
        f"- Sampled current story rows: NFL {sum(r['league']=='nfl' and r['stored_version_count'] for r in story_audit['sample_story_rows'])}/{len(samples['nfl'])}; NBA {sum(r['league']=='nba' and r['stored_version_count'] for r in story_audit['sample_story_rows'])}/{len(samples['nba_pbp'])}. Historical overwritten-preview count is not observable from this schema.",
        f"- Existing ESPN-tagged `news_items` metadata: NFL {local_news['nfl']['rows']} rows / {local_news['nfl']['unique_urls']} URLs; NBA {local_news['nba']['rows']} rows / {local_news['nba']['unique_urls']} URLs. The collector has headline, URL, publisher and published time columns; body/description was excluded from this audit query.",
        "- The existing ESPN collector stores short descriptions in `news_items.body` and an optional story fetcher stores full ESPN story text. This prototype reads no `body` column and does not call the full-story collector.",
        "",
        "## Article coverage in this sample",
        "",
        f"- NBA.com game pages with recap header metadata: {nba_found}/{len(samples['nba_metadata'])}; pages with AP origin explicitly identified in byline/credit metadata: {nba_ap}/{len(samples['nba_metadata'])}.",
        f"- ESPN per-game NFL summaries with article headline metadata: {nfl_found}/{len(samples['nfl'])}; articles with AP origin explicitly identified by source/byline metadata: {nfl_ap}/{len(samples['nfl'])}.",
        f"- NFL.com *What We Learned* weekly pages found: {sum(r.get('status')=='found' for r in nfl_weekly)}/{len(NFL_WEEKS)} sampled week pages. These are week-level packages, not one independent article per game.",
        f"- Duplicate audit: {duplicate_audit['duplicate_article_copies']} duplicate copies in {len(duplicate_audit['duplicate_groups'])} duplicate normalized headline/date groups among {duplicate_audit['headline_date_comparable_articles']} records with both fields; {duplicate_audit['url_duplicate_copies']} exact-URL duplicate copies in {len(duplicate_audit['url_duplicate_groups'])} groups. Mirrored articles can still use distinct URLs.",
        "- Headline labels are candidate labels only. This audit did not read or store article descriptions or article bodies; it therefore cannot claim coverage of themes that appear only inside the story.",
        (f"- Headline/event detector: {hits}/{labels} headline-derived candidate labels were represented by a corresponding structured event category ({matched} articles had at least one detected candidate). This measures headline agreement only; it is not a journalist-theme recall estimate."
         if validated_count else
         "- Headline/event comparison was not evaluated because no sample game had a validated PBP timeline."),
        (f"- Publication delay is available for {delay_count} fetched records, computed from publication time to the last structured PBP play. Treat it as an observed timestamp difference, not a wire-service latency guarantee."
         if delay_count else
         "- Publication delay is unavailable: the available game-clock timestamps are estimates, not measured final-whistle times."),
        "",
        "## Local database source audit",
        "",
        "- The event extractor opens the supplied Legendary Picks development database in SQLite `mode=ro` with `PRAGMA query_only=ON`. Event statistics come from local tables; this invocation made zero external game-statistics requests.",
        f"- NFL `nfl_pbp`: {local_db_coverage['nfl']['nfl_pbp']['rows']:,} plays across {local_db_coverage['nfl']['nfl_pbp']['games']:,} games, {local_db_coverage['nfl']['nfl_pbp']['first_game_date']}–{local_db_coverage['nfl']['nfl_pbp']['last_game_date']}. `drive`, `series_result`, `down`, turnover and touchdown fields are present; per-play capture timestamps and score snapshots are missing.",
        f"- NFL supporting data: `team_game_results` {local_db_coverage['nfl']['team_game_results']['rows']:,} rows, player game logs {local_db_coverage['nfl']['player_game_logs']['rows']:,} rows ({local_db_coverage['nfl']['player_game_logs']['rows_with_player_id']:,} with player IDs and {local_db_coverage['nfl']['player_game_logs']['rows_with_stats_json']:,} with stats JSON), and `nfl_snap_counts` {local_db_coverage['nfl']['nfl_snap_counts']['rows']:,} rows across seasons {local_db_coverage['nfl']['nfl_snap_counts']['first_season']}–{local_db_coverage['nfl']['nfl_snap_counts']['last_season']}. Snap counts have no game ID or capture timestamp and join through the existing season/week/team schedule identity. The DB has no separate drive-named table; drive terminals are reconstructed from `nfl_pbp.drive` and `series_result`.",
        f"- NBA full play-by-play table: none found. `scoring_plays` has {local_db_coverage['nba']['scoring_plays']['rows']:,} rows for {local_db_coverage['nba']['scoring_plays']['games']} games, captured {local_db_coverage['nba']['scoring_plays']['first_capture']}–{local_db_coverage['nba']['scoring_plays']['last_capture']}; it omits non-scoring possessions and defensive sequence data. The 50-game event sample had local scoring plays for {nba_sample_play_games} games.",
        f"- NBA box-score coverage: `team_game_stats` has {local_db_coverage['nba']['team_game_stats']['rows']:,} rows across {local_db_coverage['nba']['team_game_stats']['games']:,} games with actual `captured_at` timestamps; populated rows: turnovers {local_db_coverage['nba']['team_game_stats']['rows_with_turnovers']:,}, rebounds {local_db_coverage['nba']['team_game_stats']['rows_with_rebounds']:,}, assists {local_db_coverage['nba']['team_game_stats']['rows_with_assists']:,}, steals {local_db_coverage['nba']['team_game_stats']['rows_with_steals']:,}, blocks {local_db_coverage['nba']['team_game_stats']['rows_with_blocks']:,}. Missing values: fouls on {local_db_coverage['nba']['team_game_stats']['rows_with_fouls']:,}/{local_db_coverage['nba']['team_game_stats']['rows']:,} rows; FG%, 3P% and FT% on {local_db_coverage['nba']['team_game_stats']['rows_with_fg_pct']:,}, {local_db_coverage['nba']['team_game_stats']['rows_with_tp_pct']:,} and {local_db_coverage['nba']['team_game_stats']['rows_with_ft_pct']:,}; `largest_lead` on {local_db_coverage['nba']['team_game_stats']['rows_with_largest_lead']:,} and `lead_changes` on {local_db_coverage['nba']['team_game_stats']['rows_with_lead_changes']:,}. The 50-game sample matched {nba_sample_stats_rows} team rows.",
        f"- Player game logs have `ingested_at` but no source capture timestamp: NFL {local_db_coverage['nfl']['player_game_logs']['rows_with_player_id']:,}/{local_db_coverage['nfl']['player_game_logs']['rows']:,} rows have a player ID and NBA {local_db_coverage['nba']['player_game_logs']['rows_with_player_id']:,}/{local_db_coverage['nba']['player_game_logs']['rows']:,}. They use canonical game dates and a conservative next-day boundary; ingestion time is not treated as historical availability. NFL PBP also uses that game-date boundary. NBA team box snapshots instead use their actual `captured_at`.",
        "",
        "## Deterministic local event prototype",
        "",
        f"- Local extraction status: NFL {nfl_validated}/{len(samples['nfl'])} sample games processed from `nfl_pbp`; NBA {nba_validated}/{len(samples['nba_pbp'])} games produced team-box facts. NBA team-box facts are not full play-by-play.",
        f"- NFL reconstructed scoring totals matched `nfl_schedule` for {nfl_score_matched}/{len(samples['nfl'])} sampled games. Scoring facts are withheld on a mismatch; drive, turnover, fourth-down and snap summaries retain their own evidence IDs.",
        f"- NFL `team_game_results` score reconciliation was available for {nfl_team_result_available}/{len(samples['nfl'])} sampled games; {nfl_team_result_matched} matched and {nfl_team_result_mismatched} differed. The remaining games had no complete two-team results pair for the sample's ESPN IDs. Of {len(nfl_turnover_rows)} team turnover snapshot comparisons available in the sample, {sum(row['matches'] for row in nfl_turnover_rows)} matched and {sum(not row['matches'] for row in nfl_turnover_rows)} differed. Drive and fourth-down summaries are derived from local play fields; no independent local result table was available to reconcile those categories.",
        "- `nfl_pbp` has no per-play score snapshots, so this iteration emits no NFL comeback, lead-change, or clutch-outcome claims. NBA has no local full play sequence, and its team-game snapshots contain no `largest_lead` or `lead_changes` values; those event categories remain unavailable locally.",
        "- The five prior NBA timeline failures (401810016, 401810188, 401810257, 401809242, 401810585) are absent from local play-level storage. The old checkpoint kept only `NarrativeDataError`, not a message or failed timeline, so its exact failure class cannot be reproduced from this DB/artifact. No validation threshold was weakened.",
        f"- Event fact counts: {', '.join(f'{league} {category}={count}' for (league,category),count in sorted(event_counts.items())) or 'none'}.",
        "- Backfilled game facts use canonical database game IDs and dated source-game references. Neutral events list both participants. The renderer says a team took the lead; it never says that a particular play won the game.",
        "",
        "## Pregame retrieval and story comparison",
        "",
        "- The retriever rejects an `as_of` time after kickoff, requires `occurred_at < target_start`, `available_at <= as_of`, a verified fact with supporting game/event IDs, and team/player relevance, and excludes the target game's canonical local ID.",
        "- The comparison includes deterministic event-only and deterministic combined-facts candidates. Both use the same matchup, cutoff, and complete authorized evidence packet; the combined candidate can use standings and player-form facts alongside event facts.",
        "- Existing cached previews have no persisted source manifest. They are retained as story versions but excluded from numerical evidence scoring and the blinded candidate set until their authorized evidence can be reconstructed.",
        f"- LLM status: {llm_status}.",
        (f"- Blinded candidate coverage prepared for human rating: {', '.join(f'{league} {count} paired targets' for league, count in sorted((paired_targets_by_league or {}).items())) or 'none'}. `blind_evidence.jsonl` supplies each pair the same evidence and cutoff. The ID-to-generator key is kept outside this review packet; do not give it to raters. No human ratings have been entered."
         if blind_comparison_count else "- No blind candidate pairs were produced in this run."),
        ("- Numeric evidence gate (preview-level): " + "; ".join(
            f"{variant} {counts['unsupported']}/{counts['evaluated']} previews contained a number absent from the supplied event calculations"
            for variant, counts in sorted((numeric_evidence_stats or {}).items())) + "."),
        "- Numeric-token overlap is only a mechanical screen, not claim verification. It is not used to grade existing previews whose full evidence set is unknown. Relevance, factual accuracy, specificity, and readability still require blinded human ratings; no improvement claim is made.",
        "",
        "## Rights and limits",
        "",
        "- AP says its structured news-data products cover AI training, retrieval and archive use. Public readability alone is not a bulk-training license; the corpus here retains metadata and links only. See [AP AI, tech and data](https://www.ap.org/who-we-serve/ai-tech-and-data/) and [AP source data](https://www.ap.org/intelligence/our-offerings/source-data/).",
        "- NBA.com terms restrict commercial use of stats and prohibit certain fantasy/gambling uses without consent. These research outputs are not wired into the product; obtain rights review before bulk reuse. See [NBA.com Terms of Use](https://www.nba.com/termsofuse).",
        "- The 100-game NBA article sample is systematic across one completed regular season, not a random sample. NFL covers four selected weeks, not a full season. Not-found pages mean unavailable at the requested page/endpoint during this run, not that the publisher has no article.",
        "",
        "## Network request count",
        "",
    ]
    for host, count in sorted(requests.get("actual_by_host", {}).items()):
        lines.append(f"- `{host}`: {count} requests.")
    if not requests.get("actual_by_host"):
        if requests.get("checkpoint_rows_by_host"):
            rows_by_host = ", ".join(
                f"{host} {count} rows" for host, count in
                sorted(requests["checkpoint_rows_by_host"].items()))
            lines.append(f"- No publisher requests were made in this iteration; saved article-metadata checkpoints were read ({rows_by_host}).")
        else:
            lines.append("- Network collection was not run.")
    spend = requests.get("all_attempt_spend", {})
    if spend.get("request_counts_by_host"):
        total = sum(spend["request_counts_by_host"].values())
        host_counts = ", ".join(f"{host} {count}"
                                 for host, count in sorted(spend["request_counts_by_host"].items()))
        lines.append(f"- All logged collection attempts, including the failed first pass and metadata re-fetch: {total} requests ({host_counts}). See `network-spend.jsonl` for HTTP statuses.")
    lines += ["", "See `sample_manifest.json`, `local_database_coverage.json`, `publisher_metadata.jsonl`, `event_records.jsonl`, `blind_review_packet.zip`, and the other JSONL/CSV audit artifacts in this directory.", ""]
    return "\n".join(lines)


def _output_network_task(future, label):
    try:
        result = future.result()
    except Exception as exc:
        return {"task": label, "error_class": type(exc).__name__}
    return result


def run_audit(db_path: str, outdir: str | Path, *, network: bool = False,
              skip_core: bool = False, skip_scoreboards: bool = False,
              resume_checkpoints: bool = False,
              include_summary_pbp: bool = False,
              reuse_prior_llm: bool = False,
              blind_key_out: str | Path | None = None) -> dict[str, Any]:
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    con = open_readonly(db_path)
    try:
        nfl, (nba_pbp, nba_meta) = build_samples(con)
        metadata_start = utc_now()
        recent_nba = _recent_local_nba_event_games(con, metadata_start)
        event_games = nfl + nba_pbp + recent_nba
        story_audit = _db_story_audit(con, event_games)
        local_news = _local_news_metadata_audit(con)
        local_coverage = local_database_coverage(con)
        local_event_data = load_local_narrative_events(con, event_games)
        event_facts: list[dict[str, Any]] = local_event_data["facts"]
        expected = ({"site.api.espn.com": len(nfl), "www.nba.com": len(nba_meta),
                     "www.nfl.com": len(NFL_WEEKS)}
                    if network and not resume_checkpoints else {})
        _json_write(outdir / "sample_manifest.json", {
            "sample_as_of": "2026-10-31", "sample_design": {
                "nfl": {"games": len(nfl), "weeks": list(NFL_WEEKS), "quotas": NFL_QUOTAS},
                "nba_event": {"games": len(nba_pbp), "season_year": NBA_EVENT_SEASON,
                              "phase": "regular", "selection": "evenly spaced subset of the article sample"},
                "nba_recent_local_events": {"games": len(recent_nba), "season_year": NBA_SEASON,
                                             "max_age_days": 28,
                                             "source": "nba_schedule + player_game_logs"},
                "nba_article": {"games": len(nba_meta), "season_year": NBA_EVENT_SEASON,
                                 "regular": len(nba_meta), "preseason": 0,
                                 "population_finals": 1230,
                                 "selection": "evenly spaced across the completed regular-season population"}},
            "network_request_plan_by_host": expected if network else {},
            "network_execution_mode": ("publisher_metadata_only_local_events"
                                       if network and not resume_checkpoints else
                                       "publisher_checkpoints_only_local_events"
                                       if network else "offline_local_events"),
            "network_requests_made_this_invocation": (sum(expected.values())
                                                       if network and not resume_checkpoints else 0),
            "database": str(Path(db_path).resolve()),
            "database_mode": "read_only_query_only",
            "article_body_retained": False,
            "event_data_source": "local_legendarypicks_database",
            "external_game_statistics_requests": 0,
            "sample_games": event_games,
            "recent_local_nba_event_games": recent_nba,
            "nba_article_games": nba_meta,
        })
        _json_write(outdir / "local_database_coverage.json",
                    {"database": str(Path(db_path).resolve()), **local_coverage})
        _jsonl_write(outdir / "local_event_source_audit.jsonl", local_event_data["rows"])
        print(f"Prepared sample: {len(nfl)} NFL games, {len(nba_pbp)} historical NBA games, "
              f"{len(recent_nba)} recent local NBA games, "
              f"{len(nba_meta)} NBA article pages", flush=True)
        print(f"Database reads: local event, schedule, team/player, story, and news metadata; article body columns excluded.",
              flush=True)

        publisher_rows: list[dict[str, Any]] = []
        event_facts: list[dict[str, Any]] = list(local_event_data["facts"])
        request_result: dict[str, Any] = {
            "pbp_rows": local_event_data["rows"], "actual_by_host": {},
            "pbp_collection_status": "local_database_only",
            "external_game_statistics_requests": 0,
        }
        whistles: dict[str, str] = dict(local_event_data["postgame_at"])
        first_play: dict[str, str] = {}
        observed_whistles: dict[str, str] = {}
        observed_first_play: dict[str, str] = {}
        normalized_plays: list[dict[str, Any]] = []
        summary_checkpoint_loaded = False
        if network:
            if resume_checkpoints:
                new_request_count = 0
                print(f"Rebuilding from saved publisher checkpoints; new network requests={new_request_count}.",
                      flush=True)
            else:
                planned_total = sum(expected.values())
                print("Publisher metadata request budget:", json.dumps(expected, sort_keys=True),
                      f"total={planned_total}; game statistics are read locally with zero external requests.",
                      flush=True)
            import paced_http
            paced_http.SPEND_LOG = str(outdir / "network-spend.jsonl")
            if resume_checkpoints:
                for label, host in (("nfl_espn", "site.api.espn.com"),
                                    ("nba_pages", "www.nba.com"),
                                    ("nfl_weeklies", "www.nfl.com")):
                    rows = _jsonl_read(outdir / f"checkpoint_{label}_metadata.jsonl")
                    publisher_rows.extend(rows)
                    request_result.setdefault("checkpoint_rows_by_host", {})[host] = len(rows)
                print("Loaded completed publisher metadata checkpoints.", flush=True)
            else:
                tasks = {}
                with ThreadPoolExecutor(max_workers=4) as pool:
                    tasks[pool.submit(collect_nfl_espn_articles, nfl,
                                      include_scoreboards=False)] = "nfl_espn"
                    tasks[pool.submit(collect_nba_pages, nba_meta)] = "nba_pages"
                    tasks[pool.submit(collect_nfl_weeklies)] = "nfl_weeklies"
                    for future in as_completed(tasks):
                        result = _output_network_task(future, tasks[future])
                        if "error_class" in result:
                            _json_write(outdir / f"network_failure_{tasks[future]}.json", result)
                            print(f"{tasks[future]} task failed ({result['error_class']})", flush=True)
                            continue
                        label = tasks[future]
                        _jsonl_write(outdir / f"checkpoint_{label}_metadata.jsonl", result["rows"])
                        request_result["actual_by_host"][result["host"]] = result["requests"]
                        if label == "nfl_espn":
                            publisher_rows.extend(result["rows"])
                        elif label in {"nba_pages", "nfl_weeklies"}:
                            publisher_rows.extend(result["rows"])
            request_result["all_attempt_spend"] = _network_spend_summary(
                outdir / "network-spend.jsonl")

        # Events, standings, and player logs all come from the local DB. For backfilled
        # sources, only game-date cutoffs are used; ingested_at is not treated as availability.
        for game in event_games:
            game_key = str(game.get("espn_event_id") or game.get("source_game_id"))
            end_at = whistles.get(game_key)
            if end_at:
                event_facts.extend(_standings_events(con, game, end_at, end_at))
        event_facts.extend(_add_player_facts(event_games, first_play, whistles, con))

        if network:
            for row in publisher_rows:
                final_whistle = observed_whistles.get(str(row.get("game_id")))
                published = nek.parse_utc(row.get("published_at"))
                final_at = nek.parse_utc(final_whistle)
                row["publication_delay_seconds_from_final_whistle"] = (
                    int((published - final_at).total_seconds()) if published and final_at else None)

        # Attach headline-only candidate labels to the structured event result.
        validated_games = {(str(fact["league"]), str(fact["game_id"])) for fact in event_facts}
        game_id_crosswalk = {
            (str(game["league"]), str(game["espn_event_id"])):
                str(game.get("source_game_id") or game.get("game_id"))
            for game in event_games if game.get("espn_event_id")
        }
        article_checks = _article_detector_comparison(
            publisher_rows, event_facts, validated_games, game_id_crosswalk)
        duplicate_audit = _duplicate_audit(publisher_rows)
        as_of = utc_now() if network else metadata_start
        targets = _future_nfl_targets(con, as_of, count=60) + _future_nba_targets(con, as_of, count=60)
        existing_versions = _story_versions_for_targets(con, targets, as_of)
        story_versions = (_sample_game_story_versions(con, event_games,
                                                      observed_first_play, observed_whistles)
                          if network else []) + existing_versions
        prior_llm_versions = {}
        prior_story_path = outdir / "story_versions.jsonl"
        if reuse_prior_llm and prior_story_path.is_file():
            for prior in _jsonl_read(prior_story_path):
                if prior.get("generator") == "configured-deepseek-grounded":
                    prior_llm_versions[(prior.get("league"), prior.get("target_game_id"))] = prior
        player_names = {str(row[0]): row[1] for row in con.execute(
            "SELECT CAST(id AS TEXT),name FROM players WHERE league IN ('nfl','nba')")}
        display_teams = _team_display_names(con, targets)
        blind_rows, key_rows, blind_metrics, blind_evidence_rows, llm_attempts = [], [], [], [], Counter()
        pair_number = 0
        for target in targets:
            target_id = str(target.get("espn_event_id") or target.get("game_id") or target.get("game_page_id"))
            target_local_id = str(target.get("source_game_id") or target.get("game_id") or target_id)
            cutoff = target.get("start_utc")
            target_facts = _recent_team_streak_facts(con, target, as_of)
            ctx = nek.retrieve_pregame_context(
                [*event_facts, *target_facts], league=target["league"], target_game_id=target_local_id,
                target_start=cutoff, as_of=as_of,
                teams=[target["home_team"], target["away_team"]], limit=100)
            event_categories = {"recent_streak", "final_lead_change", "comeback", "turnover_events",
                                "fourth_down_attempts", "scoring_summary", "drive_summary",
                                "team_box_summary", "scoring_run", "late_scoring_drive",
                                "clutch_events", "lead_changes"}
            event_ctx = [fact for fact in ctx if fact.get("category") in event_categories]
            display_key = (str(target["league"]), int(target.get("season") or
                            (NBA_SEASON if target["league"] == "nba" else 2026)))
            team_names = display_teams.get(display_key, {})
            deterministic_event = _render_deterministic_preview(
                target, event_ctx, player_names, team_names)
            deterministic_combined = _render_deterministic_preview(
                target, ctx, player_names, team_names)
            if deterministic_event or deterministic_combined:
                def evidence_ids(facts):
                    return {
                        "source_event_ids": sorted({eid for fact in facts
                                                     for eid in fact["supporting_event_ids"]}),
                        "source_game_ids": sorted({gid for fact in facts
                                                    for gid in fact["supporting_game_ids"]}),
                    }

                event_version = {"target_game_id": target_id, "league": target["league"],
                                 "story_kind": "pregame_preview", "generator": "deterministic-local-events-v1",
                                 "generated_at": as_of, "preview": deterministic_event,
                                 **evidence_ids(event_ctx)}
                story_version = {"target_game_id": target_id, "league": target["league"],
                                 "story_kind": "pregame_preview", "generator": "deterministic-combined-local-v1",
                                 "generated_at": as_of, "preview": deterministic_combined,
                                 **evidence_ids(ctx)}
                if deterministic_event:
                    story_versions.append(event_version)
                if deterministic_combined:
                    story_versions.append(story_version)
                existing = next((v for v in existing_versions
                                 if v["target_game_id"] == target_id and v["league"] == target["league"]), None)
                llm_version = None
                llm_status = "not_selected"
                if network and llm_attempts[target["league"]] < 5:
                    prior_llm = prior_llm_versions.get((target["league"], target_id))
                    current_source_ids = story_version["source_event_ids"]
                    if (reuse_prior_llm and prior_llm and
                            prior_llm.get("source_event_ids") == current_source_ids):
                        result = {"status": "reused_prior_grounded_preview",
                                  "preview": prior_llm.get("preview"),
                                  "cited_event_ids": prior_llm.get("cited_event_ids", []),
                                  "provider": prior_llm.get("provider"),
                                  "model": prior_llm.get("model")}
                        llm_status = result["status"]
                    elif reuse_prior_llm:
                        result = {"status": "no_matching_prior_grounded_preview",
                                  "preview": None, "cited_event_ids": []}
                        llm_status = result["status"]
                    else:
                        llm_attempts[target["league"]] += 1
                        result = _grounded_llm_preview(target, ctx)
                        llm_status = result["status"]
                    llm_text = result.get("preview")
                    unsupported = _unsupported_numbers(llm_text, ctx)
                    if llm_text and not result.get("cited_event_ids"):
                        llm_status, llm_text = "rejected_missing_citations", None
                    if llm_text and unsupported:
                        llm_status, llm_text = "rejected_unsupported_numbers", None
                    if llm_text and re.search(r"\b(will win|likely to win|should win|favou?red to win)\b",
                                              llm_text, re.I):
                        llm_status, llm_text = "rejected_prediction_language", None
                    blind_metrics.append({"target_game_id": target_id, "league": target["league"],
                                          "variant": "llm_grounded",
                                          "cited_event_ids": result.get("cited_event_ids", []),
                                          "unsupported_numeric_tokens": unsupported,
                                          "specificity_fact_count": len(result.get("cited_event_ids", [])),
                                          "relevant_context_fact_count": len(ctx),
                                          "cutoff_leakage": any(
                                              nek.parse_utc(f["occurred_at"]) >= nek.parse_utc(cutoff)
                                              or nek.parse_utc(f["available_at"]) > nek.parse_utc(as_of)
                                              for f in ctx),
                                          "status": llm_status,
                                          "provider": result.get("provider"), "model": result.get("model")})
                    if llm_text:
                        llm_version = {"target_game_id": target_id, "league": target["league"],
                                       "story_kind": "pregame_preview", "generator": "configured-deepseek-grounded",
                                       "generated_at": as_of, "preview": llm_text,
                                       "provider": result.get("provider"), "model": result.get("model"),
                                       "cited_event_ids": result.get("cited_event_ids", []),
                                       "source_event_ids": story_version["source_event_ids"],
                                       "source_game_ids": story_version["source_game_ids"]}
                        if llm_status == "reused_prior_grounded_preview":
                            llm_version["reused_from_prior_audit"] = True
                        story_versions.append(llm_version)
                cutoff_leakage = any(
                    nek.parse_utc(f["occurred_at"]) >= nek.parse_utc(cutoff)
                    or nek.parse_utc(f["available_at"]) > nek.parse_utc(as_of)
                    for f in ctx)
                for variant, preview, evidence in (
                        ("deterministic_event", deterministic_event, event_ctx),
                        ("deterministic_combined", deterministic_combined, ctx)):
                    if preview:
                        blind_metrics.append({"target_game_id": target_id, "league": target["league"],
                                              "variant": variant,
                                              "unsupported_numeric_tokens": _unsupported_numbers(preview, evidence),
                                              "specificity_fact_count": len(evidence),
                                              "relevant_context_fact_count": len(ctx),
                                              "cutoff_leakage": cutoff_leakage, "status": "ok"})
                if existing:
                    blind_metrics.append({"target_game_id": target_id, "league": target["league"],
                                          "variant": "existing_preview",
                                          "unsupported_numeric_tokens": None,
                                          "cutoff_leakage": None,
                                          "status": "unscorable_missing_evidence_manifest"})
                if deterministic_event and deterministic_combined:
                    pair_number += 1
                    blind_target_id = f"target-{pair_number:03d}"
                    present = [("deterministic_event", event_version),
                               ("deterministic_combined", story_version),
                               ("llm_grounded", llm_version)]
                    present = [(name, value) for name, value in present if value]
                    blind_evidence_rows.append({
                        "blind_target_id": blind_target_id, "league": target["league"],
                        "target_game_id": target_local_id, "home_team": target["home_team"],
                        "away_team": target["away_team"], "kickoff": cutoff, "as_of": as_of,
                        "source_event_ids": sorted({eid for fact in ctx
                                                     for eid in fact["supporting_event_ids"]}),
                        "source_game_ids": sorted({gid for fact in ctx
                                                    for gid in fact["supporting_game_ids"]}),
                        "authorized_evidence": [{
                            "event_id": fact["event_id"], "category": fact["category"],
                            "team": fact.get("team"), "source_game_date": fact.get("source_game_date"),
                            "source_game_opponent": fact.get("source_game_opponent"),
                            "occurred_at": fact["occurred_at"], "available_at": fact["available_at"],
                            "calculation": fact["calculation"],
                            "supporting_game_ids": fact["supporting_game_ids"],
                            "supporting_event_ids": fact["supporting_event_ids"],
                        } for fact in ctx],
                    })
                    for left_index, (left_name, left_value) in enumerate(present):
                        for right_name, right_value in present[left_index + 1:]:
                            blind_metrics.append({"target_game_id": target_id,
                                                  "league": target["league"],
                                                  "variant_pair": [left_name, right_name],
                                                  "repeated_information_trigram_jaccard": _trigram_overlap(
                                                      left_value.get("preview"), right_value.get("preview"))})
                    for variant, value in present:
                        blind_id = f"blind-{secrets.token_hex(8)}"
                        blind_rows.append({"blind_id": blind_id, "blind_target_id": blind_target_id,
                                           "league": target["league"], "preview": value["preview"]})
                        key_rows.append({"blind_id": blind_id, "variant": variant,
                                         "blind_target_id": blind_target_id,
                                         "league": target["league"],
                                         "target_game_id": target_id,
                                         "generator": value.get("generator"),
                                         "story_kind": value.get("story_kind")})
        # IDs and row order are unpredictable; the separate key is needed to debrief.
        secrets.SystemRandom().shuffle(blind_rows)
        variants_by_target = defaultdict(set)
        blind_league_by_target = {}
        for row in key_rows:
            key = (row["blind_target_id"], row["league"])
            variants_by_target[key].add(row["variant"])
            blind_league_by_target[key] = row["league"]
        paired_targets_by_league = Counter(
            blind_league_by_target[key] for key, variants in variants_by_target.items()
            if len(variants) > 1)
        single_variant_targets_by_league = Counter(
            blind_league_by_target[key] for key, variants in variants_by_target.items()
            if len(variants) == 1)
        numeric_evidence_stats = defaultdict(lambda: {"evaluated": 0, "unsupported": 0})
        for metric in blind_metrics:
            variant = metric.get("variant")
            if variant not in {"deterministic_event", "deterministic_combined", "llm_grounded"}:
                continue
            if metric.get("status") not in {"available", "ok", "reused_prior_grounded_preview"}:
                continue
            numeric_evidence_stats[variant]["evaluated"] += 1
            if metric.get("unsupported_numeric_tokens"):
                numeric_evidence_stats[variant]["unsupported"] += 1
        _jsonl_write(outdir / "blind_comparison.jsonl", blind_rows)
        if blind_key_out:
            key_path = Path(blind_key_out).resolve()
            if key_path.is_relative_to(outdir):
                raise ResearchAuditError("blind key output must be outside the reviewer artifact directory")
            _json_write(key_path, key_rows)
        _jsonl_write(outdir / "blind_evidence.jsonl", blind_evidence_rows)
        with (outdir / "blind_ratings_template.csv").open("w", newline="", encoding="utf-8") as ratings_file:
            writer = csv.DictWriter(ratings_file, fieldnames=[
                "blind_id", "blind_target_id", "league", "relevance_1_to_5",
                "factual_accuracy_1_to_5", "specificity_1_to_5", "readability_1_to_5", "notes"],
                lineterminator="\n")
            writer.writeheader()
            for row in blind_rows:
                writer.writerow({key: row.get(key, "") for key in (
                    "blind_id", "blind_target_id", "league")})
        _jsonl_write(outdir / "event_records.jsonl", event_facts)
        _jsonl_write(outdir / "structured_plays.jsonl", normalized_plays)
        _jsonl_write(outdir / "publisher_metadata.jsonl", publisher_rows)
        _jsonl_write(outdir / "headline_event_agreement.jsonl", article_checks)
        _json_write(outdir / "database_audit.json", story_audit)
        _json_write(outdir / "duplicate_audit.json", duplicate_audit)
        _json_write(outdir / "network_request_counts.json", request_result)
        _jsonl_write(outdir / "blind_metrics.jsonl", blind_metrics)
        _jsonl_write(outdir / "story_versions.jsonl", story_versions)
        reused_llm_count = sum(v.get("reused_from_prior_audit") is True for v in story_versions)
        if reuse_prior_llm:
            llm_status = (f"{reused_llm_count} previously generated grounded previews reused; "
                          f"new model calls={sum(llm_attempts.values())}")
        else:
            llm_status = (f"{sum(llm_attempts.values())} bounded model calls attempted "
                          f"({llm_attempts['nfl']} NFL, {llm_attempts['nba']} NBA); "
                          f"valid LLM previews={sum(v.get('generator')=='configured-deepseek-grounded' for v in story_versions)}")
        report = _report(story_audit=story_audit, local_news=local_news,
                         local_db_coverage=local_coverage,
                         samples={"nfl": nfl, "nba_pbp": nba_pbp, "nba_metadata": nba_meta},
                         publisher_rows=publisher_rows, event_facts=event_facts,
                         article_checks=article_checks, duplicate_audit=duplicate_audit,
                         requests=request_result, capture_at=as_of, llm_status=llm_status,
                         blind_comparison_count=len(blind_rows),
                         paired_targets_by_league=paired_targets_by_league,
                         single_variant_targets_by_league=single_variant_targets_by_league,
                         numeric_evidence_stats=numeric_evidence_stats)
        (outdir / "audit_report.md").write_text(report, encoding="utf-8")
        return {"outdir": str(outdir), "nfl_games": len(nfl), "nba_event_games": len(nba_pbp),
                "nba_article_games": len(nba_meta), "network_requests": request_result.get("actual_by_host", {}),
                "event_facts": len(event_facts), "publisher_rows": len(publisher_rows),
                "llm_attempts": dict(llm_attempts), "blind_rows": len(blind_rows)}
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DEV_DB),
                        help="Legendary Picks dev database path; defaults to the shared local DB, opened read-only")
    parser.add_argument("--out", default=str(ARTIFACT_ROOT), help="research artifact directory")
    parser.add_argument("--network", action="store_true",
                        help="fetch bounded article metadata only; game statistics are read locally")
    parser.add_argument("--skip-core", action="store_true",
                        help="legacy compatibility flag; external play-by-play collection is disabled")
    parser.add_argument("--skip-scoreboards", action="store_true",
                        help="legacy compatibility flag; external scoreboard collection is disabled")
    parser.add_argument("--resume-checkpoints", action="store_true",
                        help="rebuild artifacts from completed host checkpoints without network calls")
    parser.add_argument("--include-summary-pbp", action="store_true",
                        help="legacy compatibility flag; external play-by-play collection is disabled")
    parser.add_argument("--reuse-prior-llm", action="store_true",
                        help="reuse still-grounded model previews from the existing story_versions artifact")
    parser.add_argument("--blind-key-out", default=None,
                        help="write the blinded-ID mapping outside the reviewer artifact directory")
    args = parser.parse_args()
    try:
        result = run_audit(args.db, args.out, network=args.network,
                           skip_core=args.skip_core, skip_scoreboards=args.skip_scoreboards,
                           resume_checkpoints=args.resume_checkpoints,
                           include_summary_pbp=args.include_summary_pbp,
                           reuse_prior_llm=args.reuse_prior_llm,
                           blind_key_out=args.blind_key_out)
    except Exception as exc:
        print(f"research audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
