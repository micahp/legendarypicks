#!/usr/bin/env python3
"""Freeze the full-frame event-audit game list from the pinned canonical frame.

Input  : ../official-outcome-backfill-2026-10-20/canonical_frame.csv (4,876 rows)
Output : full_frame_games.csv (game_id, season, game_date, home, away, expected
         scores, in_sample, source), plus full_frame_games.summary.json

The 300-game stratified sample stays a separate file and is never rewritten.
The full frame is a different instrument: every statement derived from it is a
statement about all 4,876 regular-season games in the frame, season by season.

Usage:
    python select_full_frame.py [--frame PATH] [--sample PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FRAME = HERE.parent / "official-outcome-backfill-2026-10-20" / "canonical_frame.csv"
DEFAULT_SAMPLE = HERE.parent / "event-data-audit-2026-10-20" / "sample_games.csv"
EXPECTED_FRAME_SHA256 = "f417a1272b2bb4adff5757dae398dd1000dd2284f43b6ccb7dd28eaae99edf2b"
EXPECTED_FRAME_GAMES = 4876
EXPECTED_SEASON_COUNTS = {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 343}

FIELDS = ["game_id", "season", "game_date", "home_team", "away_team",
          "expected_home_score", "expected_away_score", "in_sample", "frame_source"]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frame(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"empty frame: {path}")
    return rows


def load_sample_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["game_id"] for r in csv.DictReader(handle)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=Path, default=DEFAULT_FRAME)
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    ap.add_argument("--out", type=Path, default=HERE / "full_frame_games.csv")
    ap.add_argument("--allow-unpinned-frame", action="store_true",
                    help="proceed even if the frame hash differs from the pin "
                         "(records the actual hash; never silently)")
    args = ap.parse_args()

    frame_sha = file_sha256(args.frame)
    if frame_sha != EXPECTED_FRAME_SHA256 and not args.allow_unpinned_frame:
        raise SystemExit(
            f"canonical frame hash {frame_sha} != pinned {EXPECTED_FRAME_SHA256}; "
            "refusing to derive a game list from an unpinned frame"
        )
    frame = load_frame(args.frame)
    sample_ids = load_sample_ids(args.sample)

    game_ids = [r["game_id"] for r in frame]
    if len(game_ids) != len(set(game_ids)):
        raise SystemExit("canonical frame has duplicate game_id rows")
    if len(frame) != EXPECTED_FRAME_GAMES:
        raise SystemExit(f"frame has {len(frame)} rows, expected {EXPECTED_FRAME_GAMES}")
    counts = Counter(int(r["season"]) for r in frame)
    if dict(counts) != EXPECTED_SEASON_COUNTS:
        raise SystemExit(f"season counts {dict(counts)} != pinned {EXPECTED_SEASON_COUNTS}")

    out_rows = [{
        "game_id": r["game_id"],
        "season": r["season"],
        "game_date": r["game_date"],
        "home_team": r["home_team"],
        "away_team": r["away_team"],
        "expected_home_score": r["canonical_home_score"],
        "expected_away_score": r["canonical_away_score"],
        "in_sample": "1" if r["game_id"] in sample_ids else "0",
        "frame_source": args.frame.name,
    } for r in frame]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)

    by_season = Counter(int(r["season"]) for r in out_rows)
    summary = {
        "frame_source": str(args.frame),
        "frame_sha256": frame_sha,
        "frame_sha256_matches_pin": frame_sha == EXPECTED_FRAME_SHA256,
        "games": len(out_rows),
        "games_by_season": {str(k): by_season[k] for k in sorted(by_season)},
        "sample_games_in_frame": sum(1 for r in out_rows if r["in_sample"] == "1"),
        "sample_games_file": str(args.sample),
        "games_file": args.out.name,
        "games_file_sha256": file_sha256(args.out),
        "season_definition": "season = start year of the NHL season label (2018 = 2018-19)",
    }
    summary_path = args.out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
