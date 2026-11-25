"""Verify a completed chunk ledger and concatenate its logs, suppressing duplicate baselines."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
ledger = json.loads(args.manifest.read_text(encoding="utf-8"))
if not ledger.get("completed") or ledger.get("pending") or not ledger.get("chunks"):
    raise SystemExit("Ledger is incomplete or pending")
last_frame = -1
last_totals = {}
header = None
rows_out = []
for chunk in ledger["chunks"]:
    path, state = Path(chunk["csv"]), Path(chunk["state"])
    for file, expected in ((path, chunk["csv_sha256"]), (state, chunk["state_sha256"])):
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Hash mismatch: {file}")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if header is None:
            header = reader.fieldnames
        elif header != reader.fieldnames:
            raise SystemExit("Chunk CSV schemas differ")
        first = True
        for row in reader:
            frame = int(row["frame"])
            # Execute callbacks may report the current frame before frameadvance
            # increments it, so an event can share the checkpoint frame.
            if first and frame < last_frame:
                raise SystemExit("Chunk frames go backward")
            first = False
            if frame < last_frame:
                raise SystemExit("Frames go backward")
            last_frame = frame
            if row["kind"] == "total":
                key = (row["team"], row["index"])
                if last_totals.get(key) == row["value"]:
                    continue
                last_totals[key] = row["value"]
            rows_out.append(row)
        if first:
            raise SystemExit(f"Empty chunk: {path}")
with args.output.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=header)
    writer.writeheader()
    writer.writerows(rows_out)
print(f"Merged {len(ledger['chunks'])} verified chunks, {len(rows_out)} rows")
