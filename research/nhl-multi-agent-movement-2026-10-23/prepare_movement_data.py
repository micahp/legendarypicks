#!/usr/bin/env python3
"""Verify and normalize the ten-game Stathletes tracking release for ordinal movement research.

Raw release data and the complete normalized observation stream stay outside this repository.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import math
import random
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "research/nhl-ten-game-kinematics-2026-10-22"
RINK_X, RINK_Y = (-100.0, 100.0), (-42.5, 42.5)
SEED, HORIZON, INPUT = 20261023, 45, 6
REQ = {"Image Id", "Period", "Game Clock", "Player or Puck", "Team", "Player Id",
       "Player Jersey Number", "Rink Location X (Feet)", "Rink Location Y (Feet)"}
T = np.arange(INPUT, dtype=float)
LIN = np.linalg.pinv(np.column_stack((np.ones(INPUT), T)))
QUAD = np.linalg.pinv(np.column_stack((np.ones(INPUT), T, T * T)))


def frame_number(image: str) -> int:
    try:
        return int(image.rsplit("_", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"invalid Image Id {image!r}") from exc


def file_game(name: str) -> str:
    return name.split(".Tracking_", 1)[0]


def file_period(name: str) -> str:
    return name.rsplit("Tracking_", 1)[1][:-4]


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_release(data_dir: Path, files: list[Path], smoke: bool) -> tuple[dict, str]:
    manifest_path = data_dir / "download-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if len(manifest["files"]) != manifest["asset_count"]:
        raise RuntimeError("source manifest asset_count mismatch")
    manifest_hash = file_sha(manifest_path)
    chosen = {p.name for p in files}
    for asset in manifest["files"]:
        if smoke and asset["name"] not in chosen:
            continue
        path = data_dir / asset["name"]
        if not path.is_file() or path.stat().st_size != int(asset["bytes"]):
            raise RuntimeError(f"source size mismatch: {path}")
        if file_sha(path) != asset["sha256"]:
            raise RuntimeError(f"source SHA-256 mismatch: {path}")
        print(f"verified {asset['name']}", flush=True)
    return manifest, manifest_hash


def scan_conflicts(path: Path) -> dict[tuple[str, str], set[str]]:
    mapping: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        if not REQ.issubset(r.fieldnames or []):
            raise RuntimeError(f"tracking schema mismatch: {path.name}")
        if any("timestamp" in c.lower() or "frame rate" in c.lower() or "cadence" in c.lower()
               for c in (r.fieldnames or [])):
            raise RuntimeError("new timebase metadata found; freeze a new protocol before fitting")
        for row in r:
            if (row["Player or Puck"] or "").strip() != "Player":
                continue
            team, pid, jersey = ((row[k] or "").strip() for k in ("Team", "Player Id", "Player Jersey Number"))
            if team and pid and jersey:
                mapping[(team, pid)].add(jersey)
    return mapping


def kin_features(points: list[tuple[int, float, float]]) -> np.ndarray | None:
    if len(points) < INPUT:
        return None
    q = np.asarray([(p[1], p[2]) for p in points[-INPUT:]], dtype=float)
    return np.asarray([*((LIN @ q)[1]), *((2.0 * (QUAD @ q)[2]))], dtype=np.float32)


def m1_features(player: dict, frame_state: dict) -> np.ndarray:
    puck = frame_state["puck"]
    miss = puck is None
    px, py = (0.0, 0.0) if miss else (puck["x"], puck["y"])
    pprev = frame_state["puck_previous"]
    pvx = 0.0 if miss or pprev is None else px - pprev[0]
    pvy = 0.0 if miss or pprev is None else py - pprev[1]
    def aggregate(team: str) -> tuple[list[float], list[int]]:
        weight = dx = dy = dvx = dvy = 0.0
        counts = [0, 0, 0]
        for other in frame_state["players"].values():
            if other["team"] != team or other["id"] == player["id"]:
                continue
            rx, ry = other["x"] - player["x"], other["y"] - player["y"]
            distance = math.hypot(rx, ry)
            w = math.exp(-distance / 20.0)
            weight += w; dx += rx * w; dy += ry * w
            ov = other["kin"][:2]
            dvx += (float(ov[0]) - float(player["kin"][0])) * w
            dvy += (float(ov[1]) - float(player["kin"][1])) * w
            for i, threshold in enumerate((10.0, 20.0, 40.0)):
                counts[i] += int(distance <= threshold)
        vals = [dx / weight, dy / weight, dvx / weight, dvy / weight] if weight else [0.0] * 4
        return vals, counts
    mates, mate_counts = aggregate(player["team"])
    opp_team = "Away" if player["team"] == "Home" else "Home"
    opponents, opp_counts = aggregate(opp_team)
    return np.asarray([*player["kin"], px - player["x"] if not miss else 0.0,
                       py - player["y"] if not miss else 0.0, pvx, pvy, float(miss),
                       *mates, *opponents, *mate_counts, *opp_counts], dtype=np.float32)


def orientation_map(data_dir: Path) -> dict[str, str]:
    path = data_dir / "camera_orientations.csv"
    result = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("Game") or "").replace(" ", ".")
            result[key] = (row.get("GoalieTeamOnRightSideOfRink1stPeriod") or "").strip()
    return result


def categories(state: dict, orientation: str | None) -> set[str]:
    out: set[str] = set()
    players = list(state["players"].values())
    puck = state["puck"]
    if puck:
        x, y = puck["x"], puck["y"]
        if orientation in {"Home", "Away"}:
            attacking = "Away" if orientation == "Home" else "Home"
            attack_sign = 1 if attacking == "Away" else -1
            if attack_sign * x >= 70: out.add("oriented_attack_end_puck_proximity")
            if attack_sign * x <= -70: out.add("opposite_end_puck_proximity")
        if abs(x) <= 25: out.add("central_strip_geometry")
        prev = state["puck_previous"]
        if prev is not None:
            approaching = 0
            for p in players:
                d0 = math.hypot(p["x"] - x, p["y"] - y)
                displacement = p.get("past_displacement")
                if displacement is None: continue
                d1 = math.hypot((p["x"] - displacement[0]) - prev[0],
                                (p["y"] - displacement[1]) - prev[1])
                approaching += int(d0 < d1)
            if approaching >= 3: out.add("multiple_skaters_closing_on_puck_geometry")
    for p in players:
        nearest = min((math.hypot(q["x"] - p["x"], q["y"] - p["y"])
                       for q in players if q["team"] != p["team"]), default=math.inf)
        if p.get("past_displacement") is not None:
            oldx = p["x"] - p["past_displacement"][0]
            oldy = p["y"] - p["past_displacement"][1]
            old_nearest = min((math.hypot(q["x"] - q["past_displacement"][0] - oldx,
                                          q["y"] - q["past_displacement"][1] - oldy)
                               for q in players if q["team"] != p["team"] and q.get("past_displacement") is not None),
                              default=math.inf)
            if nearest > old_nearest: out.add("skater_separating_from_nearest_opponent")
    for team in ("Home", "Away"):
        same = [p for p in players if p["team"] == team and math.hypot(*p["kin"][:2]) > 0.1]
        if len(same) >= 3:
            dirs = [(p["kin"][0] / math.hypot(*p["kin"][:2]), p["kin"][1] / math.hypot(*p["kin"][:2])) for p in same]
            resultant = (sum(d[0] for d in dirs), sum(d[1] for d in dirs))
            magnitude = math.hypot(*resultant)
            if magnitude and all((d[0]*resultant[0]+d[1]*resultant[1])/magnitude > 0.7 for d in dirs):
                out.add("aligned_teammate_movement_geometry")
    if state["missing_xy_count"] or state["conflicted_present"]:
        out.add("tracking_missingness_or_identity_conflict")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("/root/lp-research-data/stathletes-big-data-cup-2026"))
    ap.add_argument("--output-dir", type=Path, default=Path("/root/lp-research-data/nhl-multi-agent-movement-2026-10-23"))
    ap.add_argument("--limit-files", type=int, default=0, help="small real-data smoke only")
    args = ap.parse_args()
    started = time.perf_counter()
    audit = json.loads((OLD / "quality/tracking_quality.json").read_text())
    if audit["manifest"]["status"] != "PASS" or not audit["gates"]["release_integrity"]:
        raise RuntimeError("existing release-integrity audit did not pass")
    files = sorted(args.data_dir.glob("*.Tracking_*.csv"))
    if args.limit_files:
        files = files[:args.limit_files]
    elif len(files) != 33:
        raise RuntimeError(f"expected all 33 audited tracking period files, found {len(files)}")
    manifest, manifest_hash = verify_release(args.data_dir, files, bool(args.limit_files))
    asset_lookup = {item["name"]: item for item in manifest["files"]}
    orientations = orientation_map(args.data_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = args.output_dir / "normalized_observations.jsonl.gz"
    window_capacity = sum(int(next(x for x in audit["period_files"] if x["file"] == p.name)["valid_windows"])
                          for p in files)
    if not args.limit_files and window_capacity != audit["overall"]["valid_windows"]:
        raise RuntimeError("audited window capacity does not reconcile")
    games = sorted({file_game(p.name) for p in files})
    game_idx = {g: i for i, g in enumerate(games)}
    dims = 23
    x0 = np.zeros((window_capacity, 4), np.float32); x1 = np.zeros((window_capacity, dims), np.float32)
    pos = np.zeros((window_capacity, 2), np.float32); target = np.zeros_like(pos)
    group = np.zeros(window_capacity, np.uint8); eligible = np.zeros(window_capacity, bool)
    cutoff_seq = np.zeros(window_capacity, np.int64); file_indices = np.zeros(window_capacity, np.int16)
    index = 0; file_meta = []; conflicts_total = 0
    # Movement-distribution samples are compact float32 arrays with game labels.
    max_motion = int(audit["overall"]["player_rows"])
    disp = np.empty(max_motion, np.float32); disp_g = np.empty(max_motion, np.uint8); nd = 0
    delta = np.empty(max_motion, np.float32); delta_g = np.empty(max_motion, np.uint8); na = 0
    turn = np.empty(max_motion, np.float32); turn_g = np.empty(max_motion, np.uint8); nt = 0
    nearest = np.empty(max_motion, np.float32); near_g = np.empty(max_motion, np.uint8); nn = 0
    rng_by_file: dict[str, random.Random] = {}
    reservoir: dict[str, list[dict]] = collections.defaultdict(list)
    candidate_counts: collections.Counter = collections.Counter()
    category_examples: dict[str, dict] = {}
    raw_groups = raw_players = invalid_xy_rows = invalid_player_xy_rows = 0

    with gzip.open(normalized_path, "wt", encoding="utf-8", compresslevel=1) as normalized:
      for file_i, path in enumerate(files):
        game, period = file_game(path.name), file_period(path.name)
        gi = game_idx[game]
        gate = next((x for x in audit["period_files"] if x["file"] == path.name), None)
        if gate is None: raise RuntimeError(f"file absent from frozen audit: {path.name}")
        known = scan_conflicts(path)
        conflicted = {key for key, jerseys in known.items() if len(jerseys) > 1}
        if len(conflicted) != int(gate["identity_conflicts"]):
            raise RuntimeError(f"identity conflicts changed for {path.name}: {len(conflicted)} != {gate['identity_conflicts']}")
        conflicts_total += len(conflicted)
        histories: dict[str, list[tuple[int, float, float]]] = {}
        last_target: dict[str, int] = {}
        states: collections.deque = collections.deque(maxlen=16)
        current = None; current_rows = []; current_players = {}; current_puck = None
        seq_to_target_candidates: list[dict] = []
        file_start = index; file_groups = 0
        file_seed = int(hashlib.sha256((path.name + str(SEED)).encode()).hexdigest()[:8], 16)
        rng_by_file[path.name] = random.Random(file_seed)
        local_candidates = 0

        def finish_frame() -> None:
            nonlocal current, current_rows, current_players, current_puck, index, raw_groups
            nonlocal raw_players, invalid_xy_rows, invalid_player_xy_rows, nd, na, nt, nn, local_candidates
            if current is None: return
            seq = current["seq"]
            # A disappearance, invalid coordinate, or suffix gap resets the trajectory history.
            for key in list(histories):
                if key not in current_players or not histories[key] or seq - histories[key][-1][0] != 1:
                    histories[key] = []; last_target.pop(key, None)
            visible_valid = {}
            for key, value in current_players.items():
                h = histories.setdefault(key, [])
                prior_v = None
                if h and seq - h[-1][0] == 1:
                    prior_v = np.asarray([value["x"] - h[-1][1], value["y"] - h[-1][2]], dtype=float)
                    stable_identity = (value["team"], value["raw_id"]) not in conflicted
                    if stable_identity:
                        disp[nd] = np.linalg.norm(prior_v); disp_g[nd] = gi; nd += 1
                    if stable_identity and len(h) >= 2 and h[-1][0] - h[-2][0] == 1:
                        old_v = np.asarray([h[-1][1] - h[-2][1], h[-1][2] - h[-2][2]], dtype=float)
                        dv = prior_v - old_v; delta[na] = np.linalg.norm(dv); delta_g[na] = gi; na += 1
                        if np.linalg.norm(prior_v) > 0.1 and np.linalg.norm(old_v) > 0.1:
                            cross = old_v[0]*prior_v[1] - old_v[1]*prior_v[0]
                            dot = np.dot(old_v, prior_v)
                            turn[nt] = abs(math.atan2(cross, dot)); turn_g[nt] = gi; nt += 1
                h.append((seq, value["x"], value["y"]))
                if len(h) > 21: del h[:-21]
                kin = kin_features(h)
                value["kin"] = kin.tolist() if kin is not None else None
                value["past_displacement"] = None if prior_v is None else prior_v.tolist()
                value["heading_rad"] = None if prior_v is None or np.linalg.norm(prior_v) == 0 else math.atan2(prior_v[1], prior_v[0])
                if value["kin"] is not None and (value["team"], value["raw_id"]) not in conflicted:
                    visible_valid[key] = value
            # Nearest-player spacing distribution, with each player counted once per observation.
            vals = [v for v in current_players.values() if (v["team"], v["raw_id"]) not in conflicted]
            for p in vals:
                ds = [math.hypot(q["x"]-p["x"], q["y"]-p["y"]) for q in vals if q["id"] != p["id"]]
                if ds: nearest[nn] = min(ds); near_g[nn] = gi; nn += 1
            previous_puck = None
            if states and states[-1]["seq"] == seq - 1 and states[-1]["puck"] is not None:
                previous_puck = [states[-1]["puck"]["x"], states[-1]["puck"]["y"]]
            puck_xy = current_puck if current_puck and current_puck.get("x") is not None else None
            frame_state = {"seq": seq, "image_id": current["image"], "puck": puck_xy,
                           "puck_previous": previous_puck, "players": visible_valid,
                           "missing_xy_count": sum(1 for r in current_rows if r["kind"] == "Player" and not r["coordinate_valid"]),
                           "conflicted_present": any(r["identity_conflict"] for r in current_rows if r["kind"] == "Player"),
                           "period": current["period"], "game_clock": current["clock"]}
            for rec in current_rows:
                if rec["kind"] != "Player":
                    continue
                key = f"{rec['team']}|{rec['player_id_source']}|{rec['jersey']}"
                tracked = current_players.get(key)
                rec["past_displacement"] = tracked.get("past_displacement") if tracked else None
                rec["heading_rad"] = tracked.get("heading_rad") if tracked else None
                rec["past_kinematic_state"] = tracked.get("kin") if tracked else None
                rec["coordinate_missing"] = not rec["coordinate_valid"]
            states.append(frame_state)

            # Canonical grouped observed record. Nulls are retained; no positions are interpolated.
            normalized.write(json.dumps({
                "game": game, "period": period, "image_id": current["image"], "observation_index": file_groups,
                "image_id_suffix": seq, "game_clock": current["clock"],
                "track_scope": f"{game}|{period}|team|track_id", "players": current_rows,
                "puck": current_puck, "visible_track_ids_by_team": {
                    t: sorted(v["track_id"] for v in current_rows if v["kind"] == "Player" and v["team"] == t and v["track_id"])
                    for t in ("Home", "Away")},
                "on_ice_personnel": {t: sum(1 for v in current_players.values()
                                             if v["team"] == t and (v["team"], v["raw_id"]) not in conflicted)
                                     for t in ("Home", "Away")},
                "personnel_completeness": "unknown", "coordinate_transform": "source rink XY; no event alignment; no flip applied",
                "period_one_goalie_right_team": orientations.get(game) if period == "P1" else None,
                "orientation_status": "publisher metadata for period one only" if period == "P1" else "unverified",
                "source_file": path.name, "source_file_sha256": asset_lookup[path.name]["sha256"],
                "source_manifest_sha256": manifest_hash,
                "timebase": "ordinal Image Id suffix only; no validated seconds", "confidence": "not supplied by source",
            }, separators=(",", ":")) + "\n")
            raw_groups += 1
            raw_players += sum(r["kind"] == "Player" for r in current_rows)
            invalid_xy_rows += sum(not r["coordinate_valid"] for r in current_rows)
            invalid_player_xy_rows += sum(r["kind"] == "Player" and not r["coordinate_valid"] for r in current_rows)

            # The target is the current frame. Cutoff state is exactly fifteen suffix increments earlier.
            if len(states) == 16 and states[0]["seq"] == seq - 15:
                cutoff = states[0]
                for key, hist in histories.items():
                    if len(hist) != 21 or (key in last_target and seq - last_target[key] < 15):
                        continue
                    target_player = current_players.get(key)
                    if target_player is None: continue
                    base = (target_player["team"], target_player["raw_id"])
                    if base not in conflicted and key in cutoff["players"]:
                        p0 = cutoff["players"][key]
                        f0 = np.asarray(p0["kin"], np.float32)
                        if index >= window_capacity: raise RuntimeError("more model windows than audit tried")
                        x0[index] = f0; x1[index] = m1_features(p0, cutoff)
                        pos[index] = [p0["x"], p0["y"]]
                        target[index] = [target_player["x"], target_player["y"]]
                        group[index] = gi; eligible[index] = True
                        cutoff_seq[index] = cutoff["seq"]; file_indices[index] = file_i
                    else:
                        # Count these as raw windows for exact comparison with the previous extractor.
                        if index >= window_capacity: raise RuntimeError("more model windows than audit tried")
                        group[index] = gi; cutoff_seq[index] = seq - 15; file_indices[index] = file_i
                    index += 1; last_target[key] = seq

            # Uniform deterministic reservoir from cutoffs satisfying only pre-cutoff gates.
            if (seq <= int(gate["end_frame"]) - HORIZON and len(states) >= INPUT and
                sum(v["team"] == "Home" for v in visible_valid.values()) >= 3 and
                sum(v["team"] == "Away" for v in visible_valid.values()) >= 3 and
                all(len(histories[k]) >= INPUT for k, v in visible_valid.items())):
                snap_players = [{"id": v["id"], "raw_id": v["raw_id"], "jersey": v["jersey"],
                                 "team": v["team"], "x": v["x"], "y": v["y"],
                                 "history": [[q[1], q[2]] for q in histories[k][-INPUT:]],
                                 "past_displacement": v["past_displacement"]}
                                for k, v in visible_valid.items()]
                snap = {"game": game, "period": period, "source_file": path.name,
                        "cutoff_seq": seq, "cutoff_image_id": current["image"],
                        "players": snap_players,
                        "puck": puck_xy, "puck_history": ([[st["puck"]["x"], st["puck"]["y"]]
                            for st in list(states)[-2:]] if len(states) >= 2 and
                            all(st["puck"] is not None for st in list(states)[-2:]) and
                            list(states)[-1]["seq"]-list(states)[-2]["seq"] == 1 else None),
                        "period_one_goalie_right_team": orientations.get(game) if period == "P1" else None,
                        "timebase": "ordinal Image Id suffix only", "future_observed": [], "categories": []}
                flags = categories(frame_state, orientations.get(game) if period == "P1" else None)
                snap["categories"] = sorted(flags)
                local_candidates += 1; candidate_counts[game] += 1
                bucket = reservoir[path.name]
                # Keep up to ten evenly randomized candidates; quota is allocated per period file later.
                if len(bucket) < 10:
                    bucket.append(snap)
                else:
                    j = rng_by_file[path.name].randrange(local_candidates)
                    if j < 10: bucket[j] = snap
                for category in flags:
                    if category not in category_examples:
                        category_examples[category] = snap

            # Future states are evaluator-only; keep them only for retained reservoir/category scenarios.
            active = {id(s): s for s in reservoir[path.name]}
            active.update({id(s): s for s in category_examples.values() if s["source_file"] == path.name})
            actual = {"seq": seq, "image_id": current["image"],
                      "players": {v["id"]: [v["x"], v["y"]] for v in current_players.values()
                                  if (v["team"], v["raw_id"]) not in conflicted},
                      "missing_xy_count": frame_state["missing_xy_count"],
                      "conflicted_present": frame_state["conflicted_present"],
                      "puck": puck_xy}
            for s in active.values():
                if s["cutoff_seq"] < seq <= s["cutoff_seq"] + HORIZON:
                    s["future_observed"].append(actual)
            current = None; current_rows = []; current_players = {}; current_puck = None

        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not REQ.issubset(reader.fieldnames or []): raise RuntimeError("schema changed during read")
            for row_no, row in enumerate(reader, 2):
                image = (row["Image Id"] or "").strip(); seq = frame_number(image)
                if current is None or image != current["image"]:
                    previous_seq = None if current is None else current["seq"]
                    if current is not None:
                        finish_frame(); file_groups += 1
                    if previous_seq is not None and seq <= previous_seq:
                        raise RuntimeError(f"Image Id order is not strictly increasing in {path.name}:{row_no}")
                    current = {"image": image, "seq": seq, "period": row["Period"], "clock": row["Game Clock"]}
                kind = (row["Player or Puck"] or "").strip()
                team = (row["Team"] or "").strip(); raw_id = (row["Player Id"] or "").strip()
                jersey = (row["Player Jersey Number"] or "").strip()
                if kind not in {"Player", "Puck"}:
                    raise RuntimeError(f"unexpected entity kind {kind!r} in {path.name}:{row_no}")
                if kind == "Player" and team not in {"Home", "Away"}:
                    raise RuntimeError(f"unexpected player team label {team!r} in {path.name}:{row_no}")
                track_id = f"{game}|{period}|{team}|{raw_id}" if raw_id else None
                try:
                    x = float(row["Rink Location X (Feet)"]); y = float(row["Rink Location Y (Feet)"])
                    valid = math.isfinite(x) and math.isfinite(y) and RINK_X[0] <= x <= RINK_X[1] and RINK_Y[0] <= y <= RINK_Y[1]
                except (TypeError, ValueError): x = y = None; valid = False
                identity_conflict = kind == "Player" and (team, raw_id) in conflicted
                rec = {"kind": kind, "team": team or None, "track_id": track_id,
                       "player_id_source": raw_id or None, "jersey": jersey or None,
                       "x": x if valid else None, "y": y if valid else None,
                       "coordinate_valid": bool(valid), "row_visible": True,
                       "identity_conflict": identity_conflict, "visibility_confidence": "unknown"}
                current_rows.append(rec)
                if kind == "Player" and raw_id and jersey:
                    key = f"{team}|{raw_id}|{jersey}"
                    if valid:
                        if key in current_players: raise RuntimeError(f"duplicate player observation {path.name}:{row_no}")
                        current_players[key] = {"id": track_id, "raw_id": raw_id, "team": team,
                                                "jersey": jersey, "x": x, "y": y}
                elif kind != "Player":
                    if current_puck is not None: raise RuntimeError(f"multiple puck rows {path.name}:{row_no}")
                    current_puck = {"x": x if valid else None, "y": y if valid else None,
                                    "coordinate_valid": bool(valid), "z": row.get("Rink Location Z (Feet)") or None}
        if current is not None:
            finish_frame(); file_groups += 1
        expected = int(gate["valid_windows"])
        observed = index - file_start
        # Window count includes conflicted IDs; a smoke run still reconciles its selected file.
        if observed != expected:
            raise RuntimeError(f"window count mismatch {path.name}: {observed} != {expected}")
        if len(reservoir[path.name]) == 0: print(f"no rollout starts in {path.name}", flush=True)
        file_meta.append({"file": path.name, "game": game, "period": period, "observation_groups": file_groups,
                          "raw_windows": observed, "eligible_windows": int(eligible[file_start:index].sum()),
                          "identity_conflicts": len(conflicted), "candidate_cutoffs_seen": local_candidates,
                          "reservoir_retained": len(reservoir[path.name])})
        print(f"normalized {file_i+1}/{len(files)} {path.name}: {file_groups:,} groups, {observed:,} windows", flush=True)

    if index != window_capacity: raise RuntimeError(f"full model window count mismatch {index} != {window_capacity}")
    if not args.limit_files:
        if raw_groups != int(audit["overall"]["frames"]): raise RuntimeError("normalized frame count differs from frozen full-population audit")
        if raw_players != int(audit["overall"]["player_rows"]): raise RuntimeError("normalized player-row count differs from audit")
        if invalid_xy_rows != int(audit["overall"]["missing_xy_rows"]): raise RuntimeError("missing coordinate count differs from audit")
        if conflicts_total != int(audit["overall"]["identity_conflicts"]): raise RuntimeError("identity conflict count mismatch")

    # Allocate twenty starts per game evenly across that game's eligible period files.
    starts = []
    for game in games:
        names = [m["file"] for m in file_meta if m["game"] == game and reservoir[m["file"]]]
        quotas = {name: 20 // len(names) for name in names} if names else {}
        for name in names[:20 % len(names)]: quotas[name] += 1
        selected = []
        for name in names:
            rows = sorted(reservoir[name], key=lambda s: s["cutoff_seq"])
            k = min(quotas[name], len(rows))
            if k:
                idxs = np.linspace(0, len(rows)-1, k).round().astype(int)
                selected.extend(rows[i] for i in idxs)
        # Reallocate any short period quota to other retained candidates in temporal order.
        if len(selected) < 20:
            selected_keys={(s["source_file"],s["cutoff_seq"]) for s in selected}
            remaining = [s for n in names for s in sorted(reservoir[n], key=lambda s: s["cutoff_seq"])
                         if (s["source_file"],s["cutoff_seq"]) not in selected_keys]
            selected.extend(remaining[:20-len(selected)])
        starts.extend(selected[:20])
    if not args.limit_files and any(sum(s["game"] == g for s in starts) != 20 for g in games):
        raise RuntimeError("could not select exactly twenty shared rollout starts per game")

    output_npz = args.output_dir / "training_windows.npz"
    np.savez_compressed(output_npz, x0=x0[:index], x1=x1[:index], position=pos[:index], target=target[:index],
                        group=group[:index], eligible=eligible[:index], cutoff_seq=cutoff_seq[:index],
                        file_index=file_indices[:index], games=np.asarray(games), files=np.asarray([p.name for p in files]),
                        step_displacement=disp[:nd], step_group=disp_g[:nd],
                        adjacent_displacement_change=delta[:na], change_group=delta_g[:na],
                        heading_change_radians=turn[:nt], turn_group=turn_g[:nt],
                        nearest_player_distance=nearest[:nn], nearest_group=near_g[:nn])
    scenarios_path = args.output_dir / "rollout_starts.json.gz"
    with gzip.open(scenarios_path, "wt", encoding="utf-8", compresslevel=5) as f:
        json.dump({"seed": SEED, "horizon_ordinal_steps": HORIZON, "starts": starts,
                   "category_examples": category_examples}, f, separators=(",", ":"))
    dist_summary = {}
    for label, values, ids, n in (("step_displacement", disp, disp_g, nd), ("adjacent_displacement_change", delta, delta_g, na),
                                  ("heading_change_radians", turn, turn_g, nt), ("nearest_player_distance", nearest, near_g, nn)):
        dist_summary[label] = {"count": n, "by_game": {games[i]: int(np.sum(ids[:n] == i)) for i in range(len(games))}}
    manifest_out = {"study": "NHL multi-agent movement data preparation", "protocol": "docs/research/NHL-MULTI-AGENT-MOVEMENT-PROTOCOL-2026-10-23.md",
        "source_release": {"url": manifest["release_url"], "tag": manifest["release_tag"], "asset_count": manifest["asset_count"],
                           "manifest_sha256": manifest_hash, "files_verified": len(files) if args.limit_files else len(manifest["files"])},
        "timebase": {"validated": False, "unit": "Image Id suffix increment", "subsecond_timestamp_field": False,
                     "cadence_fit": False, "reported_speeds_or_accelerations": "ordinal proxies only"},
        "quality_flags": {"event_coordinate_alignment": False, "cross_game_identity_verified": False,
                          "track_identity_conflicts_quarantined": True, "puck_z_continuous_flight_validated": False,
                          "personnel_completeness": "unknown", "interpolation": False},
        "counts": {"normalized_observation_groups": raw_groups, "normalized_player_rows": raw_players,
                   "rows_missing_or_invalid_xy": invalid_xy_rows,
                   "player_rows_missing_or_invalid_xy": invalid_player_xy_rows, "raw_windows": index,
                   "eligible_windows": int(eligible[:index].sum()), "excluded_conflicted_windows": int((~eligible[:index]).sum()),
                   "conflicted_track_period_ids": conflicts_total,
                   "rollout_starts": len(starts), "category_examples": {k: v["cutoff_image_id"] for k,v in category_examples.items()}},
        "window_distribution_samples": dist_summary, "files": file_meta,
        "artifacts": {p.name: {"path": str(p), "sha256": file_sha(p), "bytes": p.stat().st_size}
                      for p in (normalized_path, output_npz, scenarios_path)},
        "runtime_seconds": round(time.perf_counter()-started, 3)}
    (args.output_dir / "extraction_manifest.json").write_text(json.dumps(manifest_out, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"counts": manifest_out["counts"], "runtime_seconds": manifest_out["runtime_seconds"],
                      "output_dir": str(args.output_dir)}, indent=2), flush=True)


if __name__ == "__main__": main()
