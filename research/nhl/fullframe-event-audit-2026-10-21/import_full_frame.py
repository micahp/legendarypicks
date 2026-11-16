#!/usr/bin/env python3
"""Run the pinned frame through separate, resumable PBP and shift imports.

The two source lists, manifests, reports, raw store, and reuse caches are all
explicit CLI arguments. Requests run serially; either source stops on refusal or
failure and can be resumed by rerunning this command.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from fetch_full_frame_evidence import load_game_ids, run_import


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbp-games", type=Path, required=True)
    parser.add_argument("--shift-games", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--pbp-manifest", type=Path, required=True)
    parser.add_argument("--shift-manifest", type=Path, required=True)
    parser.add_argument("--pbp-report", type=Path, required=True)
    parser.add_argument("--shift-report", type=Path, required=True)
    parser.add_argument("--pbp-reuse-raw-dir", type=Path, action="append", default=[])
    parser.add_argument("--shift-reuse-raw-dir", type=Path, action="append", default=[])
    parser.add_argument("--pause", type=float, default=0.9)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--flush-every", type=int, default=10)
    parser.add_argument("--resume-after-refusal", action="store_true",
                        help="resume only after access has been restored and a prior refusal is cleared")
    args = parser.parse_args()

    pbp_ids = load_game_ids(args.pbp_games)
    shift_ids = load_game_ids(args.shift_games)
    if pbp_ids != shift_ids:
        raise SystemExit("PBP_SHIFT_GAME_LIST_MISMATCH; source lists must be the same pinned frame")

    for kind, games, manifest, report, reuse in (
        ("pbp", args.pbp_games, args.pbp_manifest, args.pbp_report, args.pbp_reuse_raw_dir),
        ("shifts", args.shift_games, args.shift_manifest, args.shift_report, args.shift_reuse_raw_dir),
    ):
        result = run_import(
            kind=kind, games_file=games, raw_dir=args.raw_dir,
            manifest=manifest, report_out=report, reuse_dirs=reuse,
            pause=args.pause, retries=args.retries, flush_every=args.flush_every,
            resume_after_refusal=args.resume_after_refusal,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["stop_reason"] != "complete" or result["failed_requests"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
