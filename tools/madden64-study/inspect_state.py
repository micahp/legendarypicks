"""Inspect candidate RDRAM values in a BizHawk Mupen state; layout is version-specific."""
import argparse
import ctypes
import json
import struct
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("state", type=Path)
parser.add_argument("--zstd", required=True, help="Path to BizHawk's libzstd.dll")
parser.add_argument("--ram-dump", type=Path, help="Optional independent RDRAM dump to compare")
parser.add_argument("--players", action="store_true", help="Print nonzero candidate player counters")
args = parser.parse_args()
with zipfile.ZipFile(args.state) as archive:
    version = archive.read("BizVersion.txt").decode("utf-8").strip()
    if version != "Version 2.11.1":
        raise SystemExit(f"Unverified BizHawk state version: {version}")
    sync = json.loads(archive.read("SyncSettings.json"))["o"]
    if "Nintendo.N64.N64SyncSettings" not in sync.get("$type", "") or sync.get("Core") != 1:
        raise SystemExit("Unverified N64 core or state settings")
    compressed = archive.read("Core.bin.zst")
lib = ctypes.CDLL(args.zstd)
lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
lib.ZSTD_decompress.restype = ctypes.c_size_t
lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
lib.ZSTD_isError.restype = ctypes.c_uint
source = ctypes.create_string_buffer(compressed)
output = ctypes.create_string_buffer(64 * 1024 * 1024)
size = lib.ZSTD_decompress(output, len(output), source, len(compressed))
if lib.ZSTD_isError(size) or size < 448 + 0x90000:
    raise SystemExit("Could not decompress expected core state")
raw = output.raw[448:448 + 0x90000]
ram = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
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
