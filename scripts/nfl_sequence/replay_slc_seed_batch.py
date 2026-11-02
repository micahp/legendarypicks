#!/usr/bin/env python3
"""Replay selected seeds in one process so the pinned reference data is loaded once."""
from __future__ import annotations

import argparse
import builtins
import hashlib
import inspect
import json
import linecache
import sys
from pathlib import Path

from replay_slc_seed_set import load_seeds, preflight, sha256


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")


def replay_batch(source_root: Path, run_header_path: Path, seed_list_path: Path,
                 out_dir: Path, run_id: str = "slc-seed-replay") -> dict:
    source_root = source_root.resolve()
    header = preflight(source_root, run_header_path)
    seeds = load_seeds(seed_list_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = out_dir / "traces"
    trace_dir.mkdir(exist_ok=True)
    selection_dir = out_dir / "reproduction-selections"
    selection_dir.mkdir(exist_ok=True)
    for seed in seeds:
        (selection_dir / f"seed-{seed}.json").write_text(
            json.dumps({"seeds": [seed]}, indent=2) + "\n", encoding="utf-8")
    selection_path = out_dir / "seed-selection.json"
    selection_path.write_text(json.dumps({"seeds": seeds}, indent=2) + "\n", encoding="utf-8")

    scripts = source_root / "scripts" / "nfl_sequence"
    sys.path.insert(0, str(scripts))
    import simulate_pregame_batch as batch
    import simulate_pregame_game as game_cli

    source = game_cli.producer_source()
    profile_holder = {}
    original_manifest = batch.slc_config.build_manifest
    original_play = batch.slc_engine.play
    original_range = getattr(batch, "range", None)

    def capture_profile(*args, **kwargs):
        profile = original_manifest(*args, **kwargs)
        profile_holder["value"] = profile
        return profile

    def traced_play(seed, reference, snapshot, *args, **kwargs):
        record, decisions = original_play(seed, reference, snapshot, *args, **kwargs)
        if record.get("seed") != seed:
            raise RuntimeError(f"pinned simulator returned record seed {record.get('seed')!r} for requested seed {seed}")
        profile = profile_holder.get("value")
        schedule = snapshot.get("schedule") or {}
        artifact = json.loads(Path(header["playcall_artifact_path"]).read_text(encoding="utf-8"))
        trace = {
            "model_id": (profile or {}).get("model_id"),
            "source": source,
            "seed": seed,
            "game": {"game_id": schedule.get("game_id"), "season": schedule.get("season"),
                     "week": schedule.get("week"),
                     "side_teams": batch.slc_engine.side_teams(snapshot)},
            "snapshot": {"snapshot_sha256": snapshot.get("snapshot_sha256"),
                         "as_of": snapshot.get("as_of"),
                         "roster_snapshot_id": snapshot.get("roster_snapshot_id")},
            "slc_profile_manifest": profile,
            "playcall": {"artifact_sha256": artifact.get("sha256"),
                         "summary": batch.slc_engine.summary(decisions, record)},
            "result": record,
            "event_trace": decisions,
        }
        _write_json(trace_dir / f"seed-{seed}.json", trace)
        return record, decisions

    def selected_seed_range(start, stop=None, step=None):
        caller = inspect.currentframe().f_back
        source_line = linecache.getline(caller.f_code.co_filename, caller.f_lineno).strip()
        if source_line.startswith("for seed in range(args.seed_start"):
            if start != 0 or stop != len(seeds) or step is not None:
                raise RuntimeError("pinned batch seed loop bounds changed; refusing explicit-seed replay")
            selected_loop_calls[0] += 1
            if selected_loop_calls[0] != 1:
                raise RuntimeError("pinned batch seed loop was invoked more than once")
            return iter(seeds)
        if stop is None:
            return builtins.range(start) if step is None else builtins.range(start, step)
        return builtins.range(start, stop) if step is None else builtins.range(start, stop, step)

    batch.slc_config.build_manifest = capture_profile
    batch.slc_engine.play = traced_play
    selected_loop_calls = [0]
    batch.range = selected_seed_range
    batch_out = out_dir / "batch-result.json"
    arguments = [
        "--snapshot-file", header["snapshot_path"],
        "--db", header["database_path"],
        "--playcall-artifact", header["playcall_artifact_path"],
        "--playcall-streak-file", header["streak_file_path"],
        "--slc-profile", header["profile"],
        "--slc-fg-ordinary-cutoff", str(header["field_goal_ordinary_cutoff_yards"]),
        "--seed-start", "0", "--games", str(len(seeds)),
        "--export-boxscores", "--progress-every", "1", "--out", str(batch_out),
    ]
    for blocker in header["blocker_fixes"]:
        arguments.extend(("--slc-blocker-fix", blocker))
    try:
        batch.main(arguments)
    finally:
        batch.slc_config.build_manifest = original_manifest
        batch.slc_engine.play = original_play
        if original_range is None:
            del batch.range
        else:
            batch.range = original_range
    if not batch_out.is_file():
        raise RuntimeError("pinned batch runner returned without writing its result file")
    if selected_loop_calls[0] != 1:
        raise RuntimeError("pinned batch seed loop was not intercepted; refusing to accept replay outputs")
    result = json.loads(batch_out.read_text(encoding="utf-8"))

    boxscore_path = batch_out.with_suffix(".boxscores.jsonl")
    boxscores = {}
    with boxscore_path.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item.get("type") == "game":
                seed = int(item["seed"])
                boxscores[seed] = {key: value for key, value in item.items() if key != "type"}

    traces = {}
    for path in trace_dir.glob("seed-*.json"):
        trace = json.loads(path.read_text(encoding="utf-8"))
        seed = int(trace["seed"])
        if seed in boxscores:
            trace["replay_boxscore"] = boxscores[seed]
            _write_json(path, trace)
        traces[seed] = path

    # Preserve failed and blocked outcomes as explicit replay records with their batch error details.
    ledger_path = batch_out.with_suffix(".seeds.jsonl")
    with ledger_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if "seed" not in row:
                continue
            seed = int(row["seed"])
            if seed in traces:
                continue
            outcome = row.get("outcome") or {}
            error_trace = {"seed": seed, "source": source, "result": {},
                           "replay_error": outcome.get("error") or outcome.get("status"),
                           "replay_outcome": outcome}
            path = trace_dir / f"seed-{seed}.json"
            _write_json(path, error_trace)
            traces[seed] = path

    entries = []
    for seed in seeds:
        path = traces.get(seed)
        entries.append({"seed": seed, "trace": str(path) if path else None,
                        "trace_sha256": sha256(path) if path and path.exists() else None,
                        "boxscore_present": seed in boxscores})
    manifest = {
        "schema": "lp.nfl.slc-seed-replay-batch.v1", "run_id": run_id,
        "source_commit": header["source_commit"], "source_worktree_dirty": False,
        "source_input_hashes": header["actual_input_hashes"],
        "seed_selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "requested_seed_count": len(seeds), "trace_count": len(traces),
        "boxscore_count": len(boxscores), "configuration_hash": result.get("simulation", {}).get("configuration_hash"),
        "batch_result_sha256": sha256(batch_out), "seeds": entries,
    }
    _write_json(out_dir / "replay-batch-manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--run-header", type=Path, required=True)
    parser.add_argument("--seed-list", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = replay_batch(args.source_root, args.run_header, args.seed_list, args.out_dir)
    print(json.dumps({"requested": manifest["requested_seed_count"],
                      "traces": manifest["trace_count"], "boxscores": manifest["boxscore_count"],
                      "configuration_hash": manifest["configuration_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
