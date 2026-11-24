"""Read the observed BizHawk 2.11.1 Mupen state layout; reject other versions."""
import ctypes
import json
import zipfile


def read_ram(state, zstd):
    with zipfile.ZipFile(state) as archive:
        version = archive.read("BizVersion.txt").decode("utf-8").strip()
        if version != "Version 2.11.1":
            raise ValueError(f"Unverified BizHawk state version: {version}")
        sync = json.loads(archive.read("SyncSettings.json"))["o"]
        if "Nintendo.N64.N64SyncSettings" not in sync.get("$type", "") or sync.get("Core") != 1:
            raise ValueError("Unverified N64 core or state settings")
        compressed = archive.read("Core.bin.zst")
    lib = ctypes.CDLL(str(zstd))
    lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_decompress.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    source = ctypes.create_string_buffer(compressed)
    output = ctypes.create_string_buffer(64 * 1024 * 1024)
    size = lib.ZSTD_decompress(output, len(output), source, len(compressed))
    if lib.ZSTD_isError(size) or size < 448 + 0x90000:
        raise ValueError("Could not decompress expected core state")
    raw = output.raw[448:448 + 0x90000]
    return b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
