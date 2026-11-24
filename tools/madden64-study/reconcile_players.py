"""Compare selected raw player-event sums with start/end player-table deltas."""
import argparse
import collections
import csv
import struct
from pathlib import Path
from state_memory import read_ram

parser = argparse.ArgumentParser()
parser.add_argument("csv", type=Path)
parser.add_argument("start", type=Path)
parser.add_argument("end", type=Path)
parser.add_argument("--zstd", required=True)
args = parser.parse_args()
before, after = read_ram(args.start, args.zstd), read_ram(args.end, args.zstd)
indices = (3, 4, 5, 9, 10)
sums = collections.Counter()
with args.csv.open(newline="", encoding="utf-8") as stream:
    for row in csv.DictReader(stream):
        if row["kind"] != "event":
            continue
        _, kind = map(int, row["index"].split(":"))
        if kind in indices:
            sums[(int(row["team"]), kind)] += int(row["value"])
errors = []
for team in (0, 1):
    for index in indices:
        def total(ram):
            return sum(struct.unpack_from(">h", ram, 0x81876 + team * 0x214c + row * 94 + index * 2)[0]
                       for row in range(45))
        delta = total(after) - total(before)
        if delta != sums[(team, index)]:
            errors.append(f"team {team} index {index}: events={sums[(team, index)]} player delta={delta}")
if errors:
    raise SystemExit("\n".join(errors))
print("Matched 10 selected team/player event sums to start/end state deltas")
