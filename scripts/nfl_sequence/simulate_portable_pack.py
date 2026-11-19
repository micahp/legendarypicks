#!/usr/bin/env python3
"""Execute an SLC code-and-reference package without source tables.

The pack contains the in-memory reference and exact executable source. Supply a
fresh hash-pinned pregame snapshot; this command never constructs a model,
queries SQLite, or loads research fixtures. Produces JSON results and optional
per-seed game records for exact parity comparison.
"""
from __future__ import annotations

import argparse
import builtins
import copy
import io
from collections import defaultdict
import importlib
import json
import os
from pathlib import Path
import sqlite3
import socket
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from portable_model_pack import load_pack, ModelPackError
from slc_model_registry import get_model


def _forbid_source_table_reads():
    """Block DB connections AND external model fixture/table file opens."""
    def refused(*_args, **_kwargs):
        raise RuntimeError("PORTABLE_RUNTIME_SOURCE_TABLE_ACCESS")
    sqlite3.connect = refused
    socket.create_connection = refused
    socket.socket.connect = refused

    original_builtin_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open

    def forbidden_path(file):
        if not isinstance(file, (str, bytes, Path)):
            return False
        name = os.fsdecode(file).replace("\\", "/").lower()
        suffix = Path(name).suffix
        return (suffix in {".db", ".sqlite", ".sqlite3", ".csv", ".parquet"}
                or "/docs/fixtures/" in name or "/docs/research/" in name)

    def guard(original):
        def checked(file, mode="r", *args, **kwargs):
            # The compiled pack is always allowed. Source/training material is not.
            if "r" in str(mode) and forbidden_path(file):
                raise RuntimeError("PORTABLE_RUNTIME_SOURCE_FILE_ACCESS: " + os.fsdecode(file))
            return original(file, mode, *args, **kwargs)
        return checked

    def checked_os_open(file, flags, *args, **kwargs):
        if forbidden_path(file) and flags & (os.O_RDONLY | os.O_RDWR):
            raise RuntimeError("PORTABLE_RUNTIME_SOURCE_FILE_ACCESS: " + os.fsdecode(file))
        return original_os_open(file, flags, *args, **kwargs)

    builtins.open = guard(original_builtin_open)
    io.open = guard(original_io_open)
    os.open = checked_os_open


def _run_seed(seed, reference, snapshot, gs, slc_engine=None):
    if slc_engine is not None and slc_engine.is_slc(reference):
        record, _decisions = slc_engine.play(seed, reference, copy.deepcopy(snapshot))
    else:
        record = gs.play_game(seed, reference, pregame_snapshot=copy.deepcopy(snapshot))
    gs.validate_game(record)
    return record


