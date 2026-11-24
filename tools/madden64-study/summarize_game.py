"""Summarize a candidate completed game; output is provisional pending screen checks."""
import argparse
import collections
import csv
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("csv", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
totals = {}
staged = collections.Counter()
scores = []
saw_fourth_zero = False
end_frame = None
hooks = set()
with args.csv.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        frame, quarter, clock = int(row["frame"]), int(row["quarter"]), int(row["clock"])
        if end_frame is not None and frame > end_frame:
            break
        if quarter == 4 and clock == 0:
            saw_fourth_zero = True
        if row["kind"] == "state" and saw_fourth_zero and quarter == 6 and end_frame is None:
            end_frame = frame
        if row["kind"] == "total":
            team, index, value = int(row["team"]), int(row["index"]), int(row["value"])
            totals[(team, index)] = value
            if index == 57:
                scores.append({"frame": frame, "team": team, "score": value})
        elif row["kind"] in ("staged", "event"):
            hooks.add(frame)
            if row["kind"] == "staged":
                staged[(int(row["team"]), int(row["index"]))] += int(row["value"])
if end_frame is None:
    raise SystemExit("No candidate end transition after fourth-quarter zero")
required = (0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 57)
if any((team, index) not in totals for team in (0, 1) for index in required):
    raise SystemExit("Missing initial or final team counter")
result = {"status": "candidate_end_unvalidated", "end_frame": end_frame,
          "hook_frames_with_records": len(hooks), "score_observations_including_baseline": scores,
          "teams": {str(team): {str(index): totals[(team, index)] for index in required}
                    for team in (0, 1)},
          "staged_21_22_candidates": {str(team): {str(index): staged[(team, index)]
                                                   for index in (21, 22)}
                                       for team in (0, 1)}}
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"Wrote candidate summary at frame {end_frame}")
