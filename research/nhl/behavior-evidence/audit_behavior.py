#!/usr/bin/env python3
"""Reproducible NHL behavior coverage audit over the verified local archive.

Raw GameCenter data stay outside Git. This script emits only compact aggregates,
source references, and model diagnostics. It never writes to a database.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import random
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

from evidence_core import (binary_scores, decode_situation_code, parse_clock,
                           score_state, shrink_binary_rate, strength_for_side,
                           time_remaining_bucket)


ROOT = Path(__file__).resolve().parents[3]
RESEARCH_DIR = ROOT / "research/nhl/behavior-evidence"
DEFAULT_DATA_ROOT = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21")
DEFAULT_BOXSCORE_ROOT = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20")
DEFAULT_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
DEFAULT_OUTPUT = RESEARCH_DIR / "results/nhl-behavior-evidence-2026-10-26.json"
PBP_MANIFEST_SHA256 = "d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990"
SHIFT_MANIFEST_SHA256 = "deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5"
TRAIN_SEASONS = (2019, 2020)
DEV_SEASONS = (2021,)
ATTEMPTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
SOG_EVENTS = {"goal", "shot-on-goal"}
MANPOWER_PENALTIES = {"MIN", "MAJ"}
RATE_FAMILIES = ("attempt", "sog", "goal", "penalty", "faceoff_win")
BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 20261026
COVERAGE_MATRIX = [
    {
        "mechanic": "Penalties and manpower",
        "observed_fields": "PBP play type/eventId/sortOrder/timeInPeriod/timeRemaining/periodDescriptor/situationCode; penalty details typeCode/duration/descKey/committedByPlayerId/servedByPlayerId/eventOwnerTeamId; shift playerId/teamId/period/startTime/endTime/duration",
        "deterministic": "Applicable rulebook penalty service, duration, release, coincidence and manpower tables",
        "estimable": "Penalty frequency/type by observed state; overlap candidates from assessment clocks and nominal duration; shift return proxies",
        "unobserved": "PBP has no explicit Rule 19 adjudication label or canonical expiration/release event; nominal duration endpoint is not a verified service interval",
    },
    {
        "mechanic": "Faceoffs and post-faceoff sequence",
        "observed_fields": "PBP winningPlayerId/losingPlayerId/eventOwnerTeamId/zoneCode/xCoord/yCoord/timeInPeriod/situationCode; rosterSpots playerId/teamId/positionCode",
        "deterministic": "Restart placement when the source records the location and the applicable rule specifies it",
        "estimable": "Team/player faceoff win rates; next event; winner-team attempt before next faceoff and within 30 game-clock seconds",
        "unobserved": "Continuous possession, unrecorded passes and puck control between event records",
    },
    {
        "mechanic": "Shifts and substitutions",
        "observed_fields": "Shift data rows: gameId/playerId/teamId/period/startTime/endTime/duration/typeCode/eventDescription; PBP rosterSpots playerId/teamId/positionCode",
        "deterministic": "Clock arithmetic, interval ordering and eligible personnel constraints under the applicable rules",
        "estimable": "Shift duration, observed start/deployment rates and interval overlap; context is nearest preceding PBP state",
        "unobserved": "Forward line/defensive pair labels, coaching intent, fatigue, and why a change was selected",
    },
    {
        "mechanic": "Goalie presence, pulls and returns",
        "observed_fields": "PBP situationCode goalie/skater digits and shot goalieInNetId; shift playerId/teamId/period/startTime/endTime; PBP score and clock",
        "deterministic": "Personnel-count legality and rules for substitution/re-entry when all state is observed",
        "estimable": "Empty-net intervals and goalie-presence transitions by pre-event score/time, subject to shift reconciliation",
        "unobserved": "A shift endpoint alone does not prove a pull; actual target-game starter is not a valid pregame input here",
    },
    {
        "mechanic": "Shooting and scoring",
        "observed_fields": "PBP event type goal/shot-on-goal/missed-shot/blocked-shot; shootingPlayerId/scoringPlayerId/goalieInNetId/xCoord/yCoord/zoneCode/shotType/situationCode; independent box-score team SOG and goals",
        "deterministic": "Score and SOG accounting; shootout goals separated from player regulation/OT goals",
        "estimable": "Attempt-event rate, attempt-to-SOG, SOG-to-goal, and recorded type/zone/strength/goalie conditional diagnostics",
        "unobserved": "Attempts with no recorded PBP event and true release location for many blocked shots",
    },
    {
        "mechanic": "Stoppages and restarts",
        "observed_fields": "PBP stoppage details.reason, event order/clock, following faceoff details.zoneCode/xCoord/yCoord; penalty and goal records",
        "deterministic": "Restart consequence where event cause, zone and applicable rule inputs are explicit",
        "estimable": "Recorded stoppage reason frequency and ordered next-faceoff/restart sequence",
        "unobserved": "Unrecorded whistles and geometric evidence to independently adjudicate icing/offside or other spatial calls",
    },
    {
        "mechanic": "Overtime and shootouts",
        "observed_fields": "PBP periodDescriptor/timeInPeriod/event type/team owner; official final box score and shootout events/attempts",
        "deterministic": "Season-applicable OT clock, sudden-death termination, shootout paired attempts and early-clinch rules",
        "estimable": "Tie-to-OT, OT duration/goal and shootout occurrence/attempt/outcome distributions",
        "unobserved": "Decision policy for tactics and personnel unless identifiable from the observed event sequence",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_v01(data_root: Path, boxscore_root: Path):
    path = ROOT / "research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py"
    spec = importlib.util.spec_from_file_location("nhl_v01_behavior_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import the frozen corpus validator at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.DEFAULT_BOXSCORE_ROOT = boxscore_root
    corpus = module.load_corpus(data_root, (*TRAIN_SEASONS, *DEV_SEASONS))
    return module, corpus


def _read_manifest(path: Path, expected_sha: str) -> list[dict[str, str]]:
    actual = sha256_file(path)
    if actual != expected_sha:
        raise ValueError(f"manifest SHA mismatch for {path}: {actual}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_verified_body(path: Path, row: dict[str, str]) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    expected_size = int(row["bytes_gz"])
    if path.stat().st_size != expected_size:
        raise ValueError(f"compressed size mismatch: {path}")
    actual_sha = sha256_file(path)
    if actual_sha != row["sha256_gz"]:
        raise ValueError(f"compressed SHA mismatch: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        document = json.load(handle)
    return document


def _db_inventory(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {"path": str(db_path), "available": False}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        output: dict[str, Any] = {"path": str(db_path), "available": True,
                                  "access": "SQLite URI mode=ro; query_only=ON", "tables": {}}
        for table in ("players", "player_source_ids", "player_stats", "player_game_logs",
                      "team_game_results", "team_game_stats", "roster_snapshots",
                      "roster_memberships", "game_context"):
            if table not in tables:
                continue
            columns = {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}
            row: dict[str, Any] = {"columns": sorted(columns)}
            if "league" in columns:
                row["nhl_rows"] = con.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE lower(league)=\'nhl\''
                ).fetchone()[0]
                if "source" in columns:
                    row["source_counts"] = {
                        str(item[0] or "<null>"): int(item[1])
                        for item in con.execute(
                            f'SELECT source,COUNT(*) FROM "{table}" '
                            "WHERE lower(league)='nhl' GROUP BY source ORDER BY COUNT(*) DESC")
                    }
                if "season" in columns:
                    row["season_counts"] = {
                        str(item[0]): int(item[1]) for item in con.execute(
                            f'SELECT season,COUNT(*) FROM "{table}" '
                            "WHERE lower(league)='nhl' GROUP BY season ORDER BY season")
                    }
                if "game_date" in columns:
                    row["game_date_range"] = list(con.execute(
                        f'SELECT MIN(game_date),MAX(game_date) FROM "{table}" '
                        "WHERE lower(league)='nhl'").fetchone())
            if table == "roster_snapshots":
                row["nhl_rows"] = con.execute(
                    "SELECT COUNT(*) FROM roster_snapshots WHERE lower(league)='nhl'").fetchone()[0]
                row["latest_published"] = [dict(item) for item in con.execute(
                    "SELECT season,source,status,captured_at,published_at,player_count "
                    "FROM roster_snapshots WHERE lower(league)='nhl' "
                    "ORDER BY published_at DESC LIMIT 1")]
            if table == "roster_memberships" and "roster_snapshots" in tables:
                row["nhl_memberships"] = con.execute(
                    "SELECT COUNT(*) FROM roster_memberships m JOIN roster_snapshots s "
                    "ON s.id=m.snapshot_id WHERE lower(s.league)='nhl'").fetchone()[0]
            output["tables"][table] = row
        return output
    finally:
        con.close()


def _counter_add(counter: collections.Counter, key: Any, amount: int | float = 1) -> None:
    counter[key] += amount


def _context_keys(side: str, strength: str, period_type: str,
                  state: str, time_bucket: str) -> tuple[str, ...]:
    return ("all=all", f"side={side}", f"strength={strength}",
            f"period={period_type}", f"score={state}", f"time={time_bucket}")


def _record_event_rate(local: dict[str, Any], family: str, side: str,
                       strength: str, period_type: str, state: str,
                       time_bucket: str) -> None:
    for context in _context_keys(side, strength, period_type, state, time_bucket):
        local["event_rate_counts"][f"{family}|{context}"] += 1


def _new_season_stats(season: int) -> dict[str, Any]:
    return {
        "season": season,
        "games": 0,
        "events": collections.Counter(),
        "event_fields": collections.defaultdict(collections.Counter),
        "penalty_classes": collections.Counter(),
        "penalty_reasons": collections.Counter(),
        "penalty_team_identity": collections.Counter(),
        "faceoffs": collections.Counter(),
        "faceoff_next_events": collections.Counter(),
        "faceoff_shot_within_30s": collections.Counter(),
        "stoppages": collections.Counter(),
        "stoppage_restarts": collections.Counter(),
        "attempts": collections.Counter(),
        "sog_outcomes": collections.Counter(),
        "goal_outcomes": collections.Counter(),
        "attempt_composition": collections.Counter(),
        "shot_coordinates": collections.defaultdict(collections.Counter),
        "shifts": collections.Counter(),
        "shift_duration_seconds": collections.defaultdict(list),
        "shift_duration_by_context": collections.defaultdict(list),
        "shift_start_context": collections.Counter(),
        "shift_anomalies": collections.Counter(),
        "situation_reconciliation": collections.Counter(),
        "observed_strength_exposure_minutes": collections.Counter(),
        "event_rates": collections.Counter(),
        "goalie_presence": collections.Counter(),
        "goalie_transitions": collections.Counter(),
        "goalie_pull_context": collections.Counter(),
        "overtime": collections.Counter(),
        "shootout": collections.Counter(),
        "team_games": collections.defaultdict(lambda: collections.Counter()),
        "team_faceoffs": collections.defaultdict(lambda: collections.Counter()),
        "player_events": collections.defaultdict(lambda: collections.Counter()),
        "player_positions": {},
        "goalie_shots": collections.defaultdict(lambda: collections.Counter()),
        "penalty_overlap_examples": [],
        "per_game": [],
    }


def _add_binary(bucket: dict[str, Any], key: str, success: int) -> None:
    bucket[key][0] += int(success)
    bucket[key][1] += 1


def _period_terminal_time(period_type: str, events: list[dict[str, Any]]) -> int:
    if period_type == "REG":
        return 1200
    if period_type == "OT":
        terminal = [parse_clock(str(event["timeInPeriod"])) for event in events
                    if event.get("typeDescKey") in {"period-end", "game-end"}]
        return max(terminal) if terminal else max(
            (parse_clock(str(event["timeInPeriod"])) for event in events), default=0)
    return 0


def _normalize_shift_rows(document: dict[str, Any], game_id: str,
                          team_sides: dict[str, str],
                          roster: dict[str, tuple[str, str]],
                          season_stats: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    rows = document.get("data")
    if not isinstance(rows, list) or document.get("total") != len(rows):
        raise ValueError(f"{game_id}: shift total does not equal row count")
    by_period: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    seen_team_players: set[tuple[int, str, str]] = set()
    for row_index, source in enumerate(rows):
        if str(source.get("gameId")) != game_id:
            season_stats["shift_anomalies"]["game_id_mismatch"] += 1
            continue
        try:
            period = int(source["period"])
            start = parse_clock(source.get("startTime"))
            end = parse_clock(source.get("endTime"))
            declared_duration = parse_clock(source.get("duration"))
        except (KeyError, TypeError, ValueError):
            season_stats["shift_anomalies"]["unparseable_time_or_period"] += 1
            continue
        player_id = str(source.get("playerId") or "")
        team_id = str(source.get("teamId") or "")
        side = team_sides.get(team_id)
        roster_row = roster.get(player_id)
        position = roster_row[1] if roster_row and roster_row[0] == team_id else "?"
        if not side:
            season_stats["shift_anomalies"]["unknown_team_id"] += 1
            continue
        if not player_id:
            season_stats["shift_anomalies"]["missing_player_id"] += 1
            continue
        if not roster_row:
            season_stats["shift_anomalies"]["player_not_in_pbp_roster_spots"] += 1
        elif roster_row[0] != team_id:
            season_stats["shift_anomalies"]["player_team_disagreement"] += 1
            position = "?"
        season_stats["shifts"]["rows_total"] += 1
        if start == end:
            season_stats["shifts"]["zero_duration_annotations"] += 1
            continue
        if end < start or declared_duration != end - start:
            season_stats["shift_anomalies"]["duration_disagrees_with_endpoints"] += 1
        if start > (1200 if period <= 3 else 300):
            season_stats["shift_anomalies"]["start_outside_period"] += 1
        if end > (1200 if period <= 3 else 300):
            season_stats["shift_anomalies"]["end_outside_period"] += 1
        normalized = {"row_index": row_index, "period": period, "start": start,
                      "end": end, "player_id": player_id, "team_id": team_id,
                      "side": side, "position": position,
                      "type_code": str(source.get("typeCode") or ""),
                      "event_description": source.get("eventDescription")}
        by_period[period].append(normalized)
        season_stats["shifts"]["positive_duration_rows"] += 1
        season_stats["shifts"][f"position:{position}"] += 1
        season_stats["shifts"][f"type_code:{normalized['type_code'] or '<missing>'}"] += 1
        season_stats["shift_duration_seconds"][position].append(end - start)
        season_stats["player_events"][player_id]["shift_seconds"] += end - start
        if position != "?":
            season_stats["player_positions"][player_id] = position
        seen_team_players.add((period, team_id, player_id))
    season_stats["shifts"]["distinct_period_team_players"] += len(seen_team_players)
    for (period, team_id, player_id) in seen_team_players:
        player_id_key = player_id
        season_stats["player_events"][player_id_key]["has_shift_evidence"] += 1
    for period, period_rows in by_period.items():
        by_player: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
        for row in period_rows:
            if row["player_id"]:
                by_player[row["player_id"]].append((row["start"], row["end"]))
        for intervals in by_player.values():
            intervals.sort()
            if any(curr[0] < prior[1] for prior, curr in zip(intervals, intervals[1:])):
                season_stats["shift_anomalies"]["same_player_overlapping_rows"] += 1
    return by_period


def _event_owner_side(event: dict[str, Any], team_sides: dict[str, str]) -> str | None:
    owner = (event.get("details") or {}).get("eventOwnerTeamId")
    return team_sides.get(str(owner)) if owner is not None else None


def _next_faceoff(events: list[dict[str, Any]], start: int) -> int | None:
    for index in range(start + 1, len(events)):
        if events[index].get("typeDescKey") == "faceoff":
            return index
    return None


def _store_field_coverage(stats: dict[str, Any], event: dict[str, Any]) -> None:
    event_type = str(event.get("typeDescKey") or "<missing>")
    details = event.get("details") or {}
    present = {
        "event_id": event.get("eventId") is not None,
        "owner_team_id": details.get("eventOwnerTeamId") is not None,
        "situation_code": decode_situation_code(event.get("situationCode")) is not None,
        "x_and_y": details.get("xCoord") is not None and details.get("yCoord") is not None,
        "zone_code": details.get("zoneCode") is not None,
        "shot_type": details.get("shotType") is not None,
        "shooter_id": details.get("shootingPlayerId") is not None
                       or details.get("scoringPlayerId") is not None,
        "goalie_id": details.get("goalieInNetId") is not None,
        "penalty_kind": details.get("typeCode") is not None,
        "penalty_duration": details.get("duration") is not None,
        "penalty_committed_player": details.get("committedByPlayerId") is not None,
        "penalty_served_by_player": details.get("servedByPlayerId") is not None,
        "penalty_event_owner_team": details.get("eventOwnerTeamId") is not None,
        "penalty_reason": details.get("descKey") is not None,
        "faceoff_winner": details.get("winningPlayerId") is not None,
        "faceoff_loser": details.get("losingPlayerId") is not None,
        "stoppage_reason": details.get("reason") is not None,
    }
    stats["event_fields"][event_type]["events"] += 1
    for field, has_value in present.items():
        stats["event_fields"][event_type][field + ("_present" if has_value else "_missing")] += 1


def _cluster_interval(game_values: list[tuple[int, int]], *, reps: int,
                      seed: int) -> list[float] | None:
    if not game_values or sum(den for _, den in game_values) < 100:
        return None
    rng = random.Random(seed)
    n_games = len(game_values)
    rates = []
    for _ in range(reps):
        num = den = 0
        for _ in range(n_games):
            success, trials = game_values[rng.randrange(n_games)]
            num += success
            den += trials
        if den:
            rates.append(num / den)
    rates.sort()
    return [rates[int(0.025 * (len(rates) - 1))],
            rates[int(0.975 * (len(rates) - 1))]] if rates else None


def _load_game_source(data_root: Path, pbp_rows: dict[str, dict[str, str]],
                      shift_rows: dict[str, dict[str, str]], game_id: str):
    pbp = _read_verified_body(data_root / "raw/pbp" / f"{game_id}.json.gz", pbp_rows[game_id])
    shifts = _read_verified_body(data_root / "raw/shifts" / f"{game_id}.json.gz", shift_rows[game_id])
    return pbp, shifts


def _analyze_game(pbp: dict[str, Any], shifts_doc: dict[str, Any], summary: Any,
                  season_stats: dict[str, Any], *, training: bool,
                  shot_models: dict[str, dict[str, float]] | None = None,
                  faceoff_rates: dict[str, float] | None = None) -> dict[str, Any]:
    game_id = str(pbp.get("id"))
    home_id = str((pbp.get("homeTeam") or {}).get("id"))
    away_id = str((pbp.get("awayTeam") or {}).get("id"))
    team_sides = {home_id: "home", away_id: "away"}
    team_ids = {"home": home_id, "away": away_id}
    roster: dict[str, tuple[str, str]] = {}
    for item in pbp.get("rosterSpots") or []:
        player_id = str(item.get("playerId") or "")
        if player_id:
            roster[player_id] = (str(item.get("teamId") or ""),
                                 str(item.get("positionCode") or "?"))
    period_events: dict[tuple[str, int], list[dict[str, Any]]] = collections.defaultdict(list)
    all_events = sorted(enumerate(pbp.get("plays") or []),
                        key=lambda pair: (int(pair[1].get("sortOrder", pair[0])), pair[0]))
    for _, event in all_events:
        descriptor = event.get("periodDescriptor") or {}
        kind = str(descriptor.get("periodType") or "")
        number = int(descriptor.get("number") or 0)
        if kind and number:
            period_events[(kind, number)].append(event)
    shift_by_period = _normalize_shift_rows(shifts_doc, game_id, team_sides, roster, season_stats)
    local: dict[str, Any] = {
        "game_id": game_id, "home_id": home_id, "away_id": away_id,
        "game_date": str(pbp.get("gameDate") or ""),
        "metric_counts": collections.defaultdict(
            lambda: collections.defaultdict(lambda: [0, 0])),
        "event_rate_counts": collections.Counter(),
        "event_exposure_minutes": collections.Counter(),
        "game_event_counts": collections.Counter(),
        "score_losses": collections.defaultdict(lambda: [0.0, 0.0]),
        "team_rows": collections.defaultdict(collections.Counter),
        "event_records": [],
    }
    scores = {"home": 0, "away": 0}
    prev_goalie_presence: dict[str, int] = {}

    for period_key in sorted(period_events, key=lambda key: (key[1], key[0])):
        period_type, period_number = period_key
        events = period_events[period_key]
        for event in events:
            _store_field_coverage(season_stats, event)
        if period_type == "SO":
            for event in events:
                event_type = str(event.get("typeDescKey") or "")
                details = event.get("details") or {}
                side = _event_owner_side(event, team_sides)
                season_stats["events"][event_type] += 1
                local["game_event_counts"][event_type] += 1
                if event_type in {"goal", "shot-on-goal", "missed-shot", "failed-shot-attempt"}:
                    season_stats["shootout"]["attempts"] += 1
                    if side:
                        season_stats["shootout"][f"attempts_{side}"] += 1
                    if event_type == "goal":
                        season_stats["shootout"]["goals"] += 1
                        if side:
                            season_stats["shootout"][f"goals_{side}"] += 1
                if event_type == "shootout-complete":
                    season_stats["shootout"]["complete_markers"] += 1
            continue

        shifts = shift_by_period.get(period_number, [])
        period_end = _period_terminal_time(period_type, events)
        by_time: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        for event in events:
            by_time[parse_clock(str(event.get("timeInPeriod")))].append(event)
        starts: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        ends: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        for shift in shifts:
            if shift["start"] < shift["end"] and shift["end"] <= period_end:
                starts[shift["start"]].append(shift)
                ends[shift["end"]].append(shift)
        times = sorted({0, period_end, *by_time.keys(), *starts.keys(), *ends.keys()})
        active_rows: dict[int, dict[str, Any]] = {}

        for time_index, now in enumerate(times):
            for shift in ends.get(now, []):
                active_rows.pop(shift["row_index"], None)
            for shift in starts.get(now, []):
                active_rows[shift["row_index"]] = shift
            next_time = times[time_index + 1] if time_index + 1 < len(times) else now
            by_player: dict[str, tuple[str, str]] = {}
            duplicate_players = set()
            for row in active_rows.values():
                pid = row["player_id"]
                prior = by_player.get(pid)
                if prior is not None:
                    duplicate_players.add(pid)
                else:
                    by_player[pid] = (row["side"], row["position"])
            if duplicate_players:
                season_stats["situation_reconciliation"][
                    "duplicate_active_player_track_ids_at_event_snapshot"] += len(duplicate_players)
            lineup = {side: {"skaters": 0, "goalies": 0, "unknown": 0}
                      for side in ("home", "away")}
            for side, position in by_player.values():
                if position == "G":
                    lineup[side]["goalies"] += 1
                elif position in {"C", "L", "R", "D", "F"}:
                    lineup[side]["skaters"] += 1
                else:
                    lineup[side]["unknown"] += 1

            for event in by_time.get(now, []):
                event_type = str(event.get("typeDescKey") or "<missing>")
                details = event.get("details") or {}
                owner_side = _event_owner_side(event, team_sides)
                code = decode_situation_code(event.get("situationCode"))
                goalie_event_transitions = []
                if event_type not in {"period-start", "period-end", "game-end"}:
                    season_stats["events"][event_type] += 1
                    local["game_event_counts"][event_type] += 1
                if code is not None:
                    season_stats["situation_reconciliation"]["decodable_codes"] += 1
                    has_unknown_positions = any(lineup[side]["unknown"] for side in ("home", "away"))
                    if duplicate_players:
                        season_stats["situation_reconciliation"][
                            "code_comparison_excluded_duplicate_active_tracks"] += 1
                    if has_unknown_positions:
                        season_stats["situation_reconciliation"][
                            "code_comparison_excluded_unknown_shift_positions"] += 1
                    if not duplicate_players and not has_unknown_positions:
                        line_agrees = (
                            code["home_skaters"] == lineup["home"]["skaters"]
                            and code["away_skaters"] == lineup["away"]["skaters"]
                            and code["home_goalie"] == int(lineup["home"]["goalies"] > 0)
                            and code["away_goalie"] == int(lineup["away"]["goalies"] > 0)
                        )
                        season_stats["situation_reconciliation"][
                            "codes_compared_with_unambiguous_shift_lineup"] += 1
                        season_stats["situation_reconciliation"][
                            "codes_match_shift_lineup" if line_agrees
                            else "codes_disagree_with_shift_lineup"] += 1
                else:
                    season_stats["situation_reconciliation"]["undecodable_or_missing_codes"] += 1
                if code is not None:
                    home_skaters, away_skaters = code["home_skaters"], code["away_skaters"]
                    source_strength = f"{home_skaters}v{away_skaters}"
                    for side in ("home", "away"):
                        season_stats["goalie_presence"][
                            f"{side}_goalie_{'in' if code[side + '_goalie'] else 'out'}"] += 1
                        old = prev_goalie_presence.get(side)
                        current = code[side + "_goalie"]
                        if old is not None and old != current:
                            transition = "return" if current else "pull"
                            season_stats["goalie_transitions"][f"{side}_{transition}"] += 1
                            goalie_event_transitions.append((side, transition))
                        prev_goalie_presence[side] = current
                else:
                    source_strength = "unknown"

                pre_score = dict(scores)
                event_remaining = max(0, (1200 if period_type == "REG" else 300) - now)
                when = time_remaining_bucket(period_type, 1200 if period_type == "REG" else 300, now)
                for transition_side, transition in goalie_event_transitions:
                    opponent = "away" if transition_side == "home" else "home"
                    state = score_state(pre_score[transition_side], pre_score[opponent])
                    season_stats["goalie_pull_context"][
                        f"{transition_side}:{transition}:{state}:{when}"] += 1
                side_strength = (strength_for_side(home_skaters, away_skaters, owner_side)
                                 if code is not None and owner_side else "unknown")
                shift_strength = (
                    strength_for_side(lineup["home"]["skaters"], lineup["away"]["skaters"], owner_side)
                    if owner_side and not lineup["home"]["unknown"] and not lineup["away"]["unknown"]
                    else "unknown")
                annotated = {
                    "event_id": event.get("eventId"), "sort_order": event.get("sortOrder"),
                    "type": event_type, "period_type": period_type,
                    "period": period_number, "time": now, "clock": event.get("timeInPeriod"),
                    "side": owner_side, "details": details, "code": code,
                    "penalty_team_id": (
                        roster.get(str(details.get("committedByPlayerId") or ""),
                                   (str(details.get("eventOwnerTeamId") or ""), "?"))[0]
                        if event_type == "penalty" else None),
                    "shift_lineup": lineup, "strength": side_strength,
                    "active_duplicate_player_ids": len(duplicate_players),
                    "shift_positions_complete": not any(
                        lineup[side]["unknown"] for side in ("home", "away")),
                    "score_before": dict(pre_score), "score_state": (
                        score_state(pre_score[owner_side], pre_score["away" if owner_side == "home" else "home"])
                        if owner_side else "unknown"),
                    "time_bucket": when, "remaining_seconds": event_remaining,
                }
                local["event_records"].append(annotated)

                if event_type == "penalty":
                    kind = str(details.get("typeCode") or "<missing>")
                    duration = str(details.get("duration") or "<missing>")
                    reason = str(details.get("descKey") or "<missing>")
                    season_stats["penalty_classes"][f"{kind}:{duration}"] += 1
                    season_stats["penalty_reasons"][reason] += 1
                    committed_id = str(details.get("committedByPlayerId") or "")
                    committed_roster = roster.get(committed_id)
                    committed_side = (team_sides.get(committed_roster[0])
                                      if committed_roster else None)
                    if committed_side:
                        match = committed_side == owner_side
                        season_stats["penalty_team_identity"][
                            "committed_player_team_matches_event_owner" if match
                            else "committed_player_team_differs_from_event_owner"] += 1
                    else:
                        season_stats["penalty_team_identity"]["committed_player_team_unresolved"] += 1
                    penalty_side = committed_side or owner_side
                    if penalty_side:
                        penalty_strength = (
                            strength_for_side(lineup["home"]["skaters"],
                                              lineup["away"]["skaters"], penalty_side)
                            if not lineup["home"]["unknown"] and not lineup["away"]["unknown"]
                            else "unknown")
                        penalty_state = score_state(
                            pre_score[penalty_side], pre_score["away" if penalty_side == "home" else "home"])
                        _record_event_rate(local, "penalty", penalty_side, penalty_strength,
                                           period_type, penalty_state, when)
                if event_type == "faceoff":
                    season_stats["faceoffs"]["total"] += 1
                    winner_id = str(details.get("winningPlayerId") or "")
                    loser_id = str(details.get("losingPlayerId") or "")
                    winner_roster = roster.get(winner_id)
                    loser_roster = roster.get(loser_id)
                    winner_team = winner_roster[0] if winner_roster else ""
                    loser_team = loser_roster[0] if loser_roster else ""
                    if winner_team in team_sides:
                        winner_side = team_sides[winner_team]
                        season_stats["faceoffs"]["winner_id_present"] += 1
                        season_stats["team_faceoffs"][winner_team]["won"] += 1
                        season_stats["team_faceoffs"][winner_team]["total"] += 1
                        local["team_rows"][winner_team]["faceoff_wins"] += 1
                        winner_strength = (
                            strength_for_side(lineup["home"]["skaters"],
                                              lineup["away"]["skaters"], winner_side)
                            if not lineup["home"]["unknown"] and not lineup["away"]["unknown"]
                            else "unknown")
                        winner_state = score_state(
                            pre_score[winner_side], pre_score["away" if winner_side == "home" else "home"])
                        _record_event_rate(local, "faceoff_win", winner_side, winner_strength,
                                           period_type, winner_state, when)
                        season_stats["player_events"][winner_id]["faceoffs_won"] += 1
                        season_stats["player_events"][winner_id]["faceoff_participations"] += 1
                    if loser_team in team_sides:
                        season_stats["team_faceoffs"][loser_team]["total"] += 1
                        local["team_rows"][loser_team]["faceoff_losses"] += 1
                        season_stats["player_events"][loser_id]["faceoff_participations"] += 1
                    season_stats["faceoffs"][
                        "winner_owner_match" if winner_team and winner_team == str(details.get("eventOwnerTeamId"))
                        else "winner_owner_mismatch_or_missing"] += 1
                    if not training and faceoff_rates is not None and winner_team in team_sides:
                        home_rate = faceoff_rates.get(home_id, 0.5)
                        away_rate = faceoff_rates.get(away_id, 0.5)
                        p_home = home_rate / max(1e-12, home_rate + away_rate)
                        y_home = int(winner_team == home_id)
                        for name, probability in (("team_rate", p_home), ("league_50", 0.5)):
                            local["score_losses"][f"faceoff:{name}:brier"][0] += (probability-y_home)**2
                            local["score_losses"][f"faceoff:{name}:log_loss"][0] += -math.log(
                                max(1e-12, probability if y_home else 1-probability))
                            local["score_losses"][f"faceoff:{name}:brier"][1] += 1
                            local["score_losses"][f"faceoff:{name}:log_loss"][1] += 1
                    zone = str(details.get("zoneCode") or "<missing>")
                    season_stats["faceoffs"][f"zone:{zone}"] += 1
                    if code is not None:
                        season_stats["faceoffs"][f"strength:{source_strength}"] += 1
                if event_type == "stoppage":
                    season_stats["stoppages"][str(details.get("reason") or "<missing>")] += 1

                if event_type in ATTEMPTS:
                    if owner_side:
                        _record_event_rate(local, "attempt", owner_side, shift_strength,
                                           period_type, score_state(
                                               pre_score[owner_side],
                                               pre_score["away" if owner_side == "home" else "home"]), when)
                    season_stats["attempts"]["all"] += 1
                    season_stats["attempts"][f"event:{event_type}"] += 1
                    if code is not None:
                        season_stats["attempts"][f"strength:{side_strength}"] += 1
                    if owner_side:
                        season_stats["event_rates"][f"attempts:{side_strength}"] += 1
                    season_stats["attempt_composition"][f"shot_type:{details.get('shotType') or '<missing>'}"] += 1
                    season_stats["attempt_composition"][f"zone:{details.get('zoneCode') or '<missing>'}"] += 1
                    if details.get("xCoord") is not None and details.get("yCoord") is not None:
                        season_stats["shot_coordinates"][event_type]["xy_present"] += 1
                    else:
                        season_stats["shot_coordinates"][event_type]["xy_missing"] += 1
                    is_sog = int(event_type in SOG_EVENTS)
                    shot_type = str(details.get("shotType") or "<missing>")
                    zone = str(details.get("zoneCode") or "<missing>")
                    goalie_id = str(details.get("goalieInNetId") or "<missing>")
                    _add_binary(local["metric_counts"]["sog_by_strength"], side_strength, is_sog)
                    _add_binary(local["metric_counts"]["sog_by_shot_type"],
                                shot_type, is_sog)
                    _add_binary(local["metric_counts"]["sog_by_zone"],
                                str(details.get("zoneCode") or "<missing>"), is_sog)
                    _add_binary(local["metric_counts"]["sog_all"], "all", is_sog)
                    if is_sog:
                        if owner_side:
                            _record_event_rate(local, "sog", owner_side, shift_strength,
                                               period_type, score_state(
                                                   pre_score[owner_side],
                                                   pre_score["away" if owner_side == "home" else "home"]), when)
                        season_stats["sog_outcomes"]["all"] += 1
                        season_stats["sog_outcomes"][f"event:{event_type}"] += 1
                        is_goal = int(event_type == "goal")
                        _add_binary(local["metric_counts"]["goal_by_strength"], side_strength, is_goal)
                        _add_binary(local["metric_counts"]["goal_by_shot_type"], shot_type, is_goal)
                        _add_binary(local["metric_counts"]["goal_by_zone"], zone, is_goal)
                        _add_binary(local["metric_counts"]["goal_by_goalie"], goalie_id, is_goal)
                        _add_binary(local["metric_counts"]["goal_all"], "all", is_goal)
                        if goalie_id != "<missing>":
                            season_stats["goalie_shots"][goalie_id]["shots_against"] += 1
                            season_stats["goalie_shots"][goalie_id]["goals_against"] += is_goal
                        shooter = str(details.get("shootingPlayerId") or details.get("scoringPlayerId") or "")
                        if shooter:
                            season_stats["player_events"][shooter]["sog"] += 1
                            season_stats["player_events"][shooter]["goals"] += is_goal
                    if owner_side:
                        local["team_rows"][team_ids[owner_side]]["attempts"] += 1
                        local["team_rows"][team_ids[owner_side]]["sog"] += is_sog
                    if not training and shot_models is not None:
                        # These are conditional conversion diagnostics given an observed
                        # target-shot description; they are not pregame inputs or a full-game forecast.
                        metrics = ("sog_all", "sog_by_strength", "sog_by_shot_type",
                                   "sog_by_zone")
                        for metric in metrics:
                            group_key = ("all" if metric.endswith("_all") else side_strength
                                         if metric.endswith("_strength") else shot_type
                                         if metric.endswith("_shot_type") else zone)
                            p = shot_models[metric].get(group_key, shot_models["sog_all"]["all"])
                            y = is_sog
                            local["score_losses"][f"{metric}:brier"][0] += (p-y)**2
                            local["score_losses"][f"{metric}:log_loss"][0] += -math.log(
                                max(1e-12, p if y else 1.0-p))
                            local["score_losses"][f"{metric}:brier"][1] += 1
                            local["score_losses"][f"{metric}:log_loss"][1] += 1
                        if is_sog:
                            for metric in ("goal_all", "goal_by_strength", "goal_by_shot_type",
                                           "goal_by_zone", "goal_by_goalie"):
                                group_key = ("all" if metric.endswith("_all") else side_strength
                                             if metric.endswith("_strength") else shot_type
                                             if metric.endswith("_shot_type") else zone
                                             if metric.endswith("_zone") else goalie_id)
                                p = shot_models[metric].get(group_key, shot_models["goal_all"]["all"])
                                y = int(event_type == "goal")
                                local["score_losses"][f"{metric}:brier"][0] += (p-y)**2
                                local["score_losses"][f"{metric}:log_loss"][0] += -math.log(
                                    max(1e-12, p if y else 1.0-p))
                                local["score_losses"][f"{metric}:brier"][1] += 1
                                local["score_losses"][f"{metric}:log_loss"][1] += 1

                if event_type in {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}:
                    shooter = str(details.get("shootingPlayerId") or details.get("scoringPlayerId") or "")
                    if shooter:
                        season_stats["player_events"][shooter]["shot_events"] += 1
                    if event_type == "goal" and period_type in {"REG", "OT"} and owner_side:
                        scores[owner_side] += 1
                        _record_event_rate(local, "goal", owner_side, shift_strength,
                                           period_type, score_state(
                                               pre_score[owner_side],
                                               pre_score["away" if owner_side == "home" else "home"]), when)
                    if event_type in {"goal", "shot-on-goal"} and owner_side:
                        season_stats["event_rates"][f"sog:{side_strength}"] += 1
                if owner_side and event_type in {"goal", "shot-on-goal", "missed-shot", "blocked-shot",
                                                 "faceoff", "penalty", "giveaway", "takeaway", "hit"}:
                    season_stats["event_rates"][f"{event_type}:{side_strength}"] += 1
                    player_event_id = str(details.get("shootingPlayerId")
                                          or details.get("scoringPlayerId")
                                          or details.get("winningPlayerId")
                                          or details.get("committedByPlayerId")
                                          or details.get("playerId") or "<unknown>")
                    season_stats["player_events"][player_event_id][f"event:{event_type}"] += 1

                local["event_records"][-1]["score_after"] = dict(scores)

            if next_time <= now or period_type == "SO":
                continue
            duration_minutes = (next_time - now) / 60.0
            if duration_minutes <= 0:
                continue
            for side in ("home", "away"):
                own = lineup[side]["skaters"]
                opp_side = "away" if side == "home" else "home"
                opp = lineup[opp_side]["skaters"]
                if lineup[side]["unknown"] or lineup[opp_side]["unknown"]:
                    strength = "unknown"
                else:
                    strength = f"{own}v{opp}"
                season_stats["observed_strength_exposure_minutes"][f"{side}:{strength}"] += duration_minutes
                own_score, opp_score = scores[side], scores[opp_side]
                state = score_state(own_score, opp_score)
                interval_time_bucket = time_remaining_bucket(
                    period_type, 1200 if period_type == "REG" else 300, now)
                season_stats["observed_strength_exposure_minutes"][
                    f"{side}:{strength}:{period_type}:{state}"] += duration_minutes
                for context in _context_keys(side, strength, period_type, state,
                                             interval_time_bucket):
                    local["event_exposure_minutes"][context] += duration_minutes
                if lineup[side]["goalies"] == 0 and own >= 6:
                    season_stats["observed_strength_exposure_minutes"][
                        f"{side}:empty_net:{state}"] += duration_minutes
                # The exposure is also retained per game for cluster uncertainty.
                local.setdefault("exposure", collections.Counter())
                local["exposure"][f"{side}:{strength}"] += duration_minutes

    # Faceoff sequence outcomes are descriptive transition labels, not possession truth.
    event_records = local["event_records"]
    for index, row in enumerate(event_records):
        if row["type"] == "faceoff":
            same_period = [candidate for candidate in event_records[index+1:]
                           if (candidate["period_type"], candidate["period"]) ==
                           (row["period_type"], row["period"])]
            next_row = same_period[0] if same_period else None
            next_type = next_row["type"] if next_row else "period_end_or_missing"
            season_stats["faceoff_next_events"][next_type] += 1
            winner_id = str((row["details"] or {}).get("winningPlayerId") or "")
            winner_team_id = roster.get(winner_id, ("", "?"))[0]
            winner_side = team_sides.get(winner_team_id)
            if winner_side:
                next_faceoff_idx = next((j for j in range(index+1, len(event_records))
                                         if event_records[j]["type"] == "faceoff"
                                         and (event_records[j]["period_type"], event_records[j]["period"]) ==
                                         (row["period_type"], row["period"])), None)
                shot_found = False
                for candidate in event_records[index+1:next_faceoff_idx or len(event_records)]:
                    if (candidate["period_type"], candidate["period"]) != (row["period_type"], row["period"]):
                        continue
                    if candidate["time"] - row["time"] > 30:
                        break
                    if candidate["type"] in ATTEMPTS and candidate["side"] == winner_side:
                        shot_found = True
                        break
                season_stats["faceoff_shot_within_30s"][
                    f"{row['strength']}:{'yes' if shot_found else 'no'}"] += 1
                local["metric_counts"]["faceoff_shot_30s"][row["strength"]][1] += 1
                local["metric_counts"]["faceoff_shot_30s"][row["strength"]][0] += int(shot_found)
                if not training and shot_models is not None:
                    for name, probability in (
                        ("parent", shot_models["faceoff_shot_parent"]["all"]),
                        ("strength", shot_models["faceoff_shot_by_strength"].get(
                            row["strength"], shot_models["faceoff_shot_parent"]["all"])),
                    ):
                        label = int(shot_found)
                        local["score_losses"][f"faceoff_shot:{name}:brier"][0] += (probability-label)**2
                        local["score_losses"][f"faceoff_shot:{name}:log_loss"][0] += -math.log(
                            max(1e-12, probability if label else 1-probability))
                        local["score_losses"][f"faceoff_shot:{name}:brier"][1] += 1
                        local["score_losses"][f"faceoff_shot:{name}:log_loss"][1] += 1
        if row["type"] == "stoppage":
            next_faceoff_idx = next((j for j in range(index+1, len(event_records))
                                     if event_records[j]["type"] == "faceoff"
                                     and (event_records[j]["period_type"], event_records[j]["period"]) ==
                                     (row["period_type"], row["period"])), None)
            if next_faceoff_idx is None:
                season_stats["stoppage_restarts"]["no_faceoff_before_period_end_or_missing"] += 1
            else:
                restart = event_records[next_faceoff_idx]
                zone = str((restart["details"] or {}).get("zoneCode") or "<missing>")
                reason = str((row["details"] or {}).get("reason") or "<missing>")
                season_stats["stoppage_restarts"][f"{reason}->{zone}"] += 1

    _find_penalty_overlaps(local["event_records"], game_id, team_sides,
                           shift_by_period, season_stats)

    # Use the last preceding PBP snapshot as a state proxy for the shift start.
    # Shift clocks are observed; the exact policy/intent behind a change is not.
    event_by_period: dict[tuple[str, int], list[dict[str, Any]]] = collections.defaultdict(list)
    for event in event_records:
        event_by_period[(event["period_type"], event["period"])].append(event)
    for period, shifts in shift_by_period.items():
        period_records = event_by_period.get(("REG", period), [])
        period_type = "REG"
        if not period_records:
            period_records = event_by_period.get(("OT", period), [])
            period_type = "OT"
        record_times = [event["time"] for event in period_records]
        for shift in shifts:
            index = bisect.bisect_right(record_times, shift["start"]) - 1
            preceding = period_records[index] if index >= 0 else None
            if preceding is None or preceding["code"] is None:
                strength, state = "unknown", "unknown"
            else:
                code = preceding["code"]
                strength = strength_for_side(code["home_skaters"], code["away_skaters"], shift["side"])
                score = preceding.get("score_after", preceding.get("score_before", {}))
                opponent = "away" if shift["side"] == "home" else "home"
                state = score_state(int(score.get(shift["side"], 0)), int(score.get(opponent, 0)))
            season_stats["shift_start_context"][f"{shift['side']}:{strength}:{state}"] += 1
            season_stats["shift_duration_by_context"][
                f"{shift['position']}:{shift['side']}:{strength}:{state}"].append(
                    shift["end"]-shift["start"])

    # Game-level source outcomes are the independent box-score-validated summary.
    local["result"] = {
        "reg_ot_goals": dict(summary.reg_ot_score),
        "official_final_score": {"home": summary.home_score, "away": summary.away_score},
        "sog": {"home": summary.home_sog, "away": summary.away_sog},
        "last_period_type": summary.source_last_period_type,
    }
    season_stats["games"] += 1
    season_stats["overtime"]["games"] += 1
    season_stats["overtime"][f"last_period:{summary.source_last_period_type}"] += 1
    if summary.source_last_period_type in {"OT", "SO"}:
        season_stats["overtime"]["games_reaching_ot"] += 1
    if summary.source_last_period_type == "SO":
        season_stats["overtime"]["games_reaching_shootout"] += 1
    for side in ("home", "away"):
        team_id = team_ids[side]
        score_for = summary.reg_ot_score[side]
        score_against = summary.reg_ot_score["away" if side == "home" else "home"]
        row = season_stats["team_games"][team_id]
        row["games"] += 1
        row["goals_for"] += score_for
        row["goals_against"] += score_against
        row["sog_for"] += summary.home_sog if side == "home" else summary.away_sog
        row["sog_against"] += summary.away_sog if side == "home" else summary.home_sog
        local["team_rows"][team_id]["games"] += 1
        local["team_rows"][team_id]["goals_for"] += score_for
        local["team_rows"][team_id]["goals_against"] += score_against
        local["team_rows"][team_id]["sog_for"] += summary.home_sog if side == "home" else summary.away_sog
        local["team_rows"][team_id]["sog_against"] += summary.away_sog if side == "home" else summary.home_sog

    for event in all_events:
        source = event[1]
        desc = source.get("periodDescriptor") or {}
        if desc.get("periodType") == "OT":
            season_stats["overtime"]["ot_events"] += 1
            if source.get("typeDescKey") == "goal":
                season_stats["overtime"]["ot_goals"] += 1
    local.pop("event_records", None)
    season_stats["per_game"].append(local)
    return local


def _penalty_shift_return_evidence(penalty: dict[str, Any],
                                   shift_by_period: dict[int, list[dict[str, Any]]]
                                   ) -> dict[str, Any]:
    details = penalty["event"]["details"] or {}
    player_id = str(details.get("servedByPlayerId")
                    or details.get("committedByPlayerId") or "")
    if not player_id:
        return {"player_id": None, "status": "no served/committed player ID"}
    period_rows = shift_by_period.get(int(penalty["event"]["period"]), [])
    same_player = [row for row in period_rows
                   if row["player_id"] == player_id
                   and row["team_id"] == penalty["team_id"]]
    start = int(penalty["event"]["time"])
    estimated_end = int(penalty["end_estimate"])
    first_return = min((row["start"] for row in same_player if row["start"] >= estimated_end),
                       default=None)
    spans_estimated_service = any(row["start"] < estimated_end and row["end"] > start
                                  for row in same_player)
    return {
        "player_id": player_id,
        "identity_source": "servedByPlayerId" if details.get("servedByPlayerId")
        else "committedByPlayerId fallback",
        "shift_rows_for_player_in_period": len(same_player),
        "shift_overlaps_estimated_penalty_interval": spans_estimated_service,
        "first_shift_start_at_or_after_estimated_duration_endpoint": first_return,
        "seconds_after_estimated_duration_endpoint": (
            first_return - estimated_end if first_return is not None else None),
        "status": "shift-chart proxy; penalty clock start and exact release are not explicitly recorded",
    }


def _find_penalty_overlaps(events: list[dict[str, Any]], game_id: str,
                           team_sides: dict[str, str],
                           shift_by_period: dict[int, list[dict[str, Any]]],
                           stats: dict[str, Any]) -> None:
    def manpower_counts(record: dict[str, Any]) -> tuple[int, int] | None:
        code = record.get("code")
        if code is None:
            return None
        return code["home_skaters"], code["away_skaters"]

    def shift_counts_agree(record: dict[str, Any], expected: tuple[int, int]) -> bool:
        lineup = record.get("shift_lineup") or {}
        return (
            record.get("active_duplicate_player_ids", 0) == 0
            and record.get("shift_positions_complete") is True
            and (lineup.get("home", {}).get("skaters"),
                 lineup.get("away", {}).get("skaters")) == expected
            and lineup.get("home", {}).get("goalies") == 1
            and lineup.get("away", {}).get("goalies") == 1
        )

    by_period: dict[tuple[str, int], list[dict[str, Any]]] = collections.defaultdict(list)
    for index, event in enumerate(events):
        if event["period_type"] in {"REG", "OT"}:
            by_period[(event["period_type"], event["period"])].append(
                {**event, "_sequence_index": index})

    for (period_type, period), period_events in by_period.items():
        penalties = []
        faceoff_indices = [index for index, event in enumerate(period_events)
                           if event["type"] == "faceoff"]
        for index, event in enumerate(period_events):
            if event["type"] != "penalty":
                continue
            details = event["details"] or {}
            kind = str(details.get("typeCode") or "")
            duration = details.get("duration")
            if kind not in MANPOWER_PENALTIES or not isinstance(duration, (int, float)):
                continue
            team_id = str(event.get("penalty_team_id") or details.get("eventOwnerTeamId") or "")
            side = team_sides.get(team_id)
            if side not in {"home", "away"}:
                continue
            penalty = {"event": event, "index": index, "kind": kind,
                       "duration": int(duration) * 60, "team_id": team_id, "side": side,
                       "end_estimate": int(event["time"]) + int(duration) * 60}
            penalties.append(penalty)

        for index, first in enumerate(penalties):
            for second in penalties[index + 1:]:
                if first["side"] != second["side"] and first["event"]["time"] == second["event"]["time"]:
                    stats["penalty_classes"]["same_clock_opposing_record_pairs"] += 1

        for current_faceoff_index in faceoff_indices:
            previous_faceoffs = [index for index in faceoff_indices if index < current_faceoff_index]
            if not previous_faceoffs:
                continue
            previous_faceoff_index = previous_faceoffs[-1]
            previous_faceoff = period_events[previous_faceoff_index]
            current_faceoff = period_events[current_faceoff_index]
            new_penalties = [penalty for penalty in penalties
                             if previous_faceoff_index < penalty["index"] < current_faceoff_index]
            if not new_penalties:
                continue
            pre_counts = manpower_counts(previous_faceoff)
            post_counts = manpower_counts(current_faceoff)
            if pre_counts not in {(5, 4), (4, 5)} or post_counts != (4, 4):
                continue
            if (not shift_counts_agree(previous_faceoff, pre_counts)
                    or not shift_counts_agree(current_faceoff, post_counts)):
                continue
            if (previous_faceoff["code"]["home_goalie"] != 1
                    or previous_faceoff["code"]["away_goalie"] != 1
                    or current_faceoff["code"]["home_goalie"] != 1
                    or current_faceoff["code"]["away_goalie"] != 1):
                continue
            if any(event["type"] == "goal"
                   for event in period_events[previous_faceoff_index + 1:current_faceoff_index]):
                continue

            short_side = "home" if pre_counts[0] < pre_counts[1] else "away"
            full_side = "away" if short_side == "home" else "home"
            if {penalty["side"] for penalty in new_penalties} != {full_side}:
                continue
            current_time = int(current_faceoff["time"])

            active_prior_candidates = []
            for prior in penalties:
                if prior["index"] >= previous_faceoff_index or prior["side"] != short_side:
                    continue
                if prior["end_estimate"] <= current_time:
                    continue
                first_faceoff_after = next((face_index for face_index in faceoff_indices
                                            if face_index > prior["index"]), None)
                if first_faceoff_after is None or first_faceoff_after > previous_faceoff_index:
                    continue
                first_restart = period_events[first_faceoff_after]
                if manpower_counts(first_restart) != pre_counts:
                    continue
                if not shift_counts_agree(first_restart, pre_counts):
                    continue
                if (first_restart["code"]["home_goalie"] != 1
                        or first_restart["code"]["away_goalie"] != 1):
                    continue
                prior_faceoff_index = max(
                    (face_index for face_index in faceoff_indices if face_index < first_faceoff_after),
                    default=-1)
                prior_group = [item for item in penalties
                               if prior_faceoff_index < item["index"] < first_faceoff_after]
                if not prior_group or {item["side"] for item in prior_group} != {short_side}:
                    continue
                if any(event["type"] == "goal"
                       for event in period_events[prior_faceoff_index + 1:current_faceoff_index]):
                    continue
                active_prior_candidates.append((first_faceoff_after, prior_group))
            if not active_prior_candidates:
                continue

            _, prior_group = max(active_prior_candidates, key=lambda item: item[0])
            prior_group = sorted({item["index"]: item for item in prior_group}.values(),
                                 key=lambda item: item["index"])
            prior_example_rows = []
            for penalty in prior_group:
                prior_example_rows.append({
                    "clock": penalty["event"]["clock"],
                    "event_id": penalty["event"]["event_id"],
                    "type": penalty["kind"], "duration_seconds": penalty["duration"],
                    "penalized_team_id": penalty["team_id"],
                    "shift_return_evidence": _penalty_shift_return_evidence(
                        penalty, shift_by_period),
                })
            new_example_rows = []
            for penalty in sorted(new_penalties, key=lambda item: item["index"]):
                new_example_rows.append({
                    "clock": penalty["event"]["clock"],
                    "event_id": penalty["event"]["event_id"],
                    "type": penalty["kind"], "duration_seconds": penalty["duration"],
                    "penalized_team_id": penalty["team_id"],
                    "shift_return_evidence": _penalty_shift_return_evidence(
                        penalty, shift_by_period),
                })
            example = {
                "game_id": game_id, "period_type": period_type, "period": period,
                "preceding_penalty_group": prior_example_rows,
                "new_penalty_group": new_example_rows,
                "observed_state_before_new_penalty": {
                    "clock": previous_faceoff["clock"],
                    "situation_code": "".join(str(previous_faceoff["code"][key])
                                                for key in ("away_goalie", "away_skaters",
                                                            "home_skaters", "home_goalie")),
                    "shift_skaters_home_away": [
                        previous_faceoff["shift_lineup"]["home"]["skaters"],
                        previous_faceoff["shift_lineup"]["away"]["skaters"]],
                },
                "observed_restart_after_new_penalty": {
                    "clock": current_faceoff["clock"],
                    "situation_code": "".join(str(current_faceoff["code"][key])
                                                for key in ("away_goalie", "away_skaters",
                                                            "home_skaters", "home_goalie")),
                    "shift_skaters_home_away": [
                        current_faceoff["shift_lineup"]["home"]["skaters"],
                        current_faceoff["shift_lineup"]["away"]["skaters"]],
                },
                "classification": (
                    "faceoff-delimited observed 5v4-to-4v4 transition; nominal penalty duration "
                    "and prior situation support overlap, but exact service/expiration is not exposed"),
            }
            if (example not in stats["penalty_overlap_examples"]
                    and len(stats["penalty_overlap_examples"]) < 25):
                stats["penalty_overlap_examples"].append(example)
            stats["penalty_classes"]["faceoff_delimited_5v4_to_4v4_overlap_candidates"] += 1


def _aggregate_metric(games: list[dict[str, Any]], metric: str) -> dict[str, list[int]]:
    total: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for game in games:
        for key, values in game["metric_counts"].get(metric, {}).items():
            total[str(key)][0] += int(values[0])
            total[str(key)][1] += int(values[1])
    return dict(total)


def _fit_binary_model(games: list[dict[str, Any]], metric: str,
                      *, parent_metric: str | None = None) -> tuple[dict[str, float], dict[str, Any]]:
    counts = _aggregate_metric(games, metric)
    parent_key = "all"
    if parent_metric:
        parent_counts = _aggregate_metric(games, parent_metric)
        parent = parent_counts.get("all", [0, 0])
    elif metric in {"sog_all", "goal_all"}:
        parent = counts.get("all", [0, 0])
    else:
        parent = [sum(x[0] for x in counts.values()), sum(x[1] for x in counts.values())]
    parent_rate = parent[0] / parent[1] if parent[1] else 0.5
    model: dict[str, float] = {parent_key: parent_rate}
    parent_values = [(int(game["metric_counts"].get(metric, {}).get(parent_key, [0, 0])[0]),
                      int(game["metric_counts"].get(metric, {}).get(parent_key, [0, 0])[1]))
                     for game in games]
    if parent_metric:
        parent_values = [(int(game["metric_counts"].get(parent_metric, {}).get(parent_key, [0, 0])[0]),
                          int(game["metric_counts"].get(parent_metric, {}).get(parent_key, [0, 0])[1]))
                         for game in games]
    rows = [{"group": parent_key, "successes": parent[0], "trials": parent[1],
             "observed_rate": parent_rate, "shrunk_rate": parent_rate,
             "cluster_95_ci": _cluster_interval(parent_values, reps=BOOTSTRAP_REPLICATES,
                                                seed=BOOTSTRAP_SEED+999)}]
    group_index = 0
    for key, (successes, trials) in sorted(counts.items()):
        if key == parent_key:
            continue
        if trials >= 100:
            rate = shrink_binary_rate(successes, trials, parent_rate)
            model[key] = rate
            values = [(int(game["metric_counts"].get(metric, {}).get(key, [0, 0])[0]),
                       int(game["metric_counts"].get(metric, {}).get(key, [0, 0])[1]))
                      for game in games]
            interval = _cluster_interval(values, reps=BOOTSTRAP_REPLICATES,
                                         seed=BOOTSTRAP_SEED + group_index)
            group_index += 1
            rows.append({"group": key, "successes": successes, "trials": trials,
                         "observed_rate": successes / trials, "shrunk_rate": rate,
                         "cluster_95_ci": interval})
        else:
            rows.append({"group": key, "successes": successes, "trials": trials,
                         "observed_rate": successes / trials if trials else None,
                         "shrunk_rate": None, "cluster_95_ci": None,
                         "status": "sparse; parent fallback"})
    return model, {"parent_rate": parent_rate, "groups": rows}


def _fit_shot_models(training_games: list[dict[str, Any]]) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    models: dict[str, dict[str, float]] = {}
    tables: dict[str, Any] = {}
    specs = (
        ("sog_all", None), ("sog_by_strength", "sog_all"),
        ("sog_by_shot_type", "sog_all"), ("sog_by_zone", "sog_all"),
        ("goal_all", None), ("goal_by_strength", "goal_all"),
        ("goal_by_shot_type", "goal_all"), ("goal_by_zone", "goal_all"),
        ("goal_by_goalie", "goal_all"),
    )
    for metric, parent_metric in specs:
        models[metric], tables[metric] = _fit_binary_model(
            training_games, metric, parent_metric=parent_metric)
    # The faceoff follow-up shot is a descriptive post-event transition; its
    # strength model is estimated separately from the SOG conversion stages.
    counts: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for game in training_games:
        for key, values in game["metric_counts"].get("faceoff_shot_30s", {}).items():
            counts[key][0] += int(values[0])
            counts[key][1] += int(values[1])
    total_success = sum(values[0] for values in counts.values())
    total_trials = sum(values[1] for values in counts.values())
    parent_rate = total_success / total_trials if total_trials else 0.0
    parent_model = {"all": parent_rate}
    strength_model = {}
    transition_rows = [{"group": "all", "successes": total_success,
                        "trials": total_trials, "observed_rate": parent_rate,
                        "shrunk_rate": parent_rate, "cluster_95_ci": _cluster_interval(
                            [(sum(v[0] for v in g["metric_counts"].get("faceoff_shot_30s", {}).values()),
                              sum(v[1] for v in g["metric_counts"].get("faceoff_shot_30s", {}).values()))
                             for g in training_games], reps=BOOTSTRAP_REPLICATES,
                            seed=BOOTSTRAP_SEED + 700)}]
    for index, (key, (successes, trials)) in enumerate(sorted(counts.items())):
        if trials >= 100:
            rate = shrink_binary_rate(successes, trials, parent_rate)
            strength_model[key] = rate
            values = [(int(game["metric_counts"].get("faceoff_shot_30s", {}).get(key, [0, 0])[0]),
                       int(game["metric_counts"].get("faceoff_shot_30s", {}).get(key, [0, 0])[1]))
                      for game in training_games]
            transition_rows.append({"group": key, "successes": successes, "trials": trials,
                                    "observed_rate": successes / trials, "shrunk_rate": rate,
                                    "cluster_95_ci": _cluster_interval(
                                        values, reps=BOOTSTRAP_REPLICATES,
                                        seed=BOOTSTRAP_SEED + 701 + index)})
        else:
            transition_rows.append({"group": key, "successes": successes, "trials": trials,
                                    "observed_rate": successes / trials if trials else None,
                                    "shrunk_rate": None, "cluster_95_ci": None,
                                    "status": "sparse; parent fallback"})
    models["faceoff_shot_parent"] = parent_model
    models["faceoff_shot_by_strength"] = {"all": parent_rate, **strength_model}
    tables["faceoff_shot_within_30s"] = {"parent_rate": parent_rate,
                                        "groups": transition_rows}
    return models, tables


def _fit_faceoff_team_rates(team_faceoffs: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    rates: dict[str, float] = {}
    rows = []
    for team_id, counts in sorted(team_faceoffs.items()):
        trials = int(counts["total"])
        successes = int(counts["won"])
        rate = shrink_binary_rate(successes, trials, 0.5)
        rates[team_id] = rate
        rows.append({"team_id": team_id, "wins": successes, "faceoffs": trials,
                     "observed_rate": successes / trials if trials else None,
                     "shrunk_rate": rate})
    return rates, {"prior_rate": 0.5, "prior_strength": 20,
                   "team_rates": rows}


def _poisson_deviance(observed: float, expected: float) -> float:
    expected = max(float(expected), 1e-12)
    observed = float(observed)
    if observed <= 0:
        return 2.0 * expected
    return 2.0 * (observed * math.log(observed / expected) - (observed - expected))


def _event_rate_diagnostics(training_games: list[dict[str, Any]],
                            development_games: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit event rates on training exposure, then score conditional 2021 counts.

    Exposure is shift-derived team-minutes. Contexts are one-axis-at-a-time;
    the event state is read from the pre-event record and never used as a
    pregame feature. 2021 values are therefore conditional diagnostics, not a
    prospective full-game forecast.
    """
    training: dict[str, Any] = {}
    development: dict[str, Any] = {}
    for family_index, family in enumerate(RATE_FAMILIES):
        train_counts: collections.Counter[str] = collections.Counter()
        train_exposure: collections.Counter[str] = collections.Counter()
        contexts = {"all=all"}
        for game in training_games:
            counts = game["event_rate_counts"]
            exposures = game["event_exposure_minutes"]
            for key, value in counts.items():
                if key.startswith(family + "|"):
                    context = key.split("|", 1)[1]
                    contexts.add(context)
                    train_counts[context] += value
            for context, value in exposures.items():
                train_exposure[context] += value
                contexts.add(context)
        parent_exposure = train_exposure["all=all"]
        parent_count = train_counts["all=all"]
        if parent_exposure <= 0:
            raise ValueError(f"no training team-minute exposure for event family {family}")
        parent_rate = parent_count / parent_exposure
        rates = {"all=all": parent_rate}
        train_rows = [{
            "context": "all=all", "events": int(parent_count),
            "team_exposure_minutes": parent_exposure,
            "contributing_games": sum(g["event_exposure_minutes"].get("all=all", 0) > 0
                                       for g in training_games),
            "observed_per_60_team_minutes": parent_rate * 60,
            "shrunk_per_60_team_minutes": parent_rate * 60,
            "cluster_95_ci_observed_per_60": _cluster_interval(
                [(g["event_rate_counts"].get(f"{family}|all=all", 0),
                  g["event_exposure_minutes"].get("all=all", 0)) for g in training_games],
                reps=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED + 1300 + family_index),
            "status": "parent",
        }]
        for context_index, context in enumerate(sorted(contexts - {"all=all"})):
            events = train_counts[context]
            exposure = train_exposure[context]
            contributing = [game for game in training_games
                            if game["event_exposure_minutes"].get(context, 0) > 0]
            per_game_exposure = (statistics.fmean(
                game["event_exposure_minutes"][context] for game in contributing)
                if contributing else 0.0)
            prior_exposure = 20.0 * per_game_exposure
            if events >= 100 and exposure > 0 and prior_exposure > 0:
                rate = (events + prior_exposure * parent_rate) / (exposure + prior_exposure)
                status = "shrunk_group"
                rates[context] = rate
            else:
                rate = parent_rate
                status = "sparse; parent fallback"
                rates[context] = parent_rate
            values = [(game["event_rate_counts"].get(f"{family}|{context}", 0),
                       game["event_exposure_minutes"].get(context, 0)) for game in training_games]
            train_rows.append({
                "context": context, "events": int(events),
                "team_exposure_minutes": exposure,
                "contributing_games": len(contributing),
                "prior_exposure_minutes_for_20_game_equivalents": prior_exposure,
                "observed_per_60_team_minutes": events / exposure * 60 if exposure else None,
                "shrunk_per_60_team_minutes": rate * 60,
                "cluster_95_ci_observed_per_60": _cluster_interval(
                    values, reps=BOOTSTRAP_REPLICATES,
                    seed=BOOTSTRAP_SEED + 1400 + family_index * 100 + context_index),
                "status": status,
            })

        dev_counts: collections.Counter[str] = collections.Counter()
        dev_exposure: collections.Counter[str] = collections.Counter()
        dev_contexts = set(contexts)
        for game in development_games:
            for key, value in game["event_rate_counts"].items():
                if key.startswith(family + "|"):
                    context = key.split("|", 1)[1]
                    dev_counts[context] += value
                    dev_contexts.add(context)
            for context, value in game["event_exposure_minutes"].items():
                dev_exposure[context] += value
                dev_contexts.add(context)
        dev_rows = []
        for context_index, context in enumerate(sorted(dev_contexts)):
            events = dev_counts[context]
            exposure = dev_exposure[context]
            rate = rates.get(context, parent_rate)
            expected = rate * exposure
            parent_expected = parent_rate * exposure
            game_deltas = []
            for game in development_games:
                game_exposure = game["event_exposure_minutes"].get(context, 0)
                if game_exposure <= 0:
                    continue
                game_count = game["event_rate_counts"].get(f"{family}|{context}", 0)
                game_deltas.append((_poisson_deviance(game_count, rate * game_exposure),
                                    _poisson_deviance(game_count, parent_rate * game_exposure)))
            dev_values = [(game["event_rate_counts"].get(f"{family}|{context}", 0),
                           game["event_exposure_minutes"].get(context, 0))
                          for game in development_games]
            dev_rows.append({
                "context": context, "observed_events": int(events),
                "team_exposure_minutes": exposure,
                "observed_per_60_team_minutes": events / exposure * 60 if exposure else None,
                "frozen_training_rate_per_60_team_minutes": rate * 60,
                "training_parent_rate_per_60_team_minutes": parent_rate * 60,
                "expected_events_from_frozen_rate": expected,
                "expected_events_from_parent_rate": parent_expected,
                "observed_to_expected_ratio": events / expected if expected else None,
                "cluster_95_ci_observed_per_60": _cluster_interval(
                    dev_values, reps=BOOTSTRAP_REPLICATES,
                    seed=BOOTSTRAP_SEED + 1700 + family_index * 100 + context_index),
                "mean_game_poisson_deviance_difference_vs_parent": (
                    statistics.fmean(a - b for a, b in game_deltas) if game_deltas else None),
                "deviance_difference_uncertainty": (
                    "not bootstrapped; game-cluster intervals are reported for observed event rates"),
                "scoring_label": "conditional on observed shift-derived exposure and in-game state",
            })
        training[family] = train_rows
        development[family] = dev_rows
    return {
        "exposure_definition": "shift-derived team minutes; each side contributes its own team exposure",
        "contexts": "one axis at a time: all, side, shift-derived strength, period, pre-event score state, time remaining",
        "rate_shrinkage": "Gamma-Poisson mean with prior exposure equal to 20 times mean exposure per contributing training game; groups below 100 training events use the unconditioned parent rate",
        "training_2019_2020": training,
        "development_2021": development,
    }


