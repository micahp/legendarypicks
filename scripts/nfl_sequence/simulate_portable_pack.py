#!/usr/bin/env python3
"""Execute an already-compiled SLC full-game reference without any source tables.

The pack contains the in-memory reference and frozen game overlay. This
command never constructs a model, queries SQLite, or loads CSV/parquet fixtures.
Run from the EXACT code checkout pinned by the pack and provide its external
SHA-256 lock. Produces JSON results and optional per-seed player box statistics.
"""
from __future__ import annotations

import argparse
import copy
from collections import defaultdict
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "backend"))

from portable_model_pack import load_pack, ModelPackError


def _forbid_source_table_reads():
    """Raise if any runtime code attempts to reconnect to historical model data."""
    def refused(*_args, **_kwargs):
        raise RuntimeError("PORTABLE_RUNTIME_SOURCE_TABLE_ACCESS")
    sqlite3.connect = refused


def _code_commit():
    return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()


def _run(seed, reference, snapshot, gs, slc_engine=None):
    if slc_engine is not None and slc_engine.is_slc(reference):
        record, _decisions = slc_engine.play(seed, reference, copy.deepcopy(snapshot))
    else:
        record = gs.play_game(seed, reference, pregame_snapshot=copy.deepcopy(snapshot))
    gs.validate_game(record)
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--pack-sha256", required=True, help="independent pack hash from trusted build manifest")
    ap.add_argument("--games", type=int, required=True)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-player-lines", action="store_true",
                    help="retain player box stats for each seed in output")
    args = ap.parse_args(argv)
    if args.games < 1 or args.seed_start < 0:
        ap.error("games must be positive and seed-start nonnegative")
    commit = _code_commit()
    # Loading validates the externally pinned entire pack BEFORE unpickling.
    reference, snapshot, manifest, _config = load_pack(
        args.pack, expected_sha256=args.pack_sha256, expected_code_commit=commit)
    _forbid_source_table_reads()
    gs = importlib.import_module("game_state")
    try:
        slc_engine = importlib.import_module("slc_engine")
    except ModuleNotFoundError as e:
        if e.name != "slc_engine":
            raise
        slc_engine = None
    aggregation = importlib.import_module("pregame_batch")
    rows = []
    details = []
    for seed in range(args.seed_start, args.seed_start + args.games):
        try:
            record = _run(seed, reference, snapshot, gs, slc_engine)
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
            row = {
                "seed": seed, "status": "simulation_error", "blocker": None,
                "valid_full_game": False, "complete_game": False,
                "regulation_end_reached": False, "tied_at_regulation_end": False,
                "home_points": None, "away_points": None, "score_scope": "none",
                "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            }
        rows.append(row)
    summary = aggregation.summarize_outcomes(rows, args.games)
    payload = {
        "schema": "lp-slc-portable-simulation-1",
        "pack": {"sha256": args.pack_sha256, "model_id": manifest["model_id"],
                 "source_commit": manifest["model_code_commit"],
                 "reference_sha256": manifest["reference_sha256"],
                 "snapshot_sha256": manifest["snapshot_sha256"]},
        "game_id": manifest["game_id"], "as_of_utc": manifest["as_of_utc"],
        "simulation": {"requested_games": args.games, "valid_full_games": summary["valid_full_games"],
                       "seed_start": args.seed_start, "seed_end_inclusive": args.seed_start + args.games - 1},
        "summary": summary,
    }
    if args.with_player_lines:
        payload["player_boxscores_by_seed"] = details
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"immutable output exists: {output}")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {output}: {summary['valid_full_games']}/{args.games} complete valid games")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