def _run(args, engine_dir):
    model = get_model(args.model)
    if not model["build_supported"]:
        raise ModelPackError("MODEL_PACKAGE_NOT_ENABLED: " + args.model)
    engine_root = Path(engine_dir)
    reference, snapshot, manifest, _config = load_pack(
        args.pack, expected_sha256=args.pack_sha256,
        expected_code_commit=model["code_commit"], engine_dir=engine_root)
    if manifest["model_id"] != args.model:
        raise ModelPackError("MODEL_ID_MISMATCH")
    snapshot_loader = importlib.import_module("pregame_snapshot")
    runtime_snapshot = snapshot_loader.load_frozen_snapshot(args.snapshot)
    runtime_schedule = runtime_snapshot["schedule"]
    if runtime_schedule["game_id"] != args.game:
        raise ModelPackError("RUNTIME_SNAPSHOT_GAME_ID_MISMATCH")
    cutoff = manifest.get("training_cutoff") or {}
    eligible_before = cutoff.get("eligible_before") or []
    if len(eligible_before) != 2 or int(runtime_schedule["season"]) != int(eligible_before[0]):
        raise ModelPackError("RUNTIME_SNAPSHOT_TRAINING_SEASON_MISMATCH")
    snapshot = runtime_snapshot
    # The model implementation is imported only from the extracted package tree.
    gs = importlib.import_module("game_state")
    try:
        slc_engine = importlib.import_module("slc_engine")
    except ModuleNotFoundError as e:
        if e.name != "slc_engine":
            raise
        slc_engine = None
    if slc_engine is not None and slc_engine.is_slc(reference):
        reference.contextual_sampler.side_teams = slc_engine.side_teams(snapshot)
    aggregation = importlib.import_module("pregame_batch")
    rows = []
    details = []
    records = []
    for seed in range(args.seed_start, args.seed_start + args.games):
        record = None
        record_error = None
        try:
            record = _run_seed(seed, reference, snapshot, gs, slc_engine)
            status = record.get("status", "unknown")
            blocker = record.get("blocker")
            valid = bool(record.get("valid_full_game") and record.get("complete_game"))
            reached_reg = bool(record.get("regulation_end_reached"))
            tied_reg = bool(blocker == "overtime_not_modelled" and reached_reg)
            row = {
                "seed": seed, "status": status, "blocker": blocker,
                "valid_full_game": valid, "complete_game": bool(record.get("complete_game")),
                "regulation_end_reached": reached_reg, "tied_at_regulation_end": tied_reg,
                "home_points": record["points"]["A"], "away_points": record["points"]["B"],
                "score_scope": "valid_final" if valid else "regulation_end_only" if reached_reg else "partial"
            }
            if args.with_player_lines:
                details.append({"seed": seed, "players": (record.get("stats") or {}).get("player", [])})
        except Exception as exc:
            # Table-access attempts are packaging defects, not per-seed model failures.
            if "PORTABLE_RUNTIME_SOURCE_" in str(exc):
                raise
            record_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            row = {
                "seed": seed, "status": "simulation_error", "blocker": None,
                "valid_full_game": False, "complete_game": False,
                "regulation_end_reached": False, "tied_at_regulation_end": False,
                "home_points": None, "away_points": None, "score_scope": "none",
                "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            }
        rows.append(row)
        if args.records_out:
            records.append({"seed": seed, "record": record, "error": record_error})
    summary = aggregation.summarize_outcomes(rows, args.games)
    payload = {
        "schema": "lp-slc-portable-simulation-1",
        "pack": {"sha256": args.pack_sha256, "model_id": manifest["model_id"],
                 "source_commit": manifest["model_code_commit"],
                 "reference_sha256": manifest["reference_sha256"],
                 "build_game_id": manifest["game_id"],
                 "build_snapshot_sha256": manifest["snapshot_sha256"]},
        "game_id": args.game, "as_of_utc": snapshot["as_of"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "simulation": {"requested_games": args.games, "valid_full_games": summary["valid_full_games"],
                       "seed_start": args.seed_start, "seed_end_inclusive": args.seed_start + args.games - 1},
        "summary": summary,
    }
    if args.with_player_lines:
        payload["player_boxscores_by_seed"] = details
    if args.records_out:
        records_path = Path(args.records_out)
        records_path.parent.mkdir(parents=True, exist_ok=True)
        if records_path.exists():
            raise FileExistsError(f"immutable records file exists: {records_path}")
        records_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records))
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"immutable output exists: {output}")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {output}: {summary['valid_full_games']}/{args.games} complete valid games")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="registered model ID")
    ap.add_argument("--game", required=True, help="game ID for this simulation")
    ap.add_argument("--snapshot", type=Path, required=True,
                    help="hash-pinned pregame roster/injury snapshot for this matchup")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--pack-sha256", required=True, help="independent pack hash from trusted build manifest")
    ap.add_argument("--games", type=int, required=True)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-player-lines", action="store_true",
                    help="retain player box stats for each seed in output")
    ap.add_argument("--records-out", type=Path,
                    help="write each full per-seed game record as JSONL for exact parity checks")
    args = ap.parse_args(argv)
    if args.games < 1 or args.seed_start < 0:
        ap.error("games must be positive and seed-start nonnegative")
    # Fail if imports or any seed execution tries to reach source data.
    _forbid_source_table_reads()
    with tempfile.TemporaryDirectory(prefix="slc-model-runtime-") as temporary:
        return _run(args, temporary)


if __name__ == "__main__":
    raise SystemExit(main())