def _loss_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
    for game in games:
        for key, values in game["score_losses"].items():
            totals[key][0] += values[0]
            totals[key][1] += values[1]
    result = {}
    for key, (loss, n) in sorted(totals.items()):
        if n:
            result[key] = {"n": int(n), "mean_loss": loss/n}
    return result


def _bootstrap_loss_difference(games: list[dict[str, Any]], candidate: str,
                               baseline: str, metric: str, *, seed: int) -> list[float] | None:
    key_a, key_b = f"{candidate}:{metric}", f"{baseline}:{metric}"
    rows = [(game["score_losses"].get(key_a, [0.0, 0.0]),
             game["score_losses"].get(key_b, [0.0, 0.0])) for game in games]
    if not rows or sum(a[1] for a, _ in rows) < 100 or sum(b[1] for _, b in rows) < 100:
        return None
    rng = random.Random(seed)
    diffs = []
    n_games = len(rows)
    for _ in range(BOOTSTRAP_REPLICATES):
        loss_a = loss_b = count_a = count_b = 0.0
        for _ in range(n_games):
            a, b = rows[rng.randrange(n_games)]
            loss_a += a[0]
            count_a += a[1]
            loss_b += b[0]
            count_b += b[1]
        if count_a and count_b:
            diffs.append(loss_a/count_a - loss_b/count_b)
    diffs.sort()
    return [diffs[int(0.025*(len(diffs)-1))], diffs[int(0.975*(len(diffs)-1))]]


