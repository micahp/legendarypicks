"""Validate, combine, and summarize the additional 25 hook-captured games."""
import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "docs/research/madden64-statistical-study"
RESULTS = DATA / "additional-25-run-results.json"
PLAN = DATA / "additional-25-run-plan.json"
OUTPUT = DATA / "additional-25-data"
FULL_CSV = OUTPUT / "additional-25-full-data.csv"
GAME_CSV = OUTPUT / "additional-25-game-stats.csv"
SUMMARY_JSON = DATA / "additional-25-statistics.json"
CHECKSUMS = DATA / "additional-25-SHA256SUMS.txt"

COUNTERS = {
    0: "total_offense_candidate",
    1: "passing_yards_candidate",
    2: "rushing_yards_candidate",
    3: "turnovers_candidate",
    4: "third_down_attempts_candidate",
    5: "third_down_conversions_candidate",
    6: "fourth_down_attempts_candidate",
    7: "fourth_down_conversions_candidate",
    10: "total_yards_candidate",
    11: "possession_seconds_candidate",
    12: "first_downs_candidate",
    57: "score_candidate",
}
RAW_COLUMNS_V1 = ["frame", "quarter", "clock", "down", "distance", "yard", "team",
                  "kind", "index", "value", "rng", "player_row", "drive_team_candidate"]
RAW_COLUMNS_V2 = ["frame", "period", "period_type", "mode_state", "clock", "down",
                  "distance", "yard", "team", "kind", "index", "value", "rng",
                  "player_row", "drive_team_candidate", "game_id", "chunk_id",
                  "hook_seq", "hook_id"]
SIGNED_DISPLAY_COUNTERS = {0, 1, 2, 10}


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames == RAW_COLUMNS_V2:
            return list(reader)
        if reader.fieldnames != RAW_COLUMNS_V1:
            raise SystemExit(f"Unexpected schema in {path}: {reader.fieldnames}")
        normalized = []
        for row in reader:
            kind = row["kind"]
            # V1 wrote mode_state into `quarter` on hook rows, while state and
            # counter samples used the actual period. Do not reinterpret a
            # hook row's mode byte as regulation/overtime.
            period = row["quarter"] if kind in ("state", "total") else ""
            p = int(period) if period not in (None, "") else None
            period_type = ({1: "regulation", 2: "regulation", 3: "regulation", 4: "regulation",
                            5: "overtime", 6: "game_end_state", 7: "pre_game_state"}.get(p, "unknown"))
            normalized.append({
                "frame": row["frame"], "period": period, "period_type": period_type,
                "mode_state": row["quarter"] if kind in ("event", "staged") else "",
                "clock": row["clock"], "down": row["down"], "distance": row["distance"],
                "yard": row["yard"], "team": row["team"], "kind": kind,
                "index": row["index"], "value": row["value"], "rng": row["rng"],
                "player_row": row["player_row"],
                "drive_team_candidate": row["drive_team_candidate"],
                "game_id": "", "chunk_id": "", "hook_seq": "", "hook_id": "",
            })
        return normalized


