#!/usr/bin/env python3
"""Full-population quality audit and observed-motion visualizations for Big Data Cup 2026.

Reads the local release sequentially, verifies its manifest, and writes only aggregate
metrics and plots. It never copies raw CSV rows into the repository or contacts a provider.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


RINK_X = (-100.0, 100.0)
RINK_Y = (-42.5, 42.5)
EXPECTED_TYPES = {"event": 10, "shift": 10, "tracking_regulation": 30,
                  "tracking_overtime": 3, "orientation": 1}
REQUIRED_TRACKING_COLUMNS = {
    "Image Id", "Period", "Game Clock", "Player or Puck", "Team", "Player Id",
    "Player Jersey Number", "Rink Location X (Feet)", "Rink Location Y (Feet)",
}


def parse_clock(value: str) -> int | None:
    if value is None or not value.strip():
        return None
    match = re.fullmatch(r"\s*(\d+):(\d\d)\s*", value or "")
    if not match:
        raise ValueError("invalid Game Clock: %r" % value)
    return int(match.group(1)) * 60 + int(match.group(2))


def frame_number(image_id: str) -> int:
    match = re.search(r"_(\d+)$", image_id or "")
    if not match:
        raise ValueError("Image Id does not end in a numeric frame suffix: %r" % image_id)
    return int(match.group(1))


def parse_period(value: str) -> int:
    normalized = (value or "").strip().upper()
    if normalized == "OT":
        return 4
    if re.fullmatch(r"\d+", normalized):
        return int(normalized)
    raise ValueError("invalid Period: %r" % value)


def finite_float(value: str, field: str, path: Path, row_number: int) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s:%d has invalid %s=%r" % (path, row_number, field, value))
    if not math.isfinite(result):
        raise ValueError("%s:%d has non-finite %s=%r" % (path, row_number, field, value))
    return result


def optional_xy(value: str, field: str, path: Path, row_number: int) -> float | None:
    if value is None or not value.strip():
        return None
    return finite_float(value, field, path, row_number)


def classify_asset(name: str) -> str:
    if name.endswith(".Events.csv"):
        return "event"
    if name.endswith(".Shifts.csv"):
        return "shift"
    if ".Tracking_POT.csv" in name:
        return "tracking_overtime"
    if ".Tracking_" in name:
        return "tracking_regulation"
    if name == "camera_orientations.csv":
        return "orientation"
    return "other"


def verify_manifest(data_dir: Path) -> dict:
    manifest_path = data_dir / "download-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest.get("files")
    if not isinstance(assets, list) or len(assets) != int(manifest.get("asset_count", -1)):
        raise RuntimeError("manifest asset_count does not equal listed files")
    totals = collections.Counter()
    bytes_hashed = 0
    for index, item in enumerate(assets, 1):
        path = data_dir / item["name"]
        if not path.is_file():
            raise RuntimeError("manifest asset is missing: %s" % path)
        expected_size = int(item["bytes"])
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise RuntimeError("size mismatch for %s: expected %d, got %d" % (path, expected_size, actual_size))
        expected_hash = item.get("sha256")
        if not expected_hash:
            raise RuntimeError("manifest has no SHA-256 for %s" % path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest().lower() != expected_hash.lower():
            raise RuntimeError("SHA-256 mismatch for %s" % path)
        totals[classify_asset(path.name)] += 1
        bytes_hashed += actual_size
        print("verified manifest asset %d/%d: %s" % (index, len(assets), path.name), flush=True)
    if dict(totals) != EXPECTED_TYPES:
        raise RuntimeError("release file-type population mismatch: expected %r, got %r" %
                           (EXPECTED_TYPES, dict(totals)))
    if bytes_hashed != int(manifest.get("total_bytes", -1)):
        raise RuntimeError("manifest total_bytes mismatch")
    return {
        "repository": manifest.get("repository"),
        "release_tag": manifest.get("release_tag"),
        "asset_count": len(assets),
        "total_bytes": bytes_hashed,
        "type_counts": dict(totals),
        "sha256_verified": len(assets),
        "status": "PASS",
    }


def load_event_alignment_keys(data_dir: Path, event_paths: list[Path]) -> tuple[dict, dict]:
    lookups: dict[str, dict[tuple, list[dict]]] = {}
    game_teams = {}
    for path in event_paths:
        game = path.name[:-len(".Events.csv")]
        rows = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"Home_Team", "Away_Team", "Period", "Clock", "Team", "Player_Id",
                        "X_Coordinate", "Y_Coordinate"}
            if not required.issubset(reader.fieldnames or []):
                raise RuntimeError("event schema missing columns in %s" % path)
            for line, row in enumerate(reader, 2):
                if not row.get("X_Coordinate") or not row.get("Y_Coordinate") or not row.get("Player_Id"):
                    continue
                side = "Home" if row["Team"] == row["Home_Team"] else (
                    "Away" if row["Team"] == row["Away_Team"] else "Unknown")
                if side == "Unknown":
                    raise RuntimeError("event team does not match home/away at %s:%d" % (path, line))
                key = (int(row["Period"]), parse_clock(row["Clock"]), side,
                       row["Player_Id"].strip())
                rows.append({"key": key,
                             "x": finite_float(row["X_Coordinate"], "X_Coordinate", path, line),
                             "y": finite_float(row["Y_Coordinate"], "Y_Coordinate", path, line),
                             "event": row.get("Event", "")})
                game_teams[game] = {"home": row["Home_Team"], "away": row["Away_Team"]}
        lookups[game] = collections.defaultdict(list)
        for row in rows:
            lookups[game][row["key"]].append(row)
    return lookups, game_teams


def load_shift_rosters(data_dir: Path, game_teams: dict) -> dict:
    rosters = {}
    paths = sorted(data_dir.glob("*.Shifts.csv"))
    if len(paths) != 10:
        raise RuntimeError("expected ten shift files; got %d" % len(paths))
    for path in paths:
        game = path.name[:-len(".Shifts.csv")]
        if game not in game_teams:
            raise RuntimeError("shift file lacks a matching event game: %s" % path)
        teams = game_teams[game]
        roster = {"Home": set(), "Away": set()}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"Team", "Player_Id"}.issubset(reader.fieldnames or []):
                raise RuntimeError("shift schema missing Team/Player_Id in %s" % path)
            for line, row in enumerate(reader, 2):
                side = "Home" if row["Team"] == teams["home"] else (
                    "Away" if row["Team"] == teams["away"] else None)
                if side is None:
                    raise RuntimeError("shift team does not match game at %s:%d" % (path, line))
                player_id = (row["Player_Id"] or "").strip()
                if player_id:
                    roster[side].add(player_id)
        rosters[game] = roster
    return rosters


def new_period_metrics(path: Path) -> dict:
    return {
        "file": path.name, "frames": 0, "player_rows": 0, "puck_rows": 0,
        "frames_exactly_one_puck": 0, "frames_no_puck": 0, "frames_multiple_puck": 0,
        "frames_with_3plus_skaters_each_team": 0, "jersey_present_rows": 0,
        "track_id_present_rows": 0, "id_and_jersey_present_rows": 0,
        "coordinate_rows": 0, "missing_xy_rows": 0, "finite_xy_rows": 0,
        "puck_xy_rows": 0, "in_rink_xy_rows": 0,
        "shift_eligible_rows": 0, "shift_match_rows": 0,
        "frame_id_duplicate_or_reversal": 0, "frame_id_gaps": 0, "clock_reversals": 0,
        "clock_missing_rows": 0, "frames_missing_clock": 0,
        "within_frame_duplicate_player_ids": 0, "identity_conflicts": 0,
        "identity_track_count": 0, "puck_gap_le_0_10_count": 0, "puck_gap_observations": 0,
        "clock_values_per_frame_gt1": 0, "valid_windows": 0, "valid_puck_windows": 0,
        "start_frame": None, "end_frame": None, "start_clock_seconds": None,
        "end_clock_seconds": None, "first_timed_frame": None, "last_timed_frame": None,
        "frame_id_step_counts": collections.Counter(),
        "id_to_team_jersey": collections.defaultdict(set), "identity_obs": collections.Counter(),
    }


def audit_tracking_file(path: Path, event_lookup: dict, heat_player: np.ndarray,
                        heat_puck: np.ndarray, sample: dict | None,
                        shift_roster: dict) -> tuple[dict, list]:
    metrics = new_period_metrics(path)
    event_positions: dict[tuple, list[tuple[float, float]]] = collections.defaultdict(list)
    histories: dict[tuple, list[tuple[int, float, float]]] = {}
    last_target: dict[tuple, int] = {}
    seq_seen = set()
    current = None
    prior_seq = None
    prior_clock = None
    sample_frame_idx = 0
    selected_ids = None
    current_players = {}
    puck_count = 0
    puck_xy_count = 0
    puck_valid = False
    frame_clock_set = set()
    last_puck_seq = None
    puck_gap_steps = []
    puck_history = []
    last_puck_target = None
    periods_seen = set()

    def finish_frame():
        nonlocal current_players, puck_count, puck_xy_count, puck_valid, frame_clock_set
        nonlocal last_puck_seq, puck_history, last_puck_target, prior_clock
        if current is None:
            return
        metrics["frames"] += 1
        if current["clock"] is None:
            metrics["frames_missing_clock"] += 1
        else:
            if prior_clock is not None and current["clock"] > prior_clock:
                metrics["clock_reversals"] += 1
            prior_clock = current["clock"]
            if metrics["first_timed_frame"] is None:
                metrics["first_timed_frame"] = current["seq"]
                metrics["start_clock_seconds"] = current["clock"]
            metrics["last_timed_frame"] = current["seq"]
            metrics["end_clock_seconds"] = current["clock"]
        metrics["end_frame"] = current["seq"]
        if puck_count == 1:
            metrics["frames_exactly_one_puck"] += 1
            if last_puck_seq is not None:
                puck_gap_steps.append(current["seq"] - last_puck_seq)
            last_puck_seq = current["seq"]
        elif puck_count == 0:
            metrics["frames_no_puck"] += 1
        else:
            metrics["frames_multiple_puck"] += 1
        if puck_count == 1 and puck_xy_count == 1 and puck_valid:
            if puck_history and current["seq"] - puck_history[-1] != 1:
                puck_history = []
                last_puck_target = None
            puck_history.append(current["seq"])
            if len(puck_history) > 21:
                del puck_history[:-21]
            if len(puck_history) == 21 and (last_puck_target is None or
                                            current["seq"] - last_puck_target >= 15):
                metrics["valid_puck_windows"] += 1
                last_puck_target = current["seq"]
        else:
            puck_history = []
            last_puck_target = None
        team_counts = collections.Counter(row["team"] for row in current_players.values())
        if team_counts["Home"] >= 3 and team_counts["Away"] >= 3:
            metrics["frames_with_3plus_skaters_each_team"] += 1
        if len(frame_clock_set) > 1:
            metrics["clock_values_per_frame_gt1"] += 1
        for entity_key in list(histories):
            if entity_key not in current_players:
                histories[entity_key] = []
                last_target.pop(entity_key, None)
        for entity_key, player in current_players.items():
            seq, x, y = current["seq"], player["x"], player["y"]
            series = histories.setdefault(entity_key, [])
            if series and seq - series[-1][0] != 1:
                series.clear()
                last_target.pop(entity_key, None)
            series.append((seq, x, y))
            if len(series) > 21:
                del series[:-21]
            if len(series) == 21 and (entity_key not in last_target or
                                      seq - last_target[entity_key] >= 15):
                metrics["valid_windows"] += 1
                last_target[entity_key] = seq
        current_players = {}
        puck_count = 0
        puck_xy_count = 0
        puck_valid = False
        frame_clock_set = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not REQUIRED_TRACKING_COLUMNS.issubset(reader.fieldnames or []):
            raise RuntimeError("tracking schema missing columns in %s" % path)
        for line, row in enumerate(reader, 2):
            image = row["Image Id"].strip()
            seq = frame_number(image)
            period = parse_period(row["Period"])
            clock_seconds = parse_clock(row["Game Clock"])
            if current is None or image != current["image"]:
                finish_frame()
                if seq in seq_seen:
                    metrics["frame_id_duplicate_or_reversal"] += 1
                    raise RuntimeError("noncontiguous duplicate frame id %s in %s" % (image, path))
                seq_seen.add(seq)
                if prior_seq is not None:
                    step = seq - prior_seq
                    if step <= 0:
                        metrics["frame_id_duplicate_or_reversal"] += 1
                        raise RuntimeError("image frame ids do not increase in %s" % path)
                    metrics["frame_id_step_counts"][step] += 1
                    if step > 1:
                        metrics["frame_id_gaps"] += 1
                else:
                    metrics["start_frame"] = seq
                current = {"image": image, "period": period, "seq": seq,
                           "clock": clock_seconds}
                periods_seen.add(period)
                if len(periods_seen) > 1:
                    raise RuntimeError("tracking file contains multiple periods: %s" % path)
                prior_seq = seq
                sample_frame_idx += 1
                if sample is not None and sample_frame_idx <= 300:
                    sample["frames"].append({"seq": seq, "clock": clock_seconds, "players": {}, "puck": None})
                    sample_row = sample["frames"][-1]
                else:
                    sample_row = None
            else:
                if period != current["period"]:
                    raise RuntimeError("one Image Id maps to inconsistent period/clock in %s" % path)
                if clock_seconds is not None:
                    if current["clock"] is None:
                        current["clock"] = clock_seconds
                    elif clock_seconds != current["clock"]:
                        raise RuntimeError("one Image Id maps to inconsistent period/clock in %s" % path)
                sample_row = sample["frames"][-1] if sample is not None and sample_frame_idx <= 300 else None
            if clock_seconds is None:
                metrics["clock_missing_rows"] += 1
            else:
                frame_clock_set.add(clock_seconds)
            entity = (row["Player or Puck"] or "").strip()
            team = (row["Team"] or "").strip()
            if entity not in ("Player", "Puck"):
                raise RuntimeError("unknown tracking entity %r in %s:%d" % (entity, path, line))
            x = optional_xy(row["Rink Location X (Feet)"], "Rink Location X (Feet)", path, line)
            y = optional_xy(row["Rink Location Y (Feet)"], "Rink Location Y (Feet)", path, line)
            metrics["coordinate_rows"] += 1
            if x is None or y is None:
                metrics["missing_xy_rows"] += 1
                inside = False
            else:
                metrics["finite_xy_rows"] += 1
                if entity == "Puck":
                    metrics["puck_xy_rows"] += 1
                inside = RINK_X[0] <= x <= RINK_X[1] and RINK_Y[0] <= y <= RINK_Y[1]
                if inside:
                    metrics["in_rink_xy_rows"] += 1
                    xi = min(int(x - RINK_X[0]), heat_player.shape[1] - 1)
                    yi = min(int(y - RINK_Y[0]), heat_player.shape[0] - 1)
                    if entity == "Puck":
                        puck_xy_count += 1
                        puck_valid = True
                        heat_puck[yi, xi] += 1
                    else:
                        heat_player[yi, xi] += 1
            if entity == "Puck":
                puck_count += 1
                metrics["puck_rows"] += 1
                if sample_row is not None and inside:
                    sample_row["puck"] = (x, y)
                continue
            metrics["player_rows"] += 1
            track_id = (row.get("Player Id") or "").strip()
            jersey = (row.get("Player Jersey Number") or "").strip()
            if track_id:
                metrics["track_id_present_rows"] += 1
            if jersey:
                metrics["jersey_present_rows"] += 1
                metrics["shift_eligible_rows"] += 1
                if jersey in shift_roster.get(team, set()):
                    metrics["shift_match_rows"] += 1
            if track_id and jersey:
                metrics["id_and_jersey_present_rows"] += 1
            if track_id:
                id_key = (period, team, track_id)
                metrics["id_to_team_jersey"][id_key].add(jersey)
                metrics["identity_obs"][id_key] += 1
            if track_id and jersey and inside:
                player_key = (team, track_id, jersey)
                if player_key in current_players:
                    metrics["within_frame_duplicate_player_ids"] += 1
                current_players[player_key] = {"team": team, "x": x, "y": y}
            if sample_row is not None and track_id and inside:
                sample_row["players"][(team, track_id, jersey)] = (x, y)
            if team in ("Home", "Away") and jersey and inside and clock_seconds is not None:
                lookup_key = (period, clock_seconds, team, jersey)
                if lookup_key in event_lookup:
                    event_positions[lookup_key].append((x, y))

    finish_frame()
    metrics["frames"] = int(metrics["frames"])
    if metrics["frames"] == 0:
        raise RuntimeError("empty tracking file: %s" % path)
    metrics["identity_conflicts"] = sum(1 for values in metrics["id_to_team_jersey"].values()
                                        if len(values - {""}) > 1)
    metrics["identity_track_count"] = len(metrics["id_to_team_jersey"])
    del metrics["id_to_team_jersey"]
    del metrics["identity_obs"]
    step_counts = metrics.pop("frame_id_step_counts")
    metrics["adjacent_frame_gap_fraction"] = metrics["frame_id_gaps"] / max(metrics["frames"] - 1, 1)
    timed_span = metrics["start_clock_seconds"] - metrics["end_clock_seconds"]
    if (timed_span <= 0 or metrics["first_timed_frame"] is None or
            metrics["last_timed_frame"] is None):
        raise RuntimeError("cannot infer tracking rate from timed frames in %s" % path)
    metrics["inferred_fps"] = (
        metrics["last_timed_frame"] - metrics["first_timed_frame"]) / timed_span
    metrics["frame_id_step_counts"] = {str(k): v for k, v in sorted(step_counts.items())}
    metrics["puck_exactly_one_fraction"] = metrics["frames_exactly_one_puck"] / metrics["frames"]
    metrics["player_id_and_jersey_fraction"] = metrics["id_and_jersey_present_rows"] / max(metrics["player_rows"], 1)
    metrics["inside_rink_fraction"] = metrics["in_rink_xy_rows"] / max(metrics["coordinate_rows"], 1)
    metrics["xy_present_fraction"] = metrics["finite_xy_rows"] / max(metrics["coordinate_rows"], 1)
    metrics["puck_xy_fraction"] = metrics["puck_xy_rows"] / max(metrics["puck_rows"], 1)
    metrics["clock_row_fraction"] = (metrics["coordinate_rows"] - metrics["clock_missing_rows"]) / max(metrics["coordinate_rows"], 1)
    metrics["clock_frame_fraction"] = (metrics["frames"] - metrics["frames_missing_clock"]) / max(metrics["frames"], 1)
    metrics["puck_gap_le_0_10_seconds_fraction"] = (
        float(np.mean(np.asarray(puck_gap_steps, dtype=float) / metrics["inferred_fps"] <= 0.10))
        if puck_gap_steps else 0.0)
    metrics["puck_gap_observations"] = len(puck_gap_steps)
    metrics["puck_gap_le_0_10_count"] = sum(
        step / metrics["inferred_fps"] <= 0.10 for step in puck_gap_steps)
    alignments = []
    transforms = {"identity": (1, 1), "x_flip": (-1, 1), "y_flip": (1, -1), "xy_flip": (-1, -1)}
    for key, events in event_lookup.items():
        positions = event_positions.get(key, [])
        if not positions:
            continue
        for event in events:
            for transform, (sx, sy) in transforms.items():
                ex, ey = sx * event["x"], sy * event["y"]
                distance = min(math.hypot(ex - px, ey - py) for px, py in positions)
                alignments.append({"transform": transform, "distance_ft": distance,
                                  "event": event["event"]})
    metrics["event_actor_clock_matches"] = len(alignments) // 4
    metrics["event_alignment_by_transform"] = {}
    for transform in transforms:
        values = [row["distance_ft"] for row in alignments if row["transform"] == transform]
        metrics["event_alignment_by_transform"][transform] = {
            "n": len(values), "median_ft": float(np.median(values)) if values else None,
            "p95_ft": float(np.percentile(values, 95)) if values else None,
            "within_20ft_fraction": float(np.mean(np.asarray(values) <= 20)) if values else None,
            "within_40ft_fraction": float(np.mean(np.asarray(values) <= 40)) if values else None,
        }
    return metrics, (sample["frames"] if sample is not None else [])


def draw_rink(ax):
    ax.set_xlim(*RINK_X)
    ax.set_ylim(*RINK_Y)
    ax.set_aspect("equal")
    ax.set_xticks([-100, -89, -25, 0, 25, 89, 100])
    ax.set_yticks([-42.5, -25, 0, 25, 42.5])
    ax.grid(alpha=0.18)
    ax.set_xlabel("Rink X (feet)")
    ax.set_ylabel("Rink Y (feet)")
    for x in (-89, -25, 0, 25, 89):
        ax.axvline(x, color="#d9e2ec" if x not in (-25, 25) else "#b8c9d9",
                   linewidth=0.6 if x not in (-25, 25) else 1.0, zorder=0)


def write_plots(output_dir: Path, heat_player: np.ndarray, heat_puck: np.ndarray,
                sample_frames: list, game_metrics: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), constrained_layout=True)
    for ax, data, title in ((axes[0], heat_player, "Observed skater locations"),
                            (axes[1], heat_puck, "Observed puck locations")):
        draw_rink(ax)
        im = ax.imshow(np.log1p(data), origin="lower", extent=(-100, 100, -42.5, 42.5),
                       aspect="auto", cmap="viridis")
        ax.set_title(title)
        fig.colorbar(im, ax=ax, label="log(1 + row count)")
    fig.suptitle("Actual tracking observations across all ten games")
    fig.savefig(output_dir / "observed_rink_occupancy.png", dpi=160)
    plt.close(fig)

    if sample_frames:
        player_counts = collections.Counter(key for frame in sample_frames for key in frame["players"])
        selected = [key for key, _ in player_counts.most_common(6)]
        fig, ax = plt.subplots(figsize=(9, 6), constrained_layout=True)
        draw_rink(ax)
        colors = plt.cm.tab10(np.linspace(0, 1, max(len(selected), 1)))
        for color, key in zip(colors, selected):
            points = [frame["players"][key] for frame in sample_frames if key in frame["players"]]
            if len(points) < 2:
                continue
            ax.scatter([p[0] for p in points], [p[1] for p in points], c=np.linspace(0, 1, len(points)),
                       cmap=matplotlib.colors.ListedColormap([color]), s=5, alpha=0.65,
                       label="%s id=%s jersey=%s" % key)
            ax.scatter([points[0][0]], [points[0][1]], color=[color], marker="o", s=22)
            ax.scatter([points[-1][0]], [points[-1][1]], color=[color], marker="x", s=30)
        puck = [frame["puck"] for frame in sample_frames if frame["puck"] is not None]
        if len(puck) > 1:
            ax.scatter([p[0] for p in puck], [p[1] for p in puck], s=4, color="black",
                       alpha=0.55, label="puck observations")
        ax.set_title("Observed positions in one real tracking segment\n"
                     "points only; missing frames are not interpolated")
        ax.legend(fontsize=7, loc="upper right")
        fig.savefig(output_dir / "observed_trajectories_10s.png", dpi=160)
        plt.close(fig)

    games = sorted(game_metrics)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4), constrained_layout=True)
    windows = [game_metrics[g]["valid_windows"] for g in games]
    puck = [game_metrics[g]["puck_xy_fraction"] for g in games]
    axes[0].bar(range(len(games)), windows, color="#2a6fbb")
    axes[0].set_xticks(range(len(games)))
    axes[0].set_xticklabels([g[-12:] for g in games], rotation=55, ha="right")
    axes[0].set_ylabel("valid 21-frame skater windows")
    axes[0].set_title("Forecast-window coverage by game")
    axes[1].bar(range(len(games)), puck, color="#3a9d6f")
    axes[1].axhline(0.95, color="red", linestyle="--", label="frozen gate: 0.95")
    axes[1].set_ylim(0, 1.02)
    axes[1].set_xticks(range(len(games)))
    axes[1].set_xticklabels([g[-12:] for g in games], rotation=55, ha="right")
    axes[1].set_ylabel("fraction of puck rows with finite XY")
    axes[1].set_title("Puck-coordinate coverage by game")
    axes[1].legend()
    fig.savefig(output_dir / "coverage_by_game.png", dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path,
                        default=Path("/root/lp-research-data/stathletes-big-data-cup-2026"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "quality")
    args = parser.parse_args()
    started = time.perf_counter()
    if not args.data_dir.is_dir():
        raise SystemExit("data directory not found: %s" % args.data_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = verify_manifest(args.data_dir)
    event_paths = sorted(args.data_dir.glob("*.Events.csv"))
    tracking_paths = sorted(args.data_dir.glob("*.Tracking_*.csv"))
    if len(event_paths) != 10 or len(tracking_paths) != 33:
        raise RuntimeError("expected 10 event and 33 tracking files; got %d and %d" %
                           (len(event_paths), len(tracking_paths)))
    event_lookup_by_game, game_teams = load_event_alignment_keys(args.data_dir, event_paths)
    shift_rosters = load_shift_rosters(args.data_dir, game_teams)
    orientations = {}
    with (args.data_dir / "camera_orientations.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            orientations[row["Game"].replace(" ", ".")] = row["GoalieTeamOnRightSideOfRink1stPeriod"]
    if len(orientations) != 10:
        raise RuntimeError("expected ten camera orientation rows; got %d" % len(orientations))

    heat_player = np.zeros((85, 200), dtype=np.uint64)
    heat_puck = np.zeros((85, 200), dtype=np.uint64)
    file_metrics = []
    game_metrics = collections.defaultdict(lambda: {
        "frames": 0, "player_rows": 0, "puck_rows": 0, "frames_exactly_one_puck": 0,
        "valid_windows": 0, "track_id_present_rows": 0, "jersey_present_rows": 0,
        "id_and_jersey_present_rows": 0,
        "coordinate_rows": 0, "missing_xy_rows": 0, "finite_xy_rows": 0,
        "clock_missing_rows": 0, "frames_missing_clock": 0,
        "puck_xy_rows": 0, "in_rink_xy_rows": 0, "frame_id_gaps": 0,
        "shift_eligible_rows": 0, "shift_match_rows": 0, "valid_puck_windows": 0,
        "clock_reversals": 0, "frames_with_3plus_skaters_each_team": 0,
        "fps_by_file": [], "identity_conflicts": 0, "identity_track_count": 0,
        "within_frame_duplicate_player_ids": 0, "puck_gap_le_0_10_count": 0,
        "puck_gap_observations": 0, "puck_gap_fractions": [],
        "event_alignment_by_transform": collections.defaultdict(list),
        "event_actor_clock_matches": 0,
    })
    for index, path in enumerate(tracking_paths, 1):
        game = path.name.split(".Tracking_", 1)[0]
        if game not in event_lookup_by_game:
            raise RuntimeError("tracking file has no matching event file: %s" % path)
        sample = {"frames": []} if index == 1 else None
        metrics, sample_frames = audit_tracking_file(
            path, event_lookup_by_game[game], heat_player, heat_puck, sample, shift_rosters[game])
        metrics["game"] = game
        metrics["orientation_goalie_right_p1"] = orientations.get(game)
        file_metrics.append(metrics)
        gm = game_metrics[game]
        for field in ("frames", "player_rows", "puck_rows", "frames_exactly_one_puck",
                      "valid_windows", "track_id_present_rows", "jersey_present_rows",
                      "id_and_jersey_present_rows", "coordinate_rows", "missing_xy_rows",
                      "finite_xy_rows", "clock_missing_rows", "frames_missing_clock",
                      "puck_xy_rows", "in_rink_xy_rows",
                      "shift_eligible_rows", "shift_match_rows", "valid_puck_windows",
                      "frame_id_gaps", "clock_reversals", "identity_track_count",
                      "within_frame_duplicate_player_ids", "puck_gap_le_0_10_count",
                      "puck_gap_observations",
                      "frames_with_3plus_skaters_each_team", "identity_conflicts",
                      "event_actor_clock_matches"):
            gm[field] += metrics[field]
        gm["fps_by_file"].append(metrics["inferred_fps"])
        gm["puck_gap_fractions"].append(metrics["puck_gap_le_0_10_seconds_fraction"])
        for transform, values in metrics["event_alignment_by_transform"].items():
            if values["median_ft"] is not None:
                gm["event_alignment_by_transform"][transform].append(values)
        if index == 1:
            sample_for_plot = sample_frames
        print("audited tracking file %d/%d: %s (%d frames; %.2f inferred fps; %d windows)" %
              (index, len(tracking_paths), path.name, metrics["frames"],
               metrics["inferred_fps"], metrics["valid_windows"]), flush=True)

    if set(game_metrics) != {p.name[:-len(".Events.csv")] for p in event_paths}:
        raise RuntimeError("tracking and event game populations differ")
    for gm in game_metrics.values():
        gm["puck_exactly_one_fraction"] = gm["frames_exactly_one_puck"] / max(gm["frames"], 1)
        gm["player_id_and_jersey_fraction"] = gm["id_and_jersey_present_rows"] / max(gm["player_rows"], 1)
        gm["shift_identity_match_fraction"] = gm["shift_match_rows"] / max(gm["shift_eligible_rows"], 1)
        gm["inside_rink_fraction"] = gm["in_rink_xy_rows"] / max(gm["coordinate_rows"], 1)
        gm["xy_present_fraction"] = gm["finite_xy_rows"] / max(gm["coordinate_rows"], 1)
        gm["clock_row_fraction"] = (gm["coordinate_rows"] - gm["clock_missing_rows"]) / max(gm["coordinate_rows"], 1)
        gm["clock_frame_fraction"] = (gm["frames"] - gm["frames_missing_clock"]) / max(gm["frames"], 1)
        gm["puck_xy_fraction"] = gm["puck_xy_rows"] / max(gm["puck_rows"], 1)
        gm["inferred_fps_median"] = float(np.median(gm["fps_by_file"]))
        gm["puck_gap_le_0_10_seconds_fraction"] = (
            gm["puck_gap_le_0_10_count"] / max(gm["puck_gap_observations"], 1))
        gm["event_alignment_by_transform"] = {
            t: {"n": sum(v["n"] for v in vals),
                "median_ft_weighted_by_game_file": float(np.median([v["median_ft"] for v in vals])),
                "p95_ft_max_across_files": float(max(v["p95_ft"] for v in vals))}
            for t, vals in gm["event_alignment_by_transform"].items()
        }

    total = collections.Counter()
    for gm in game_metrics.values():
        for field in ("frames", "player_rows", "puck_rows", "frames_exactly_one_puck",
                      "valid_windows", "track_id_present_rows", "jersey_present_rows",
                      "id_and_jersey_present_rows", "identity_track_count",
                      "within_frame_duplicate_player_ids", "puck_gap_le_0_10_count",
                      "puck_gap_observations",
                      "coordinate_rows", "missing_xy_rows", "finite_xy_rows", "puck_xy_rows",
                      "clock_missing_rows", "frames_missing_clock",
                      "shift_eligible_rows", "shift_match_rows", "valid_puck_windows",
                      "in_rink_xy_rows", "frame_id_gaps", "clock_reversals",
                      "frames_with_3plus_skaters_each_team", "identity_conflicts",
                      "event_actor_clock_matches"):
            total[field] += gm[field]
    total["puck_exactly_one_fraction"] = total["frames_exactly_one_puck"] / max(total["frames"], 1)
    total["player_id_and_jersey_fraction"] = total["id_and_jersey_present_rows"] / max(total["player_rows"], 1)
    total["shift_identity_match_fraction"] = total["shift_match_rows"] / max(total["shift_eligible_rows"], 1)
    total["identity_conflict_fraction"] = total["identity_conflicts"] / max(total["identity_track_count"], 1)
    total["inside_rink_fraction"] = total["in_rink_xy_rows"] / max(total["coordinate_rows"], 1)
    total["xy_present_fraction"] = total["finite_xy_rows"] / max(total["coordinate_rows"], 1)
    total["clock_row_fraction"] = (total["coordinate_rows"] - total["clock_missing_rows"]) / max(total["coordinate_rows"], 1)
    total["clock_frame_fraction"] = (total["frames"] - total["frames_missing_clock"]) / max(total["frames"], 1)
    total["puck_xy_fraction"] = total["puck_xy_rows"] / max(total["puck_rows"], 1)
    total["puck_gap_le_0_10_seconds_fraction"] = (
        total["puck_gap_le_0_10_count"] / max(total["puck_gap_observations"], 1))
    fps_games = [gm["inferred_fps_median"] for gm in game_metrics.values()]
    gates = {
        "release_integrity": manifest["status"] == "PASS",
        "tracking_coordinate_validity": total["inside_rink_fraction"] >= 0.99 and
                                         total["xy_present_fraction"] >= 0.99,
        "temporal_rate": sum(25 <= fps <= 32 for fps in fps_games) >= 8 and
                         total["clock_row_fraction"] >= 0.99 and
                         total["clock_frame_fraction"] >= 0.99 and
                         all(m["clock_reversals"] == 0 and m["frame_id_duplicate_or_reversal"] == 0
                             for m in file_metrics),
        "player_identity_coverage": total["player_id_and_jersey_fraction"] >= 0.90 and
                                    total["shift_identity_match_fraction"] >= 0.90 and
                                    total["identity_conflict_fraction"] < 0.001 and
                                    total["within_frame_duplicate_player_ids"] == 0,
        "puck_continuity": total["puck_exactly_one_fraction"] >= 0.99 and
                           total["puck_gap_le_0_10_seconds_fraction"] >= 0.95 and
                           total["puck_xy_fraction"] >= 0.95 and
                           total["valid_puck_windows"] >= 10000 and
                           sum(gm["valid_puck_windows"] >= 1000 for gm in game_metrics.values()) >= 8,
        "forecast_window_coverage": total["valid_windows"] >= 10000 and
                                    sum(gm["valid_windows"] >= 1000 for gm in game_metrics.values()) >= 8,
        "event_coordinate_alignment": sum(
            gm["event_actor_clock_matches"] >= 100 and
            gm["event_alignment_by_transform"].get("identity", {}).get("median_ft_weighted_by_game_file", float("inf")) <= 20 and
            gm["event_alignment_by_transform"].get("identity", {}).get("p95_ft_max_across_files", float("inf")) <= 40
            for gm in game_metrics.values()) >= 8,
    }
    result = {
        "study": "NHL ten-game movement quality audit",
        "source": str(args.data_dir),
        "manifest": manifest,
        "frozen_thresholds": {
            "coordinate_in_bounds_fraction": 0.99,
            "xy_present_fraction": 0.99,
            "event_alignment_min_matches_per_game": 100,
            "event_alignment_min_games": 8,
            "event_alignment_median_ft": 20,
            "event_alignment_p95_ft": 40,
            "fps_range": [25, 32], "fps_min_games": 8,
            "game_clock_row_fraction_min": 0.99,
            "game_clock_frame_fraction_min": 0.99,
            "player_id_and_jersey_fraction": 0.90,
            "shift_identity_match_fraction": 0.90,
            "identity_conflict_fraction_max_exclusive": 0.001,
            "puck_exactly_one_fraction": 0.99,
            "puck_xy_fraction": 0.95,
            "puck_gap_seconds_max": 0.10,
            "puck_gap_fraction_min": 0.95,
            "valid_puck_windows_min": 10000,
            "puck_games_min": 8,
            "puck_windows_per_game_min": 1000,
            "forecast_windows_min": 10000,
            "forecast_games_min": 8,
            "forecast_windows_per_game_min": 1000,
            "forecast_window_input_frames": 6,
            "forecast_horizon_frames": 15,
        },
        "gates": gates,
        "overall": dict(total),
        "games": game_metrics,
        "period_files": file_metrics,
        "interpretation": {
            "event_alignment": "The direct unreflected mapping is frozen from the first-period pilot. Event coordinates are compared to same-game/team/jersey, same-second tracking positions; candidate sign reflections are diagnostics only.",
            "identity": "Tracking IDs and jerseys are retained as game-scoped identifiers. No cross-game athlete identity is assumed.",
            "clock": "Image Id numeric suffix supplies within-file order. Game Clock is integer-second resolution; fps and physical forecast duration are estimates.",
        },
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }
    out_json = args.output_dir / "tracking_quality.json"
    out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "tracking_quality_by_game.csv").write_text(
        "game,frames,player_rows,puck_rows,valid_windows,puck_exactly_one_fraction,"
        "player_id_and_jersey_fraction,inside_rink_fraction,clock_row_fraction,clock_frame_fraction,"
        "inferred_fps_median,clock_reversals,frame_id_gaps\n" +
        "".join("{game},{frames},{player_rows},{puck_rows},{valid_windows},{puck_exactly_one_fraction:.6f},"
                "{player_id_and_jersey_fraction:.6f},{inside_rink_fraction:.6f},{clock_row_fraction:.6f},"
                "{clock_frame_fraction:.6f},{inferred_fps_median:.4f},"
                "{clock_reversals},{frame_id_gaps}\n".format(game=g, **gm)
                for g, gm in sorted(game_metrics.items())), encoding="utf-8")
    write_plots(args.output_dir, heat_player, heat_puck, sample_for_plot, game_metrics)
    print(json.dumps({"manifest": manifest, "overall": dict(total), "gates": gates,
                      "runtime_seconds": result["runtime_seconds"],
                      "output_dir": str(args.output_dir)}, indent=2, sort_keys=True))
    if any(value is False for value in gates.values()):
        raise SystemExit("one or more frozen quality gates failed; see %s" % out_json)


if __name__ == "__main__":
    main()
