#!/usr/bin/env python3
"""Run the pinned legacy engine and export exact per-seed records for parity."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from slc_model_registry import get_model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--records-out", type=Path, required=True)
    parser.add_argument("legacy_args", nargs=argparse.REMAINDER,
                        help="arguments passed to that version's simulate_pregame_batch")
    args = parser.parse_args(argv)
    if args.legacy_args and args.legacy_args[0] == "--":
        args.legacy_args = args.legacy_args[1:]
    if not args.legacy_args:
        parser.error("pass the legacy batch runner arguments")
    if args.records_out.exists():
        raise FileExistsError(f"immutable parity records exist: {args.records_out}")
    spec = get_model(args.model)
    root = args.engine_root.resolve()
    status = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], text=True
    )
    if status.strip():
        raise RuntimeError("DIRTY_MODEL_CODE: parity capture requires the clean pinned source tree")
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if commit != spec["code_commit"]:
        raise RuntimeError("MODEL_CODE_COMMIT_MISMATCH")
    sys.path[:0] = [str(root / "scripts" / "nfl_sequence"), str(root / "backend")]
    batch = importlib.import_module("simulate_pregame_batch")
    records = []
    original_game = batch.gs.play_game
    original_slc = batch.slc_engine.play

    def capture_slc(seed, *positional, **keywords):
        record, decisions = original_slc(seed, *positional, **keywords)
        records.append({"seed": seed, "record": record})
        return record, decisions

    # slc_engine.play delegates into game_state.play_game. Hooking both layers
    # records every SLC seed twice, which makes an otherwise valid comparison
    # fail on duplicate seed IDs.
    if spec.get("enabled_layers"):
        batch.slc_engine.play = capture_slc
    else:
        def capture_game(seed, *positional, **keywords):
            record = original_game(seed, *positional, **keywords)
            records.append({"seed": seed, "record": record})
            return record
        batch.gs.play_game = capture_game
    try:
        batch.main(args.legacy_args)
    finally:
        batch.gs.play_game = original_game
        batch.slc_engine.play = original_slc
    path = args.records_out.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"immutable parity records exist: {path}")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records))
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"wrote {len(records)} legacy records from {commit} to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