def _forward_team_rate_evaluation(training_stats: dict[str, Any],
                                  development_games: list[dict[str, Any]]) -> dict[str, Any]:
    history = {team: collections.Counter(counts)
               for team, counts in training_stats["team_games"].items()}
    total_games = sum(int(row["games"]) for row in history.values())
    league_goal_rate = (sum(int(row["goals_for"]) for row in history.values()) / total_games
                        if total_games else 0.0)
    league_sog_rate = (sum(int(row["sog_for"]) for row in history.values()) / total_games
                       if total_games else 0.0)
    by_date: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for game in development_games:
        by_date[game["game_date"] or game["game_id"]].append(game)
    team_count_rows = []
    goal_game_losses: list[tuple[float, float]] = []
    sog_game_losses: list[tuple[float, float]] = []
    prediction_count = 0
    for game_date in sorted(by_date):
        same_day = sorted(by_date[game_date], key=lambda game: game["game_id"])
        for game in same_day:
            outputs = {"game_id": game["game_id"], "date": game_date, "teams": {}}
            game_goal_error = [0.0, 0.0]
            game_sog_error = [0.0, 0.0]
            sides = ((game["home_id"], game["away_id"], "home"),
                     (game["away_id"], game["home_id"], "away"))
            for team_id, opponent_id, side in sides:
                team = history.get(team_id, collections.Counter())
                opponent = history.get(opponent_id, collections.Counter())
                n = int(team["games"])
                n_opp = int(opponent["games"])
                attack_goal = (team["goals_for"] + 20*league_goal_rate)/(n+20)
                defense_goal = (opponent["goals_against"] + 20*league_goal_rate)/(n_opp+20)
                attack_sog = (team["sog_for"] + 20*league_sog_rate)/(n+20)
                defense_sog = (opponent["sog_against"] + 20*league_sog_rate)/(n_opp+20)
                pred_goal = (attack_goal + defense_goal)/2
                pred_sog = (attack_sog + defense_sog)/2
                actual_goal = int(game["result"]["reg_ot_goals"][side])
                actual_sog = int(game["result"]["sog"][side])
                outputs["teams"][side] = {
                    "team_id": team_id, "history_games": n,
                    "predicted_goals": pred_goal, "actual_goals": actual_goal,
                    "league_goal_baseline": league_goal_rate,
                    "predicted_sog": pred_sog, "actual_sog": actual_sog,
                    "league_sog_baseline": league_sog_rate,
                }
                game_goal_error[0] += (pred_goal-actual_goal)**2
                game_goal_error[1] += (league_goal_rate-actual_goal)**2
                game_sog_error[0] += (pred_sog-actual_sog)**2
                game_sog_error[1] += (league_sog_rate-actual_sog)**2
            prediction_count += 1
            goal_game_losses.append(tuple(game_goal_error))
            sog_game_losses.append(tuple(game_sog_error))
        # Withhold every target-date result until all same-date forecasts exist.
        for game in same_day:
            result = game["result"]["reg_ot_goals"]
            for side, team_id, opponent_id in (("home", game["home_id"], game["away_id"]),
                                                ("away", game["away_id"], game["home_id"])):
                row = history.setdefault(team_id, collections.Counter())
                opp_row = history.setdefault(opponent_id, collections.Counter())
                row["games"] += 1
                row["goals_for"] += int(result[side])
                row["goals_against"] += int(result["away" if side == "home" else "home"])
                row["sog_for"] += int(game["result"]["sog"][side])
                row["sog_against"] += int(game["result"]["sog"]["away" if side == "home" else "home"])
    def summarize(loss_rows: list[tuple[float, float]], label: str, seed: int) -> dict[str, Any]:
        n_games = len(loss_rows)
        n = 2*n_games
        candidate_mean = sum(x[0] for x in loss_rows)/n if n else None
        baseline_mean = sum(x[1] for x in loss_rows)/n if n else None
        rng = random.Random(seed)
        differences = []
        if n_games >= 30:
            for _ in range(BOOTSTRAP_REPLICATES):
                total_diff = 0.0
                for _ in range(n_games):
                    chosen = loss_rows[rng.randrange(n_games)]
                    total_diff += chosen[0] - chosen[1]
                differences.append(total_diff/n)
            differences.sort()
        return {"n_team_games": n, "model_mse": candidate_mean,
                "league_baseline_mse": baseline_mean,
                "paired_mse_difference_model_minus_baseline": candidate_mean-baseline_mean
                    if n else None,
                "game_bootstrap_95_ci_difference": [differences[int(.025*(len(differences)-1))],
                    differences[int(.975*(len(differences)-1))]] if differences else None}
    for team_id, row in sorted(history.items()):
        team_count_rows.append({"team_id": team_id, **{k: int(v) for k,v in row.items()}})
    return {
        "fit_population": "eligible 2019/20 GameCenter games, then forward-only 2021 history",
        "same_date_results_withheld": True,
        "shrinkage_pseudo_games": 20,
        "league_training_goal_rate_per_team_game": league_goal_rate,
        "league_training_sog_rate_per_team_game": league_sog_rate,
        "goal_count_evaluation": summarize(goal_game_losses, "goals", BOOTSTRAP_SEED+900),
        "sog_count_evaluation": summarize(sog_game_losses, "sog", BOOTSTRAP_SEED+901),
        "team_history_at_end_of_walk_forward": team_count_rows,
        "forecast_count": prediction_count,
    }