def main():
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    if results.get("status") != "complete" or results.get("games_completed") != 25:
        raise SystemExit("Run results do not confirm all 25 games completed")
    games = results.get("games", [])
    if len(games) != 25 or len({game["game_id"] for game in games}) != 25:
        raise SystemExit("Expected 25 unique completed games")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    all_rows = []
    game_rows = []
    by_quarter = defaultdict(list)
    kinds = Counter()
    hook_total = Counter()
    candidate_frames = 0
    ambiguous_frames = 0

    for game in games:
        game_id = game["game_id"]
        quarter = int(game["quarter_s"])
        manifest_path = Path(game["manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (not manifest.get("completed") or manifest.get("pending") is not None
                or not manifest["fingerprint"].get("capture_hooks")):
            raise SystemExit(f"Incomplete or hook-disabled manifest: {manifest_path}")
        if len(manifest["chunks"]) != game["chunks"]:
            raise SystemExit(f"Chunk count mismatch for {game_id}")
        for chunk in manifest["chunks"]:
            for field, hash_field in (("csv", "csv_sha256"), ("state", "state_sha256")):
                file_path = Path(chunk[field])
                if digest(file_path) != chunk[hash_field]:
                    raise SystemExit(f"Chunk hash mismatch: {file_path}")

        csv_path = DATA / game["merged_csv"]
        if digest(csv_path) != game["merged_csv_sha256"]:
            raise SystemExit(f"Merged CSV hash mismatch: {csv_path}")
        rows = read_csv(csv_path)
        for raw in rows:
            if raw["game_id"] not in ("", game_id):
                raise SystemExit(f"Recorder game ID mismatch in {csv_path}: {raw['game_id']}")
            if raw["hook_id"]:
                expected = f"{game_id}:{raw['chunk_id']}:{raw['hook_seq']}"
                if raw["hook_id"] != expected:
                    raise SystemExit(f"Malformed hook invocation ID in {csv_path}: {raw['hook_id']}")
        entered_overtime = any(raw["period"] == "5" for raw in rows)
        count = Counter(row["kind"] for row in rows)
        for key in ("event", "staged", "total", "state"):
            kinds[key] += count[key]
        if count["event"] != game["event_rows"] or count["staged"] != game["staged_rows"]:
            raise SystemExit(f"Hook row counts differ for {game_id}")

        summary_path = DATA / game["summary_json"]
        run_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if run_summary.get("status") != "candidate_end_unvalidated":
            raise SystemExit(f"Unexpected candidate-summary status for {game_id}")
        teams = run_summary["teams"]
        final_scores = {team: int(teams[str(team)]["57"]) for team in (0, 1)}
        plays_path = DATA / game["candidate_plays_json"]
        plays_summary = json.loads(plays_path.read_text(encoding="utf-8"))
        plays = plays_summary["plays"]
        ambiguous = sum(bool(play["ambiguous"]) for play in plays)
        candidate_frames += len(plays)
        ambiguous_frames += ambiguous
        if ambiguous:
            raise SystemExit(f"Unexpected ambiguous candidate frame in {game_id}")

        row = {
            "game_id": game_id,
            "quarter_minutes": quarter,
            "candidate_rng_word": game["seed"],
            "batch": game["batch"],
            "completed_chunks": game["chunks"],
            "hook_hits": game["hook_hits"],
            "event_rows": count["event"],
            "staged_rows": count["staged"],
            "total_counter_rows": count["total"],
            "state_transition_rows": count["state"],
            "candidate_end_frame": run_summary["end_frame"],
            "entered_overtime_candidate": entered_overtime,
            "candidate_play_frames": len(plays),
            "ambiguous_candidate_frames": ambiguous,
            "team0_score_candidate": final_scores[0],
            "team1_score_candidate": final_scores[1],
        }
        for team in (0, 1):
            for index, name in COUNTERS.items():
                raw_value = int(teams[str(team)][str(index)])
                display_value = (raw_value - 65536
                                 if index in SIGNED_DISPLAY_COUNTERS and raw_value >= 32768
                                 else raw_value)
                row[f"team{team}_{name}"] = display_value
                row[f"team{team}_{name}_raw_u16"] = raw_value
        game_rows.append(row)
        by_quarter[quarter].append(row)

        for raw in rows:
            all_rows.append({**raw, "game_id": game_id, "quarter_minutes": quarter})

    full_columns = ["game_id", "quarter_minutes", *[c for c in RAW_COLUMNS_V2 if c != "game_id"]]
    with FULL_CSV.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=full_columns)
        writer.writeheader()
        writer.writerows(all_rows)

    game_columns = list(game_rows[0])
    with GAME_CSV.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=game_columns)
        writer.writeheader()
        writer.writerows(game_rows)

    grouped = {}
    for quarter, rows in sorted(by_quarter.items()):
        outcomes = Counter()
        for row in rows:
            s0, s1 = row["team0_score_candidate"], row["team1_score_candidate"]
            outcomes["team0_wins" if s0 > s1 else "team1_wins" if s1 > s0 else "ties"] += 1
        metric_summary = {}
        for team in (0, 1):
            for index, name in COUNTERS.items():
                values = [row[f"team{team}_{name}"] for row in rows]
                metric_summary[f"team{team}_{name}"] = {
                    "sum": sum(values),
                    "mean_per_game": round(statistics.mean(values), 3),
                    "median_per_game": statistics.median(values),
                    "min_per_game": min(values),
                    "max_per_game": max(values),
                }
        combined_points = [r["team0_score_candidate"] + r["team1_score_candidate"] for r in rows]
        grouped[str(quarter)] = {
            "games": len(rows),
            "games_entering_overtime_candidate": sum(bool(r["entered_overtime_candidate"]) for r in rows),
            "outcomes_by_team_index": dict(outcomes),
            "combined_points_per_game": {
                "mean": round(statistics.mean(combined_points), 3),
                "median": statistics.median(combined_points),
                "min": min(combined_points), "max": max(combined_points),
            },
            "candidate_counters": metric_summary,
            "hook_rows": {
                "hook_hits": sum(r["hook_hits"] for r in rows),
                "event_rows": sum(r["event_rows"] for r in rows),
                "staged_rows": sum(r["staged_rows"] for r in rows),
                "candidate_play_frames": sum(r["candidate_play_frames"] for r in rows),
            },
        }

    summary = {
        "status": "complete_descriptive_pilot",
        "completed_utc": results["completed_utc"],
        "games": len(game_rows),
        "games_by_quarter_minutes": {str(q): len(rows) for q, rows in sorted(by_quarter.items())},
        "batch_sizes": [len(batch) for batch in results["batches"]],
        "capture": {
            "hook_address": "0x80025b10",
            "hook_time_screenshots": False,
            "hook_hits": sum(r["hook_hits"] for r in game_rows),
            "event_rows": kinds["event"],
            "staged_rows": kinds["staged"],
            "team_counter_rows": kinds["total"],
            "state_transition_rows": kinds["state"],
            "candidate_play_frames": candidate_frames,
            "ambiguous_candidate_frames": ambiguous_frames,
            "merged_raw_rows": len(all_rows),
        },
        "groups": grouped,
        "provenance": {
            "run_results": RESULTS.name,
            "run_plan": PLAN.name,
            "full_data_csv": str(FULL_CSV.relative_to(DATA)),
            "full_data_csv_sha256": digest(FULL_CSV),
            "game_stats_csv": str(GAME_CSV.relative_to(DATA)),
            "game_stats_csv_sha256": digest(GAME_CSV),
            "checksum_manifest": CHECKSUMS.name,
        },
        "signed_counter_interpretation": {
            "indices": sorted(SIGNED_DISPLAY_COUNTERS),
            "rule": "For selected yardage counters, convert raw u16 values >=32768 to signed s16 by subtracting 65536; both interpreted and raw values are written to game-stats CSV, while full-data CSV preserves raw capture rows.",
            "basis": "The matched roster_stat_process accessor returns s16 after reading u16 team counters; applying the signed display interpretation to all runs is a source-based inference, not a per-game screen verification.",
        },
        "limitations": [
            "Summary counters and candidate play labels are provisional; candidate end transitions were not screen-checked game by game.",
            "RNG words are unique candidate seeds, but independent full-game outcomes have not been established.",
            "All games use the same Seattle-at-Green-Bay CPU-controlled exhibition and start states; results do not estimate general NFL or Madden realism.",
            "The hook captures one routine's event staging and frame-sampled counters; unclassified, no-play, and some direct-update events may be absent.",
        ],
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan["status"] = "complete"
    plan["completed_utc"] = results["completed_utc"]
    plan["results_file"] = RESULTS.name
    PLAN.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    checksummed = [RESULTS, PLAN, SUMMARY_JSON, FULL_CSV, GAME_CSV]
    for game in games:
        checksummed.extend(DATA / game[field] for field in
                           ("merged_csv", "summary_json", "candidate_plays_json"))
    lines = [f"{digest(path)}  {path.relative_to(DATA).as_posix()}"
             for path in sorted(checksummed, key=lambda path: path.relative_to(DATA).as_posix())]
    CHECKSUMS.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "games": len(game_rows),
        "games_by_quarter_minutes": summary["games_by_quarter_minutes"],
        "capture": summary["capture"],
        "outputs": [str(FULL_CSV), str(GAME_CSV), str(SUMMARY_JSON), str(CHECKSUMS)],
    }, indent=2))


if __name__ == "__main__":
    main()
