"""Run 25 more Madden 64 games in waves of six and archive hook data."""
import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "docs/research/madden64-statistical-study"
EMU = Path("E:/emu/bizhawk/EmuHawk.exe")
CORE = Path("E:/emu/bizhawk/dll/mupen64plus.dll")
ROM = Path("E:/emu/madden64/rom.z64")
DRIVER = REPO / "tools/madden64-study/driver.lua"
RUNNER = REPO / "tools/madden64-study/run_chunks.py"
MERGER = REPO / "tools/madden64-study/merge_chunks.py"
SUMMARIZER = REPO / "tools/madden64-study/summarize_game.py"
PLAY_EXTRACTOR = REPO / "tools/madden64-study/candidate_plays.py"
BASELINE = Path("E:/emu/madden64-w5/chunks/q3-s1/manifest.json")
STARTS = {
    3: (Path("E:/emu/madden64/q3control.state"),
        "73ccee9a5e793e53481f0f82a26cf87509bf0cfc2e37a8782a565c79372eb942"),
    5: (Path("E:/emu/madden64/controllers.state"),
        "580676c7fd1726aed1cbe9a3477ca872207a8e3591f3cfbb0846574f695eb158"),
    10: (Path("E:/emu/madden64/q10control.state"),
         "172ff089c8bef8a9c523ea8d7b08eb215292e111ce24d86b00af63358a59012d"),
}
PRINT_LOCK = threading.Lock()


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def build_batches():
    specs = [
        [(3, n) for n in range(9, 15)],
        [(5, n) for n in range(9, 15)],
        [(10, n) for n in range(9, 15)],
        [(3, 15), (3, 16), (5, 15), (5, 16), (10, 15), (10, 16)],
        [(5, 17)],
    ]
    seed = 8001
    batches = []
    for batch_number, entries in enumerate(specs, 1):
        batch = []
        for worker_slot, (quarter_s, serial) in enumerate(entries):
            batch.append({
                "game_id": f"q{quarter_s}-s{serial}",
                "quarter_s": quarter_s,
                "seed": seed,
                "batch": batch_number,
                "worker_slot": worker_slot,
            })
            seed += 1
        batches.append(batch)
    return batches


def verify_inputs():
    for path in (EMU, CORE, ROM, DRIVER, RUNNER, MERGER, SUMMARIZER, PLAY_EXTRACTOR, BASELINE):
        if not path.is_file():
            raise SystemExit(f"Required input is missing: {path}")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["fingerprint"]
    actual = {"emulator": digest(EMU), "core": digest(CORE), "rom": digest(ROM)}
    expected = {"emulator": baseline["emulator_sha256"], "core": baseline["core_sha256"],
                "rom": baseline["rom_sha256"]}
    if actual != expected:
        raise SystemExit(f"Emulator/core/ROM hashes differ from the verified run: {actual}")
    for quarter_s, (state, expected_hash) in STARTS.items():
        if not state.is_file() or digest(state) != expected_hash:
            raise SystemExit(f"Start state is missing or changed for {quarter_s}-second quarters: {state}")
    if sys.platform != "win32":
        raise SystemExit("This runner requires Windows process verification")


def make_workers(first_worker, count, speed):
    workers = []
    roots = [Path(f"E:/emu/madden64-w{first_worker + slot}") for slot in range(count)]
    for root in roots:
        if root.exists() and any(root.iterdir()):
            raise SystemExit(f"Worker folder is not empty; inspect before using {root}")
    try:
        for slot, root in enumerate(roots):
            worker_id = first_worker + slot
            root.mkdir(parents=True, exist_ok=True)
            if (root / "capture-hook-screenshots.flag").exists():
                raise SystemExit(f"Hook screenshot capture is enabled; inspect before using {root}")
            (root / "capture-hooks.flag").write_text("enabled\n", encoding="utf-8")
            env = os.environ.copy()
            env["MADDEN_WORK"] = root.as_posix() + "/"
            env["MADDEN_SPEED"] = str(speed)
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            log_stream = (root / "emulator-launch.log").open("ab")
            process = subprocess.Popen(
                [str(EMU), f"--lua={DRIVER}", str(ROM)], cwd=str(EMU.parent), env=env,
                startupinfo=startup, stdout=log_stream, stderr=subprocess.STDOUT,
            )
            workers.append({"id": worker_id, "root": root, "process": process,
                            "log_stream": log_stream})
        for worker in workers:
            deadline = time.monotonic() + 120
            ready = worker["root"] / "buttons.txt"
            while time.monotonic() < deadline and not ready.is_file():
                if worker["process"].poll() is not None:
                    raise SystemExit(f"BizHawk exited during startup for worker {worker['id']}")
                time.sleep(1)
            if not ready.is_file():
                raise SystemExit(f"Lua driver did not become ready for worker {worker['id']}")
            print(f"worker {worker['id']} ready pid={worker['process'].pid}", flush=True)
        return workers
    except BaseException:
        stop_workers(workers)
        raise


