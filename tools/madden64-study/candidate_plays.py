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
            # V2 separates distinct event-hook calls made in the same frame.
            # V1 has no invocation key, so preserve its historical frame grouping.
            key = row.get("hook_id") or int(row["frame"])
            groups[key].append(row)
plays = []
for group_key, rows in sorted(groups.items(), key=lambda item: (
        int(item[1][0]["frame"]), int(item[1][0].get("hook_seq") or 0), str(item[0]))):
    frame = int(rows[0]["frame"])
    triggers = []
    for row in rows:
        if row["kind"] == "event":
            slot, event_type = map(int, row["index"].split(":"))
            if event_type in (3, 8, 9) and int(row["value"]) != 0:
                triggers.append({"team": int(row["team"]), "slot": slot,
                                 "player_row": int(row["player_row"]) if row.get("player_row") else None,
                                 "raw_type": event_type, "value": int(row["value"])})
    if not triggers:
        continue
    first = rows[0]
    period_raw = first.get("period")
    period = int(period_raw) if period_raw not in (None, "") else None
    legacy_quarter = first.get("quarter")
    # V1's event rows used the mode-state byte in their `quarter` column.
    # Keep it as raw evidence, but do not misreport it as a period.
    if period is None and legacy_quarter not in (None, ""):
        mode_state_raw = int(legacy_quarter)
    else:
        mode_state_raw = int(first["mode_state"]) if first.get("mode_state") not in (None, "") else None
    plays.append({"frame": frame, "period": period,
                  "period_type": first.get("period_type") or "unknown",
                  "legacy_mode_state_candidate": mode_state_raw,
                  "hook_id": first.get("hook_id") or None,
                  "clock": int(first["clock"]),
                  "down": int(first["down"]), "distance": int(first["distance"]),
                  "yard_display": int(first["yard"]),
                  "drive_team_candidate": int(first["drive_team_candidate"]) if first.get("drive_team_candidate") else None,
                  "triggers": triggers,
                  "ambiguous": len(triggers) != 1,
                  "raw_records": [{"team": int(r["team"]), "kind": r["kind"],
                                   "index": r["index"], "value": int(r["value"])} for r in rows]})
result = {"status": "provisional_incomplete", "definitions": {
    "3": "pass attempt candidate", "8": "sack candidate", "9": "rush attempt candidate"},
    "limitations": "Excludes unclassified, no-play and special-teams events; down, spot and team semantics remain under validation. V1 event-row period is unknown because its quarter field was a mode-state byte.",
    "plays": plays}
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(plays)} candidate frames; {sum(p['ambiguous'] for p in plays)} ambiguous")
