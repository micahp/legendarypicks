#!/usr/bin/env python3
"""Replay a selected seed list using a clean, hash-pinned SLC source checkout."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_seeds(path: Path) -> list[int]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        value = json.loads(raw)
        if isinstance(value, dict):
            value = value.get("seeds", value.get("candidates", []))
        seeds = [int(row["seed"] if isinstance(row, dict) else row) for row in value]
    else:
        seeds = [int(line.strip()) for line in raw.splitlines() if line.strip()]
    if len(seeds) != len(set(seeds)):
        raise ValueError("seed list contains duplicate IDs")
    return sorted(seeds)


def preflight(source_root: Path, header_path: Path) -> dict:
    header = json.loads(header_path.read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=source_root, text=True).strip()
    if commit != header["source_commit"]:
        raise RuntimeError(f"source commit mismatch: expected {header['source_commit']}, found {commit}")
    if dirty:
        raise RuntimeError("pinned source checkout is dirty; refusing replay")
    pinned = {
        "database_path": header["database_path"],
        "snapshot_path": header["snapshot_path"],
        "playcall_artifact_path": header["playcall_artifact_path"],
        "streak_file_path": header["streak_file_path"],
    }
    expected = {
        "database_path": header["database_sha256"],
        "snapshot_path": header["snapshot_sha256"],
        "playcall_artifact_path": header["playcall_artifact_sha256"],
        "streak_file_path": header["streak_file_sha256"],
    }
    actual = {}
    for label, raw_path in pinned.items():
        path = Path(raw_path)
        actual[label] = sha256(path)
        if actual[label] != expected[label]:
            raise RuntimeError(f"pinned input hash mismatch for {label}: {actual[label]}")
    header["actual_input_hashes"] = actual
    return header


def replay_one(seed: int, *, source_root: Path, header: dict, out_dir: Path) -> dict:
    scripts = source_root / "scripts" / "nfl_sequence"
    trace_path = out_dir / f"seed-{seed}.json"
    command = [
        sys.executable, str(scripts / "run_slc_game.py"),
        "--artifact", header["playcall_artifact_path"],
        "--slc-profile", header["profile"],
        "--snapshot-file", header["snapshot_path"],
        "--streak-file", header["streak_file_path"],
    ]
    for blocker in header["blocker_fixes"]:
        command.extend(("--slc-blocker-fix", blocker))
    command.extend((
        "--slc-fg-ordinary-cutoff", str(header["field_goal_ordinary_cutoff_yards"]),
        "--db", header["database_path"], "--seed", str(seed), "--out", str(trace_path),
    ))
    completed = subprocess.run(command, cwd=source_root, capture_output=True, text=True)
    if completed.returncode != 0:
        return {"seed": seed, "ok": False, "returncode": completed.returncode,
                "stderr": completed.stderr[-2000:], "command": command}

    sys.path.insert(0, str(scripts))
    import simulate_pregame_batch
    import slc_outputs

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    record = trace.get("result") or {}
    outcome = simulate_pregame_batch._record_outcome(seed, record)
    try:
        boxscore = slc_outputs.build_boxscore(
            seed, outcome, record, record.get("pregame_snapshot") or {},
            trace.get("slc_profile_manifest") or {},
        )
        trace["replay_boxscore"] = boxscore
        trace_path.write_text(json.dumps(trace, indent=1, sort_keys=True, default=str) + "\n",
                              encoding="utf-8")
        return {"seed": seed, "ok": True, "trace": str(trace_path),
                "stdout": completed.stdout[-1000:]}
    except Exception as exc:  # keep all candidate failures auditable
        return {"seed": seed, "ok": False, "trace": str(trace_path),
                "boxscore_error": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--run-header", type=Path, required=True)
    parser.add_argument("--seed-list", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args(argv)
    source_root = args.source_root.resolve()
    header = preflight(source_root, args.run_header)
    seeds = load_seeds(args.seed_list)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(replay_one, seed, source_root=source_root,
                               header=header, out_dir=args.out_dir) for seed in seeds]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({key: result.get(key) for key in ("seed", "ok", "returncode", "boxscore_error")},
                             sort_keys=True), flush=True)
    results.sort(key=lambda row: row["seed"])
    manifest = {
        "schema": "lp.nfl.slc-seed-replay-batch.v1",
        "run_id": header.get("run_id"), "source_commit": header["source_commit"],
        "source_worktree_dirty": False, "input_hashes": header["actual_input_hashes"],
        "requested_seed_count": len(seeds), "successful_seed_count": sum(row["ok"] for row in results),
        "results": results,
    }
    (args.out_dir / "replay-batch-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if manifest["successful_seed_count"] == len(seeds) else 1


if __name__ == "__main__":
    raise SystemExit(main())
