#!/usr/bin/env python3
"""Build normalized seed and historical features from the frozen MIN-DET artifacts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ACTION_TYPES = {"run", "pass", "qb_kneel", "qb_spike", "punt", "field_goal"}
SCRIMMAGE_TYPES = {"run", "pass"}
TERMINALS = ("punt", "touchdown", "field_goal_attempt", "turnover_on_downs", "turnover",
             "safety", "qb_kneel", "period_end", "other")
SCORE_BUCKETS = ("leading", "tied", "trailing")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _terminal(value: str | None) -> str:
    text = (value or "").strip().lower()
    if "turnover on downs" in text or text == "downs":
        return "turnover_on_downs"
    if "touchdown" in text:
        return "touchdown"
    if "field goal" in text:
        return "field_goal_attempt"
    if "punt" in text:
        return "punt"
    if "turnover" in text or "interception" in text or "fumble" in text:
        return "turnover"
    if "safety" in text:
        return "safety"
    if "qb kneel" in text:
        return "qb_kneel"
    if "end of" in text or "half" in text or "game" in text:
        return "period_end"
    return "other"


def _combine(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    result = {}
    for key in sorted(set(left) | set(right)):
        a = _number(left.get(key))
        b = _number(right.get(key))
        if a is None or b is None:
            continue
        result[f"{key}_mean"] = (a + b) / 2
        result[f"{key}_absdiff"] = abs(a - b)
    return result


def _player_usage(players: list[dict], team: str) -> dict[str, float]:
    lines = [player for player in players if player.get("team") == team]
    qbs = [player for player in lines if str(player.get("position", "")).upper() == "QB"]
    rbs = [player for player in lines if str(player.get("position", "")).upper() == "RB"]
    receivers = [player for player in lines if str(player.get("position", "")).upper() in {"WR", "TE", "RB"}]
    pass_attempts = [float((player.get("passing") or {}).get("att") or 0) for player in qbs]
    carries = [float((player.get("rushing") or {}).get("att") or 0) for player in rbs]
    targets = [float((player.get("receiving") or {}).get("tgt") or 0) for player in receivers]
    rb_total = sum(carries)
    target_total = sum(targets)
    rb_shares = [value / rb_total for value in carries if rb_total]
    target_shares = [value / target_total for value in targets if target_total]
    drive_features = {
        "qb_attempts_top": max(pass_attempts, default=0.0),
        "rb_carry_share_top": max(rb_shares, default=0.0),
        "rb_carry_hhi": sum(value * value for value in rb_shares),
        "wr_target_share_top": max(target_shares, default=0.0),
        "wr_target_hhi": sum(value * value for value in target_shares),
        "qb_attempts_team": sum(pass_attempts),
        "rb_carries_team": rb_total,
        "receiver_targets_team": target_total,
        "sacks_taken": sum(float((player.get("passing") or {}).get("sacked") or 0) for player in qbs),
        "participants_with_opportunity": float(sum(
            bool((player.get("passing") or {}).get("att") or (player.get("rushing") or {}).get("att")
                 or (player.get("receiving") or {}).get("tgt")) for player in lines)),
    }
    return drive_features


def _drive_features(drives: list[dict]) -> dict[str, float]:
    n = len(drives)
    terminal_counts = Counter(_terminal(drive.get("terminal")) for drive in drives)
    event_counts = [float(_number(drive.get("play_count")) or 0) for drive in drives]
    yardages = [float(_number(drive.get("net_yards")) or 0) for drive in drives]
    starts = [float(value) for drive in drives
              if (value := _number(drive.get("start_yardline_100"))) is not None]
    scored = sum(float(_number(drive.get("points")) or 0) > 0 for drive in drives)
    turnovers = sum(float(_number(drive.get("turnovers")) or 0) > 0 for drive in drives)
    features = {
        "drive_count": float(n),
        "scoring_drive_rate": scored / n if n else 0.0,
        "turnover_drive_rate": turnovers / n if n else 0.0,
        "plays_per_drive": _safe_mean(event_counts),
        "yards_per_drive": _safe_mean(yardages),
        "starting_yardline": _safe_mean(starts),
        "yards_per_game": sum(yardages),
        "events_per_game": sum(event_counts),
    }
    for terminal in TERMINALS:
        features[f"terminal_{terminal}_rate"] = terminal_counts[terminal] / n if n else 0.0
    return features


def _decision_features(decisions: list[dict], team: str) -> dict[str, float]:
    rows = [row for row in decisions if row.get("team") == team]
    count = lambda predicate: sum(float(_number(row.get("count")) or 0)
                                  for row in rows if predicate(row))
    run = count(lambda row: row.get("action") == "run")
    passed = count(lambda row: row.get("action") == "pass")
    scrimmage = run + passed
    features = {"run_share": run / scrimmage if scrimmage else 0.0,
                "pass_share": passed / scrimmage if scrimmage else 0.0,
                "decision_count": scrimmage}
    for down in (1, 2, 3, 4):
        run_down = count(lambda row, d=down: row.get("down") == d and row.get("action") == "run")
        pass_down = count(lambda row, d=down: row.get("down") == d and row.get("action") == "pass")
        total = run_down + pass_down
        features[f"down_{down}_run_share"] = run_down / total if total else 0.0
        features[f"down_{down}_decision_count"] = total
    for bucket in SCORE_BUCKETS:
        run_bucket = count(lambda row, b=bucket: _score_bucket(row.get("score_bucket")) == b
                           and row.get("action") == "run")
        pass_bucket = count(lambda row, b=bucket: _score_bucket(row.get("score_bucket")) == b
                            and row.get("action") == "pass")
        total = run_bucket + pass_bucket
        features[f"score_{bucket}_run_share"] = run_bucket / total if total else 0.0
    for quarter in range(1, 5):
        run_q = count(lambda row, q=quarter: row.get("quarter") == q and row.get("action") == "run")
        pass_q = count(lambda row, q=quarter: row.get("quarter") == q and row.get("action") == "pass")
        total = run_q + pass_q
        features[f"q{quarter}_run_share"] = run_q / total if total else 0.0
    return features


def _score_bucket(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"tied", "tie", "even"}:
        return "tied"
    if text.startswith(("up", "lead", "ahead")):
        return "leading"
    if text.startswith(("dn", "down", "trail", "behind")):
        return "trailing"
    return "unknown"


def _candidate_feature_record(row: dict, drives_by_seed: dict[int, list[dict]]) -> dict:
    outcome = row.get("outcome") or {}
    box = outcome.get("boxscore") or {}
    teams = box.get("teams") or []
    if len(teams) != 2:
        teams = []
    names = [str(item.get("team")) for item in teams]
    team_rows = {str(item.get("team")): item for item in teams}
    seed_drives = drives_by_seed.get(int(row["seed"]), [])
    drive_by_team = defaultdict(list)
    for drive in seed_drives:
        drive_by_team[str(drive.get("offense_team"))].append(drive)
    player_lines = box.get("players") or []
    decisions = (outcome.get("playcall") or {}).get("situational_decision_counts") or []
    team_features = {}
    for team in names:
        stats = team_rows[team].get("stats") or {}
        drive_feats = _drive_features(drive_by_team.get(team, []))
        drive_feats.update({
            "scrimmage_plays": float(_number(stats.get("plays")) or 0),
            "team_yards": float(_number(stats.get("passing_yards")) or 0)
                          + float(_number(stats.get("rushing_yards")) or 0),
            "team_turnovers": float(_number(stats.get("turnovers")) or 0),
        })
        team_features[team] = {
            "drives": drive_feats,
            "decisions": _decision_features(decisions, team),
            "workloads": _player_usage(player_lines, team),
        }

    if len(names) == 2:
        group_features = {group: _combine(team_features[names[0]][group], team_features[names[1]][group])
                          for group in ("drives", "decisions", "workloads")}
    else:
        group_features = {group: {} for group in ("drives", "decisions", "workloads")}
    points_by_period = box.get("points_by_period") or {}
    point_values = {team: _number((team_rows.get(team, {}).get("stats") or {}).get("points")) or 0.0
                    for team in names}
    all_points = sorted(point_values.values(), reverse=True)
    team_total = sum(point_values.values())
    margin = abs(point_values[names[0]] - point_values[names[1]]) if len(names) == 2 else None
    game = {
        "score_total_proxy": team_total,
        "score_margin_proxy": float(margin or 0),
        "score_mean_proxy": _safe_mean(list(point_values.values())),
        "score_high_proxy": max(all_points, default=0.0),
        "total_yards": sum((team_features[t]["drives"].get("team_yards", 0) for t in names), 0.0),
        "yards_absdiff": abs(team_features[names[0]]["drives"].get("team_yards", 0)
                             - team_features[names[1]]["drives"].get("team_yards", 0)) if len(names) == 2 else 0.0,
        "turnovers_total": sum((team_features[t]["drives"].get("team_turnovers", 0) for t in names), 0.0),
    }
    for quarter in range(1, 5):
        values = [float(_number((points_by_period.get(team) or {}).get(f"Q{quarter}")) or 0) for team in names]
        game[f"q{quarter}_points_total_proxy"] = sum(values)
        game[f"q{quarter}_points_absdiff_proxy"] = abs(values[0] - values[1]) if len(values) == 2 else 0.0
    group_features["game"] = game

    paired = {tuple(sorted(names)), (names[0], names[1])}
    home_points = float(_number(outcome.get("home_points")) or 0)
    away_points = float(_number(outcome.get("away_points")) or 0)
    drive_summaries = box.get("quarter_by_quarter", {}).get("drive_summaries", [])
    score_only_overtime = any(str(drive.get("start_period", "")).upper() == "OT"
                              and int(_number(drive.get("play_count")) or 0) == 0 for drive in drive_summaries)
    reconciliation = box.get("reconciliation") or {}
    matches = (reconciliation.get("status") == "passed"
               and all(team.get("matches") is True for team in reconciliation.get("teams", [])))
    return {
        "seed": int(row["seed"]), "teams": sorted(names), "features": group_features,
        "status": outcome.get("status", "unknown"), "valid_full_game": outcome.get("valid_full_game") is True,
        "reconciliation": {"matches": matches},
        "score_only_overtime": score_only_overtime,
        "complete_sequence": False, "replay_status": "not_tested",
        "points": {"team": home_points, "opponent": away_points},
        "story": {"margin": margin, "total_points": team_total,
                  "comeback": _has_comeback(points_by_period, names),
                  "defensive_score": team_total <= 38 and (
                      group_features["drives"].get("terminal_punt_rate_mean", 0) >= 0.25
                      or group_features["game"].get("turnovers_total", 0) >= 3),
                  "plausible_star": _plausible_star(player_lines)},
        "team_features": team_features,
        "source_status": outcome.get("status"),
    }


def _has_comeback(points_by_period: dict, teams: list[str]) -> bool:
    if len(teams) != 2:
        return False
    totals = {team: 0.0 for team in teams}
    was_behind = {team: False for team in teams}
    recovered = {team: False for team in teams}
    for quarter in range(1, 5):
        for team in teams:
            totals[team] += float(_number((points_by_period.get(team) or {}).get(f"Q{quarter}")) or 0)
        for team, other in ((teams[0], teams[1]), (teams[1], teams[0])):
            if totals[team] < totals[other]:
                was_behind[team] = True
            elif was_behind[team] and totals[team] > totals[other]:
                recovered[team] = True
    return any(recovered.values())


def _plausible_star(players: list[dict]) -> bool:
    # The shortlist is already realism-ranked; this selects a high but bounded workload.
    rushes = [float((p.get("rushing") or {}).get("att") or 0) for p in players
              if str(p.get("position", "")).upper() == "RB"]
    targets = [float((p.get("receiving") or {}).get("tgt") or 0) for p in players
               if str(p.get("position", "")).upper() in {"WR", "TE"}]
    attempts = [float((p.get("passing") or {}).get("att") or 0) for p in players]
    return (18 <= max(rushes, default=0) <= 30
            or 8 <= max(targets, default=0) <= 16
            or 35 <= max(attempts, default=0) <= 50)


def read_seed_rows(ledger_paths: list[Path], *, expected_count: int = 10000) -> list[dict]:
    rows = []
    seen = set()
    for path in sorted(ledger_paths):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("type") == "manifest" or item.get("schema") or "header" in item:
                    continue
                seed = item.get("seed")
                if type(seed) is not int or seed < 1 or seed > expected_count:
                    raise ValueError(f"{path}:{line_number}: invalid seed identity {seed!r}")
                if seed in seen:
                    raise ValueError(f"duplicate archived seed identity: {seed}")
                if item.get("outcome", {}).get("seed") != seed:
                    raise ValueError(f"{path}:{line_number}: seed and outcome identities differ")
                seen.add(seed)
                rows.append(item)
    expected = set(range(1, expected_count + 1))
    if seen != expected:
        raise ValueError(f"archived seed identity coverage mismatch: missing={len(expected - seen)}, extra={len(seen - expected)}")
    return sorted(rows, key=lambda row: row["seed"])


def verify_boxscore_sidecars(seed_rows: list[dict], sidecar_paths: list[Path], *, expected_count: int = 10000) -> None:
    """Verify each embedded per-seed boxscore against its separately archived sidecar row."""
    hashes = {}
    for path in sorted(sidecar_paths):
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("type") == "manifest":
                    continue
                seed = row.get("seed")
                if type(seed) is not int or seed < 1 or seed > expected_count:
                    raise ValueError(f"{path}:{line_number}: invalid boxscore seed identity {seed!r}")
                if seed in hashes:
                    raise ValueError(f"duplicate boxscore sidecar seed identity: {seed}")
                canonical = json.dumps({key: value for key, value in row.items() if key != "type"},
                                       sort_keys=True, separators=(",", ":"))
                hashes[seed] = hashlib.sha256(canonical.encode()).hexdigest()
    expected = set(range(1, expected_count + 1))
    if set(hashes) != expected:
        raise ValueError(f"boxscore sidecar identity coverage mismatch: missing={len(expected - set(hashes))}")
    for row in seed_rows:
        seed = int(row["seed"])
        embedded = row.get("outcome", {}).get("boxscore") or {}
        canonical = json.dumps(embedded, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        if digest != hashes.get(seed):
            raise ValueError(f"embedded boxscore differs from archived sidecar for seed {seed}")


def read_drive_csv(path: Path) -> dict[int, list[dict]]:
    by_seed: dict[int, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            seed = int(row["seed"])
            for key in ("drive_index", "play_count", "net_yards", "points", "turnovers", "start_yardline_100"):
                row[key] = _number(row.get(key))
            by_seed[seed].append(row)
    return by_seed


def _historical_rows(db_path: Path) -> list[dict]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(nfl_pbp)")}
    wanted = ["game_id", "play_id", "season", "week", "posteam", "defteam", "home_team", "away_team", "drive",
              "game_date", "qtr", "down", "ydstogo", "yardline_100", "game_seconds_remaining",
              "play_type", "series_result", "yards_gained", "touchdown", "two_point_attempt",
              "pass_attempt", "rush_attempt", "passer_player_id", "rusher_player_id", "receiver_player_id",
              "interception", "fumble_lost", "sack", "qb_dropback"]
    selected = [name for name in wanted if name in columns]
    query = f"SELECT {', '.join(selected)} FROM nfl_pbp WHERE season BETWEEN 2022 AND 2025 AND week BETWEEN 1 AND 18 ORDER BY game_id, play_id"
    source = [dict(row) for row in connection.execute(query)]
    player_positions = {}
    player_columns = {row["name"] for row in connection.execute("PRAGMA table_info(players)")}
    id_col = next((name for name in ("gsis_id", "gsis_player_id", "player_id") if name in player_columns), None)
    pos_col = "position" if "position" in player_columns else None
    if id_col and pos_col:
        player_positions = {str(row[0]): str(row[1] or "").upper()
                            for row in connection.execute(f"SELECT {id_col}, {pos_col} FROM players")}
    connection.close()
    return _aggregate_historical(source, player_positions)


def _aggregate_historical(rows: list[dict], player_positions: dict[str, str]) -> list[dict]:
    games: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        games[str(row["game_id"])].append(row)
    output = []
    for game_id, events in sorted(games.items()):
        if not events:
            continue
        first = events[0]
        teams = [str(first.get("home_team") or ""), str(first.get("away_team") or "")]
        teams = [team for team in teams if team]
        if len(teams) != 2:
            continue
        team_rows = {team: [] for team in teams}
        game_points = {team: 0.0 for team in teams}
        quarter_points = {team: Counter() for team in teams}
        player_qb = defaultdict(Counter)
        player_rb = defaultdict(Counter)
        player_target = defaultdict(Counter)
        player_participation = defaultdict(set)
        current_points = {team: 0.0 for team in teams}
        drive_groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
        # The archived PBP snapshot has no authoritative schedule score or conversion result.
        # Keep an explicitly labelled scoring proxy (TD=6, FG=3, every EP attempt=1).
        for event in events:
            posteam = event.get("posteam")
            if posteam in team_rows:
                team_rows[posteam].append(event)
            try:
                drive_number = int(float(event.get("drive")))
            except (TypeError, ValueError):
                drive_number = 0
            if posteam in team_rows and drive_number:
                drive_groups[(drive_number, posteam)].append(event)
            event_team = posteam if posteam in team_rows else None
            quarter = int(_number(event.get("qtr")) or 1)
            if event.get("play_type") == "field_goal" and str(event.get("series_result") or "").lower() == "field goal" and event_team:
                current_points[event_team] += 3
                quarter_points[event_team][quarter] += 3
            elif int(_number(event.get("touchdown")) or 0) == 1 and event_team:
                scorer = event_team
                if str(event.get("series_result") or "").lower() == "opp touchdown":
                    scorer = event.get("defteam") if event.get("defteam") in team_rows else event_team
                current_points[scorer] += 6
                quarter_points[scorer][quarter] += 6
            elif event.get("play_type") == "extra_point" and event_team:
                current_points[event_team] += 1
                quarter_points[event_team][quarter] += 1
            if event.get("play_type") == "safety" and event_team:
                opponent = event.get("defteam")
                if opponent in team_rows:
                    current_points[opponent] += 2
                    quarter_points[opponent][quarter] += 2
            if event_team:
                pid = event.get("passer_player_id")
                if pid and int(_number(event.get("pass_attempt")) or 0):
                    player_qb[(event_team, str(pid))]["attempts"] += 1
                    player_participation[event_team].add(str(pid))
                rid = event.get("rusher_player_id")
                if rid and int(_number(event.get("rush_attempt")) or 0):
                    player_rb[(event_team, str(rid))]["carries"] += 1
                    player_participation[event_team].add(str(rid))
                target = event.get("receiver_player_id")
                if target and event.get("play_type") == "pass":
                    player_target[(event_team, str(target))]["targets"] += 1
                    player_participation[event_team].add(str(target))
        # Score state is reconstructed with the same transparent proxy for decision context.
        score_before = {team: 0.0 for team in teams}
        decision_rows = defaultdict(list)
        for event in events:
            team = event.get("posteam")
            if team not in team_rows:
                continue
            if event.get("play_type") in SCRIMMAGE_TYPES:
                down = int(_number(event.get("down")) or 0)
                action = "run" if event.get("play_type") == "run" else "pass"
                diff = score_before[team] - score_before.get(event.get("defteam"), 0.0)
                bucket = "tied" if diff == 0 else ("leading" if diff > 0 else "trailing")
                decision_rows[team].append({"team": team, "action": action, "down": down,
                                            "score_bucket": bucket, "quarter": int(_number(event.get("qtr")) or 1),
                                            "count": 1})
            # Update after recording any scrimmage decision so its result cannot affect its own state bucket.
            result = str(event.get("series_result") or "").lower()
            if event.get("play_type") == "field_goal" and result == "field goal":
                score_before[team] += 3
            if int(_number(event.get("touchdown")) or 0) == 1:
                score_before[team] += 6
            if event.get("play_type") == "extra_point":
                score_before[team] += 1

        per_team = {}
        for team in teams:
            plays = team_rows[team]
            drive_rows = []
            for (_drive_index, offense), drive_events in drive_groups.items():
                if offense != team:
                    continue
                action_rows = [event for event in drive_events if event.get("play_type") in ACTION_TYPES]
                terminal_raw = next((str(event.get("series_result")) for event in reversed(drive_events)
                                     if event.get("series_result") not in (None, "")), None)
                start = next((_number(event.get("yardline_100")) for event in action_rows
                              if _number(event.get("yardline_100")) is not None), None)
                drive_rows.append({
                    "terminal": _terminal(terminal_raw), "play_count": len(action_rows),
                    "net_yards": sum(_number(event.get("yards_gained")) or 0 for event in action_rows),
                    "start_yardline_100": start,
                    "points": 1 if terminal_raw and ("touchdown" in terminal_raw.lower()
                                                      or terminal_raw.lower() == "field goal") else 0,
                    "turnovers": int(any(int(_number(event.get("interception")) or 0)
                                          or int(_number(event.get("fumble_lost")) or 0)
                                          for event in drive_events)),
                })
            drive_features = _drive_features(drive_rows)
            runs = sum(event.get("play_type") == "run" for event in plays)
            passes = sum(event.get("play_type") == "pass" for event in plays)
            scrimmage = runs + passes
            decisions = decision_rows[team]
            decision_features = _decision_features(decisions, team)
            qb = [count["attempts"] for (tm, _pid), count in player_qb.items() if tm == team]
            rb_all = [count["carries"] for (tm, _pid), count in player_rb.items()
                      if tm == team and player_positions.get(_pid, "RB") == "RB"]
            targets = [count["targets"] for (tm, _pid), count in player_target.items() if tm == team]
            rb_total = sum(rb_all)
            target_total = sum(targets)
            rb_shares = [value / rb_total for value in rb_all if rb_total]
            target_shares = [value / target_total for value in targets if target_total]
            workloads = {
                "qb_attempts_top": float(max(qb, default=0)),
                "rb_carry_share_top": max(rb_shares, default=0.0),
                "rb_carry_hhi": sum(value * value for value in rb_shares),
                "wr_target_share_top": max(target_shares, default=0.0),
                "wr_target_hhi": sum(value * value for value in target_shares),
                "qb_attempts_team": float(sum(qb)), "rb_carries_team": float(rb_total),
                "receiver_targets_team": float(target_total),
                "sacks_taken": float(sum(int(_number(event.get("sack")) or 0) for event in plays)),
                "participants_with_opportunity": float(len(player_participation[team])),
            }
            team_yards = sum(_number(event.get("yards_gained")) or 0 for event in plays
                             if event.get("play_type") in SCRIMMAGE_TYPES)
            turnover_count = sum(int(_number(event.get("interception")) or 0)
                                 + int(_number(event.get("fumble_lost")) or 0) for event in plays)
            drive_features.update({"scrimmage_plays": float(scrimmage), "team_yards": float(team_yards),
                                   "team_turnovers": float(turnover_count)})
            # Include rates unavailable from the staged sidecar only when both sources provide them.
            decision_features["run_share"] = runs / scrimmage if scrimmage else 0.0
            decision_features["pass_share"] = passes / scrimmage if scrimmage else 0.0
            decision_features["decision_count"] = float(scrimmage)
            per_team[team] = {"drives": drive_features, "decisions": decision_features,
                              "workloads": workloads}

        group_features = {group: _combine(per_team[teams[0]][group], per_team[teams[1]][group])
                          for group in ("drives", "decisions", "workloads")}
        points = {team: current_points[team] for team in teams}
        values = list(points.values())
        quarter_totals = []
        game_features = {
            "score_total_proxy": sum(values), "score_margin_proxy": abs(values[0] - values[1]),
            "score_mean_proxy": _safe_mean(values), "score_high_proxy": max(values),
            "total_yards": sum(per_team[team]["drives"]["team_yards"] for team in teams),
            "yards_absdiff": abs(per_team[teams[0]]["drives"]["team_yards"]
                                 - per_team[teams[1]]["drives"]["team_yards"]),
            "turnovers_total": sum(per_team[team]["drives"]["team_turnovers"] for team in teams),
        }
        for quarter in range(1, 5):
            qvalues = [float(quarter_points[team][quarter]) for team in teams]
            game_features[f"q{quarter}_points_total_proxy"] = sum(qvalues)
            game_features[f"q{quarter}_points_absdiff_proxy"] = abs(qvalues[0] - qvalues[1])
        group_features["game"] = game_features
        output.append({"game_id": game_id, "season": int(first["season"]), "teams": sorted(teams),
                       "features": group_features, "points_proxy": points,
                       "scoring_proxy_note": "TD=6, field goal=3, every recorded extra-point attempt=1; conversion result unavailable"})
    return output


def prepare(seed_rows: list[dict], drive_csv: Path, database: Path) -> tuple[list[dict], list[dict]]:
    drive_data = read_drive_csv(drive_csv)
    seeds = [_candidate_feature_record(row, drive_data) for row in seed_rows]
    historical = _historical_rows(database)
    return seeds, historical


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--boxscore-dir", type=Path, required=True)
    parser.add_argument("--drive-csv", type=Path, required=True)
    parser.add_argument("--historical-db", type=Path, required=True)
    parser.add_argument("--historical-manifest", type=Path, required=True)
    parser.add_argument("--input-hash-manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--expected-games", type=int, default=10000)
    args = parser.parse_args(argv)

    historical_manifest = json.loads(args.historical_manifest.read_text())
    expected_db = historical_manifest["historical"]["database_sha256"]
    actual_db = sha256(args.historical_db)
    if actual_db != expected_db:
        raise SystemExit(f"historical DB SHA-256 mismatch: expected {expected_db}, got {actual_db}")
    run_manifest = json.loads(args.input_hash_manifest.read_text())
    expected_hashes = run_manifest.get("sha256", {})
    ledgers = sorted(args.raw_dir.glob("worker-*.seeds.jsonl"))
    sidecars = sorted(args.boxscore_dir.glob("worker-*.boxscores.jsonl"))
    if not ledgers:
        raise SystemExit(f"no per-seed ledgers under {args.raw_dir}")
    if len(sidecars) != len(ledgers):
        raise SystemExit(f"expected one boxscore sidecar for each seed ledger; found {len(sidecars)} vs {len(ledgers)}")
    for path in ledgers:
        expected = expected_hashes.get(path.name)
        if not expected:
            raise SystemExit(f"missing frozen hash for {path.name}")
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(f"seed ledger SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")
    seed_rows = read_seed_rows(ledgers, expected_count=args.expected_games)
    for path in sidecars:
        expected = expected_hashes.get(path.name)
        if not expected:
            raise SystemExit(f"missing frozen hash for {path.name}")
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(f"boxscore sidecar SHA-256 mismatch for {path.name}: expected {expected}, got {actual}")
    verify_boxscore_sidecars(seed_rows, sidecars, expected_count=args.expected_games)
    seeds, historical = prepare(seed_rows, args.drive_csv, args.historical_db)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("seed-features.jsonl", seeds), ("historical-features.jsonl", historical)):
        with (args.out_dir / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    provenance = {
        "schema": "lp.nfl.slc-realism-inputs.v1",
        "run": run_manifest.get("run"),
        "source_commit": run_manifest.get("source_commit"),
        "seed_count": len(seeds),
        "historical_game_count": len(historical),
        "historical_seasons": sorted({row["season"] for row in historical}),
        "historical_source_manifest_sha256": sha256(args.historical_manifest),
        "historical_source_manifest_pin_sha256": historical_manifest["historical"].get("source_manifest_sha256"),
        "historical_database_sha256": actual_db,
        "drive_csv_sha256": sha256(args.drive_csv),
        "seed_ledger_sha256": {path.name: sha256(path) for path in ledgers},
        "boxscore_sidecar_sha256": {path.name: sha256(path) for path in sidecars},
        "historical_score_limit": "Historical PBP snapshot lacks authoritative schedule scores and try results; game score features are a labelled proxy.",
        "team_conditioning": "Nearest neighbors are league-wide with same-team and exact-pair cohorts shrunk by cohort size.",
    }
    (args.out_dir / "input-provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"seed_count": len(seeds), "historical_games": len(historical),
                      "out_dir": str(args.out_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
