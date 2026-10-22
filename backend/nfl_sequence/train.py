"""Fit the nfl-seq v0.1 count tables from nflverse play-by-play. Offline; needs pyarrow.

Usage (from backend/, with an environment that has pyarrow):
  python -m nfl_sequence.train --source-dir <dir with play_by_play_YYYY.parquet> \
      --train-seasons 2010-2021 --out-dir <dir> [--min-n 200]

Writes one JSON model per variant and a manifest with the source SHA-256 digests, row counts and
every skip reason. The test seasons are never read here: the caller passes the training range.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from typing import Dict, List

from .model import CountBuilder, DEFAULT_MIN_N, MODEL_SCHEMA, VARIANT_LEVELS
from .nflverse import game_finals, iter_observations, read_season

VARIANTS = tuple(sorted(VARIANT_LEVELS))


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_seasons(text: str) -> List[int]:
    """'2010-2021' or '2010,2012' -> sorted list of seasons."""
    seasons: List[int] = []
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-")
            seasons.extend(range(int(low), int(high) + 1))
        else:
            seasons.append(int(part))
    return sorted(set(seasons))


def fit(source_dir: str, seasons: List[int], min_n: int, out_dir: str) -> Dict[str, object]:
    skips: Counter = Counter()
    builders = {variant: CountBuilder(variant, min_n) for variant in VARIANTS}
    source = {}
    observations = Counter()
    games = 0
    finals = {"games": 0, "home_mean": 0.0, "away_mean": 0.0, "home_wins": 0, "away_wins": 0, "ties": 0}
    for season in seasons:
        path = os.path.join(source_dir, "play_by_play_%d.parquet" % season)
        source["play_by_play_%d.parquet" % season] = _sha256(path)
        rows = read_season(path)
        games += len({row["game_id"] for row in rows})
        for game in game_finals(rows).values():
            finals["games"] += 1
            finals["home_mean"] += game["home"]
            finals["away_mean"] += game["away"]
            finals["home_wins"] += game["home"] > game["away"]
            finals["away_wins"] += game["away"] > game["home"]
            finals["ties"] += game["home"] == game["away"]
        for name, ctx, value in iter_observations(rows, skips):
            observations[name] += 1
            for builder in builders.values():
                builder.add(name, ctx, value)
        del rows

    finals["home_mean"] /= finals["games"]
    finals["away_mean"] /= finals["games"]
    manifest = {
        "schema": MODEL_SCHEMA,
        "finals": finals,
        "train_seasons": seasons,
        "source_sha256": source,
        "games": games,
        "observations": dict(sorted(observations.items())),
        "skips": dict(sorted(skips.items())),
        "min_n": min_n,
    }
    os.makedirs(out_dir, exist_ok=True)
    for variant, builder in builders.items():
        model = builder.build(manifest)
        model.save(os.path.join(out_dir, "nfl-seq-v0.1-%s.json" % variant))
    with open(os.path.join(out_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--train-seasons", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--min-n", type=int, default=DEFAULT_MIN_N)
    args = parser.parse_args()
    manifest = fit(args.source_dir, parse_seasons(args.train_seasons), args.min_n, args.out_dir)
    print(json.dumps({"games": manifest["games"], "observations": manifest["observations"], "skips": manifest["skips"]}, indent=2))


if __name__ == "__main__":
    main()
