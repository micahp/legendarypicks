#!/usr/bin/env python3
"""Build a snap-anchored, all-player movement cohort without outcome labels.

The frozen observed-tackle manifest is deliberately not an input. Eligibility
uses a ball_snap event, pre-snap play metadata, roster roles, and tracking-row
presence. Coordinates after the snap are written only as evaluation labels.
Weeks 6-9 are excluded by the CLI's week allowlist.
"""

import argparse
import collections
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = Path("/root/nfl-tracking-data/bdb2025")
CODE_DATA = DATA / "code-data"
AUDIT = DATA / "audit"
MANIFEST_DEFAULT = ROOT / "docs/research/bdb2025-snap-all-player-manifest-v1.csv"
SUMMARY_DEFAULT = ROOT / "docs/research/bdb2025-snap-all-player-cohort-v1.json"
OBSERVATIONS_DEFAULT = AUDIT / "bdb2025-snap-all-player-observations-v1.jsonl.gz"
YARDS_TO_METERS = 0.9144
HISTORY_FRAMES = 5
HORIZON_FRAMES = 10
TRACKED_PLAYERS = 22
SNAP_METADATA_FIELDS = (
    "quarter", "down", "yardsToGo", "possessionTeam", "defensiveTeam",
    "yardlineSide", "yardlineNumber", "gameClock", "preSnapHomeScore",
    "preSnapVisitorScore", "offenseFormation", "receiverAlignment",
    "playClockAtSnap",
)


def csv_map(path, key_fields, selected_fields=None):
    out = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = tuple(row[k] for k in key_fields)
            if selected_fields is not None:
                row = {k: row.get(k, "") for k in selected_fields}
            if key in out:
                raise RuntimeError(f"Duplicate metadata key {key} in {path}")
            out[key] = row
    return out


def play_groups(path):
    """Yield one play at a time; fail if the source is not key-contiguous."""
    with path.open(newline="", encoding="utf-8") as f:
        current = None
        rows = []
        closed = set()
        for row in csv.DictReader(f):
            key = (row["gameId"], row["playId"])
            if current is not None and key != current:
                closed.add(current)
                yield current, rows
                rows = []
                if key in closed:
                    raise RuntimeError(f"Non-contiguous play rows in {path}: {key}")
            current = key
            rows.append(row)
        if current is not None:
            yield current, rows


def position_rows(rows):
    frames = collections.defaultdict(lambda: {"players": {}, "football": []})
    for row in rows:
        frame = int(row["frameId"])
        player_id = row["nflId"]
        if player_id in ("", "NA"):
            frames[frame]["football"].append(row)
        else:
            if player_id in frames[frame]["players"]:
                raise RuntimeError(f"Duplicate player {player_id} at frame {frame}")
            frames[frame]["players"][player_id] = row
    return frames


def point_m(row):
    x, y = float(row["x"]), float(row["y"])
    if not math.isfinite(x) or not math.isfinite(y):
        raise RuntimeError("Non-finite tracking coordinate")
    return [x * YARDS_TO_METERS, y * YARDS_TO_METERS]


def event_frames(rows, event_name):
    return sorted({int(row["frameId"]) for row in rows if row["event"] == event_name})