def _counter_rows(counter: collections.Counter, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [{"key": str(key), "count": int(value)} for key, value in counter.most_common()]
    return rows if limit is None else rows[:limit]


def _event_frequency_table(games: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    names = sorted({name for game in games for name in game["game_event_counts"]})
    rows = []
    for index, name in enumerate(names):
        counts = [float(game["game_event_counts"].get(name, 0)) for game in games]
        total = sum(counts)
        interval = None
        status = "sparse; fewer than 100 observed events" if total < 100 else "measured"
        if len(counts) >= 30 and total >= 100:
            rng = random.Random(seed + index)
            means = []
            for _ in range(BOOTSTRAP_REPLICATES):
                means.append(sum(counts[rng.randrange(len(counts))]
                                 for _ in range(len(counts))) / len(counts))
            means.sort()
            interval = [means[int(.025 * (len(means) - 1))],
                        means[int(.975 * (len(means) - 1))]]
        rows.append({
            "event_type": name, "events": int(total), "eligible_games": len(games),
            "games_with_event": sum(value > 0 for value in counts),
            "mean_events_per_eligible_game": total / len(games) if games else None,
            "game_cluster_95_ci_mean_per_game": interval,
            "status": status,
        })
    return rows


def _season_summary(stats: dict[str, Any], eligible: int) -> dict[str, Any]:
    durations = {}
    for position, values in sorted(stats["shift_duration_seconds"].items()):
        sorted_values = sorted(values)
        if sorted_values:
            durations[position] = {
                "n_shifts": len(sorted_values),
                "median_seconds": statistics.median(sorted_values),
                "p90_seconds": sorted_values[int(.90*(len(sorted_values)-1))],
                "mean_seconds": statistics.fmean(sorted_values),
            }
    def distribution(values: list[float]) -> dict[str, Any]:
        ordered = sorted(values)
        if not ordered:
            return {"n": 0, "median": None, "p90": None}
        return {"n": len(ordered), "median": statistics.median(ordered),
                "p90": ordered[int(.90*(len(ordered)-1))]}
    context_durations = {
        key: distribution(values) for key, values in sorted(stats["shift_duration_by_context"].items())
    }
    player_shot_rates = [row["sog"]*3600/row["shift_seconds"]
                         for pid, row in stats["player_events"].items()
                         if row["shift_seconds"] >= 3600 and stats["player_positions"].get(pid) != "G"]
    player_finishing_rates = [row["goals"]/row["sog"]
                              for pid, row in stats["player_events"].items()
                              if row["sog"] >= 50 and stats["player_positions"].get(pid) != "G"]
    player_faceoff_rates = [row["faceoffs_won"]/row["faceoff_participations"]
                            for row in stats["player_events"].values()
                            if row["faceoff_participations"] >= 100]
    goalie_save_rates = [1-row["goals_against"]/row["shots_against"]
                         for row in stats["goalie_shots"].values()
                         if row["shots_against"] >= 100]
    field_coverage = {}
    for event_type, counts in sorted(stats["event_fields"].items()):
        total = int(counts["events"])
        fields = {}
        for key, value in sorted(counts.items()):
            if key == "events" or not key.endswith("_present"):
                continue
            base = key[:-8]
            missing = int(counts.get(base + "_missing", 0))
            fields[base] = {"present": int(value), "missing": missing,
                            "coverage": value/total if total else None}
        field_coverage[event_type] = {"events": total, "fields": fields}
    players_with_shifts = [row for row in stats["player_events"].values()
                           if row["shift_seconds"] > 0]
    players_with_faceoffs = [row for row in stats["player_events"].values()
                             if row["faceoff_participations"] > 0]
    return {
        "eligible_games_processed": eligible,
        "events": _counter_rows(stats["events"]),
        "event_frequency_per_eligible_game": _event_frequency_table(
            stats["per_game"], seed=BOOTSTRAP_SEED + stats["season"]),
        "event_field_coverage": field_coverage,
        "penalty_classes": _counter_rows(stats["penalty_classes"]),
        "penalty_reasons": _counter_rows(stats["penalty_reasons"], 20),
        "penalty_overlap_examples_found": int(stats["penalty_classes"][
            "faceoff_delimited_5v4_to_4v4_overlap_candidates"]),
        "penalty_overlap_examples": stats["penalty_overlap_examples"],
        "penalty_committed_player_team_vs_event_owner": _counter_rows(
            stats["penalty_team_identity"]),
        "faceoffs": _counter_rows(stats["faceoffs"]),
        "faceoff_next_event": _counter_rows(stats["faceoff_next_events"]),
        "faceoff_winner_team_shot_within_30_seconds_before_next_faceoff":
            _counter_rows(stats["faceoff_shot_within_30s"]),
        "stoppages": _counter_rows(stats["stoppages"], 30),
        "stoppage_to_faceoff_zone": _counter_rows(stats["stoppage_restarts"], 50),
        "shot_attempt_events": _counter_rows(stats["attempts"]),
        "sog_events": _counter_rows(stats["sog_outcomes"]),
        "shot_type_zone_composition": _counter_rows(stats["attempt_composition"], 40),
        "shot_coordinates_by_event": {
            event_type: _counter_rows(counts) for event_type, counts in sorted(stats["shot_coordinates"].items())},
        "shift_rows": _counter_rows(stats["shifts"]),
        "shift_duration_by_position": durations,
        "shift_start_context_nearest_preceding_pbp": _counter_rows(stats["shift_start_context"]),
        "shift_duration_by_nearest_pbp_context_seconds": context_durations,
        "shift_anomalies": _counter_rows(stats["shift_anomalies"]),
        "situation_code_shift_reconciliation": _counter_rows(stats["situation_reconciliation"]),
        "observed_strength_exposure_team_minutes": _counter_rows(
            collections.Counter({k:v for k,v in stats["observed_strength_exposure_minutes"].items()
                                 if k.count(":") == 1})),
        "event_counts_by_strength": _counter_rows(stats["event_rates"]),
        "goalie_presence_events": _counter_rows(stats["goalie_presence"]),
        "goalie_pull_return_events": _counter_rows(stats["goalie_transitions"]),
        "overtime": _counter_rows(stats["overtime"]),
        "shootout": _counter_rows(stats["shootout"]),
        "team_rates": [
            {"team_id": team, "games": int(row["games"]),
             "goals_for_per_game": row["goals_for"]/row["games"],
             "goals_against_per_game": row["goals_against"]/row["games"],
             "sog_for_per_game": row["sog_for"]/row["games"],
             "sog_against_per_game": row["sog_against"]/row["games"]}
            for team, row in sorted(stats["team_games"].items()) if row["games"]],
        "player_coverage": {
            "players_with_shift_or_event_evidence": len(stats["player_events"]),
            "players_with_positive_shift_seconds": len(players_with_shifts),
            "players_with_faceoff_participations": len(players_with_faceoffs),
            "players_with_100_plus_sog": sum(1 for row in stats["player_events"].values()
                                              if row["sog"] >= 100),
            "players_with_20_plus_sog": sum(1 for row in stats["player_events"].values()
                                             if row["sog"] >= 20),
            "skater_sog_per_60_shift_minutes_n_at_least_60_shift_minutes": distribution(player_shot_rates),
            "player_goal_per_sog_n_at_least_50_sog": distribution(player_finishing_rates),
            "faceoff_win_rate_n_at_least_100_faceoffs": distribution(player_faceoff_rates),
        },
        "goalie_coverage": {
            "goalies_with_shots_faced": len(stats["goalie_shots"]),
            "goalies_with_100_plus_sog": sum(1 for row in stats["goalie_shots"].values()
                                              if row["shots_against"] >= 100),
            "observed_save_pct_n_at_least_100_sog": distribution(goalie_save_rates),
        },
    }


def _model_tables(training_stats: dict[str, Any],
                  development_stats: dict[str, Any],
                  fitted: tuple[dict[str, dict[str, float]], dict[str, Any],
                                dict[str, float], dict[str, Any]] | None = None
                  ) -> tuple[dict[str, dict[str, float]], dict[str, float], dict[str, Any],
                             tuple[dict[str, dict[str, float]], dict[str, Any],
                                   dict[str, float], dict[str, Any]]]:
    if fitted is None:
        models, training_tables = _fit_shot_models(training_stats["per_game"])
        faceoff_rates, faceoff_table = _fit_faceoff_team_rates(training_stats["team_faceoffs"])
        fitted = (models, training_tables, faceoff_rates, faceoff_table)
    else:
        models, training_tables, faceoff_rates, faceoff_table = fitted
    # The faceoff rate model and per-shot conversion models are frozen on 2019/20.
    dev_games = development_stats["per_game"]
    eval_summary = _loss_summary(dev_games)
    comparisons = {}
    baseline_keys = {
        "sog_by_strength": "sog_all:brier",
        "sog_by_shot_type": "sog_all:brier",
        "sog_by_zone": "sog_all:brier",
        "goal_by_strength": "goal_all:brier",
        "goal_by_shot_type": "goal_all:brier",
        "goal_by_zone": "goal_all:brier",
        "goal_by_goalie": "goal_all:brier",
    }
    for metric, baseline_key in baseline_keys.items():
        base_name = baseline_key.split(":")[0]
        comparisons[metric] = {
            "brier_difference_ci_vs_parent": _bootstrap_loss_difference(
                dev_games, metric, base_name, "brier", seed=BOOTSTRAP_SEED+1000+len(comparisons)),
            "log_loss_difference_ci_vs_parent": _bootstrap_loss_difference(
                dev_games, metric, base_name, "log_loss", seed=BOOTSTRAP_SEED+1100+len(comparisons)),
        }
    for name in ("team_rate",):
        comparisons[f"faceoff_{name}"] = {
            "brier_difference_ci_vs_50_50": _bootstrap_loss_difference(
                dev_games, f"faceoff:{name}", "faceoff:league_50", "brier",
                seed=BOOTSTRAP_SEED+1200),
            "log_loss_difference_ci_vs_50_50": _bootstrap_loss_difference(
                dev_games, f"faceoff:{name}", "faceoff:league_50", "log_loss",
                seed=BOOTSTRAP_SEED+1201),
        }
    for name in ("strength",):
        comparisons[f"faceoff_shot_{name}"] = {
            "brier_difference_ci_vs_parent": _bootstrap_loss_difference(
                dev_games, f"faceoff_shot:{name}", "faceoff_shot:parent", "brier",
                seed=BOOTSTRAP_SEED+1202),
            "log_loss_difference_ci_vs_parent": _bootstrap_loss_difference(
                dev_games, f"faceoff_shot:{name}", "faceoff_shot:parent", "log_loss",
                seed=BOOTSTRAP_SEED+1203),
        }
    report = {"training_conditional_rates": training_tables,
              "team_faceoff_rates": faceoff_table,
              "development_proper_scores": eval_summary,
              "development_paired_uncertainty": comparisons,
              "development_scope": (
                  "2021 observed shot location/type and on-ice goalie are conditional diagnostic labels; "
                  "they were not pregame inputs or fed into a simulation")}
    return models, faceoff_rates, report, fitted


def _manifest_inventory(rows: list[dict[str, str]], asset: str) -> dict[str, Any]:
    by_season: dict[str, int] = collections.Counter()
    status: collections.Counter = collections.Counter()
    origin: collections.Counter = collections.Counter()
    for row in rows:
        by_season[str(row["game_id"][:4])] += 1
        status[row.get("http_status", "<missing>")] += 1
        origin[row.get("evidence_origin", "<missing>")] += 1
    return {"asset": asset, "rows": len(rows), "rows_by_start_season": dict(sorted(by_season.items())),
            "http_status_counts": {str(k): int(v) for k,v in status.items()},
            "evidence_origin_counts": {str(k): int(v) for k,v in origin.items()},
            "all_rows_http_200": len(rows) > 0 and status == {"200": len(rows)}}


def _render_markdown(result: dict[str, Any]) -> str:
    pop = result["population"]
    source = result["source_inventory"]
    train = result["behavior"]["training_2019_2020"]
    dev = result["behavior"]["development_2021"]
    models = result["model_diagnostics"]
    db = result["legendarypicks_database"]
    lines = [
        "# NHL Behavior Evidence and Rules Coverage Audit",
        "",
        f"- **Date:** {result['metadata']['date']}",
        f"- **Branch:** `{result['metadata']['branch']}`",
        f"- **Base:** `{result['metadata']['base_commit']}`",
        "- **Purpose:** research-only source audit and conditional behavior diagnostics; no adoption or gate decision.",
        "",
        "## Population and provenance",
        "",
        "| Population | Listed | Eligible | Excluded/quarantined |",
        "|---|---:|---:|---:|",
    ]
    for season in (2019, 2020, 2021):
        row = pop["seasons"][str(season)]
        reasons = sum(row["quarantine_reasons"].values())
        lines.append(f"| {season} start season | {row['listed']} | {row['eligible']} | {reasons} reason records |")
    lines += [
        "",
        f"PBP manifest: {source['pbp']['rows']} bodies, all listed HTTP statuses 200: "
        f"{source['pbp']['all_rows_http_200']}. Shift manifest: {source['shifts']['rows']} bodies, "
        f"all listed HTTP statuses 200: {source['shifts']['all_rows_http_200']}. The source-origin breakdown "
        "is retained in the JSON because most bodies were reused from a cache whose original retrieval "
        "provenance was not recorded.",
        "",
        f"The independent box-score manifest listed {result['boxscore']['games']} records; "
        f"the validated corpus reports source counts `{json.dumps(result['boxscore']['source_counts'], sort_keys=True)}`. "
        "PBP and box-score bodies, game/team identity, clocks, score, and SOG were checked by the frozen v0.1 loader.",
        "",
        "## Existing Legendary Picks NHL data",
        "",
        "Read-only inventory of `picks.dev.db`; these current-season tables were not used to fit the 2019/20 or 2021 historical models:",
        "",
        "| Table | NHL rows | Seasons / range | Source evidence |",
        "|---|---:|---|---|",
    ]
    for table, row in db.get("tables", {}).items():
        count = row.get("nhl_rows", row.get("nhl_memberships", "—"))
        seasons = row.get("season_counts") or row.get("game_date_range") or "current roster snapshots"
        sources = row.get("source_counts") or "—"
        lines.append(f"| `{table}` | {count} | `{json.dumps(seasons, sort_keys=True)}` | `{json.dumps(sources, sort_keys=True)}` |")
    lines += [
        "",
        "The database contains useful current pregame roster/player/team inputs, but its NHL player logs and team outcomes begin in 2025–26; it does not supply the historical training/development population. The official GameCenter archive remains the behavior-evidence source. All database reads used URI `mode=ro` and `PRAGMA query_only=ON`.",
        "",
        "## Behavior evidence",
        "",
        "The full event, field-coverage, shift, player, goalie, transition, and uncertainty tables are in the generated JSON. Selected counts:",
        "",
        "| Measure | 2019/20 training | 2021 development |",
        "|---|---:|---:|",
    ]
    def count(rows, key):
        return next((row["count"] for row in rows if row["key"] == key), 0)
    def situation_match(rows):
        matched = count(rows, "codes_match_shift_lineup")
        compared = count(rows, "codes_compared_with_unambiguous_shift_lineup")
        return f"{matched}/{compared} ({matched/compared:.1%})" if compared else "—"
    lines.extend([
        f"| Eligible games | {train['eligible_games_processed']} | {dev['eligible_games_processed']} |",
        f"| Faceoffs | {count(train['faceoffs'], 'total')} | {count(dev['faceoffs'], 'total')} |",
        f"| Shot attempts | {count(train['shot_attempt_events'], 'all')} | {count(dev['shot_attempt_events'], 'all')} |",
        f"| SOG events | {count(train['sog_events'], 'all')} | {count(dev['sog_events'], 'all')} |",
        f"| Penalty events | {sum(row['count'] for row in train['penalty_classes'] if ':' in row['key'])} | {sum(row['count'] for row in dev['penalty_classes'] if ':' in row['key'])} |",
        f"| Stoppages | {sum(row['count'] for row in train['stoppages'])} | {sum(row['count'] for row in dev['stoppages'])} |",
        f"| Situation-code/shift matches among unambiguous decodable rows | {situation_match(train['situation_code_shift_reconciliation'])} | {situation_match(dev['situation_code_shift_reconciliation'])} |",
        f"| Situation-code rows excluded (unknown positions / duplicate active tracks) | {count(train['situation_code_shift_reconciliation'], 'code_comparison_excluded_unknown_shift_positions')} / {count(train['situation_code_shift_reconciliation'], 'code_comparison_excluded_duplicate_active_tracks')} | {count(dev['situation_code_shift_reconciliation'], 'code_comparison_excluded_unknown_shift_positions')} / {count(dev['situation_code_shift_reconciliation'], 'code_comparison_excluded_duplicate_active_tracks')} |",
        "",
        "### Evidence coverage and limits by mechanic",
        "",
        "| Mechanic | Exact observed fields | Deterministic rule work | Empirical behavior supported | Remaining unobserved |",
        "|---|---|---|---|---|",
    ])
    for row in result["coverage_matrix"]:
        lines.append("| " + " | ".join(row[key] for key in (
            "mechanic", "observed_fields", "deterministic", "estimable", "unobserved")) + " |")
    lines += [
        "",
        "### Conditional scoring diagnostics",
        "",
        "Parameters were fit on 2019/20 only, with 20 parent-equivalent observations for shrinkage and a parent fallback below 100 training opportunities. The 2021 score table is a once-scored development diagnostic. Shot-type/location/goalie scores condition on recorded target events and are not full-game simulation inputs.",
        "",
        "| 2021 event model | N | Mean Brier / log loss | Paired 95% CI of loss difference vs parent |",
        "|---|---:|---|---|",
    ]
    for key, metrics in models["development_proper_scores"].items():
        if not (key.endswith(":brier") or key.endswith(":log_loss")):
            continue
        pair = key.rsplit(":", 1)[0]
        lines.append(f"| `{pair}` {key.rsplit(':',1)[1]} | {metrics['n']} | {metrics['mean_loss']:.5f} | — |")
    for name, intervals in models["development_paired_uncertainty"].items():
        brier = intervals.get("brier_difference_ci_vs_parent") or intervals.get("brier_difference_ci_vs_50_50")
        logloss = intervals.get("log_loss_difference_ci_vs_parent") or intervals.get("log_loss_difference_ci_vs_50_50")
        lines.append(f"| `{name}` paired delta | — | Brier {brier}; log loss {logloss} | game-cluster percentile bootstrap |")
    rate_diag = result["event_rate_diagnostics"]
    lines += [
        "",
        "### Event rates by observed game state",
        "",
        "Train-only rates use shift-derived team-minute exposure. The listed conditional rates use one context axis at a time; groups under 100 training events fall back to the unconditioned parent. The 2021 comparison conditions on the observed shift exposure and in-game state, so it is a diagnostic and not a pregame game forecast. Full support, sparse cells, and cluster intervals are in the JSON.",
        "",
        "| Event family | Context | Train events / team-minutes | Frozen train rate / 60 team-min | 2021 observed / expected | Observed/expected | 2021 mean game Poisson deviance delta vs parent |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    selected_contexts = {"all=all", "strength=5v5", "strength=5v4", "strength=4v5",
                         "period=REG", "period=OT", "score=tied", "time=>10m", "time=<=1m"}
    for family, train_rows in rate_diag["training_2019_2020"].items():
        train_by_context = {row["context"]: row for row in train_rows}
        dev_by_context = {row["context"]: row
                          for row in rate_diag["development_2021"][family]}
        for context in sorted(selected_contexts & train_by_context.keys()):
            trained = train_by_context[context]
            checked = dev_by_context.get(context, {})
            actual_expected = (
                f"{checked.get('observed_events', 0)} / "
                f"{checked.get('expected_events_from_frozen_rate', 0):.1f}"
                if checked.get("team_exposure_minutes", 0) > 0 else "—")
            ratio = checked.get("observed_to_expected_ratio")
            ratio_text = f"{ratio:.3f}" if ratio is not None else "—"
            delta = checked.get("mean_game_poisson_deviance_difference_vs_parent")
            delta_text = f"{delta:.4f}" if delta is not None else "—"
            lines.append(
                f"| `{family}` | `{context}` | {trained['events']} / "
                f"{trained['team_exposure_minutes']:.1f} | "
                f"{trained['shrunk_per_60_team_minutes']:.4f} | {actual_expected} | "
                f"{ratio_text} | {delta_text} |")
    lines += [
        "",
        "Unconditioned event-type frequencies use eligible games as the denominator, with game-cluster intervals when support is at least 100. This includes stoppage types and shootout records; the full per-game table is in each season section of the JSON.",
        "",
        "| Event type | Train count / mean per eligible game (95% CI) | 2021 count / mean per eligible game (95% CI) |",
        "|---|---:|---:|",
    ]
    train_events = {row["event_type"]: row
                    for row in train["event_frequency_per_eligible_game"]}
    dev_events = {row["event_type"]: row
                  for row in dev["event_frequency_per_eligible_game"]}
    for event_type in ("faceoff", "penalty", "stoppage", "goal", "shot-on-goal",
                       "missed-shot", "blocked-shot", "giveaway", "takeaway", "shootout-complete"):
        if event_type not in train_events and event_type not in dev_events:
            continue
        cells = []
        for table in (train_events, dev_events):
            row = table.get(event_type)
            cells.append("—" if row is None else
                         f"{row['events']} / {row['mean_events_per_eligible_game']:.3f} "
                         f"({row['game_cluster_95_ci_mean_per_game']})")
        lines.append(f"| `{event_type}` | {cells[0]} | {cells[1]} |")
    team_goals = result["team_rate_evaluation"]["goal_count_evaluation"]
    team_sog = result["team_rate_evaluation"]["sog_count_evaluation"]
    lines += [
        "",
        "### Forward-only team-rate check",
        "",
        "The simple pregame rate comparator uses 2019/20 team goals/SOG for and against, 20-game league shrinkage, then updates after each completed 2021 date. Same-date outcomes are held back until every game that date has a forecast. It is a diagnostic baseline, not a fitted full game generator.",
        "",
        f"- Goal-count MSE: team-rate {team_goals['model_mse']:.4f}; league-only {team_goals['league_baseline_mse']:.4f}; paired difference {team_goals['paired_mse_difference_model_minus_baseline']:.4f} (95% CI {team_goals['game_bootstrap_95_ci_difference']}).",
        f"- SOG-count MSE: team-rate {team_sog['model_mse']:.4f}; league-only {team_sog['league_baseline_mse']:.4f}; paired difference {team_sog['paired_mse_difference_model_minus_baseline']:.4f} (95% CI {team_sog['game_bootstrap_95_ci_difference']}).",
        "",
        "## Penalty/manpower correction",
        "",
        "The simulator’s regulation manpower calculation now counts active noncoincidental penalties per team. Equal opposing counts do not cancel merely because the net difference is zero. Matching penalties classified coincidental remain excluded. Overtime retains its separate manpower table. The independent Gate 1 validator remains separate and unchanged.",
        "",
        f"This bounded correction is grounded in the [2021–22 NHL Official Rules]("
        f"{result['rulebook']['url']}) (pinned SHA-256 `{result['rulebook']['sha256']}`). "
        "It is a direct reference for 2021 development rules; do not transfer edition-sensitive details to earlier training seasons without checking those editions.",
        "",
        "Observed opposing-penalty overlap candidates and their pre/post situation-code and shift-count checks are included in the JSON. The feed does not contain an explicit Rule 19 adjudication label or exact penalty-expiration event; estimated duration endpoints and return-to-shift times are therefore identified as estimates, not official expiration timestamps.",
        "",
    ]
    train_overlap_count = train["penalty_overlap_examples_found"]
    dev_overlap_count = dev["penalty_overlap_examples_found"]
    lines.append(
        f"Strict source-evidence transitions (faceoff-delimited asymmetric state, no intervening goal, "
        f"new penalty by the previously full side, then 4v4 with shift-count agreement before the "
        f"prior nominal duration endpoint): {train_overlap_count} in training and "
        f"{dev_overlap_count} in 2021 development.")
    lines += ["", "| Population | Game | Period | Prior penalty group | New opposing penalty group | Situation code before → restart | Shift skaters home/away before → after |", "|---|---|---|---|---|---|---|"]
    for season_name, season_summary in (("2019/20", train), ("2021", dev)):
        for example in season_summary["penalty_overlap_examples"][:5]:
            before = example["observed_state_before_new_penalty"]
            after = example["observed_restart_after_new_penalty"]
            prior_text = "; ".join(
                f"{item['type']} {item['clock']} (event {item['event_id']})"
                for item in example["preceding_penalty_group"])
            new_text = "; ".join(
                f"{item['type']} {item['clock']} (event {item['event_id']})"
                for item in example["new_penalty_group"])
            shift_text = (f"{before['shift_skaters_home_away']} → "
                          f"{after['shift_skaters_home_away']}")
            lines.append(
                f"| {season_name} `{example['game_id']}` | {example['period_type']} {example['period']} | "
                f"{prior_text} | {new_text} | `{before['situation_code']}` → `{after['situation_code']}` | "
                f"{shift_text} |")
    lines += [
        "",
        "## Limits and decision",
        "",
        "- A faceoff winner and subsequent event are recorded; continuous possession and unrecorded passes are not. Follow-up shots are sequence proxies, not possession truth.",
        "- Shift charts identify player IDs and intervals; they do not expose line identity, coaching intent, exact bench policy, or fatigue state.",
        "- Situation-code/shift agreement is computed only when positions are known and no active player track is duplicated; excluded and mismatching rows remain visible in the JSON.",
        "- Official shot-event coordinates and types support conditional conversion analysis, but blocked-shot coordinates are not treated as release locations. The source does not observe shot opportunities that produced no event.",
        "- Goalie identity on a target shot is a retrospective condition. It was not used as a pregame starting-goalie input.",
        "- 2021 is development evidence, not an independent adoption test; 2022 remains excluded. No candidate is selected and no validity gate is changed.",
        "- Structural accounting does not establish autonomous puck possession, tactical decisions, physical movement, or complete rule adjudication.",
        "",
        "## Reproduction",
        "",
        "```bash",
        "python research/nhl/behavior-evidence/audit_behavior.py \\",
        "  --data-root /root/lp-data/nhl-fullframe-event-audit-2026-10-21 \\",
        "  --boxscore-root /root/lp-data/nhl-official-outcome-backfill-2026-10-20 \\",
        "  --db /root/legendarypicks/backend/data/picks.dev.db \\",
        "  --output research/nhl/behavior-evidence/results/nhl-behavior-evidence-2026-10-26.json \\",
        "  --report docs/research/NHL-BEHAVIOR-EVIDENCE-AND-RULES-COVERAGE-2026-10-26.md",
        "```",
        "",
        f"Elapsed audit time: {result['metadata']['elapsed_seconds']:.1f} seconds. JSON and report content are emitted by the script; raw data are not copied into Git.",
        "",
    ]
    return "\n".join(lines)


def run_audit(data_root: Path, boxscore_root: Path, db_path: Path,
              output_path: Path, report_path: Path) -> dict[str, Any]:
    import datetime as dt
    import subprocess
    import time

    started = time.perf_counter()
    pbp_manifest_path = data_root / "manifests/hardened-v1/pbp_verified_manifest.csv"
    shift_manifest_path = data_root / "manifests/hardened-v1/shifts_verified_manifest.csv"
    pbp_manifest = _read_manifest(pbp_manifest_path, PBP_MANIFEST_SHA256)
    shift_manifest = _read_manifest(shift_manifest_path, SHIFT_MANIFEST_SHA256)
    pbp_rows = {str(row["game_id"]): row for row in pbp_manifest
                if row.get("kind") == "pbp" and row.get("http_status") == "200"}
    shift_rows = {str(row["game_id"]): row for row in shift_manifest
                  if row.get("kind") == "shifts" and row.get("http_status") == "200"}
    if len(pbp_rows) != 4876 or len(shift_rows) != 4876:
        raise ValueError(f"verified archive population changed: PBP={len(pbp_rows)}, shifts={len(shift_rows)}")
    v01, corpus = _load_v01(data_root, boxscore_root)

    populations = {}
    for season in (*TRAIN_SEASONS, *DEV_SEASONS):
        listed = int(corpus.listed_by_season.get(season, 0))
        eligible = int(corpus.eligible_by_season.get(season, 0))
        populations[str(season)] = {
            "listed": listed, "eligible": eligible,
            "quarantine_reasons": corpus.quarantined_by_reason.get(season, {}),
        }
    training_stats = _new_season_stats(0)
    development_stats = _new_season_stats(2021)
    training_ids = [game_id for game_id, summary in sorted(corpus.games.items())
                    if summary.start_season in TRAIN_SEASONS and summary.eligible]
    development_ids = [game_id for game_id, summary in sorted(corpus.games.items())
                       if summary.start_season in DEV_SEASONS and summary.eligible]
    if len(training_ids) != sum(populations[str(y)]["eligible"] for y in TRAIN_SEASONS):
        raise ValueError("training eligible-game count does not reconcile to corpus population")
    if len(development_ids) != sum(populations[str(y)]["eligible"] for y in DEV_SEASONS):
        raise ValueError("development eligible-game count does not reconcile to corpus population")

    shift_bodies_verified = collections.Counter()
    for game_id in training_ids:
        summary = corpus.games[game_id]
        pbp, shifts = _load_game_source(data_root, pbp_rows, shift_rows, game_id)
        if str(pbp.get("id")) != game_id:
            raise ValueError(f"{game_id}: PBP body game ID mismatch")
        _analyze_game(pbp, shifts, summary, training_stats, training=True)
        shift_bodies_verified[str(summary.start_season)] += 1

    shot_models, faceoff_rates, _, fitted = _model_tables(
        training_stats, _new_season_stats(2021))
    # Frozen train-only rates are applied to the 2021 events exactly once.
    for game_id in development_ids:
        summary = corpus.games[game_id]
        pbp, shifts = _load_game_source(data_root, pbp_rows, shift_rows, game_id)
        if str(pbp.get("id")) != game_id:
            raise ValueError(f"{game_id}: PBP body game ID mismatch")
        _analyze_game(pbp, shifts, summary, development_stats, training=False,
                      shot_models=shot_models, faceoff_rates=faceoff_rates)
        shift_bodies_verified[str(summary.start_season)] += 1

    _, _, model_report, _ = _model_tables(training_stats, development_stats, fitted)
    team_evaluation = _forward_team_rate_evaluation(training_stats, development_stats["per_game"])
    populations_with_years = {
        year: {**payload, "shift_bodies_hash_verified": int(shift_bodies_verified.get(year, 0))}
        for year, payload in populations.items()
    }
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        head, branch = "unavailable", "unavailable"
    script_path = Path(__file__).resolve()
    result = {
        "metadata": {
            "title": "NHL behavior evidence and rules coverage audit",
            "date": dt.date.today().isoformat(),
            "branch": branch,
            "base_commit": "9501768f1410484d8be235fe0700f710f5ec189e",
            "code_commit_at_run": head,
            "script_sha256": sha256_file(script_path),
            "elapsed_seconds": time.perf_counter()-started,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "analysis_method_corrections": [
                "Source review found the initial clock-only penalty-pair prototype could select a same-second faceoff as if it preceded a penalty and could skip an immediate restart. Final overlap evidence uses sequence order and faceoff-delimited state transitions, requires clean shift-count agreement and no intervening goal, and reports penalty groups when service identity is ambiguous.",
                "Situation-code reconciliation excludes rows with unknown shift positions or duplicate active player tracks; all exclusions and remaining disagreements are counted separately.",
                "The final event-rate report retains the preregistered 2,000 game-cluster intervals for rates; descriptive Poisson-deviance differences are point estimates and are not separately bootstrapped.",
            ],
            "training_seasons": list(TRAIN_SEASONS),
            "development_seasons": list(DEV_SEASONS),
            "excluded_seasons": {"2018": "chronology/source-quality quarantine",
                                 "2022": "previously exposed; not used"},
        },
        "source_inventory": {
            "data_root": str(data_root),
            "pbp": _manifest_inventory(pbp_manifest, "GameCenter PBP"),
            "shifts": _manifest_inventory(shift_manifest, "NHL shift charts"),
            "pbp_manifest_sha256": PBP_MANIFEST_SHA256,
            "shift_manifest_sha256": SHIFT_MANIFEST_SHA256,
            "source_list_games": 4876,
            "body_hashes_checked_by_v01_for_selected_seasons": True,
            "shift_body_hashes_checked_for_each_processed_eligible_game": True,
        },
        "boxscore": {
            "manifest_sha256": corpus.boxscore_manifest_sha256,
            "games": corpus.boxscore_manifest_games,
            "source_counts": corpus.boxscore_source_counts,
            "validated_independently_against_pbp": True,
        },
        "rulebook": {
            "edition": "2021-22 NHL Official Rules",
            "url": "https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf",
            "sha256": "17ef416dcb556f510df51efd45451e8d37da80da9e69488f78e3d8771228caa7",
            "scope_note": "direct deterministic rule reference for the 2021 development season; earlier training seasons require their applicable editions before rule-specific claims are transferred",
        },
        "coverage_matrix": COVERAGE_MATRIX,
        "population": {"seasons": populations_with_years,
                        "train_games": len(training_ids), "development_games": len(development_ids)},
        "legendarypicks_database": _db_inventory(db_path),
        "behavior": {
            "training_2019_2020": _season_summary(training_stats, len(training_ids)),
            "development_2021": _season_summary(development_stats, len(development_ids)),
        },
        "model_diagnostics": model_report,
        "event_rate_diagnostics": _event_rate_diagnostics(
            training_stats["per_game"], development_stats["per_game"]),
        "team_rate_evaluation": team_evaluation,
        "deterministic_vs_empirical": {
            "deterministic_rule_transitions": [
                "period/clock boundaries and regular-season OT/SO path for the pinned rule edition",
                "penalty durations, releases, manpower and restarts where the exact rule table inputs exist"],
            "empirical_behavior_to_estimate": [
                "penalty occurrence and type rates", "faceoff outcomes and post-faceoff event sequences",
                "shift durations and deployment", "goalie pull timing conditional on score/time",
                "attempt/SOG/goal conversion", "stoppage reasons and restart distributions",
                "OT/SO occurrence and outcomes"],
            "not_observed_by_these_sources": [
                "continuous possession and passes", "unrecorded shot opportunities",
                "all whistles and the geometric basis of offside/icing calls",
                "coach intent, exact line identity, fatigue, physical shot release points for blocked shots"],
        },
        "decision": "development evidence and targeted rule correction only; no candidate selected, no validity gate changed, no adoption claim",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # The report time is written consistently into both emitted artifacts.
    result["metadata"]["elapsed_seconds"] = time.perf_counter()-started
    output_path.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n",
                           encoding="utf-8")
    report_path.write_text(_render_markdown(result), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--boxscore-root", type=Path, default=DEFAULT_BOXSCORE_ROOT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path,
                        default=ROOT / "docs/research/NHL-BEHAVIOR-EVIDENCE-AND-RULES-COVERAGE-2026-10-26.md")
    args = parser.parse_args()
    result = run_audit(args.data_root, args.boxscore_root, args.db, args.output, args.report)
    print(json.dumps({"eligible_train": result["population"]["train_games"],
                      "eligible_development": result["population"]["development_games"],
                      "elapsed_seconds": result["metadata"]["elapsed_seconds"],
                      "json": str(args.output), "report": str(args.report)}, sort_keys=True))


if __name__ == "__main__":
    main()
