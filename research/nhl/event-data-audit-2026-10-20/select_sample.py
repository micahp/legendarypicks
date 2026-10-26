#!/usr/bin/env python3
"""Select the stratified event-data audit sample.

The audit frame is the pinned 4,876-game official-outcome frame
(`official-outcome-backfill-2026-10-20/canonical_frame.csv`, SHA256
336d8a8d055febd742dbf31ce7a613bd2e47c2cd8fbc7a8d956fc8967ba47b1c).

Event evidence is fetched for a deterministic stratified sample rather than the
whole frame: field availability is a property of the source and is settled by a
sample, while a full-frame fetch is a 100-minute network job that is not needed
to answer "can we reconstruct the game". Every rate in the report is reported
with its per-season n, never as a frame-level fact.

Sampling: 60 games per start season, uniform without replacement, seed 20261021,
ordered by numeric game id so the sample is reproducible from this file alone.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = (HERE.parent / "official-outcome-backfill-2026-10-20" / "canonical_frame.csv")
OUT = HERE / "sample_games.csv"
SEED = 20261021
PER_SEASON = 60


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(SOURCE))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--per-season", type=int, default=PER_SEASON)
    args = ap.parse_args()

    src = Path(args.source)
    with src.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(f"frame: {len(rows)} games, sha256 {sha256_file(src)}")

    by_season: dict[int, list[dict]] = {}
    for r in rows:
        by_season.setdefault(int(r["season"]), []).append(r)

    rng = random.Random(SEED)
    picked: list[dict] = []
    for season in sorted(by_season):
        games = sorted(by_season[season], key=lambda r: int(r["game_id"]))
        take = min(args.per_season, len(games))
        chosen = rng.sample(games, take)
        for r in chosen:
            picked.append({
                "game_id": r["game_id"],
                "season": r["season"],
                "game_date": r["game_date"],
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "canonical_home_score": r["canonical_home_score"],
                "canonical_away_score": r["canonical_away_score"],
            })
        print(f"  season {season}: {take} of {len(games)} games")

    picked.sort(key=lambda r: int(r["game_id"]))
    out = Path(args.out)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(picked[0].keys()))
        w.writeheader()
        w.writerows(picked)
    print(f"sample: {len(picked)} games -> {out}")
    print(f"sample sha256: {sha256_file(out)}")


if __name__ == "__main__":
    main()
