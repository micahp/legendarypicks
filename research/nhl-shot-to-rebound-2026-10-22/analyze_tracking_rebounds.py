#!/usr/bin/env python3
"""Audit Stathletes Big Data Cup 2026 coverage and compare grouped-CV shot models.

This script reads the release CSVs sequentially. It never writes the source files,
does not contact a provider or database, and does not copy raw tracking rows into
the repository. Movement features use only the two complete integer-second clock
bins before each shot's recorded clock. The labels are later event-sequence
outcomes and are never used as predictors.
"""

from __future__ import print_function

import argparse
import collections
import csv
import datetime
import glob
import json
import math
import os
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


SHOT_EVENTS = set(("Shot", "Goal"))
POSSESSION_EVENTS = set(("Play", "Incomplete Play", "Takeaway", "Zone Entry", "Dump In/Out"))
STOP_EVENTS = set(("Faceoff Win", "Penalty Taken", "Goal"))
SHOT_TYPES = ("Deflection", "Fan", "Slapshot", "Snapshot", "Wrap around", "Wristshot", "other")
PREVIOUS_EVENTS = (
    "Faceoff Win", "Puck Recovery", "Zone Entry", "Shot", "Goal", "Play",
    "Incomplete Play", "Dump In/Out", "Takeaway", "Penalty Taken", "other", "none",
)

EVENT_NUMERIC = (
    "shot_x_abs", "shot_abs_y", "shot_x_edge_distance", "period",
    "seconds_remaining", "pre_score_diff", "skater_diff", "home_shot",
    "traffic", "one_timer", "previous_event_elapsed",
)
MOVEMENT_NUMERIC = (
    "puck_vx", "puck_vy", "puck_speed",
    "same_nearest", "same_second_nearest", "opp_nearest", "opp_second_nearest",
    "same_within_10", "same_within_20", "opp_within_10", "opp_within_20",
    "same_nearest_closing", "opp_nearest_closing",
    "goalie_proxy_found", "goalie_proxy_identified", "goalie_proxy_goal_distance", "goalie_proxy_puck_distance",
    "goalie_proxy_vx", "goalie_proxy_vy", "tracked_same_count", "tracked_opp_count",
    "shooter_tracking_matched", "shooter_puck_distance", "shooter_speed",
    "shooter_vx", "shooter_vy",
)
CATEGORICAL = {
    "shot_type": SHOT_TYPES,
    "previous_event": PREVIOUS_EVENTS,
}

TARGETS = (
    "goal_from_attempt",
    "recovery_within_3s",
    "any_followup_shot_within_5s",
    "same_team_followup_shot_within_5s",
)

ROBUSTNESS_ALPHAS = (0.2, 1.0, 5.0, 20.0, 100.0, 500.0)
ROBUSTNESS_BOOTSTRAP_REPS = 2000
ROBUSTNESS_NULL_REPS = 20


def parse_clock(value):
    if not value:
        return None
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def number(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def truth(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y"):
        return 1.0
    if text in ("0", "false", "no", "n"):
        return 0.0
    return None


def percentile(values, quantile):
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), quantile))


def load_orientations(data_dir):
    path = os.path.join(data_dir, "camera_orientations.csv")
    result = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            game = (row.get("Game") or "").strip()
            side = (row.get("GoalieTeamOnRightSideOfRink1stPeriod") or "").strip()
            result[game] = side
    return result


