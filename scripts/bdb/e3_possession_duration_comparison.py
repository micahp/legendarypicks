#!/usr/bin/env python3
"""Compare week-5 observed game-clock possession durations with fold-local E1 drives.

E1 is fitted from 2022 weeks 1-4 only. Week-5 observed drive starts provide
conditional initial states; generated terminal outcomes and durations are not
observed inputs. The script never reads weeks 6-9.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import sqlite3
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
E1_COMMIT = "2248f7e1f9710daa3092104526ab6003a0fc3b18"
E1_SHA256 = "b2a36750c6ed66d31297eaa317b9ab95367ae0a574d50f9ed06434a7f5ead95f"
E0_SHA256 = "b4ee37588b871f3406f61d35060d625d84634d2339fe5db2420f739a08fdcf02"
REDUCER_SHA256 = "ba423ce95c3062f87f379cf2b9d522afc2fff8cbce8fa8621245bfe6d4b0e32b"
WEEKS_TRAIN = (1, 2, 3, 4)
WEEK_TARGET = 5
DRAWS_PER_START = 5
DEFAULT_DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
DEFAULT_E1_ROOT = Path("/root/lp-nfl-sequence-e1")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_e1(e1_root: Path):
    root = e1_root.resolve()
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if commit != E1_COMMIT:
        raise RuntimeError(f"E1 source checkout must be pinned to {E1_COMMIT}; got {commit}")
    module_path = root / "scripts/nfl_sequence"
    for name, expected in (("e1_drive.py", E1_SHA256), ("e0_single_play.py", E0_SHA256), ("reducer.py", REDUCER_SHA256)):
        actual = sha256_file(module_path / name)
        if actual != expected:
            raise RuntimeError(f"pinned E1 source hash mismatch for {name}: {actual}")
    sys.path.insert(0, str(module_path))
    for name in ("e1_drive", "e0_single_play", "reducer"):
        sys.modules.pop(name, None)
    return importlib.import_module("e1_drive")


def load_rows(db_path: Path, e1) -> tuple[list[dict], str]:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        available = {row[1] for row in connection.execute("PRAGMA table_info(nfl_pbp)")}
        columns = tuple(e1.COLUMNS) + ("drive",) + (("safety",) if "safety" in available else ())
        missing = sorted(set(columns) - available)
        if missing:
            raise RuntimeError(f"nfl_pbp missing columns required for pinned E1 comparison: {missing}")
        query = (
            f"SELECT {', '.join(columns)} FROM nfl_pbp WHERE season=2022 AND week IN (1,2,3,4,5) "
            "ORDER BY game_id, play_id"
        )
        rows = [dict(row) for row in connection.execute(query)]
    finally:
        connection.close()
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return rows, hashlib.sha256(encoded).hexdigest()


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valid_start(row: dict) -> bool:
    try:
        return (
            row.get("posteam") is not None and row.get("defteam") is not None
            and 1 <= int(row["qtr"]) <= 4 and 0 <= float(row["game_seconds_remaining"]) <= 900
            and 1 <= int(row["down"]) <= 4 and 1 <= int(row["ydstogo"])
            and 1 <= int(row["yardline_100"]) <= 99
        )
    except (KeyError, TypeError, ValueError):
        return False


def _observed_terminal(row: dict, next_row: dict | None) -> str:
    if row.get("touchdown") == 1:
        return "touchdown"
    if row.get("safety") == 1:
        return "safety"
    if row.get("interception") == 1:
        return "interception"
    if row.get("fumble_lost") == 1:
        return "fumble_lost"
    if row.get("play_type") == "punt":
        return "punt"
    if row.get("play_type") == "field_goal":
        return "field_goal_attempt"
    if next_row and next_row.get("posteam") not in (None, row.get("posteam")):
        return "turnover_or_change"
    return "drive_end_other"


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * p
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] if lo == hi else values[lo] + (values[hi] - values[lo]) * (index - lo)


def _summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean_s": round(statistics.mean(values), 3) if values else None,
        "p10_s": round(_percentile(values, 0.1), 3) if values else None,
        "median_s": round(statistics.median(values), 3) if values else None,
        "p90_s": round(_percentile(values, 0.9), 3) if values else None,
    }


def _observed_drives(rows: list[dict], e1) -> tuple[list[dict], dict]:
    ordered_by_game: dict[str, list[dict]] = defaultdict(list)
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        if int(row["week"]) != WEEK_TARGET:
            continue
        ordered_by_game[str(row["game_id"])].append(row)
        if row.get("drive") is not None:
            grouped[(str(row["game_id"]), int(row["drive"]))].append(row)
    following = {}
    for game, plays in ordered_by_game.items():
        plays.sort(key=lambda r: int(r["play_id"]))
        for index, row in enumerate(plays):
            following[(game, int(row["play_id"]))] = plays[index + 1] if index + 1 < len(plays) else None

    output, reasons = [], Counter()
    for (game_id, drive_id), drive_rows in sorted(grouped.items()):
        drive_rows.sort(key=lambda r: int(r["play_id"]))
        scrimmage = [r for r in drive_rows if r.get("play_type") in e1.PLAY_TYPES]
        if not scrimmage:
            reasons["no_e1_vocabulary_play"] += 1
            continue
        start, terminal = scrimmage[0], scrimmage[-1]
        next_row = following.get((game_id, int(terminal["play_id"])))
        if not _valid_start(start):
            reasons["invalid_or_missing_initial_state"] += 1
            continue
        if next_row is None:
            reasons["no_next_pbp_row"] += 1
            continue
        if any(int(r["qtr"]) != int(start["qtr"]) for r in scrimmage) or int(next_row["qtr"]) != int(start["qtr"]):
            reasons["period_boundary_censored"] += 1
            continue
        begin_clock, end_clock = _number(start.get("game_seconds_remaining")), _number(next_row.get("game_seconds_remaining"))
        if begin_clock is None or end_clock is None or begin_clock < end_clock:
            reasons["clock_delta_unresolvable_or_negative"] += 1
            continue
        output.append({
            "game_id": game_id, "drive": drive_id, "start_play_id": int(start["play_id"]),
            "quarter": int(start["qtr"]), "observed_seconds": round(begin_clock - end_clock, 3),
            "observed_scrimmage_plays": len(scrimmage),
            "terminal_family": _observed_terminal(terminal, next_row),
            "start": {
                "quarter": int(start["qtr"]), "clock": int(begin_clock), "offense": start["posteam"],
                "defense": start["defteam"], "yl": int(start["yardline_100"]),
                "down": int(start["down"]), "togo": int(start["ydstogo"]), "dir": 1,
            },
        })
    return output, dict(reasons)


def build(rows: list[dict], source_sha: str, e1, e1_root: Path) -> dict:
    train_rows = [r for r in rows if int(r["week"]) in WEEKS_TRAIN]
    pool, excluded = e1.build_pool(train_rows)
    observed, exclusion_reasons = _observed_drives(rows, e1)
    eligible, skipped = [], Counter()
    for drive in observed:
        state = drive["start"]
        cell = (state["down"], e1.e0.ydstogo_bucket(state["togo"]), e1.e0.yardline_bucket(state["yl"]))
        size = len(pool.get(cell, []))
        if size < e1.MIN_POOL:
            skipped["training_cell_below_E1_min_pool"] += 1
            continue
        eligible.append({**drive, "training_cell": list(cell), "training_cell_rows": size})

    generated = []
    for drive in eligible:
        observations = []
        for draw in range(DRAWS_PER_START):
            token = f"possession-e1|{drive['game_id']}|{drive['drive']}|{draw}".encode()
            seed = int.from_bytes(hashlib.sha256(token).digest()[:8], "big") % (2**31 - 1)
            sim_id = f"e3-possession-{drive['game_id']}-{drive['drive']}-{draw}"
            plays, terminal = e1.simulate(drive["start"], seed, pool, sim_id)
            if plays is None:
                skipped["E1_simulation_incomplete"] += 1
                continue
            summary = e1.check_drive(plays, terminal)
            if summary["quarter_changes"] or summary["clock_clamped_plays"]:
                skipped["E1_period_crossing_or_clock_clamp"] += 1
                continue
            duration = float(summary["clock_runoff_total_seconds"])
            observations.append({
                "seed": seed, "duration_s": duration, "scrimmage_plays": summary["plays"],
                "terminal_family": terminal,
            })
        if observations:
            generated.extend({"drive": drive, **sample} for sample in observations)
            drive["generated_draws"] = observations
            drive["generated_expected_abs_error_s"] = round(
                statistics.mean(abs(sample["duration_s"] - drive["observed_seconds"]) for sample in observations), 3
            )

    paired_starts = [drive for drive in eligible if drive.get("generated_draws")]
    observed_values = [drive["observed_seconds"] for drive in paired_starts]
    generated_values = [sample["duration_s"] for drive in paired_starts for sample in drive["generated_draws"]]
    observed_plays = [drive["observed_scrimmage_plays"] for drive in paired_starts]
    generated_plays = [sample["scrimmage_plays"] for drive in paired_starts for sample in drive["generated_draws"]]
    per_observed_terminal = {}
    terminals = sorted({drive["terminal_family"] for drive in paired_starts})
    for terminal in terminals:
        observed_group = [drive["observed_seconds"] for drive in paired_starts if drive["terminal_family"] == terminal]
        generated_group = [sample["duration_s"] for drive in paired_starts if drive["terminal_family"] == terminal for sample in drive["generated_draws"]]
        per_observed_terminal[terminal] = {
            "observed_week5_drives": _summary(observed_group),
            "E1_generated_from_these_observed_start_conditions": _summary(generated_group),
        }
    generated_by_terminal = defaultdict(list)
    for sample in generated:
        generated_by_terminal[sample["terminal_family"]].append(sample["duration_s"])

    return {
        "schema": "lp.e3.possession_duration_comparison.v1",
        "source": {
            "PBP_input_slice_sha256": source_sha,
            "E1_repo": str(e1_root.resolve()), "E1_commit": E1_COMMIT,
            "E1_e1_drive_sha256": E1_SHA256, "E1_e0_single_play_sha256": E0_SHA256,
            "E1_reducer_sha256": REDUCER_SHA256,
        },
        "scope": {
            "season": 2022, "training_weeks": list(WEEKS_TRAIN), "target_week": WEEK_TARGET,
            "query_filter": "season=2022 AND week IN (1,2,3,4,5); E1 pool weeks 1-4 only",
            "holdout_status": "NOT HOLDOUT-VALIDATED: weeks 6-9 were already examined in prior E3 work; week 5 is development evidence only",
            "metric": "same-quarter game-clock delta from first scrimmage snap in a drive through the PBP row immediately after its final E1-vocabulary play; this is game-clock time, not wall-clock possession duration",
            "authored_conditioning": "Week-5 observed initial state; E1 field direction is authored dir=+1; no outcome from the target drive enters the generated sequence",
            "E1_draws_per_observed_start": DRAWS_PER_START,
        },
        "coverage": {
            "PBP_rows_weeks1to5": len(rows), "observed_week5_drives_resolved_same_quarter": len(observed),
            "observed_drives_with_E1_start_cell_support": len(eligible),
            "paired_observed_starts": len(paired_starts), "E1_generated_drive_draws": len(generated),
            "observed_drive_exclusions": exclusion_reasons,
            "observed_drives_below_E1_cell_support": skipped["training_cell_below_E1_min_pool"],
            "E1_simulation_attempted_draws": len(eligible) * DRAWS_PER_START,
            "E1_simulation_incomplete_draws": skipped["E1_simulation_incomplete"],
            "E1_simulation_period_crossing_or_clock_clamp_draws": skipped["E1_period_crossing_or_clock_clamp"],
            "training_pool_usable_plays": sum(len(v) for v in pool.values()),
            "training_pool_exclusions": dict(excluded),
        },
        "duration_seconds": {
            "observed_week5_paired_starts": _summary(observed_values),
            "E1_generated_week5_start_conditions": _summary(generated_values),
            "paired_start_expected_absolute_error": {
                "n_drives": len(paired_starts),
                "mae_s": round(statistics.mean(d["generated_expected_abs_error_s"] for d in paired_starts), 3) if paired_starts else None,
            },
        },
        "scrimmage_plays_per_drive": {
            "observed_week5_paired_starts": _summary([float(v) for v in observed_plays]),
            "E1_generated_week5_start_conditions": _summary([float(v) for v in generated_plays]),
        },
        "by_observed_terminal_family_duration_seconds": per_observed_terminal,
        "E1_generated_by_simulated_terminal_family_duration_seconds": {
            terminal: _summary(values) for terminal, values in sorted(generated_by_terminal.items())
        },
        "paired_drives": [
            {key: value for key, value in drive.items() if key != "start"}
            | {"generated_draws": drive.get("generated_draws", [])}
            for drive in paired_starts
        ],
        "limitations": [
            "The E1 baseline is an empirical drive generator, not an independently calibrated physical model.",
            "Week-5 starts are conditioned from observed PBP, while generated terminal outcomes and subsequent states are sampled from weeks 1-4.",
            "Game-clock delta omits wall-clock stoppage duration and cannot be interpreted as real elapsed possession time.",
            "Same-quarter censoring drops drives crossing quarter boundaries; E1 samples only five deterministic draws per observed start.",
            "Weeks 6-9 were already examined in prior E3 work, so none of this comparison is holdout-validated.",
            "The authored dir=+1 field orientation is a simulation convention, not an observed direction assignment.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--e1-root", type=Path, default=DEFAULT_E1_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        e1 = load_e1(args.e1_root)
        rows, source_sha = load_rows(args.db, e1)
        result = build(rows, source_sha, e1, args.e1_root)
    except (OSError, sqlite3.Error, subprocess.CalledProcessError, ValueError, RuntimeError, KeyError) as error:
        parser.error(str(error))
    result["source"]["comparison_script_sha256"] = sha256_file(Path(__file__))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Observed same-quarter week-5 drives={result['coverage']['observed_week5_drives_resolved_same_quarter']}; paired starts={result['coverage']['paired_observed_starts']}")
    print(f"E1 generated drives={result['coverage']['E1_generated_drive_draws']}; mean absolute duration error={result['duration_seconds']['paired_start_expected_absolute_error']['mae_s']} s")
    print(f"Observed median={result['duration_seconds']['observed_week5_paired_starts']['median_s']} s; E1 median={result['duration_seconds']['E1_generated_week5_start_conditions']['median_s']} s")
    print("Holdout status: NOT HOLDOUT-VALIDATED")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