def assess_play(key, rows, frames, plays, players):
    snaps = event_frames(rows, "ball_snap")
    if len(snaps) != 1:
        return None, "ball_snap_missing_or_nonunique"
    snap = snaps[0]
    meta = plays.get(key)
    if not meta:
        return None, "snap_metadata_missing"
    offense = meta["possessionTeam"]
    defense = meta["defensiveTeam"]
    if not offense or not defense or offense == defense:
        return None, "snap_team_metadata_invalid"
    required = list(range(snap - HISTORY_FRAMES, snap + HORIZON_FRAMES + 1))
    if any(frame not in frames for frame in required):
        return None, "incomplete_frame_span"
    directions = set()
    team_ids = set()
    player_ids_at_snap = set(frames[snap]["players"])
    for frame in required:
        current = frames[frame]
        if len(current["players"]) != TRACKED_PLAYERS:
            return None, "not_22_players_through_1s"
        if len(current["football"]) != 1:
            return None, "football_missing_or_duplicate_through_1s"
        if set(current["players"]) != player_ids_at_snap:
            return None, "player_identity_gap_through_1s"
        for row in current["players"].values():
            directions.add(row["playDirection"])
            team_ids.add(row["club"])
    if len(directions) != 1 or not directions <= {"left", "right"}:
        return None, "play_direction_invalid"
    if team_ids != {offense, defense}:
        return None, "tracking_teams_disagree_with_snap_metadata"
    at_snap = frames[snap]["players"]
    offense_ids = sorted(pid for pid, row in at_snap.items() if row["club"] == offense)
    defense_ids = sorted(pid for pid, row in at_snap.items() if row["club"] == defense)
    if len(offense_ids) != 11 or len(defense_ids) != 11:
        return None, "team_roles_not_11_vs_11"

    actor_rows = []
    for player_id in sorted(player_ids_at_snap):
        roster = players.get((player_id,))
        if not roster:
            raise RuntimeError(f"Missing season roster metadata for tracked player {player_id}")
        weight_lb = float(roster["weight"])
        if not math.isfinite(weight_lb) or weight_lb <= 0:
            raise RuntimeError(f"Invalid roster weight for tracked player {player_id}")
        team = at_snap[player_id]["club"]
        role = "offense" if team == offense else "defense"
        actor_rows.append({
            "nflId": player_id,
            "team": team,
            "role": role,
            "position": roster["position"],
            "weightKg": weight_lb * 0.45359237,
        })

    input_frames = list(range(snap - HISTORY_FRAMES, snap + 1))
    label_frames = list(range(snap, snap + HORIZON_FRAMES + 1))
    for actor in actor_rows:
        pid = actor["nflId"]
        actor["inputPositionsM"] = [point_m(frames[frame]["players"][pid]) for frame in input_frames]
        actor["labelPositionsM"] = [point_m(frames[frame]["players"][pid]) for frame in label_frames]
    football_labels = [point_m(frames[frame]["football"][0]) for frame in label_frames]
    directions = list(directions)
    observation = {
        "week": int(rows[0]["week"]) if "week" in rows[0] else None,
        "gameId": key[0],
        "playId": key[1],
        "snapFrame": snap,
        "inputFrameIds": input_frames,
        "labelFrameIds": label_frames,
        "playDirection": directions[0],
        "offenseTeam": offense,
        "defenseTeam": defense,
        "metadata": meta,
        "players": actor_rows,
        "footballLabelsM": football_labels,
    }
    manifest = {
        "schema_version": "bdb2025-snap-all-player-manifest/v1",
        "dataset": "unofficial b00nk3r/NFL-Big-Data-Bowl-2025 mirror; 2022 season",
        "week": observation["week"],
        "game_id": key[0],
        "play_id": key[1],
        "snap_frame": snap,
        "input_history_start_frame": snap - HISTORY_FRAMES,
        "input_cutoff_frame": snap,
        "horizon_0_5_frame": snap + 5,
        "horizon_1_0_frame": snap + 10,
        "players_total": len(actor_rows),
        "offense_players": len(offense_ids),
        "defense_players": len(defense_ids),
        "football_label_frames": len(football_labels),
        "play_direction": directions[0],
        "offense_team": offense,
        "defense_team": defense,
        **{k: meta.get(k, "") for k in SNAP_METADATA_FIELDS},
        "players_at_snap": json.dumps([
            {k: actor[k] for k in ("nflId", "team", "role", "position")}
            for actor in actor_rows
        ], separators=(",", ":")),
    }
    return (manifest, observation), None


