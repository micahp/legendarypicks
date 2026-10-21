#!/usr/bin/env python3
"""Create separately pinned PBP and shift game lists from full_frame_games.csv."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

EXPECTED_FRAME_SHA256 = "f417a1272b2bb4adff5757dae398dd1000dd2284f43b6ccb7dd28eaae99edf2b"
EXPECTED_FULL_FRAME_GAMES_SHA256 = "ef02d94ff0ff5e494b8cdcb7eeca2f3e466e1fac1d30682c3e25cf4065ae55a8"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temp.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    import io
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=Path, default=here / "full_frame_games.csv")
    parser.add_argument("--games-summary", type=Path, default=here / "full_frame_games.summary.json")
    parser.add_argument("--pbp-out", type=Path, required=True)
    parser.add_argument("--shift-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args()

    source_hash = sha256_file(args.games)
    source_summary = json.loads(args.games_summary.read_text(encoding="utf-8"))
    expected_hash = source_summary.get("games_file_sha256")
    if (not source_summary.get("frame_sha256_matches_pin")
            or source_summary.get("frame_sha256") != EXPECTED_FRAME_SHA256):
        raise SystemExit(
            f"CANONICAL_FRAME_HASH_MISMATCH expected={EXPECTED_FRAME_SHA256} "
            f"summary={source_summary.get('frame_sha256')}"
        )
    if source_hash != expected_hash or source_hash != EXPECTED_FULL_FRAME_GAMES_SHA256:
        raise SystemExit(f"FULL_FRAME_GAME_LIST_HASH_MISMATCH expected={expected_hash} actual={source_hash}")
    with args.games.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    ids = [row.get("game_id", "") for row in rows]
    if len(rows) != 4876 or len(set(ids)) != 4876:
        raise SystemExit(f"FULL_FRAME_GAME_LIST_POPULATION_MISMATCH rows={len(rows)} unique={len(set(ids))}")
    invalid_ids = [game_id for game_id in ids if len(game_id) != 10 or not game_id.isdigit()]
    if invalid_ids:
        raise SystemExit(f"FULL_FRAME_GAME_ID_INVALID {invalid_ids[:5]}")
    seasons = Counter(int(row["season"]) for row in rows)
    if dict(seasons) != {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 343}:
        raise SystemExit(f"FULL_FRAME_SEASON_POPULATION_MISMATCH {dict(sorted(seasons.items()))}")

    source_ids = [{"game_id": game_id} for game_id in ids]
    data = csv_bytes(source_ids, ["game_id"])
    atomic_bytes(args.pbp_out, data)
    atomic_bytes(args.shift_out, data)
    summary = {
        "games": len(rows),
        "games_by_start_season": {str(year): seasons[year] for year in sorted(seasons)},
        "canonical_frame_sha256": source_summary["frame_sha256"],
        "full_frame_games_sha256": source_hash,
        "pbp_games_file": str(args.pbp_out.resolve()),
        "pbp_games_sha256": sha256_file(args.pbp_out),
        "shift_games_file": str(args.shift_out.resolve()),
        "shift_games_sha256": sha256_file(args.shift_out),
    }
    atomic_bytes(args.summary_out, (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
