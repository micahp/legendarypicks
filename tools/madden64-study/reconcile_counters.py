"""Compare latest sampled counters at a specified frame with a transcribed screen."""
import argparse
import csv
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("csv", type=Path)
parser.add_argument("expected", type=Path)
args = parser.parse_args()
expected = json.loads(args.expected.read_text(encoding="utf-8"))
frame = expected["frame"]
latest = {}
with args.csv.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        if (int(row["frame"]) <= frame and int(row["team"]) in (0, 1)
                and ("kind" not in row or row["kind"] == "total")):
            latest[(int(row["team"]), int(row["index"]))] = int(row["value"])
errors = []
for team, values in expected["teams"].items():
    for index, value in values.items():
        actual = latest.get((int(team), int(index)))
        if actual != value:
            errors.append(f"team {team} index {index}: expected {value}, got {actual}")
if errors:
    raise SystemExit("\n".join(errors))
print(f"Matched {sum(map(len, expected['teams'].values()))} counters at frame {frame}")
