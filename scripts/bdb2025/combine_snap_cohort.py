#!/usr/bin/env python3
"""Combine one-week snap cohort builds after resource-throttled scans."""

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = Path("/root/nfl-tracking-data/bdb2025")
PARTS = DATA / "audit/bdb2025-snap-all-player-parts-v1"
MANIFEST_OUT = ROOT / "docs/research/bdb2025-snap-all-player-manifest-v1.csv"
SUMMARY_OUT = ROOT / "docs/research/bdb2025-snap-all-player-cohort-v1.json"
OBSERVATIONS_OUT = DATA / "audit/bdb2025-snap-all-player-observations-v1-combined.jsonl.gz"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", type=Path, default=PARTS)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_OUT)
    parser.add_argument("--summary", type=Path, default=SUMMARY_OUT)
    parser.add_argument("--observations", type=Path, default=OBSERVATIONS_OUT)
    args = parser.parse_args()
    outputs = (args.manifest, args.summary, args.observations)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite outputs: {existing}")

    parts = []
    all_rows = []
    counts_by_week = {}
    source_hashes = {}
    expected_header = None
    for week in range(1, 6):
        stem = args.parts / f"week-{week}"
        manifest_path = stem.with_suffix(".csv")
        summary_path = stem.with_suffix(".json")
        observations_path = stem.with_suffix(".jsonl.gz")
        if not all(path.is_file() for path in (manifest_path, summary_path, observations_path)):
            raise FileNotFoundError(f"Missing complete week {week} part under {args.parts}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary["weeksScanned"] != [week] or summary["includedByWeek"].get(str(week), 0) != summary["includedTotal"]:
            raise RuntimeError(f"Week {week} part summary is inconsistent")
        with manifest_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if expected_header is None:
                expected_header = reader.fieldnames
            elif reader.fieldnames != expected_header:
                raise RuntimeError(f"Week {week} manifest columns differ")
            rows = list(reader)
        if len(rows) != summary["includedTotal"] or any(int(row["week"]) != week for row in rows):
            raise RuntimeError(f"Week {week} manifest disagrees with its summary")
        with gzip.open(observations_path, "rt", encoding="utf-8") as f:
            observation_count = sum(1 for _ in f)
        if observation_count != len(rows):
            raise RuntimeError(f"Week {week} observation rows do not match the manifest")
        for name, source_hash in summary["sourceSha256FromStagedManifest"].items():
            if name in source_hashes and source_hashes[name] != source_hash:
                raise RuntimeError(f"Week {week} used a different source hash for {name}")
            source_hashes[name] = source_hash
        counts_by_week[str(week)] = summary["countsByWeek"][str(week)]
        parts.append((week, manifest_path, observations_path, len(rows)))
        all_rows.extend(rows)

    all_rows.sort(key=lambda row: (int(row["week"]), row["game_id"], row["play_id"]))
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.observations.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=expected_header)
        writer.writeheader()
        writer.writerows(all_rows)
    with gzip.open(args.observations, "wt", encoding="utf-8", newline="") as target:
        for _, _, observations_path, _ in parts:
            with gzip.open(observations_path, "rt", encoding="utf-8") as source:
                for line in source:
                    target.write(line)

    summary = {
        "schemaVersion": "bdb2025-snap-all-player-cohort/v1",
        "dataset": "unofficial b00nk3r/NFL-Big-Data-Bowl-2025 mirror; 2022 season",
        "weeksScanned": [1, 2, 3, 4, 5],
        "weeksReserved": [6, 7, 8, 9],
        "eligibility": {
            "selection": "ball_snap event; snap metadata and role from possession/defense teams; tracking-row presence only",
            "players": "all 22 tracked players, with 11 offense and 11 defense at snap",
            "inputFrames": "snapFrame-5 through snapFrame inclusive; input cutoff is snapFrame",
            "labels": "all 22 player locations plus football at snapFrame through snapFrame+10",
            "requiredPresence": "22 unique players and one football row at every frame from snapFrame-5 through snapFrame+10",
            "prohibitedInputs": ["eventual tackle frame", "credited tackler", "player_play outcome labels", "post-snap coordinates"],
        },
        "sourceSha256FromStagedManifest": source_hashes,
        "includedTotal": len(all_rows),
        "includedByWeek": {str(week): sum(int(row["week"]) == week for row in all_rows) for week in range(1, 6)},
        "countsByWeek": counts_by_week,
        "outputs": {"manifest": str(args.manifest), "observations": str(args.observations)},
    }
    summary["manifestSha256"] = digest(args.manifest)
    summary["observationsSha256"] = digest(args.observations)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "included": summary["includedTotal"],
        "includedByWeek": summary["includedByWeek"],
        "manifest": str(args.manifest),
        "summary": str(args.summary),
        "observations": str(args.observations),
    }, indent=2))


if __name__ == "__main__":
    main()
