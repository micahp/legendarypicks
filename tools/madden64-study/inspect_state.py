"""Inspect candidate RDRAM values in a BizHawk Mupen state; layout is version-specific."""
import argparse
import struct
from pathlib import Path
from state_memory import read_ram

parser = argparse.ArgumentParser()
parser.add_argument("state", type=Path)
parser.add_argument("--zstd", required=True, help="Path to BizHawk's libzstd.dll")
parser.add_argument("--ram-dump", type=Path, help="Optional independent RDRAM dump to compare")
parser.add_argument("--players", action="store_true", help="Print nonzero candidate player counters")
args = parser.parse_args()
ram = read_ram(args.state, args.zstd)
if args.ram_dump:
    expected = args.ram_dump.read_bytes()
    if ram != expected:
        raise SystemExit("State RDRAM does not match independent dump")
    print("RDRAM matched independent dump")
u16 = lambda offset: struct.unpack_from(">H", ram, offset)[0]
print(f"candidate quarter={u16(0x876dc)} clock_seconds={u16(0x87aac)}")
print("display-state candidates: " + " ".join(
    f"{name}={struct.unpack_from('>i', ram, offset)[0]}"
    for name, offset in (("quarter", 0x89538), ("clock", 0x8953c),
                         ("play_clock", 0x89540), ("down", 0x89544),
                         ("distance", 0x89548), ("yard", 0x8954c))))
print(f"candidate RNG={struct.unpack_from('>I', ram, 0x87998)[0]:08x}")
for team in range(2):
    base = 0x82d22 + 0x214c * team
    indices = (0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 57)
    print(f"team {team}: " + " ".join(f"{i}={u16(base + 2 * i)}" for i in indices))
    if args.players:
        for player in range(45):
            row = 0x81876 + 0x214c * team + 94 * player
            stats = {i: struct.unpack_from(">h", ram, row + 2 * i)[0] for i in (3, 4, 5, 9, 10)}
            if any(stats.values()):
                print(f"  player-row {player}: " + " ".join(f"{i}={v}" for i, v in stats.items()))
