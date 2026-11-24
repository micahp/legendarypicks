"""Check staged deltas against sampled totals for a single bounded game segment."""
import argparse
import collections
import csv
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("csv", type=Path)
args = parser.parse_args()
initial, final, initial_frame = {}, {}, {}
staged = collections.Counter()
first_event = {}
with args.csv.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        if row["kind"] not in ("total", "staged"):
            continue
        key = (int(row["team"]), int(row["index"]))
        frame = int(row["frame"])
        value = int(row["value"])
        if row["kind"] == "total":
            if key not in initial:
                initial[key], initial_frame[key] = value, frame
            final[key] = value
        else:
            staged[key] += value
            first_event.setdefault(key, frame)

# Possession seconds and red-zone fields can change outside this routine.
# These indices have only been checked in the pilot logs; mismatch fails loudly.
covered = set(range(11)) | {12, 21, 22}
keys = [key for key in initial if key[1] in covered]
if not keys:
    raise SystemExit("No sampled counters found")
errors = []
for key in keys:
    if key in first_event and first_event[key] <= initial_frame[key]:
        errors.append(f"{key}: staged update at or before baseline")
    elif (final[key] - initial[key]) % 65536 != staged[key] % 65536:
        errors.append(f"{key}: staged sum {staged[key]}, counter delta {final[key] - initial[key]}")
if errors:
    raise SystemExit("\n".join(errors))
print(f"Matched staged sums to {len(keys)} sampled team counter deltas")