def source_hashes(weeks):
    sums_path = DATA / "SHA256SUMS.txt"
    expected = {}
    for line in sums_path.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        expected[name.lstrip("* ")] = digest
    names = ["code-data/plays.csv", "code-data/players.csv"]
    names += [f"code-data/tracking_week_{week}.csv" for week in weeks]
    missing = [name for name in names if name not in expected]
    if missing:
        raise RuntimeError(f"Source hash manifest is missing entries: {missing}")
    return {name: expected[name] for name in names}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks", nargs="+", type=int, choices=range(1, 6), default=[1, 2, 3, 4, 5])
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--summary", type=Path, default=SUMMARY_DEFAULT)
    parser.add_argument("--observations", type=Path, default=OBSERVATIONS_DEFAULT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    weeks = sorted(set(args.weeks))
    if len(weeks) != len(args.weeks):
        raise RuntimeError("Repeated weeks are not allowed")
    if any(week not in (1, 2, 3, 4, 5) for week in weeks):
        raise RuntimeError("Weeks 6-9 are reserved and cannot be scanned")
    for path in (args.manifest, args.summary, args.observations):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.overwrite:
            raise FileExistsError(f"Refusing to overwrite existing output: {path}")

    plays = csv_map(CODE_DATA / "plays.csv", ("gameId", "playId"), SNAP_METADATA_FIELDS)
    players = csv_map(CODE_DATA / "players.csv", ("nflId",), ("weight", "position"))
    manifest_rows = []
    counters = {week: collections.Counter() for week in weeks}
    fields = [
        "schema_version", "dataset", "week", "game_id", "play_id", "snap_frame",
        "input_history_start_frame", "input_cutoff_frame", "horizon_0_5_frame",
        "horizon_1_0_frame", "players_total", "offense_players", "defense_players",
        "football_label_frames", "play_direction", "offense_team", "defense_team",
        *SNAP_METADATA_FIELDS, "players_at_snap",
    ]
    with gzip.open(args.observations, "wt", encoding="utf-8", newline="") as observations:
        for week in weeks:
            path = CODE_DATA / f"tracking_week_{week}.csv"
            for key, rows in play_groups(path):
                counters[week]["plays_in_tracking"] += 1
                frames = position_rows(rows)
                if event_frames(rows, "ball_snap"):
                    counters[week]["plays_with_ball_snap_event"] += 1
                result, reason = assess_play(key, rows, frames, plays, players)
                if reason:
                    counters[week][f"excluded:{reason}"] += 1
                    continue
                manifest, observation = result
                observation["week"] = week
                manifest["week"] = week
                manifest_rows.append(manifest)
                observations.write(json.dumps(observation, separators=(",", ":")) + "\n")
                counters[week]["included"] += 1

    with args.manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest_rows)
    summary = {
        "schemaVersion": "bdb2025-snap-all-player-cohort/v1",
        "dataset": "unofficial b00nk3r/NFL-Big-Data-Bowl-2025 mirror; 2022 season",
        "weeksScanned": weeks,
        "weeksReserved": [6, 7, 8, 9],
        "eligibility": {
            "selection": "ball_snap event; snap metadata and role from possession/defense teams; tracking-row presence only",
            "players": "all 22 tracked players, with 11 offense and 11 defense at snap",
            "inputFrames": "snapFrame-5 through snapFrame inclusive; input cutoff is snapFrame",
            "labels": "all 22 player locations plus football at snapFrame through snapFrame+10",
            "requiredPresence": "22 unique players and one football row at every frame from snapFrame-5 through snapFrame+10",
            "prohibitedInputs": ["eventual tackle frame", "credited tackler", "player_play outcome labels", "post-snap coordinates"],
        },
        "sourceSha256FromStagedManifest": source_hashes(weeks),
        "includedTotal": len(manifest_rows),
        "includedByWeek": {str(w): counters[w]["included"] for w in weeks},
        "countsByWeek": {str(w): dict(sorted(counters[w].items())) for w in weeks},
        "outputs": {"manifest": str(args.manifest), "observations": str(args.observations)},
    }
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary["manifestSha256"] = digest(args.manifest)
    summary["observationsSha256"] = digest(args.observations)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"included": summary["includedTotal"], "byWeek": summary["includedByWeek"],
                      "manifest": str(args.manifest), "summary": str(args.summary),
                      "observations": str(args.observations)}, indent=2))


if __name__ == "__main__":
    main()