def run_game(job, worker, args):
    quarter_s = job["quarter_s"]
    start_state, _ = STARTS[quarter_s]
    manifest = worker["root"] / "chunks" / job["game_id"] / "manifest.json"
    log_dir = worker["root"] / "run-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job['game_id']}.log"
    description = (f"additional batch {job['batch']}, SEA at GB exhibition, {quarter_s}-second quarters, "
                   f"controller state hash verified, candidate RNG word {job['seed']}, speed {args.speed}, "
                   f"event hook enabled, worker {worker['id']}")
    command = [
        sys.executable, str(RUNNER), "--game-id", job["game_id"],
        "--start", str(start_state), "--rom", str(ROM), "--driver", str(DRIVER),
        "--emulator", str(EMU), "--emulator-pid", str(worker["process"].pid),
        "--core", str(CORE), "--root", str(worker["root"]),
        "--description", description, "--seed", str(job["seed"]),
        "--frames", str(args.frames), "--max-chunks", str(args.max_chunks),
        "--wait-seconds", str(args.wait_seconds), "--capture-hooks", "--recover-dead-pending",
    ]
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
        raise RuntimeError(f"{job['game_id']} failed (exit {result.returncode}); log={log_path}\n{tail}")
    ledger = json.loads(manifest.read_text(encoding="utf-8"))
    if not ledger.get("completed") or ledger.get("pending") or not ledger["fingerprint"].get("capture_hooks"):
        raise RuntimeError(f"{job['game_id']} did not complete with hook capture enabled")
    events = staged = totals = state_rows = hook_hits = 0
    for chunk in ledger["chunks"]:
        status = chunk["status"]
        match = __import__("re").search(r"hits=(\d+)", status)
        if match:
            hook_hits += int(match.group(1))
        with Path(chunk["csv"]).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                events += row["kind"] == "event"
                staged += row["kind"] == "staged"
                totals += row["kind"] == "total"
                state_rows += row["kind"] == "state"
    if hook_hits < 1 or events < 1:
        raise RuntimeError(f"{job['game_id']} ended without hook hits and event records")
    final_state = Path(ledger["chunks"][-1]["state"])
    outcome = {
        **job, "worker": worker["id"], "manifest": str(manifest),
        "final_state_sha256": digest(final_state), "chunks": len(ledger["chunks"]),
        "hook_hits": hook_hits, "event_rows": events, "staged_rows": staged,
        "team_counter_rows": totals, "state_transition_rows": state_rows,
        "capture_hooks": True, "speed_percent": args.speed,
    }
    with PRINT_LOCK:
        print(f"completed {job['game_id']} q={quarter_s}s chunks={outcome['chunks']} "
              f"hook_hits={hook_hits} event_rows={events} staged_rows={staged}", flush=True)
    return outcome


def wait_batch(futures, workers):
    results, failures = [], []
    pending = dict(futures)
    last_report = time.monotonic()
    while pending:
        done, _ = concurrent.futures.wait(
            pending, timeout=30, return_when=concurrent.futures.FIRST_COMPLETED)
        if not done and time.monotonic() - last_report >= 30:
            for future, job in pending.items():
                worker = workers[job["worker_slot"]]
                progress = worker["root"] / "hook-progress.txt"
                state = progress.read_text(encoding="utf-8", errors="replace").strip() if progress.exists() else "starting"
                with PRINT_LOCK:
                    print(f"running {job['game_id']} worker={worker['id']}: {state}", flush=True)
            last_report = time.monotonic()
        for future in done:
            job = pending.pop(future)
            try:
                results.append(future.result())
            except Exception as exc:
                failures.append({"game_id": job["game_id"], "error": str(exc)})
                with PRINT_LOCK:
                    print(f"FAILED {job['game_id']}: {exc}", flush=True)
    return results, failures