def inspect_release_manifest(data_dir):
    path = os.path.join(data_dir, "download-manifest.json")
    with open(path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    files = manifest.get("files", [])
    missing = []
    size_mismatches = []
    type_counts = collections.Counter()
    for item in files:
        name = item.get("name")
        source_path = os.path.join(data_dir, name)
        if not os.path.isfile(source_path):
            missing.append(name)
            continue
        if os.path.getsize(source_path) != int(item.get("bytes", -1)):
            size_mismatches.append(name)
        if name.endswith(".Events.csv"):
            kind = "event"
        elif name.endswith(".Shifts.csv"):
            kind = "shifts"
        elif ".Tracking_" in name:
            kind = "tracking"
        elif name == "camera_orientations.csv":
            kind = "orientation"
        else:
            kind = "other"
        type_counts[kind] += 1
    if int(manifest.get("asset_count", -1)) != len(files):
        raise RuntimeError("release manifest asset_count does not match its file list")
    if missing or size_mismatches:
        raise RuntimeError("release files do not match manifest: missing=%r size_mismatch=%r" % (missing, size_mismatches))
    return {
        "repository": manifest.get("repository"),
        "release_tag": manifest.get("release_tag"),
        "release_url": manifest.get("release_url"),
        "listed_asset_count": int(manifest.get("asset_count", 0)),
        "listed_total_bytes": int(manifest.get("total_bytes", 0)),
        "file_type_counts": dict(type_counts),
        "manifest_size_check": "PASS",
        "sha256_values_present_in_manifest": sum(1 for item in files if item.get("sha256")),
        "note": "this run checked listed names and byte sizes; it did not recompute SHA-256 digests",
    }


def game_label_from_event_path(path):
    name = os.path.basename(path)
    suffix = ".Events.csv"
    if not name.endswith(suffix):
        raise ValueError("unexpected event filename: " + name)
    return name[:-len(suffix)].replace(".", " ")


def read_events(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        for index, raw in enumerate(csv.DictReader(handle)):
            row = dict(raw)
            row["_index"] = index
            row["_period"] = int(row["Period"])
            row["_clock"] = parse_clock(row["Clock"])
            row["_event"] = (row.get("Event") or "").strip()
            row["_team"] = (row.get("Team") or "").strip()
            rows.append(row)
    return rows


def inspect_shifts(path):
    if not os.path.isfile(path):
        raise RuntimeError("missing shifts file: " + path)
    rows = 0
    player_teams = set()
    player_ids_by_team = collections.defaultdict(set)
    periods = collections.Counter()
    goal_tokens = 0
    lengths = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows += 1
            team = (row.get("Team") or "").strip()
            player = (row.get("Player_Id") or "").strip()
            if team and player:
                player_teams.add((team, player))
                player_ids_by_team[team].add(player)
            if player.lower() in ("go", "goalie", "g"):
                goal_tokens += 1
            try:
                periods[str(int(row.get("period") or 0))] += 1
            except ValueError:
                pass
            duration = parse_clock(row.get("shift_length"))
            if duration is not None:
                lengths.append(duration)
    return {
        "file": os.path.basename(path),
        "shift_rows": rows,
        "unique_team_player_ids": len(player_teams),
        "unique_player_ids_by_team": {team: len(ids) for team, ids in player_ids_by_team.items()},
        "goalie_placeholder_rows": goal_tokens,
        "shift_rows_by_period": dict(periods),
        "shift_length_seconds_median": percentile(lengths, 50),
    }


def previous_score(row, events, index):
    if index > 0:
        previous = events[index - 1]
        try:
            return int(previous["Home_Team_Goals"]), int(previous["Away_Team_Goals"])
        except (KeyError, TypeError, ValueError):
            pass
    try:
        home = int(row["Home_Team_Goals"])
        away = int(row["Away_Team_Goals"])
    except (KeyError, TypeError, ValueError):
        return None, None
    if row["_event"] == "Goal":
        if row["_team"] == row.get("Home_Team"):
            home = max(0, home - 1)
        elif row["_team"] == row.get("Away_Team"):
            away = max(0, away - 1)
    return home, away


def recovery_label(events, shot_index, shooter_team):
    shot = events[shot_index]
    start = shot["_clock"]
    if start is None:
        return None, None, None
    for later in events[shot_index + 1:]:
        if later["_period"] != shot["_period"]:
            break
        clock = later["_clock"]
        if clock is None:
            continue
        elapsed = start - clock
        if elapsed < 0:
            continue
        if elapsed > 3:
            break
        event = later["_event"]
        if event == "Puck Recovery":
            team = later["_team"]
            return 1, int(team == shooter_team), elapsed
        if event in STOP_EVENTS or event in POSSESSION_EVENTS or event in SHOT_EVENTS:
            break
    return 0, 0, None


def followup_labels(events, shot_index, shooter_team):
    shot = events[shot_index]
    start = shot["_clock"]
    if start is None:
        return 0, 0, None
    for later in events[shot_index + 1:]:
        if later["_period"] != shot["_period"]:
            break
        clock = later["_clock"]
        if clock is None:
            continue
        elapsed = start - clock
        if elapsed < 0:
            continue
        if elapsed > 5:
            break
        event = later["_event"]
        if event in SHOT_EVENTS:
            same_team = int(later["_team"] == shooter_team)
            return 1, same_team, elapsed
        if event in STOP_EVENTS:
            break
        if event == "Puck Recovery":
            if later["_team"] != shooter_team:
                break
            continue
        if event in POSSESSION_EVENTS and later["_team"] != shooter_team:
            break
    return 0, 0, None


def shot_features(events, index, orientation_label):
    row = events[index]
    home = row.get("Home_Team", "")
    away = row.get("Away_Team", "")
    shooter = row["_team"]
    prev = events[index - 1] if index > 0 else None
    prev_event = (prev.get("_event") if prev else "none") or "none"
    if prev_event not in PREVIOUS_EVENTS:
        prev_event = "other"
    x = number(row.get("X_Coordinate"))
    y = number(row.get("Y_Coordinate"))
    remaining = row["_clock"]
    home_score, away_score = previous_score(row, events, index)
    if shooter == home:
        score_diff = None if home_score is None or away_score is None else home_score - away_score
        skater_diff = number(row.get("Home_Team_Skaters"))
        opp_skaters = number(row.get("Away_Team_Skaters"))
        home_shot = 1.0
    elif shooter == away:
        score_diff = None if home_score is None or away_score is None else away_score - home_score
        skater_diff = number(row.get("Away_Team_Skaters"))
        opp_skaters = number(row.get("Home_Team_Skaters"))
        home_shot = 0.0
    else:
        score_diff = None
        skater_diff = None
        opp_skaters = None
        home_shot = None
    if skater_diff is not None and opp_skaters is not None:
        skater_diff -= opp_skaters
    previous_elapsed = None
    if prev and prev["_period"] == row["_period"] and prev["_clock"] is not None and remaining is not None:
        delta = prev["_clock"] - remaining
        previous_elapsed = float(delta) if delta >= 0 else None
    shot_type = (row.get("Detail_1") or "").strip()
    if shot_type not in SHOT_TYPES:
        shot_type = "other"
    orientation_valid = orientation_label in ("Home", "Away")
    return {
        "game": game_label_from_event_path(row["_path"]),
        "period": row["_period"],
        "clock": remaining,
        "team": shooter,
        "shooter_id": (row.get("Player_Id") or "").strip(),
        "home": home,
        "away": away,
        "event": row["_event"],
        "shot_type": shot_type,
        "previous_event": prev_event,
        "shot_x_abs": None if x is None else abs(x),
        "shot_abs_y": None if y is None else abs(y),
        # The source's camera-orientation file identifies which team defends
        # the right-side net. Until coordinate-axis direction is independently
        # verified, use absolute raw x/y and report this coarse x-edge distance.
        "shot_x_edge_distance": None if x is None else abs(89.0 - abs(x)),
        "seconds_remaining": None if remaining is None else float(remaining),
        "pre_score_diff": score_diff,
        "skater_diff": skater_diff,
        "home_shot": home_shot,
        "traffic": truth(row.get("Detail_3")),
        "one_timer": truth(row.get("Detail_4")),
        "previous_event_elapsed": previous_elapsed,
        "orientation_valid": orientation_valid,
        "orientation_label": orientation_label,
        "targets": {},
        "movement": None,
    }


def clock_label(seconds):
    minutes, remainder = divmod(int(seconds), 60)
    return "%d:%02d" % (minutes, remainder)


def close(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_and_closing(current, previous, puck_now, puck_before, team):
    candidates = []
    for key, value in current.items():
        if value["team"] != team:
            continue
        before = previous.get(key)
        dist = close((value["x"], value["y"]), puck_now)
        closing = None
        if before is not None:
            d_before = close((before["x"], before["y"]), puck_before)
            closing = d_before - dist
        candidates.append((dist, closing))
    candidates.sort(key=lambda item: item[0])
    dists = [item[0] for item in candidates]
    closest_closing = candidates[0][1] if candidates else None
    return dists, closest_closing


def movement_features(snapshot_now, snapshot_before, shooter_team, defending_team, right_goalie_team, shooter_jersey):
    if not snapshot_now or not snapshot_before:
        return None
    puck_now = snapshot_now.get("puck")
    puck_before = snapshot_before.get("puck")
    if puck_now is None or puck_before is None:
        return None
    players_now = snapshot_now.get("players", {})
    players_before = snapshot_before.get("players", {})
    same_now = [p for p in players_now.values() if p["team"] == shooter_team]
    opp_now = [p for p in players_now.values() if p["team"] == defending_team]
    same_matched = sum(1 for key in players_now if players_now[key]["team"] == shooter_team and key in players_before)
    opp_matched = sum(1 for key in players_now if players_now[key]["team"] == defending_team and key in players_before)
    if len(same_now) < 3 or len(opp_now) < 3 or same_matched < 3 or opp_matched < 3:
        return None
    same_dists, same_closing = nearest_and_closing(players_now, players_before, puck_now, puck_before, shooter_team)
    opp_dists, opp_closing = nearest_and_closing(players_now, players_before, puck_now, puck_before, defending_team)
    puck_vx = puck_now[0] - puck_before[0]
    puck_vy = puck_now[1] - puck_before[1]
    goalie_x = 89.0 if defending_team == right_goalie_team else -89.0
    identified_goalies = []
    goalie_options = []
    for key, player in players_now.items():
        if player["team"] != defending_team:
            continue
        if (player.get("jersey") or "").strip().lower() in ("go", "g", "goalie"):
            identified_goalies.append((key, player))
        if abs(player["x"]) < 60:
            continue
        goal_distance = close((player["x"], player["y"]), (goalie_x, 0.0))
        goalie_options.append((goal_distance, key, player))
    goalie_options.sort(key=lambda row: row[0])
    if identified_goalies:
        goalie_key, goalie_player = min(
            identified_goalies,
            key=lambda item: close((item[1]["x"], item[1]["y"]), (goalie_x, 0.0)),
        )
        goalie_goal_dist = close((goalie_player["x"], goalie_player["y"]), (goalie_x, 0.0))
        goalie_found = True
        goalie_identified = True
    else:
        goalie_found = bool(goalie_options and goalie_options[0][0] <= 25)
        goalie_identified = False
        goalie_goal_dist = goalie_options[0][0] if goalie_found else None
        goalie_key = goalie_options[0][1] if goalie_found else None
        goalie_player = goalie_options[0][2] if goalie_found else None
    goalie_puck_dist = None
    goalie_vx = None
    goalie_vy = None
    if goalie_found:
        goalie_puck_dist = close((goalie_player["x"], goalie_player["y"]), puck_now)
        before = players_before.get(goalie_key)
        if before is not None:
            goalie_vx = goalie_player["x"] - before["x"]
            goalie_vy = goalie_player["y"] - before["y"]
    shooter_player = None
    shooter_key = None
    for key, player in players_now.items():
        if player["team"] == shooter_team and player.get("jersey") == shooter_jersey:
            shooter_player = player
            shooter_key = key
            break
    shooter_vx = None
    shooter_vy = None
    shooter_speed = None
    shooter_puck_distance = None
    if shooter_player is not None:
        shooter_puck_distance = close((shooter_player["x"], shooter_player["y"]), puck_now)
        shooter_before = players_before.get(shooter_key)
        if shooter_before is not None:
            shooter_vx = shooter_player["x"] - shooter_before["x"]
            shooter_vy = shooter_player["y"] - shooter_before["y"]
            shooter_speed = math.hypot(shooter_vx, shooter_vy)
    return {
        "puck_vx": puck_vx,
        "puck_vy": puck_vy,
        "puck_speed": math.hypot(puck_vx, puck_vy),
        "same_nearest": same_dists[0] if same_dists else None,
        "same_second_nearest": same_dists[1] if len(same_dists) > 1 else None,
        "opp_nearest": opp_dists[0] if opp_dists else None,
        "opp_second_nearest": opp_dists[1] if len(opp_dists) > 1 else None,
        "same_within_10": sum(1 for dist in same_dists if dist <= 10),
        "same_within_20": sum(1 for dist in same_dists if dist <= 20),
        "opp_within_10": sum(1 for dist in opp_dists if dist <= 10),
        "opp_within_20": sum(1 for dist in opp_dists if dist <= 20),
        "same_nearest_closing": same_closing,
        "opp_nearest_closing": opp_closing,
        "goalie_proxy_found": 1.0 if goalie_found else 0.0,
        "goalie_proxy_identified": 1.0 if goalie_identified else 0.0,
        "goalie_proxy_goal_distance": goalie_goal_dist,
        "goalie_proxy_puck_distance": goalie_puck_dist,
        "goalie_proxy_vx": goalie_vx,
        "goalie_proxy_vy": goalie_vy,
        "tracked_same_count": len(same_now),
        "tracked_opp_count": len(opp_now),
        "shooter_tracking_matched": 1.0 if shooter_player is not None else 0.0,
        "shooter_puck_distance": shooter_puck_distance,
        "shooter_speed": shooter_speed,
        "shooter_vx": shooter_vx,
        "shooter_vy": shooter_vy,
    }


def team_right_for_period(home, away, right_first_label, period):
    if right_first_label == "Home":
        right = home
        left = away
    elif right_first_label == "Away":
        right = away
        left = home
    else:
        return None
    if period % 2 == 0:
        return left
    return right


def aggregate_snapshot(accumulator):
    snapshot = {"puck": None, "players": {}}
    for key, value in accumulator.items():
        count = value["n"]
        x = value["x"] / count
        y = value["y"] / count
        if key[0] == "puck":
            snapshot["puck"] = (x, y)
        else:
            snapshot["players"][(key[1], key[2])] = {
                "team": key[1], "id": key[2], "x": x, "y": y,
                "jersey": value.get("jersey"),
            }
    return snapshot


def summarize_z_counts(counts):
    blank = int(counts.get("<blank>", 0))
    values = []
    invalid = 0
    for raw, count in counts.items():
        if raw == "<blank>":
            continue
        value = number(raw)
        if value is None:
            invalid += int(count)
        else:
            values.extend([value] * int(count))
    if not values:
        return {"nonblank_rows": 0, "blank_rows": blank, "invalid_rows": invalid, "unique_numeric_values": 0}
    array = np.asarray(values, dtype=float)
    fixed_count = int(np.sum(np.abs(array - 0.02) < 1e-12))
    return {
        "nonblank_rows": int(array.size + invalid),
        "blank_rows": blank,
        "invalid_rows": invalid,
        "unique_numeric_values": int(len(set(values))),
        "exactly_0_02_rows": fixed_count,
        "nonfixed_rows": int(array.size - fixed_count),
        "negative_rows": int(np.sum(array < 0.0)),
        "min": float(np.min(array)),
        "p50": float(np.percentile(array, 50)),
        "p90": float(np.percentile(array, 90)),
        "p99": float(np.percentile(array, 99)),
        "max": float(np.max(array)),
    }


def inspect_tracking_file(path, wanted_clocks):
    started = time.perf_counter()
    row_count = 0
    frames = 0
    frame_ids = set()
    frame_repeats_noncontiguous = 0
    last_frame = None
    frame_player_count = 0
    frame_puck_count = 0
    frames_with_exactly_one_puck = 0
    frames_with_multiple_pucks = 0
    player_count_hist = collections.Counter()
    puck_frame_count = 0
    puck_rows = 0
    rows_by_kind = collections.Counter()
    z_by_kind = collections.defaultdict(collections.Counter)
    puck_goal_z_values = []
    puck_goal_score_rows = 0
    jersey_unknown = collections.Counter()
    xy_missing = collections.Counter()
    clocks = set()
    periods = collections.Counter()
    bucket_acc = {}
    player_id_jerseys = collections.defaultdict(set)

    def flush_frame():
        nonlocal frames, puck_frame_count, frames_with_exactly_one_puck, frames_with_multiple_pucks
        if last_frame is None:
            return
        frames += 1
        player_count_hist[frame_player_count] += 1
        if frame_puck_count:
            puck_frame_count += 1
        if frame_puck_count == 1:
            frames_with_exactly_one_puck += 1
        elif frame_puck_count > 1:
            frames_with_multiple_pucks += 1

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_count += 1
            frame_id = row.get("Image Id")
            if frame_id != last_frame:
                flush_frame()
                if frame_id in frame_ids:
                    frame_repeats_noncontiguous += 1
                frame_ids.add(frame_id)
                last_frame = frame_id
                frame_player_count = 0
                frame_puck_count = 0
            clock = parse_clock(row.get("Game Clock"))
            if clock is not None:
                clocks.add(clock)
            try:
                periods[int(row.get("Period") or 0)] += 1
            except ValueError:
                pass
            kind = (row.get("Player or Puck") or "").strip()
            team = (row.get("Team") or "").strip()
            rows_by_kind[kind] += 1
            z = row.get("Rink Location Z (Feet)")
            z_by_kind[kind][str(z or "<blank>")] += 1
            if kind == "Puck" and (row.get("Goal Score") or "").strip().upper() == "G":
                puck_goal_score_rows += 1
                goal_z = number(z)
                if goal_z is not None:
                    puck_goal_z_values.append(goal_z)
            x = number(row.get("Rink Location X (Feet)"))
            y = number(row.get("Rink Location Y (Feet)"))
            if x is None or y is None:
                xy_missing[kind] += 1
            if kind == "Puck":
                puck_rows += 1
                frame_puck_count += 1
            elif kind == "Player":
                frame_player_count += 1
                if not (row.get("Player Jersey Number") or "").strip():
                    jersey_unknown[team] += 1
                else:
                    player_id_jerseys[(team, (row.get("Player Id") or "").strip())].add((row.get("Player Jersey Number") or "").strip())
            if clock in wanted_clocks and x is not None and y is not None:
                if kind == "Puck":
                    key = ("puck", "n/a", "puck")
                elif kind == "Player":
                    player_id = (row.get("Player Id") or "").strip()
                    if not player_id or team not in ("Home", "Away"):
                        continue
                    key = ("player", team, player_id)
                else:
                    continue
                bucket = bucket_acc.setdefault(clock, {})
                value = bucket.setdefault(key, {"x": 0.0, "y": 0.0, "n": 0, "jersey": None})
                value["x"] += x
                value["y"] += y
                value["n"] += 1
                if kind == "Player" and (row.get("Player Jersey Number") or "").strip():
                    value["jersey"] = (row.get("Player Jersey Number") or "").strip()
    flush_frame()
    if not clocks or frames == 0:
        raise RuntimeError("no rows or frames in " + path)
    nonempty_player_ids = [values for values in player_id_jerseys.values() if values]
    inconsistent_ids = sum(1 for values in nonempty_player_ids if len(values) > 1)
    span = max(clocks) - min(clocks)
    if frame_repeats_noncontiguous:
        raise RuntimeError("noncontiguous repeated Image Ids in " + path)
    summary = {
        "file": os.path.basename(path),
        "rows": row_count,
        "frames": frames,
        "frame_ids_noncontiguous_repeats": frame_repeats_noncontiguous,
        "clock_seconds": len(clocks),
        "min_clock": clock_label(min(clocks)),
        "max_clock": clock_label(max(clocks)),
        "elapsed_clock_span_seconds": span,
        "measured_frames_per_second": None if span <= 0 else frames / float(span),
        "puck_rows": puck_rows,
        "frames_with_puck": puck_frame_count,
        "frames_missing_puck": frames - puck_frame_count,
        "frames_with_exactly_one_puck": frames_with_exactly_one_puck,
        "frames_with_multiple_pucks": frames_with_multiple_pucks,
        "mean_player_rows_per_frame": sum(n * c for n, c in player_count_hist.items()) / float(frames),
        "player_rows_per_frame_histogram": {str(k): v for k, v in sorted(player_count_hist.items())},
        "rows_by_kind": dict(rows_by_kind),
        "z_by_kind": {key: summarize_z_counts(value) for key, value in z_by_kind.items()},
        "puck_goal_score_rows": puck_goal_score_rows,
        "puck_goal_z": {
            "nonblank_rows": len(puck_goal_z_values),
            "min": float(min(puck_goal_z_values)) if puck_goal_z_values else None,
            "median": percentile(puck_goal_z_values, 50),
            "max": float(max(puck_goal_z_values)) if puck_goal_z_values else None,
        },
        "jersey_unknown_rows_by_team": dict(jersey_unknown),
        "xy_missing_rows_by_kind": dict(xy_missing),
        "player_ids_with_multiple_jersey_values": inconsistent_ids,
        "actual_period_rows": {str(k): v for k, v in periods.items()},
        "scan_seconds": time.perf_counter() - started,
    }
    snapshots = {clock: aggregate_snapshot(acc) for clock, acc in bucket_acc.items()}
    return summary, snapshots


def collect_game(data_dir, event_path, orientations, total_event_counts):
    game_label = game_label_from_event_path(event_path)
    orientation_label = orientations.get(game_label)
    events = read_events(event_path)
    if not events:
        raise RuntimeError("empty event file: " + event_path)
    for row in events:
        row["_path"] = event_path
        total_event_counts[row["_event"]] += 1
    home = events[0].get("Home_Team", "")
    away = events[0].get("Away_Team", "")
    if orientation_label not in ("Home", "Away"):
        raise RuntimeError("no camera orientation for " + game_label)

    reversals = 0
    for previous, current in zip(events, events[1:]):
        if previous["_period"] == current["_period"] and previous["_clock"] is not None and current["_clock"] is not None:
            if current["_clock"] > previous["_clock"]:
                reversals += 1

    attempts = []
    shot_detail2 = collections.Counter()
    period_counts = collections.Counter()
    for index, row in enumerate(events):
        if row["_event"] not in SHOT_EVENTS:
            continue
        period_counts[str(row["_period"])] += 1
        if row["_event"] == "Shot":
            shot_detail2[(row.get("Detail_2") or "<blank>").strip()] += 1
        features = shot_features(events, index, orientation_label)
        recovery, same_recovery, recovery_seconds = recovery_label(events, index, row["_team"])
        any_follow, same_follow, follow_seconds = followup_labels(events, index, row["_team"])
        features["targets"] = {
            "goal_from_attempt": int(row["_event"] == "Goal"),
            "recovery_within_3s": recovery,
            "same_team_recovery_within_3s": same_recovery,
            "same_team_followup_shot_within_5s": same_follow,
            "any_followup_shot_within_5s": any_follow,
            "recovery_elapsed_seconds": recovery_seconds,
            "followup_elapsed_seconds": follow_seconds,
        }
        attempts.append(features)

    attempts_by_period = collections.defaultdict(list)
    for attempt in attempts:
        if attempt["period"] <= 3 and attempt["clock"] is not None:
            attempts_by_period[attempt["period"]].append(attempt)

    tracking_summaries = []
    shooter_track_matches = 0
    shooter_track_opportunities = 0
    for period in (1, 2, 3):
        period_attempts = attempts_by_period.get(period, [])
        expected = os.path.join(data_dir, os.path.basename(event_path)[:-len("Events.csv")] + "Tracking_P%d.csv" % period)
        if not os.path.isfile(expected):
            raise RuntimeError("missing regulation tracking file: " + expected)
        needed = set()
        for attempt in period_attempts:
            needed.add(attempt["clock"] + 1)
            needed.add(attempt["clock"] + 2)
        summary, snapshots = inspect_tracking_file(expected, needed)
        summary["game"] = game_label
        summary["period_from_filename"] = period
        tracking_summaries.append(summary)
        for attempt in period_attempts:
            now = snapshots.get(attempt["clock"] + 1)
            before = snapshots.get(attempt["clock"] + 2)
            right_goalie_team = team_right_for_period(home, away, orientation_label, period)
            defending = away if attempt["team"] == home else home
            if right_goalie_team == home:
                right_track_team = "Home"
            elif right_goalie_team == away:
                right_track_team = "Away"
            else:
                right_track_team = None
            defending_track_team = "Away" if attempt["team"] == home else "Home"
            shooter_track_team = "Home" if attempt["team"] == home else "Away"
            shooter_track_opportunities += 1
            if now and any(
                player["team"] == shooter_track_team and player.get("jersey") == attempt.get("shooter_id")
                for player in now.get("players", {}).values()
            ):
                shooter_track_matches += 1
            if right_track_team is None:
                attempt["movement"] = None
            else:
                attempt["movement"] = movement_features(
                    now, before, shooter_track_team, defending_track_team, right_track_team,
                    attempt.get("shooter_id"),
                )

    overtime_path = os.path.join(data_dir, os.path.basename(event_path)[:-len("Events.csv")] + "Tracking_POT.csv")
    if os.path.isfile(overtime_path):
        overtime_summary, unused_snapshots = inspect_tracking_file(overtime_path, set())
        overtime_summary["game"] = game_label
        overtime_summary["period_from_filename"] = "POT"
        tracking_summaries.append(overtime_summary)

    shifts_path = os.path.join(data_dir, os.path.basename(event_path)[:-len("Events.csv")] + "Shifts.csv")
    shift_summary = inspect_shifts(shifts_path)

    game_summary = {
        "game": game_label,
        "date": events[0].get("Date"),
        "home": home,
        "away": away,
        "orientation_goalie_right_p1": orientation_label,
        "event_rows": len(events),
        "event_types": dict(collections.Counter(row["_event"] for row in events)),
        "shot_attempts": len(attempts),
        "goals": sum(a["targets"]["goal_from_attempt"] for a in attempts),
        "attempts_by_period": dict(period_counts),
        "shot_detail2": dict(shot_detail2),
        "eligible_movement_attempts": sum(1 for a in attempts if a["movement"] is not None),
        "shooter_track_matches_in_preclock_bucket": shooter_track_matches,
        "shooter_track_match_opportunities": shooter_track_opportunities,
        "shifts": shift_summary,
        "event_clock_reversals_within_period": reversals,
        "tracking_files": tracking_summaries,
    }
    return game_summary, attempts


def feature_raw(record, include_movement):
    raw = {key: record.get(key) for key in EVENT_NUMERIC}
    raw["shot_type"] = record.get("shot_type")
    raw["previous_event"] = record.get("previous_event")
    if include_movement:
        movement = record.get("movement") or {}
        for key in MOVEMENT_NUMERIC:
            raw[key] = movement.get(key)
    return raw


def build_matrix(train_records, test_records, include_movement):
    numeric_keys = list(EVENT_NUMERIC) + (list(MOVEMENT_NUMERIC) if include_movement else [])
    categories = CATEGORICAL
    train_columns = []
    test_columns = []
    names = []
    train_raw = [feature_raw(row, include_movement) for row in train_records]
    test_raw = [feature_raw(row, include_movement) for row in test_records]
    for key in numeric_keys:
        train_vals = np.asarray([np.nan if raw.get(key) is None else float(raw[key]) for raw in train_raw], dtype=float)
        test_vals = np.asarray([np.nan if raw.get(key) is None else float(raw[key]) for raw in test_raw], dtype=float)
        finite = train_vals[np.isfinite(train_vals)]
        fill = float(np.median(finite)) if finite.size else 0.0
        train_missing = ~np.isfinite(train_vals)
        test_missing = ~np.isfinite(test_vals)
        train_vals[train_missing] = fill
        test_vals[test_missing] = fill
        mean = float(np.mean(train_vals)) if train_vals.size else 0.0
        scale = float(np.std(train_vals)) if train_vals.size else 1.0
        if scale < 1e-8:
            scale = 1.0
        train_columns.append((train_vals - mean) / scale)
        test_columns.append((test_vals - mean) / scale)
        names.append(key)
        train_columns.append(train_missing.astype(float))
        test_columns.append(test_missing.astype(float))
        names.append(key + "__missing")
    for key, allowed in categories.items():
        train_vals = [raw.get(key) for raw in train_raw]
        test_vals = [raw.get(key) for raw in test_raw]
        for category in allowed:
            train_columns.append(np.asarray([1.0 if value == category else 0.0 for value in train_vals]))
            test_columns.append(np.asarray([1.0 if value == category else 0.0 for value in test_vals]))
            names.append(key + "=" + category)
    x_train = np.column_stack([np.ones(len(train_records))] + train_columns)
    x_test = np.column_stack([np.ones(len(test_records))] + test_columns)
    return x_train, x_test, ["intercept"] + names


def fit_logistic(x_train, y_train, alpha=0.2):
    y = np.asarray(y_train, dtype=float)
    n, p = x_train.shape
    if n == 0:
        raise RuntimeError("empty training fold")
    penalty = np.ones(p, dtype=float)
    penalty[0] = 0.01

    def objective(beta):
        z = np.clip(x_train.dot(beta), -35.0, 35.0)
        loss = np.logaddexp(0.0, z).mean() - np.dot(y, z) / n
        loss += 0.5 * alpha * np.dot(penalty * beta, beta)
        residual = expit(z) - y
        grad = x_train.T.dot(residual) / n + alpha * penalty * beta
        return loss, grad

    result = minimize(
        objective, np.zeros(p, dtype=float), method="L-BFGS-B", jac=True,
        options={"maxiter": 500, "ftol": 1e-10, "gtol": 1e-7},
    )
    if not result.success:
        raise RuntimeError("logistic fit failed: " + str(result.message))
    return result.x


def grouped_oof(records, target, include_movement, alpha=0.2):
    games = sorted(set(row["game"] for row in records))
    predictions = np.full(len(records), np.nan, dtype=float)
    fold_seconds = []
    for game in games:
        test_idx = [i for i, row in enumerate(records) if row["game"] == game]
        train_idx = [i for i, row in enumerate(records) if row["game"] != game]
        train_records = [records[i] for i in train_idx]
        test_records = [records[i] for i in test_idx]
        y_train = np.asarray([row["targets"][target] for row in train_records], dtype=float)
        x_train, x_test, _ = build_matrix(train_records, test_records, include_movement)
        started = time.perf_counter()
        beta = fit_logistic(x_train, y_train, alpha=alpha)
        predictions[test_idx] = expit(np.clip(x_test.dot(beta), -35.0, 35.0))
        fold_seconds.append(time.perf_counter() - started)
    y = np.asarray([row["targets"][target] for row in records], dtype=float)
    return y, predictions, {"folds": len(games), "fit_predict_seconds": sum(fold_seconds)}


def grouped_conditional_recovery_team(records, include_movement):
    """Predict same-team recovery conditional on a recovery, using training folds only."""
    games = sorted(set(row["game"] for row in records))
    predictions = np.full(len(records), np.nan, dtype=float)
    fold_seconds = []
    for game in games:
        test_idx = [i for i, row in enumerate(records) if row["game"] == game]
        train_idx = [i for i, row in enumerate(records) if row["game"] != game]
        train_records = [records[i] for i in train_idx]
        test_records = [records[i] for i in test_idx]
        recovered_train = [row for row in train_records if row["targets"]["recovery_within_3s"] == 1]
        if not recovered_train:
            raise RuntimeError("conditional recovery fold has no recovered training attempts")
        y_train = np.asarray([
            row["targets"]["same_team_recovery_within_3s"] for row in recovered_train
        ], dtype=float)
        x_train, x_test, _ = build_matrix(recovered_train, test_records, include_movement)
        started = time.perf_counter()
        beta = fit_logistic(x_train, y_train)
        predictions[test_idx] = expit(np.clip(x_test.dot(beta), -35.0, 35.0))
        fold_seconds.append(time.perf_counter() - started)
    return predictions, {"folds": len(games), "fit_predict_seconds": sum(fold_seconds)}


def _inner_binary_brier(records, target, include_movement, alpha):
    games = sorted(set(row["game"] for row in records))
    inner_y = []
    inner_pred = []
    for game in games:
        train_records = [row for row in records if row["game"] != game]
        valid_records = [row for row in records if row["game"] == game]
        y_train = np.asarray([row["targets"][target] for row in train_records], dtype=float)
        x_train, x_valid, _ = build_matrix(train_records, valid_records, include_movement)
        beta = fit_logistic(x_train, y_train, alpha=alpha)
        inner_y.extend(row["targets"][target] for row in valid_records)
        inner_pred.extend(expit(np.clip(x_valid.dot(beta), -35.0, 35.0)))
    brier, _ = losses(inner_y, inner_pred)
    return float(brier.mean())


def _inner_conditional_brier(records, include_movement, alpha):
    games = sorted(set(row["game"] for row in records))
    inner_y = []
    inner_pred = []
    for game in games:
        train_records = [
            row for row in records
            if row["game"] != game and row["targets"]["recovery_within_3s"] == 1
        ]
        valid_records = [
            row for row in records
            if row["game"] == game and row["targets"]["recovery_within_3s"] == 1
        ]
        if not valid_records:
            continue
        if not train_records:
            raise RuntimeError("inner conditional recovery fold has no recovered training attempts")
        y_train = np.asarray([
            row["targets"]["same_team_recovery_within_3s"] for row in train_records
        ], dtype=float)
        x_train, x_valid, _ = build_matrix(train_records, valid_records, include_movement)
        beta = fit_logistic(x_train, y_train, alpha=alpha)
        inner_y.extend(row["targets"]["same_team_recovery_within_3s"] for row in valid_records)
        inner_pred.extend(expit(np.clip(x_valid.dot(beta), -35.0, 35.0)))
    if not inner_y:
        raise RuntimeError("inner conditional recovery validation has no recovered attempts")
    brier, _ = losses(inner_y, inner_pred)
    return float(brier.mean())


def _select_alpha(train_records, include_movement, target=None, conditional=False):
    scores = {}
    for alpha in ROBUSTNESS_ALPHAS:
        if conditional:
            score = _inner_conditional_brier(train_records, include_movement, alpha)
        else:
            score = _inner_binary_brier(train_records, target, include_movement, alpha)
        scores[str(alpha)] = score
    selected = min(ROBUSTNESS_ALPHAS, key=lambda alpha: (scores[str(alpha)], ROBUSTNESS_ALPHAS.index(alpha)))
    return selected, scores


def nested_grouped_oof(records, target, include_movement):
    games = sorted(set(row["game"] for row in records))
    predictions = np.full(len(records), np.nan, dtype=float)
    folds = []
    started = time.perf_counter()
    for game in games:
        test_idx = [i for i, row in enumerate(records) if row["game"] == game]
        train_idx = [i for i, row in enumerate(records) if row["game"] != game]
        train_records = [records[i] for i in train_idx]
        test_records = [records[i] for i in test_idx]
        alpha, inner_scores = _select_alpha(train_records, include_movement, target=target)
        y_train = np.asarray([row["targets"][target] for row in train_records], dtype=float)
        x_train, x_test, _ = build_matrix(train_records, test_records, include_movement)
        beta = fit_logistic(x_train, y_train, alpha=alpha)
        predictions[test_idx] = expit(np.clip(x_test.dot(beta), -35.0, 35.0))
        folds.append({
            "held_out_game": game,
            "training_rows": len(train_records),
            "held_out_rows": len(test_records),
            "selected_alpha": alpha,
            "inner_leave_one_game_out_brier_by_alpha": inner_scores,
        })
    if np.isnan(predictions).any():
        raise RuntimeError("nested grouped evaluation left predictions missing")
    y = np.asarray([row["targets"][target] for row in records], dtype=float)
    return y, predictions, folds, time.perf_counter() - started


def nested_conditional_recovery_team_oof(records, include_movement):
    games = sorted(set(row["game"] for row in records))
    predictions = np.full(len(records), np.nan, dtype=float)
    folds = []
    started = time.perf_counter()
    for game in games:
        test_idx = [i for i, row in enumerate(records) if row["game"] == game]
        train_idx = [i for i, row in enumerate(records) if row["game"] != game]
        train_records = [records[i] for i in train_idx]
        test_records = [records[i] for i in test_idx]
        alpha, inner_scores = _select_alpha(train_records, include_movement, conditional=True)
        recovered_train = [
            row for row in train_records if row["targets"]["recovery_within_3s"] == 1
        ]
        y_train = np.asarray([
            row["targets"]["same_team_recovery_within_3s"] for row in recovered_train
        ], dtype=float)
        x_train, x_test, _ = build_matrix(recovered_train, test_records, include_movement)
        beta = fit_logistic(x_train, y_train, alpha=alpha)
        predictions[test_idx] = expit(np.clip(x_test.dot(beta), -35.0, 35.0))
        folds.append({
            "held_out_game": game,
            "training_rows": len(train_records),
            "training_recovered_rows": len(recovered_train),
            "held_out_rows": len(test_records),
            "held_out_recovered_rows": sum(
                row["targets"]["recovery_within_3s"] == 1 for row in test_records
            ),
            "selected_alpha": alpha,
            "inner_leave_one_game_out_brier_by_alpha": inner_scores,
        })
    if np.isnan(predictions).any():
        raise RuntimeError("nested conditional evaluation left predictions missing")
    return predictions, folds, time.perf_counter() - started


def _binary_metric_summary(records, target, predictions):
    y = np.asarray([row["targets"][target] for row in records], dtype=float)
    brier, logloss = losses(y, predictions)
    return {
        "n": int(len(y)),
        "positive": int(y.sum()),
        "event_rate": float(y.mean()),
        "mean_prediction": float(np.mean(predictions)),
        "brier": float(brier.mean()),
        "logloss": float(logloss.mean()),
        "auc": auc_score(y, predictions),
        "reliability_5_bins": calibration_bins(y, predictions),
    }


def permute_training_movement_columns(records, seed):
    """Independently shuffle each movement feature over training rows only."""
    rng = np.random.default_rng(seed)
    output = []
    for row in records:
        copied = dict(row)
        copied["movement"] = dict(row.get("movement") or {})
        output.append(copied)
    for key in MOVEMENT_NUMERIC:
        values = [row.get("movement", {}).get(key) for row in records]
        shuffled = rng.permutation(np.asarray(values, dtype=object)).tolist()
        for row, value in zip(output, shuffled):
            row["movement"][key] = value
    return output


def matched_null_recovery(records, event_predictions, real_movement_predictions, movement_folds):
    """Permute movement columns within each outer training fold; keep held-out rows intact."""
    games = sorted(set(row["game"] for row in records))
    game_indices = {game: [i for i, row in enumerate(records) if row["game"] == game] for game in games}
    fold_alpha = {fold["held_out_game"]: fold["selected_alpha"] for fold in movement_folds}
    y = np.asarray([row["targets"]["recovery_within_3s"] for row in records], dtype=float)
    event_brier, event_logloss = losses(y, event_predictions)
    real_brier, real_logloss = losses(y, real_movement_predictions)
    real_delta_brier = float(real_brier.mean() - event_brier.mean())
    real_delta_logloss = float(real_logloss.mean() - event_logloss.mean())
    null_deltas_brier = []
    null_deltas_logloss = []
    null_fold_alphas = []
    started = time.perf_counter()
    for replicate in range(ROBUSTNESS_NULL_REPS):
        null_predictions = np.full(len(records), np.nan, dtype=float)
        replicate_fold_alphas = {}
        for fold_index, game in enumerate(games):
            test_idx = game_indices[game]
            train_records = [row for row in records if row["game"] != game]
            test_records = [records[index] for index in test_idx]
            seed = 20261022 + replicate * len(games) + fold_index
            permuted_train = permute_training_movement_columns(train_records, seed)
            y_train = np.asarray([
                row["targets"]["recovery_within_3s"] for row in permuted_train
            ], dtype=float)
            x_train, x_test, _ = build_matrix(permuted_train, test_records, True)
            alpha = fold_alpha[game]
            beta = fit_logistic(x_train, y_train, alpha=alpha)
            null_predictions[test_idx] = expit(np.clip(x_test.dot(beta), -35.0, 35.0))
            replicate_fold_alphas[game] = alpha
        if np.isnan(null_predictions).any():
            raise RuntimeError("matched-null evaluation left predictions missing")
        null_brier, null_logloss = losses(y, null_predictions)
        null_deltas_brier.append(float(null_brier.mean() - event_brier.mean()))
        null_deltas_logloss.append(float(null_logloss.mean() - event_logloss.mean()))
        null_fold_alphas.append(replicate_fold_alphas)

    def summarize(values, real_delta):
        values = np.asarray(values, dtype=float)
        less = int(np.sum(values < real_delta))
        ties = int(np.sum(values == real_delta))
        return {
            "real_movement_delta": float(real_delta),
            "null_mean": float(values.mean()),
            "null_median": float(np.median(values)),
            "null_p05": float(np.percentile(values, 5)),
            "null_p95": float(np.percentile(values, 95)),
            "null_min": float(values.min()),
            "null_max": float(values.max()),
            "real_delta_empirical_percentile": float(100.0 * (less + 0.5 * ties) / len(values)),
            "null_deltas": values.tolist(),
        }

    return {
        "target": "recovery_within_3s",
        "repetitions": ROBUSTNESS_NULL_REPS,
        "seed_schedule": "base seed 20261022; replicate/fold seed = base + replicate_index * 10 + sorted_game_index, indices zero-based",
        "permutation": "each of 26 movement values/missing values independently permuted across outer-training rows; held-out game movement stays intact",
        "alpha_control": "each null fold uses the real movement arm's alpha selected by inner leave-one-game-out on that same outer training set; no held-out labels/features enter alpha choice",
        "movement_parameter_count": 94,
        "null_fold_alphas": null_fold_alphas,
        "brier_movement_minus_event": summarize(null_deltas_brier, real_delta_brier),
        "logloss_movement_minus_event": summarize(null_deltas_logloss, real_delta_logloss),
        "fit_predict_seconds": time.perf_counter() - started,
    }


def run_robustness_analysis(records):
    started = time.perf_counter()
    output = {
        "metadata": {
            "evaluation": "outer leave-one-game-out; alpha selected independently within each outer training set by inner leave-one-game-out",
            "alpha_grid": list(ROBUSTNESS_ALPHAS),
            "selection_metric": "pooled inner-LOO Brier score; minimum selected, ties resolve to first alpha in the listed ascending grid",
            "outer_heldout_games": 10,
            "rows": len(records),
            "game_rows": {game: sum(row["game"] == game for row in records) for game in sorted(set(row["game"] for row in records))},
            "event_only_parameter_count_including_intercept": len(EVENT_NUMERIC) * 2 + sum(len(v) for v in CATEGORICAL.values()) + 1,
            "movement_augmented_parameter_count_including_intercept": (len(EVENT_NUMERIC) + len(MOVEMENT_NUMERIC)) * 2 + sum(len(v) for v in CATEGORICAL.values()) + 1,
            "binary_cluster_bootstrap": {"unit": "game", "replicates": ROBUSTNESS_BOOTSTRAP_REPS, "seed": 20261022},
            "matched_null_repetitions": ROBUSTNESS_NULL_REPS,
        },
        "targets": {},
        "runtime": {},
    }
    predictions = {}
    for target in TARGETS:
        target_result = {}
        arm_predictions = {}
        for arm, include_movement in (("event_only", False), ("movement_augmented", True)):
            y, pred, folds, elapsed = nested_grouped_oof(records, target, include_movement)
            arm_predictions[arm] = pred
            target_result[arm] = {
                "metrics": _binary_metric_summary(records, target, pred),
                "outer_folds": folds,
                "fit_predict_seconds": elapsed,
            }
        target_result["paired_uncertainty"] = bootstrap_loss_difference(
            records, target, arm_predictions["event_only"], arm_predictions["movement_augmented"],
            ROBUSTNESS_BOOTSTRAP_REPS,
        )
        output["targets"][target] = target_result
        predictions[target] = arm_predictions

    recovery_team_result = {}
    team_predictions = {}
    for arm, include_movement in (("event_only", False), ("movement_augmented", True)):
        pred, folds, elapsed = nested_conditional_recovery_team_oof(records, include_movement)
        team_predictions[arm] = pred
        recovery_team_result[arm] = {
            "outer_folds": folds,
            "fit_predict_seconds": elapsed,
        }
    labels_event, probs_event = recovery_team_probabilities(
        records, predictions["recovery_within_3s"]["event_only"], team_predictions["event_only"]
    )
    labels_move, probs_move = recovery_team_probabilities(
        records, predictions["recovery_within_3s"]["movement_augmented"], team_predictions["movement_augmented"]
    )
    if not np.array_equal(labels_event, labels_move):
        raise RuntimeError("nested recovery-category labels differ by arm")
    metrics_event = multiclass_metrics(labels_event, probs_event)
    metrics_move = multiclass_metrics(labels_move, probs_move)
    recovery_team_result["event_only"]["metrics"] = {
        key: value for key, value in metrics_event.items() if not key.startswith("row_")
    }
    recovery_team_result["movement_augmented"]["metrics"] = {
        key: value for key, value in metrics_move.items() if not key.startswith("row_")
    }
    recovery_team_result["paired_uncertainty"] = bootstrap_multiclass_difference(
        records, metrics_event, metrics_move, ROBUSTNESS_BOOTSTRAP_REPS
    )
    output["targets"]["recovery_team_category"] = recovery_team_result
    output["matched_null"] = matched_null_recovery(
        records,
        predictions["recovery_within_3s"]["event_only"],
        predictions["recovery_within_3s"]["movement_augmented"],
        output["targets"]["recovery_within_3s"]["movement_augmented"]["outer_folds"],
    )
    output["runtime"] = {
        "total_seconds": time.perf_counter() - started,
        "nested_binary_model_seconds": sum(
            output["targets"][target][arm]["fit_predict_seconds"]
            for target in TARGETS for arm in ("event_only", "movement_augmented")
        ),
        "matched_null_seconds": output["matched_null"]["fit_predict_seconds"],
        "bootstrap_replicates_per_comparison": ROBUSTNESS_BOOTSTRAP_REPS,
    }
    return output


def auc_score(y, pred):
    y = np.asarray(y, dtype=int)
    pred = np.asarray(pred, dtype=float)
    positives = int(y.sum())
    negatives = int(len(y) - positives)
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(pred)
    ranks = np.empty(len(y), dtype=float)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and pred[order[j]] == pred[order[i]]:
            j += 1
        average_rank = (i + 1 + j) / 2.0
        ranks[order[i:j]] = average_rank
        i = j
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2.0) / (positives * negatives))


def losses(y, pred):
    pred = np.clip(np.asarray(pred, dtype=float), 1e-8, 1.0 - 1e-8)
    y = np.asarray(y, dtype=float)
    return (pred - y) ** 2, -(y * np.log(pred) + (1.0 - y) * np.log(1.0 - pred))


def calibration_bins(y, pred, bins=5):
    output = []
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    bucket = np.minimum((pred * bins).astype(int), bins - 1)
    for i in range(bins):
        mask = bucket == i
        if not np.any(mask):
            continue
        output.append({
            "bin": "%0.1f-%0.1f" % (i / float(bins), (i + 1) / float(bins)),
            "n": int(mask.sum()),
            "mean_prediction": float(pred[mask].mean()),
            "observed_rate": float(y[mask].mean()),
        })
    return output


def bootstrap_loss_difference(records, target, pred_event, pred_move, reps=2000):
    y = np.asarray([row["targets"][target] for row in records], dtype=float)
    event_brier, event_logloss = losses(y, pred_event)
    move_brier, move_logloss = losses(y, pred_move)
    games = sorted(set(row["game"] for row in records))
    indexes = {game: np.asarray([i for i, row in enumerate(records) if row["game"] == game], dtype=int) for game in games}
    rng = np.random.default_rng(20261022)
    brier_diffs = []
    logloss_diffs = []
    for _ in range(reps):
        sampled_games = rng.choice(games, size=len(games), replace=True)
        sampled = np.concatenate([indexes[game] for game in sampled_games])
        brier_diffs.append(float(move_brier[sampled].mean() - event_brier[sampled].mean()))
        logloss_diffs.append(float(move_logloss[sampled].mean() - event_logloss[sampled].mean()))
    return {
        "brier_movement_minus_event": {
            "mean": float(move_brier.mean() - event_brier.mean()),
            "cluster_bootstrap_95pct": [float(np.percentile(brier_diffs, 2.5)), float(np.percentile(brier_diffs, 97.5))],
        },
        "logloss_movement_minus_event": {
            "mean": float(move_logloss.mean() - event_logloss.mean()),
            "cluster_bootstrap_95pct": [float(np.percentile(logloss_diffs, 2.5)), float(np.percentile(logloss_diffs, 97.5))],
        },
        "bootstrap_unit": "game",
        "bootstrap_games": len(games),
        "bootstrap_replicates": reps,
        "seed": 20261022,
    }


def recovery_team_probabilities(records, recovery_probability, same_given_recovery):
    p_recovery = np.asarray(recovery_probability, dtype=float)
    p_same = np.asarray(same_given_recovery, dtype=float)
    probs = np.column_stack((1.0 - p_recovery, p_recovery * (1.0 - p_same), p_recovery * p_same))
    labels = []
    for row in records:
        if row["targets"]["recovery_within_3s"] == 0:
            labels.append(0)
        elif row["targets"]["same_team_recovery_within_3s"] == 1:
            labels.append(2)
        else:
            labels.append(1)
    return np.asarray(labels, dtype=int), probs


def multiclass_metrics(labels, probs):
    labels = np.asarray(labels, dtype=int)
    probs = np.clip(np.asarray(probs, dtype=float), 1e-8, 1.0)
    onehot = np.eye(3)[labels]
    row_index = np.arange(len(labels))
    logloss = -np.log(probs[row_index, labels])
    brier = np.sum((probs - onehot) ** 2, axis=1)
    categories = ("no_recovery_within_3s", "opponent_recovery", "shooting_team_recovery")
    calibration = []
    for category_index, category in enumerate(categories):
        calibration.append({
            "category": category,
            "n_observed": int((labels == category_index).sum()),
            "mean_predicted_probability": float(probs[:, category_index].mean()),
            "observed_rate": float((labels == category_index).mean()),
        })
    return {
        "n": int(len(labels)),
        "multiclass_brier": float(brier.mean()),
        "multiclass_logloss": float(logloss.mean()),
        "accuracy": float((probs.argmax(axis=1) == labels).mean()),
        "class_calibration": calibration,
        "row_brier": brier,
        "row_logloss": logloss,
    }


def bootstrap_multiclass_difference(records, event_metrics, movement_metrics, reps):
    games = sorted(set(row["game"] for row in records))
    indexes = {game: np.asarray([i for i, row in enumerate(records) if row["game"] == game], dtype=int) for game in games}
    rng = np.random.default_rng(20261022)
    brier_diffs = []
    logloss_diffs = []
    for _ in range(reps):
        sampled_games = rng.choice(games, size=len(games), replace=True)
        sampled = np.concatenate([indexes[game] for game in sampled_games])
        brier_diffs.append(float(movement_metrics["row_brier"][sampled].mean() - event_metrics["row_brier"][sampled].mean()))
        logloss_diffs.append(float(movement_metrics["row_logloss"][sampled].mean() - event_metrics["row_logloss"][sampled].mean()))
    return {
        "multiclass_brier_movement_minus_event": {
            "mean": float(movement_metrics["row_brier"].mean() - event_metrics["row_brier"].mean()),
            "cluster_bootstrap_95pct": [float(np.percentile(brier_diffs, 2.5)), float(np.percentile(brier_diffs, 97.5))],
        },
        "multiclass_logloss_movement_minus_event": {
            "mean": float(movement_metrics["row_logloss"].mean() - event_metrics["row_logloss"].mean()),
            "cluster_bootstrap_95pct": [float(np.percentile(logloss_diffs, 2.5)), float(np.percentile(logloss_diffs, 97.5))],
        },
        "bootstrap_unit": "game",
        "bootstrap_games": len(games),
        "bootstrap_replicates": reps,
        "seed": 20261022,
    }


def score_model(records, target, include_movement):
    y, pred, runtime = grouped_oof(records, target, include_movement)
    brier, logloss = losses(y, pred)
    return {
        "n": int(len(y)),
        "positive": int(y.sum()),
        "event_rate": float(y.mean()),
        "mean_prediction": float(pred.mean()),
        "brier": float(brier.mean()),
        "logloss": float(logloss.mean()),
        "auc": auc_score(y, pred),
        "reliability_5_bins": calibration_bins(y, pred),
        "runtime": runtime,
        "predictions": pred,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="/root/lp-research-data/stathletes-big-data-cup-2026")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--robustness-output-json", default=None)
    parser.add_argument("--bootstrap-reps", type=int, default=2000)
    args = parser.parse_args()
    started = time.perf_counter()
    release_manifest = inspect_release_manifest(args.data_dir)
    orientations = load_orientations(args.data_dir)
    event_paths = sorted(glob.glob(os.path.join(args.data_dir, "*.Events.csv")))
    if len(event_paths) != 10:
        raise RuntimeError("expected ten event files; found %d" % len(event_paths))

    all_attempts = []
    game_summaries = []
    period_summaries = []
    event_counts = collections.Counter()
    for path in event_paths:
        summary, attempts = collect_game(args.data_dir, path, orientations, event_counts)
        game_summaries.append(summary)
        all_attempts.extend(attempts)
        period_summaries.extend(summary["tracking_files"])

    shift_files = [summary["shifts"] for summary in game_summaries]
    regulation_files = [row for row in period_summaries if isinstance(row["period_from_filename"], int)]
    overtime_files = [row for row in period_summaries if row["period_from_filename"] == "POT"]
    if len(regulation_files) != 30 or len(overtime_files) != 3 or len(shift_files) != 10:
        raise RuntimeError("release inventory mismatch: regulation=%d overtime=%d shifts=%d" % (
            len(regulation_files), len(overtime_files), len(shift_files)
        ))

    movement_eligible = [row for row in all_attempts if row["movement"] is not None]
    matched = [
        row for row in movement_eligible
        if all(row["targets"].get(target) in (0, 1) for target in TARGETS)
    ]
    excluded_incomplete_targets = len(movement_eligible) - len(matched)
    if not matched:
        raise RuntimeError("no attempts have usable pre-shot movement features")
    if len(set(row["game"] for row in matched)) < 5:
        raise RuntimeError("fewer than five games have movement-eligible attempts")

    model_results = {}
    oof_predictions = {}
    model_runtime_started = time.perf_counter()
    for target in TARGETS:
        event_result = score_model(matched, target, False)
        movement_result = score_model(matched, target, True)
        oof_predictions[target] = {
            "event_only": event_result["predictions"],
            "movement_augmented": movement_result["predictions"],
        }
        comparison = {
            "target": target,
            "n_same_rows": len(matched),
            "n_games": len(set(row["game"] for row in matched)),
            "observed_positive": int(sum(row["targets"][target] for row in matched)),
            "event_only": {key: value for key, value in event_result.items() if key != "predictions"},
            "movement_augmented": {key: value for key, value in movement_result.items() if key != "predictions"},
            "paired_uncertainty": bootstrap_loss_difference(
                matched, target, event_result["predictions"], movement_result["predictions"], args.bootstrap_reps
            ),
        }
        model_results[target] = comparison

    event_team_conditional, event_team_runtime = grouped_conditional_recovery_team(matched, False)
    movement_team_conditional, movement_team_runtime = grouped_conditional_recovery_team(matched, True)
    recovery_y = np.asarray([row["targets"]["recovery_within_3s"] for row in matched], dtype=float)
    recovery_prob_event = oof_predictions["recovery_within_3s"]["event_only"]
    recovery_prob_move = oof_predictions["recovery_within_3s"]["movement_augmented"]
    recovery_labels_event, recovery_probs_event = recovery_team_probabilities(
        matched, recovery_prob_event, event_team_conditional
    )
    recovery_labels_move, recovery_probs_move = recovery_team_probabilities(
        matched, recovery_prob_move, movement_team_conditional
    )
    if not np.array_equal(recovery_labels_event, recovery_labels_move):
        raise RuntimeError("recovery category labels changed between model arms")
    recovery_team_metrics_event = multiclass_metrics(recovery_labels_event, recovery_probs_event)
    recovery_team_metrics_move = multiclass_metrics(recovery_labels_move, recovery_probs_move)
    recovered_mask = recovery_y == 1
    conditional_y = np.asarray([
        row["targets"]["same_team_recovery_within_3s"] for row in matched
    ], dtype=float)[recovered_mask]
    conditional_event = event_team_conditional[recovered_mask]
    conditional_move = movement_team_conditional[recovered_mask]
    conditional_event_brier, conditional_event_logloss = losses(conditional_y, conditional_event)
    conditional_move_brier, conditional_move_logloss = losses(conditional_y, conditional_move)
    recovery_team_result = {
        "class_order": ["no_recovery_within_3s", "opponent_recovery", "shooting_team_recovery"],
        "n_same_rows": len(matched),
        "n_games": len(set(row["game"] for row in matched)),
        "observed_class_counts": {
            "no_recovery_within_3s": int((recovery_labels_event == 0).sum()),
            "opponent_recovery": int((recovery_labels_event == 1).sum()),
            "shooting_team_recovery": int((recovery_labels_event == 2).sum()),
        },
        "event_only": {key: value for key, value in recovery_team_metrics_event.items() if not key.startswith("row_")},
        "movement_augmented": {key: value for key, value in recovery_team_metrics_move.items() if not key.startswith("row_")},
        "paired_uncertainty": bootstrap_multiclass_difference(
            matched, recovery_team_metrics_event, recovery_team_metrics_move, args.bootstrap_reps
        ),
        "conditional_same_team_given_recovery": {
            "n_recovered_rows": int(recovered_mask.sum()),
            "observed_same_team_rate": float(conditional_y.mean()) if conditional_y.size else None,
            "event_only_brier": float(conditional_event_brier.mean()) if conditional_event_brier.size else None,
            "event_only_logloss": float(conditional_event_logloss.mean()) if conditional_event_logloss.size else None,
            "movement_augmented_brier": float(conditional_move_brier.mean()) if conditional_move_brier.size else None,
            "movement_augmented_logloss": float(conditional_move_logloss.mean()) if conditional_move_logloss.size else None,
        },
        "conditional_fit_runtime": {
            "event_only_seconds": event_team_runtime["fit_predict_seconds"],
            "movement_augmented_seconds": movement_team_runtime["fit_predict_seconds"],
        },
    }
    model_results["recovery_team_category"] = recovery_team_result
    model_runtime = time.perf_counter() - model_runtime_started

    category_counts = collections.Counter()
    shot_destination_counts = collections.Counter()
    recovery_delays = []
    followup_delays = []
    for attempt in all_attempts:
        if attempt["targets"]["recovery_within_3s"]:
            label = "same_team" if attempt["targets"]["same_team_recovery_within_3s"] else "opponent_team"
            category_counts[label] += 1
            recovery_delays.append(attempt["targets"]["recovery_elapsed_seconds"])
        else:
            category_counts["none_within_3s"] += 1
        if attempt["targets"]["any_followup_shot_within_5s"]:
            category_counts["any_followup_shot_within_5s"] += 1
            followup_delays.append(attempt["targets"]["followup_elapsed_seconds"])
        if attempt["targets"]["same_team_followup_shot_within_5s"]:
            category_counts["same_team_followup_shot_within_5s"] += 1
    for game in game_summaries:
        for destination, count in game["shot_detail2"].items():
            shot_destination_counts[destination] += count

    frame_rates = [row["measured_frames_per_second"] for row in period_summaries if row["measured_frames_per_second"] is not None]
    output = {
        "metadata": {
            "generated_utc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "data_directory": os.path.abspath(args.data_dir),
            "event_files": len(event_paths),
            "tracking_period_files": len(period_summaries),
            "single_process": True,
            "no_database_or_network_calls": True,
            "feature_time_cutoff": "two complete integer-second Game Clock bins before the shot row's recorded Clock",
            "shot_location_features": "shot event release coordinates are included; coordinate-axis orientation is not assumed beyond absolute coordinates",
            "grouped_evaluation": "leave-one-game-out, ten anonymized games, no hyperparameter tuning",
            "logistic_ridge_alpha": 0.2,
            "bootstrap": {"unit": "game", "replicates": args.bootstrap_reps, "seed": 20261022},
            "permission": "user confirmed separate written permission; permission document not inspected or copied",
        },
        "coverage": {
            "release_manifest": release_manifest,
            "event_rows_by_type": dict(event_counts),
            "event_rows_total": int(sum(event_counts.values())),
            "shot_destination_detail2_counts_for_unsuccessful_shots": dict(shot_destination_counts),
            "explicit_save_event_rows": int(sum(count for name, count in event_counts.items() if "save" in name.lower())),
            "explicit_rebound_event_rows": int(sum(count for name, count in event_counts.items() if "rebound" in name.lower())),
            "puck_recovery_event_rows": int(event_counts.get("Puck Recovery", 0)),
            "goal_event_rows": int(event_counts.get("Goal", 0)),
            "games": game_summaries,
            "tracking_period_file_count": len(period_summaries),
            "regulation_tracking_files": len(regulation_files),
            "overtime_tracking_files": len(overtime_files),
            "shifts_files": len(shift_files),
            "shift_rows_total": int(sum(row["shift_rows"] for row in shift_files)),
            "shift_goalie_placeholder_rows": int(sum(row["goalie_placeholder_rows"] for row in shift_files)),
            "shift_files": shift_files,
            "measured_fps_median": percentile(frame_rates, 50),
            "measured_fps_p10": percentile(frame_rates, 10),
            "measured_fps_p90": percentile(frame_rates, 90),
            "tracking_period_files": period_summaries,
        },
        "targets": {
            "all_shot_attempts": len(all_attempts),
            "movement_eligible_attempts": len(movement_eligible),
            "common_model_rows_with_complete_targets": len(matched),
            "movement_eligible_rows_excluded_for_incomplete_targets": excluded_incomplete_targets,
            "movement_eligible_games": len(set(row["game"] for row in matched)),
            "movement_quality": {
                "goalie_position_explicitly_identified_attempts": int(sum(
                    row["movement"].get("goalie_proxy_identified", 0.0) == 1.0 for row in matched
                )),
                "goalie_position_fallback_proxy_attempts": int(sum(
                    row["movement"].get("goalie_proxy_found", 0.0) == 1.0
                    and row["movement"].get("goalie_proxy_identified", 0.0) == 0.0 for row in matched
                )),
                "goalie_position_unavailable_attempts": int(sum(
                    row["movement"].get("goalie_proxy_found", 0.0) == 0.0 for row in matched
                )),
                "shooter_jersey_match_attempts": int(sum(
                    row["movement"].get("shooter_tracking_matched", 0.0) == 1.0 for row in matched
                )),
            },
            "observed_event_sequence_counts": dict(category_counts),
            "recovery_elapsed_seconds_median": percentile(recovery_delays, 50),
            "followup_shot_elapsed_seconds_median": percentile(followup_delays, 50),
            "model_comparisons": model_results,
            "definitions": {
                "goal_from_attempt": "Goal event versus Shot event; all attempts included; Detail_2 shot destination is excluded from features",
                "recovery_within_3s": "first Puck Recovery event within 3 integer game-clock seconds after the attempt, before a stop, another shot, or possession event",
                "same_team_recovery_within_3s": "recovery label above; 1 only when recovery Team equals shooting Team, 0 for opponent recovery or none",
                "same_team_followup_shot_within_5s": "next Shot or Goal by the original shooting Team within 5 integer game-clock seconds before a stop or opposing possession event",
                "any_followup_shot_within_5s": "next Shot or Goal by either team within 5 integer game-clock seconds before a stop",
            },
        },
        "runtime": {
            "total_seconds": time.perf_counter() - started,
            "model_cv_seconds": model_runtime,
            "tracking_scan_seconds": float(sum(row["scan_seconds"] for row in period_summaries)),
            "bootstrap_replicates_per_target": args.bootstrap_reps,
        },
    }
    rendered = json.dumps(output, indent=2, sort_keys=True, allow_nan=False)
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    print(rendered)
    if args.robustness_output_json:
        robustness = run_robustness_analysis(matched)
        robustness_rendered = json.dumps(robustness, indent=2, sort_keys=True, allow_nan=False)
        output_dir = os.path.dirname(os.path.abspath(args.robustness_output_json))
        os.makedirs(output_dir, exist_ok=True)
        with open(args.robustness_output_json, "w", encoding="utf-8") as handle:
            handle.write(robustness_rendered + "\n")
        print(json.dumps({
            "robustness_output_json": os.path.abspath(args.robustness_output_json),
            "robustness_runtime_seconds": robustness["runtime"]["total_seconds"],
        }, sort_keys=True))


if __name__ == "__main__":
    main()
