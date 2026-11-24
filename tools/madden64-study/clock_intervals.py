"""Summarize frame gaps between successive game-clock decrements in regulation."""
import argparse
import collections
import csv
import json
import statistics
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("csv", type=Path)
parser.add_argument("--quarter-seconds", type=int, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
previous = None
intervals, jumps = [], []
with args.csv.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        if row["kind"] != "state":
            continue
        q, clock, frame = int(row["quarter"]), int(row["clock"]), int(row["frame"])
        if not 1 <= q <= 4:
            continue
        if previous is None or (q, clock) != previous[:2]:
            if previous and previous[0] == q:
                if previous[1] - clock == 1:
                    intervals.append(frame - previous[2])
                elif clock != previous[1]:
                    jumps.append({"frame": frame, "quarter": q, "from": previous[1], "to": clock})
            previous = (q, clock, frame)
if len(intervals) != args.quarter_seconds * 4 or jumps:
    raise SystemExit(f"Incomplete or discontinuous regulation clock: {len(intervals)} decrements, {len(jumps)} jumps")
result = {"quarter_seconds": args.quarter_seconds, "decrements": len(intervals),
          "median_frames": statistics.median(intervals), "minimum_frames": min(intervals),
          "maximum_frames": max(intervals), "frames_49_to_51": sum(49 <= v <= 51 for v in intervals),
          "frames_over_100": sum(v > 100 for v in intervals),
          "histogram_frames": dict(sorted(collections.Counter(intervals).items()))}
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"Measured {len(intervals)} clock decrements; median {result['median_frames']} frames")
