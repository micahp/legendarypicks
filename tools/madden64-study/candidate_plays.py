"""Extract provisional scrimmage candidates from staged events, not a complete play log."""
import argparse
import collections
import csv
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("csv", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
groups = collections.defaultdict(list)
with args.csv.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        if row["kind"] in ("event", "staged"):
            groups[int(row["frame"])].append(row)
plays = []
for frame, rows in sorted(groups.items()):
    triggers = []
    for row in rows:
        if row["kind"] == "event":
            slot, event_type = map(int, row["index"].split(":"))
            if event_type in (3, 8, 9) and int(row["value"]) != 0:
                triggers.append({"team": int(row["team"]), "slot": slot,
                                 "raw_type": event_type, "value": int(row["value"])})
    if not triggers:
        continue
    first = rows[0]
    plays.append({"frame": frame, "quarter": int(first["quarter"]), "clock": int(first["clock"]),
                  "down": int(first["down"]), "distance": int(first["distance"]),
                  "yard_display": int(first["yard"]), "triggers": triggers,
                  "ambiguous": len(triggers) != 1,
                  "raw_records": [{"team": int(r["team"]), "kind": r["kind"],
                                   "index": r["index"], "value": int(r["value"])} for r in rows]})
result = {"status": "provisional_incomplete", "definitions": {
    "3": "pass attempt candidate", "8": "sack candidate", "9": "rush attempt candidate"},
    "limitations": "Excludes unclassified, no-play and special-teams events; down, spot and team semantics remain under validation.",
    "plays": plays}
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(plays)} candidate frames; {sum(p['ambiguous'] for p in plays)} ambiguous")
