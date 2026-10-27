#!/usr/bin/env python3
"""Forward-only B2 whole-game sample for the independent NHL Gate 1 audit.

Full game records are written outside Git. Native validation exceptions are
captured so the independent validator can audit the returned record and
preserve its seed.
"""

from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SIM_DIR = ROOT / "research/nhl/statistical-full-game-v0.2b"
DATA_DIR = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21")
OUTPUT_DIR = Path("/root/lp-data/nhl-game-rules-gate1-2026-10-26")
MEMORY_FLOOR_BYTES = int(1.5 * 1024**3)
ELIGIBLE_2021_TARGETS = 1292
SAMPLE_POSITIONS_6 = (0, 258, 516, 775, 1033, 1291)
SEED_BASE = 202610260001
SEED_GAME_STRIDE = 100
SEED_DRAW_STRIDE = 1


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _available_ram() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("cannot read MemAvailable from /proc/meminfo")


def _json_sha(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _write_jsonl(handle, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _selected_indices(target_count: int, requested: int) -> list[int]:
    if requested < 1 or requested > len(SAMPLE_POSITIONS_6):
        raise ValueError(f"games must be between 1 and {len(SAMPLE_POSITIONS_6)}")
    if target_count != ELIGIBLE_2021_TARGETS:
        raise ValueError(f"eligible target population changed: {target_count}")
    if requested == 1:
        return [SAMPLE_POSITIONS_6[0]]
    return list(SAMPLE_POSITIONS_6[:requested])


def _run_one(sim: Any, corpus: Any, inputs: Any, shift_manifest: Any,
             quality_model: Any, transition_model: Any, seed: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    native_errors: list[dict[str, Any]] = []
    native_validate = sim.validate_generated_game

    def capture_native_error(game: dict[str, Any]) -> None:
        try:
            native_validate(game)
        except Exception as exc:  # retain the failed seed and returned game for an independent audit
            native_errors.append({"exception_type": type(exc).__name__, "message": str(exc)})

    sim.validate_generated_game = capture_native_error
    try:
        game = sim.generate_game(corpus, inputs, seed, shift_manifest,
                                 quality_model, transition_model)
    finally:
        sim.validate_generated_game = native_validate
    return game, native_errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=6,
                        help="number of fixed, evenly spaced 2021 matchups (1-6)")
    parser.add_argument("--draws", type=int, default=20,
                        help="deterministic B2 seeds per selected matchup")
    parser.add_argument("--smoke", action="store_true",
                        help="one matchup/seed twice to verify reproducibility; no full sample")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if args.draws < 1 or (args.smoke and args.games != 6):
        parser.error("draws must be positive; --smoke uses the canonical six-game target map")
    if _available_ram() < MEMORY_FLOOR_BYTES:
        raise RuntimeError("available RAM is below the 1.5 GiB diagnostic floor")

    started = time.monotonic()
    sys.path.insert(0, str(SIM_DIR))
    sim = _load("nhl_gate1_sim", SIM_DIR / "nhl_game_state_sim.py")
    adapter = _load("nhl_gate1_historical_adapter", SIM_DIR / "historical_adapter.py")
    validator = _load("nhl_gate1_independent_validator", HERE / "validator.py")

    years = tuple(sim.v01.TRAIN_SEASONS) + tuple(sim.v01.DEVELOPMENT_SEASONS)
    corpus = sim.v01.load_corpus(sim.v01.DEFAULT_DATA_ROOT, years)
    boxscore_manifest = adapter.load_boxscore_manifest(sim.v01)
    targets = sorted((game for game in corpus.games.values()
                      if game.start_season == 2021 and sim.v01._eligible_game(game)),
                     key=lambda game: (boxscore_manifest[str(game.game_id)]["game_date"],
                                       str(game.game_id)))
    indices = _selected_indices(len(targets), args.games)
    selected = {str(targets[index].game_id): index for index in indices}

    training = copy.copy(corpus)
    training.games = {key: game for key, game in corpus.games.items()
                      if game.start_season in sim.v01.TRAIN_SEASONS
                      and sim.v01._eligible_game(game)}
    shift_manifest = sim.load_shift_manifest()
    quality_model = sim.fit_shot_quality(training)
    transition_model = sim.fit_event_transition_model(training)
    fit_seconds = time.monotonic() - started
    history = adapter.ForwardOnlyHistory()
    history_days = adapter.eligible_history_days(corpus, boxscore_manifest, years)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    games_path = args.output_dir / ("smoke-games.jsonl" if args.smoke else "games.jsonl")
    failures_path = args.output_dir / ("smoke-failures.jsonl" if args.smoke else "failures.jsonl")
    summary_name = "smoke-summary.json" if args.smoke else "summary.json"
    if games_path.exists() or failures_path.exists() or (args.output_dir / summary_name).exists():
        raise FileExistsError(f"diagnostic outputs already exist under {args.output_dir}; choose a new directory")
    audits: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    generated_count = 0
    generation_errors = 0
    runtimes: list[float] = []
    native_error_counts: collections.Counter[str] = collections.Counter()

    with games_path.open("w", encoding="utf-8") as games_handle, \
            failures_path.open("w", encoding="utf-8") as failures_handle:
        for game_date, day_games in history_days.items():
            selected_today: list[tuple[Any, dict[str, Any], int, Any | None, str | None]] = []
            for game in day_games:
                game_id = str(game.game_id)
                if game_id not in selected:
                    continue
                row = boxscore_manifest[game_id]
                index = selected[game_id]
                try:
                    inputs = history.make_inputs(sim=sim, game_key=game_id, game_date=game_date,
                        home=str(row["canonical_home_team"]), away=str(row["canonical_away_team"]))
                    if inputs.snapshot.get("actual_target_game_stats_or_lineups_used") is not False:
                        raise ValueError("snapshot does not affirm target-game outcomes/lineups excluded")
                    latest = inputs.snapshot.get("latest_history_date")
                    if latest is None or latest >= game_date:
                        raise ValueError(f"forward-only history cutoff failed: latest={latest} target={game_date}")
                    selected_today.append((game, row, index, inputs, None))
                except Exception as exc:
                    selected_today.append((game, row, index, None,
                        f"{type(exc).__name__}: {exc}"))

            # All selected matchups for this date are prepared before any same-day
            # source result is added to forward-only history.
            for game, row, index, inputs, input_error in selected_today:
                game_id = str(game.game_id)
                game_seeds = [SEED_BASE + index * SEED_GAME_STRIDE + draw * SEED_DRAW_STRIDE
                              for draw in range(args.draws)]
                if args.smoke:
                    game_seeds = [SEED_BASE + index * SEED_GAME_STRIDE]
                if inputs is None:
                    diagnostic = {"game_id": game_id, "game_date": game_date,
                        "target_index": index, "input_error": input_error,
                        "game_seeds": game_seeds, "simulation_record": None,
                        "independent_audit": None, "native_validation": "NOT_RUN"}
                    _write_jsonl(games_handle, diagnostic)
                    failure = {"game_id": game_id, "game_date": game_date,
                        "target_index": index, "seed": None, "stage": "pregame_inputs",
                        "error": input_error}
                    _write_jsonl(failures_handle, failure)
                    failure_rows.append(failure)
                    generation_errors += 1
                    continue

                for draw, seed in enumerate(game_seeds):
                    available = _available_ram()
                    if available < MEMORY_FLOOR_BYTES:
                        raise RuntimeError(f"available RAM fell below 1.5 GiB before seed {seed}")
                    game_started = time.monotonic()
                    try:
                        game_record, native_errors = _run_one(sim, training, inputs,
                            shift_manifest, quality_model, transition_model, seed)
                        audit = validator.audit_game(game_record, ruleset="2021-22")
                        native_error_counts.update(error["exception_type"] for error in native_errors)
                        native_result = "PASS" if not native_errors else "FAIL"
                        diagnostic = {"game_id": game_id, "game_date": game_date,
                            "target_index": index, "draw_index": draw, "seed": seed,
                            "pregame_snapshot_sha256": _json_sha(inputs.snapshot),
                            "native_validation": native_result,
                            "native_errors": native_errors,
                            "independent_audit": audit,
                            "simulation_record": game_record}
                        _write_jsonl(games_handle, diagnostic)
                        audits.append(audit)
                        generated_count += 1
                        if native_errors or not audit["structural_valid"]:
                            failed_checks = [{"code": check["code"], "status": check["status"],
                                "findings": check["findings"]}
                                for check in audit["checks"]
                                if check["status"] in {"FAIL", "QUARANTINED"}
                                or (check["code"] in validator.STRUCTURAL_CHECKS
                                    and check["status"] == "NOT_ASSESSED")]
                            failure = {"game_id": game_id, "game_date": game_date,
                                "target_index": index, "draw_index": draw, "seed": seed,
                                "native_errors": native_errors, "independent_failures": failed_checks}
                            _write_jsonl(failures_handle, failure)
                            failure_rows.append(failure)
                    except Exception as exc:
                        error = {"game_id": game_id, "game_date": game_date,
                            "target_index": index, "draw_index": draw, "seed": seed,
                            "stage": "generation", "exception_type": type(exc).__name__,
                            "message": str(exc)}
                        _write_jsonl(failures_handle, error)
                        failure_rows.append(error)
                        generation_errors += 1
                    runtimes.append(time.monotonic() - game_started)
                    print(json.dumps({"game_id": game_id, "seed": seed,
                        "generated": generated_count, "generation_errors": generation_errors,
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                        "available_ram_gib": round(_available_ram() / 1024**3, 2)},
                        sort_keys=True), flush=True)

                    if args.smoke and draw == 0 and inputs is not None:
                        # Repeat exactly the same immutable pregame input and seed.
                        repeat, repeat_native = _run_one(sim, training, inputs,
                            shift_manifest, quality_model, transition_model, seed)
                        repeat_sha = _json_sha(repeat)
                        original_sha = _json_sha(game_record)
                        reproducible = repeat_sha == original_sha
                        smoke = {"game_id": game_id, "seed": seed,
                            "first_record_sha256": original_sha,
                            "repeat_record_sha256": repeat_sha,
                            "byte_identical_after_canonical_json": reproducible,
                            "first_native_errors": native_errors,
                            "repeat_native_errors": repeat_native}
                        (args.output_dir / "fixed-seed-reproducibility.json").write_text(
                            json.dumps(smoke, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                        if not reproducible:
                            raise RuntimeError(f"fixed-seed game output changed for seed {seed}")
                if args.smoke:
                    break

            # Update history only after all selected target forecasts for this
            # calendar date have been generated from the prior-date snapshot.
            for game in day_games:
                row = boxscore_manifest[str(game.game_id)]
                boxscore = adapter.read_verified_boxscore(game, row, sim.v01.DEFAULT_BOXSCORE_ROOT)
                history.add_game(game, row, boxscore)
            if args.smoke and selected_today:
                break

    check_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    finding_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for audit in audits:
        for check in audit["checks"]:
            check_counts[check["code"]][check["status"]] += 1
            if check["status"] in {"FAIL", "QUARANTINED"}:
                finding_counts[check["code"]][check["status"]] += len(check["findings"])
    ruleset_hash = validator.RULEBOOKS["2021-22"]["sha256"]
    metadata = {
        "report_kind": "independent_gate1_diagnostic_sample",
        "branch_base": "a23d08b54bf1bb1939a4842d0e6c9f94acd785ec",
        "ruleset": "2021-22", "rulebook_sha256": ruleset_hash,
        "training_start_seasons": list(sim.v01.TRAIN_SEASONS),
        "development_target_season": 2021,
        "eligible_2021_target_games": len(targets),
        "canonical_six_target_indices": list(SAMPLE_POSITIONS_6),
        "selected_target_indices": indices[:1] if args.smoke else indices,
        "selected_target_games": [{"target_index": index,
            "game_id": str(targets[index].game_id),
            "game_date": boxscore_manifest[str(targets[index].game_id)]["game_date"]}
            for index in (indices[:1] if args.smoke else indices)],
        "draws_requested_per_game": args.draws,
        "seed_mapping": "202610260001 + target_index * 100 + draw_index",
        "smoke_reproducibility_mode": args.smoke,
        "database_used": False,
        "target_date_outcomes_used_before_generation": False,
        "same_day_results_excluded_until_all_selected_targets_generated": True,
        "input_sources": {
            "pbp_manifest_sha256": sim.v01.EXPECTED_MANIFEST_SHA256,
            "boxscore_manifest_sha256": sim.v01.EXPECTED_BOXSCORE_MANIFEST_SHA256,
            "shift_manifest_sha256": sim.SHIFT_MANIFEST_SHA256,
        },
        "code_sha256": {
            "simulator": sim.sha256_file(SIM_DIR / "nhl_game_state_sim.py"),
            "game_state": sim.sha256_file(SIM_DIR / "game_state.py"),
            "historical_adapter": sim.sha256_file(SIM_DIR / "historical_adapter.py"),
            "independent_validator": sim.sha256_file(HERE / "validator.py"),
            "runner": sim.sha256_file(Path(__file__).resolve()),
        },
        "fit_seconds": round(fit_seconds, 3),
        "generation_wall_seconds": round(sum(runtimes), 3),
        "game_runtime_median_seconds": round(sorted(runtimes)[len(runtimes)//2], 3) if runtimes else None,
        "generated_games": generated_count,
        "generation_errors": generation_errors,
        "independent_structural_valid_games": sum(audit["structural_valid"] for audit in audits),
        "independent_full_rule_assessed_games": sum(audit["full_rule_assessed"] for audit in audits),
        "native_validation_error_types": dict(sorted(native_error_counts.items())),
        "check_status_counts": {code: dict(sorted(counts.items()))
                                 for code, counts in sorted(check_counts.items())},
        "failed_finding_counts": {code: dict(sorted(counts.items()))
                                  for code, counts in sorted(finding_counts.items())},
        "preserved_failure_count": len(failure_rows),
        "preserved_failure_examples": [
            {"game_id": row.get("game_id"), "seed": row.get("seed"),
             "stage": row.get("stage"),
             "native_error_types": [error.get("exception_type") for error in row.get("native_errors", [])],
             "independent_failures": [
                 {"code": check.get("code"), "status": check.get("status"),
                  "finding_count": len(check.get("findings", [])),
                  "event_sequences": sorted({finding.get("event_sequence")
                      for finding in check.get("findings", [])
                      if finding.get("event_sequence") is not None}),
                  "first_message": (check.get("findings") or [{}])[0].get("message")}
                 for check in row.get("independent_failures", [])]}
            for row in failure_rows[:50]],
    }
    metadata["games_jsonl_sha256"] = sim.sha256_file(games_path)
    metadata["failures_jsonl_sha256"] = sim.sha256_file(failures_path)
    metadata["available_ram_at_completion_bytes"] = _available_ram()
    metadata["total_wall_seconds"] = round(time.monotonic() - started, 3)
    summary_path = args.output_dir / summary_name
    summary_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    print(json.dumps({"summary_path": str(summary_path),
        "generated_games": generated_count, "generation_errors": generation_errors,
        "structural_valid_games": metadata["independent_structural_valid_games"],
        "preserved_failure_count": len(failure_rows),
        "summary_sha256": sim.sha256_file(summary_path)}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
