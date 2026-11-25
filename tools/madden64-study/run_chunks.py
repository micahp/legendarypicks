"""Drive one BizHawk game in resumable chunks. Never reissue an uncertain pending command."""
import argparse
import ctypes
import hashlib
import json
import os
import re
import time
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic(path, text):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def process_info(pid):
    """Return (alive, image) or fail if process status cannot be established."""
    if os.name != "nt":
        raise SystemExit("Emulator process verification currently requires Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    api.OpenProcess.restype = ctypes.c_void_p
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    api.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False, None
        raise SystemExit(f"Cannot verify process {pid}: Windows error {ctypes.get_last_error()}")
    try:
        code = ctypes.c_ulong()
        if not api.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise SystemExit(f"Cannot read exit status for process {pid}")
        if code.value != 259:
            return False, None
        size = ctypes.c_ulong(32768)
        name = ctypes.create_unicode_buffer(size.value)
        if not api.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            raise SystemExit(f"Cannot read image path for process {pid}")
        return True, Path(name.value)
    finally:
        api.CloseHandle(handle)


parser = argparse.ArgumentParser()
parser.add_argument("--game-id", required=True)
parser.add_argument("--start", type=Path, required=True, help="Controller-select state")
parser.add_argument("--rom", type=Path, required=True)
parser.add_argument("--driver", type=Path, required=True, help="Lua file loaded by the running emulator")
parser.add_argument("--emulator-pid", type=int, required=True)
parser.add_argument("--recover-dead-pending", action="store_true", help="Quarantine an incomplete chunk only if its recorded emulator process has exited")
parser.add_argument("--emulator", type=Path, default=Path("E:/emu/bizhawk/EmuHawk.exe"))
parser.add_argument("--core", type=Path, default=Path("E:/emu/bizhawk/dll/mupen64plus.dll"))
parser.add_argument("--root", type=Path, default=Path("E:/emu/madden64"))
parser.add_argument("--frames", type=int, default=12000)
parser.add_argument("--max-chunks", type=int, default=100)
parser.add_argument("--wait-seconds", type=int, default=600)
parser.add_argument("--initial-input", choices=("A", "none"), default="A")
parser.add_argument("--description", required=True, help="Teams, duration, settings and seed provenance")
parser.add_argument("--capture-hooks", action="store_true", help="Expect capture-hooks.flag to exist")
parser.add_argument("--seed", type=int, help="Experimental candidate RNG word, written only after initial input")
args = parser.parse_args()
if not re.fullmatch(r"[A-Za-z0-9_-]+", args.game_id) or args.frames <= 0 or args.max_chunks <= 0:
    raise SystemExit("Invalid game ID or chunk size")
if args.seed is not None and not 0 <= args.seed <= 0xffffffff:
    raise SystemExit("Seed must be an unsigned 32-bit integer")
if any(any(c.isspace() for c in str(p)) for p in (args.root, args.start)):
    raise SystemExit("Driver command paths may not contain whitespace")
args.root = args.root.resolve()
args.start = args.start.resolve()
if (args.root / "capture-hooks.flag").exists() != args.capture_hooks:
    raise SystemExit("capture-hooks.flag does not match run configuration")
if any(any(c.isspace() for c in str(p)) for p in (args.root, args.start)):
    raise SystemExit("Resolved driver command paths may not contain whitespace")
folder = args.root / "chunks" / args.game_id
folder.mkdir(parents=True, exist_ok=True)
manifest = folder / "manifest.json"
fingerprint = {"schema": 1, "game_id": args.game_id, "frames": args.frames,
               "initial_state_sha256": digest(args.start), "rom_sha256": digest(args.rom),
               "driver_sha256": digest(args.driver), "runner_sha256": digest(Path(__file__)),
               "emulator_sha256": digest(args.emulator), "core_sha256": digest(args.core),
               "initial_input": args.initial_input, "description": args.description,
               "capture_hooks": args.capture_hooks, "candidate_seed": args.seed}
if manifest.exists():
    ledger = json.loads(manifest.read_text(encoding="utf-8"))
    if ledger["fingerprint"] != fingerprint:
        raise SystemExit("Run fingerprint differs; refusing resume")
    for chunk in ledger["chunks"]:
        if digest(Path(chunk["csv"])) != chunk["csv_sha256"] or digest(Path(chunk["state"])) != chunk["state_sha256"]:
            raise SystemExit("Committed chunk or checkpoint hash differs; refusing resume")
else:
    ledger = {"fingerprint": fingerprint, "chunks": [], "pending": None,
              "armed": False, "completed": False, "next_state": str(args.start)}
    atomic(manifest, json.dumps(ledger, indent=2) + "\n")

if ledger["pending"] and args.recover_dead_pending:
    pending = ledger["pending"]
    status_path = Path(pending["output"] + ".status.txt")
    if not status_path.exists():
        old_pid = pending.get("emulator_pid")
        if old_pid is None or process_info(old_pid)[0]:
            raise SystemExit("Pending chunk's emulator is still live or unknown; refusing recovery")
        output = Path(pending["output"])
        if output.parent.resolve() != folder.resolve():
            raise SystemExit("Pending output is outside the game folder")
        stamp = str(time.time_ns())
        command_file = args.root / "cmd.txt"
        if command_file.exists():
            if pending["command"] not in command_file.read_text(encoding="utf-8"):
                raise SystemExit("A different command is present; refusing recovery")
            command_file.rename(args.root / f"cmd.orphan-{stamp}.txt")
        for item in folder.glob(output.name + "*"):
            if item.is_file() and item.parent.resolve() == folder.resolve():
                item.rename(folder / (item.name + ".orphan-" + stamp))
        ledger.setdefault("failures", []).append({"reason": "emulator exited before chunk status", "pending": pending})
        ledger["pending"] = None
        atomic(manifest, json.dumps(ledger, indent=2) + "\n")

while not ledger["completed"] and len(ledger["chunks"]) < args.max_chunks:
    if ledger["pending"] is None:
        alive, image = process_info(args.emulator_pid)
        if not alive or os.path.normcase(str(image.resolve())) != os.path.normcase(str(args.emulator.resolve())):
            raise SystemExit("Requested emulator process is not live or has a different executable")
        number = len(ledger["chunks"]) + 1
        output = folder / f"chunk-{number:04}.csv"
        if any(folder.glob(output.name + "*")) or (args.root / "cmd.txt").exists():
            raise SystemExit("Existing output or command requires inspection before proceeding")
        state = Path(ledger["next_state"])
        if not state.is_file():
            raise SystemExit("Checkpoint state missing")
        lines = [f"load {state.as_posix()}"]
        if number == 1 and args.initial_input == "A":
            lines.append("press A 8")
        if number == 1 and args.seed is not None:
            lines.append(f"seed {args.seed}")
        lines.append(f"gamechunk {output.as_posix()} {args.frames}")
        ledger["pending"] = {"output": str(output), "command": lines[-1], "input_state_sha256": digest(state),
                             "emulator_pid": args.emulator_pid}
        atomic(manifest, json.dumps(ledger, indent=2) + "\n")
        atomic(args.root / "armed.txt", "1\n" if ledger["armed"] else "0\n")
        done = args.root / "done.txt"
        if done.exists():
            done.unlink()
        atomic(args.root / "cmd.txt", "\n".join(lines) + "\n")
    pending = ledger["pending"]
    deadline = time.monotonic() + args.wait_seconds
    last_report = 0
    status_path = Path(pending["output"] + ".status.txt")
    while True:
        status = status_path.read_text(encoding="utf-8").strip() if status_path.exists() else ""
        if re.fullmatch(r"limit=\d+ hits=\d+ candidate_end=(true|false) armed=(true|false)", status):
            break
        if time.monotonic() >= deadline:
            raise SystemExit("Command still pending; ledger preserved. Inspect emulator before retrying; do not reissue.")
        if time.monotonic() - last_report >= 30:
            progress = args.root / "hook-progress.txt"
            print(f"waiting for {pending['output']}: {progress.read_text().strip() if progress.exists() else 'starting'}", flush=True)
            last_report = time.monotonic()
        time.sleep(1)
    end = "candidate_end=true" in status
    armed = "armed=true" in status
    output = Path(pending["output"])
    checkpoint = Path(str(output) + (".end.state" if end else ".checkpoint.state"))
    if not output.is_file() or not checkpoint.is_file() or output.stat().st_size == 0:
        raise SystemExit("Driver reported completion but output or checkpoint is missing")
    ledger["chunks"].append({"csv": str(output), "csv_sha256": digest(output),
                             "state": str(checkpoint), "state_sha256": digest(checkpoint),
                             "status": status.strip(), "input_state_sha256": pending["input_state_sha256"]})
    ledger.update(pending=None, armed=armed, completed=end, next_state=str(checkpoint))
    atomic(manifest, json.dumps(ledger, indent=2) + "\n")
    print(f"completed chunks={len(ledger['chunks'])} candidate_end={end} checkpoint={checkpoint}", flush=True)
if not ledger["completed"]:
    raise SystemExit("Chunk limit reached; ledger and checkpoint preserved")
print(f"Candidate end captured; validate against display: {manifest}")