def archive_game(job, workers_by_id, output_dir):
    worker = workers_by_id[job["worker"]]
    manifest = Path(job["manifest"])
    slug = job["game_id"]
    merged = output_dir / f"{slug}.csv"
    summary = output_dir / f"{slug}.summary.json"
    plays = output_dir / f"{slug}.candidate-plays.json"
    subprocess.run([sys.executable, str(MERGER), str(manifest), "--output", str(merged)], check=True)
    subprocess.run([sys.executable, str(SUMMARIZER), str(merged), "--output", str(summary)], check=True)
    subprocess.run([sys.executable, str(PLAY_EXTRACTOR), str(merged), "--output", str(plays)], check=True)
    job.update({
        "merged_csv": str(merged.relative_to(DATA)), "merged_csv_sha256": digest(merged),
        "summary_json": str(summary.relative_to(DATA)), "candidate_plays_json": str(plays.relative_to(DATA)),
    })
    return job


def stop_workers(workers):
    for worker in workers:
        process = worker["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        worker["log_stream"].close()


parser = argparse.ArgumentParser()
parser.add_argument("--first-worker", type=int, default=7)
parser.add_argument("--workers", type=int, default=6)
parser.add_argument("--speed", type=int, default=6400)
parser.add_argument("--frames", type=int, default=12000)
parser.add_argument("--max-chunks", type=int, default=100)
parser.add_argument("--wait-seconds", type=int, default=1800)
args = parser.parse_args()
if args.workers != 6 or args.speed <= 0 or args.frames <= 0:
    raise SystemExit("This run plan is fixed to six workers and positive speed/frame settings")
verify_inputs()
batches = build_batches()
plan = [job for batch in batches for job in batch]
if len(plan) != 25 or len({job["game_id"] for job in plan}) != 25:
    raise SystemExit("Run plan is not 25 unique games")
for job in plan:
    start, start_hash = STARTS[job["quarter_s"]]
    job["start_state"] = str(start)
    job["start_state_sha256"] = start_hash
    job["batch_size"] = len(batches[job["batch"] - 1])
    job["worker"] = args.first_worker + job["worker_slot"]
    job["speed_percent"] = args.speed
    job["capture_hooks"] = True
plan_path = DATA / "additional-25-run-plan.json"
atomic_json(plan_path, {
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "status": "planned", "games": plan,
    "batches": [[job["game_id"] for job in batch] for batch in batches],
    "settings": {"parallel_workers": 6, "frames_per_chunk": args.frames,
                 "speed_percent": args.speed, "event_hook": "0x80025b10",
                 "hook_time_screenshots": False,
                 "rng_note": "Seeds are candidate RNG words; full-game independence is not established."},
})
print(f"Plan written: {plan_path}; 25 games across batches {[len(b) for b in batches]}", flush=True)

workers = []
completed = []
failures = []
result_path = DATA / "additional-25-run-results.json"
try:
    workers = make_workers(args.first_worker, args.workers, args.speed)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for batch_number, batch in enumerate(batches, 1):
            print(f"starting batch {batch_number}/5 ({len(batch)} games)", flush=True)
            futures = {}
            for job in batch:
                worker = workers[job["worker_slot"]]
                futures[executor.submit(run_game, job, worker, args)] = job
            wave_results, wave_failures = wait_batch(futures, workers)
            completed.extend(wave_results)
            failures.extend(wave_failures)
            atomic_json(result_path, {"status": "running", "completed": completed,
                                      "failures": failures, "updated_utc": datetime.now(timezone.utc).isoformat()})
            if wave_failures:
                break
    if failures:
        raise SystemExit(f"Stopped after a batch failure; successful games and logs are preserved in {result_path}")
    output_dir = DATA / "additional-25-data"
    output_dir.mkdir(parents=True, exist_ok=True)
    workers_by_id = {worker["id"]: worker for worker in workers}
    archived = [archive_game(job, workers_by_id, output_dir) for job in completed]
    atomic_json(result_path, {
        "status": "complete", "completed_utc": datetime.now(timezone.utc).isoformat(),
        "games_completed": len(archived), "games": archived,
        "batches": [[job["game_id"] for job in batch] for batch in batches],
        "hook_totals": {key: sum(job[key] for job in archived) for key in
                        ("hook_hits", "event_rows", "staged_rows", "team_counter_rows", "state_transition_rows")},
    })
    print(f"All 25 runs completed and archived: {result_path}", flush=True)
finally:
    stop_workers(workers)
