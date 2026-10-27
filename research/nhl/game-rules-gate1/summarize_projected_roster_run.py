#!/usr/bin/env python3
"""Re-audit a frozen Gate 1 run and emit compact projected-roster diagnostics.

The validator is rerun from each saved immutable simulation record. Historical
target lineups are not loaded, and raw game records remain outside Git.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validator  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _position_group(position: str) -> str:
    if position in {"C", "L", "R", "LW", "RW", "F"}:
        return "F"
    return position


def summarize(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    games_path = run_dir / "games.jsonl"
    if not summary_path.is_file() or not games_path.is_file():
        raise FileNotFoundError(f"expected summary.json and games.jsonl under {run_dir}")
    source_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    status_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    game_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    target_lineup_flags: collections.Counter[str] = collections.Counter()
    official_lineup_statuses: collections.Counter[str] = collections.Counter()
    shootout_games = shootout_attempts = shooters_outside_projected_roster = 0
    projected_roster_sizes: collections.Counter[str] = collections.Counter()
    structural_valid = full_rule_assessed = generation_errors = 0
    stored_audit_mismatches = 0

    with games_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            row = json.loads(line)
            game = row.get("simulation_record")
            if not isinstance(game, dict):
                generation_errors += 1
                continue
            game_id, seed = str(row.get("game_id")), int(row.get("seed", game.get("seed", -1)))
            key = (game_id, seed)
            if key in seen:
                raise ValueError(f"duplicate game/seed at line {line_number}: {key}")
            seen.add(key)
            if int(game.get("seed", -2)) != seed:
                raise ValueError(f"saved row seed disagrees with record at line {line_number}")
            audit = validator.audit_game(game, ruleset=source_summary.get("ruleset"))
            stored = row.get("independent_audit")
            if not isinstance(stored, dict) or stored.get("input_sha256") != audit.get("input_sha256") \
                    or stored.get("checks") != audit.get("checks"):
                stored_audit_mismatches += 1
            for check in audit["checks"]:
                status_counts[check["code"]][check["status"]] += 1
            structural_valid += int(audit["structural_valid"])
            full_rule_assessed += int(audit["full_rule_assessed"])

            snapshot = game.get("pregame_snapshot") or {}
            projection = snapshot.get("projected_game_roster") or {}
            target_lineup_flags[str(projection.get("actual_target_game_lineup_used"))] += 1
            official = next((check["status"] for check in audit["checks"]
                             if check["code"] == "game_lineup_eligibility"), "MISSING")
            official_lineup_statuses[official] += 1
            by_side = projection.get("players_by_side") or {}
            selected_ids: dict[str, set[str]] = {side: set() for side in ("home", "away")}
            for side in ("home", "away"):
                players = by_side.get(side) or []
                projected_roster_sizes[str(len(players))] += 1
                selected_ids[side] = {str(player["player_id"]) for player in players}
            is_shootout = game.get("summary", {}).get("shootout_winner") is not None
            shootout_games += int(is_shootout)
            if is_shootout:
                for event in game.get("events", []):
                    if event.get("event_type") != "shootout-attempt":
                        continue
                    shootout_attempts += 1
                    side = event.get("team_side")
                    shooter = str((event.get("participants") or {}).get("shooter_id") or "")
                    if side not in selected_ids or shooter not in selected_ids[side]:
                        shooters_outside_projected_roster += 1
            game_rows.append({"game_id": game_id, "game_date": row.get("game_date"),
                              "target_index": row.get("target_index"), "seed": seed,
                              "simulation_id": game.get("simulation_id"),
                              "record_hash": hashlib.sha256(json.dumps(
                                  game, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False).encode("utf-8")).hexdigest(),
                              "shootout": is_shootout})

    generated = int(source_summary.get("generated_games", -1))
    expected_errors = int(source_summary.get("generation_errors", -1))
    if len(game_rows) != generated or generation_errors != expected_errors:
        raise ValueError("saved JSONL record/error counts do not reconcile to runner summary")
    generated_status_counts = {code: dict(sorted(counts.items()))
                               for code, counts in sorted(status_counts.items())}
    if generated_status_counts != source_summary.get("check_status_counts"):
        raise ValueError("independently recomputed validator status counts disagree with runner summary")
    if stored_audit_mismatches:
        raise ValueError(f"{stored_audit_mismatches} stored audits differ from fresh independent validation")
    if shooters_outside_projected_roster:
        raise ValueError(f"{shooters_outside_projected_roster} shootout shooters are outside the projected roster")
    if target_lineup_flags != collections.Counter({"False": generated}):
        raise ValueError(f"pregame target-lineup exclusion flags are not all false: {target_lineup_flags}")

    return {
        "report_kind": "projected_game_roster_gate1_reaudit",
        "run_kind": source_summary.get("report_kind"),
        "branch_base": source_summary.get("branch_base"),
        "ruleset": source_summary.get("ruleset"),
        "run_directory": str(run_dir),
        "source_artifact_sha256": {
            "runner_summary": sha256_file(summary_path),
            "saved_game_records": sha256_file(games_path),
        },
        "generated_games": generated,
        "generation_errors": generation_errors,
        "fresh_independent_audit_mismatches": stored_audit_mismatches,
        "structural_valid_games": structural_valid,
        "full_rule_assessed_games": full_rule_assessed,
        "check_status_counts": generated_status_counts,
        "shootout_games": shootout_games,
        "shootout_attempts": shootout_attempts,
        "shooters_outside_projected_roster": shooters_outside_projected_roster,
        "projected_team_roster_size_counts": dict(sorted(projected_roster_sizes.items(),
                                                          key=lambda item: int(item[0]))),
        "target_game_lineup_used_flags": dict(sorted(target_lineup_flags.items())),
        "official_target_lineup_check_statuses": dict(sorted(official_lineup_statuses.items())),
        "runtime_seconds": {
            "fit": source_summary.get("fit_seconds"),
            "generation_wall": source_summary.get("generation_wall_seconds"),
            "per_game_median": source_summary.get("game_runtime_median_seconds"),
        },
        "sampled_games_and_seeds": game_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path,
                        help="JSON destination; defaults to <run_dir>/projected-roster-audit.json")
    args = parser.parse_args()
    result = summarize(args.run_dir)
    output = args.output or args.run_dir / "projected-roster-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output),
                      "generated_games": result["generated_games"],
                      "shootout_games": result["shootout_games"],
                      "structural_valid_games": result["structural_valid_games"],
                      "sha256": sha256_file(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
