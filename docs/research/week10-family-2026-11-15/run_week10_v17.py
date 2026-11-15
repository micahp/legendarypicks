"""Week 10, V1.7 arms (PR #42 base and PR #43 precision fix), 1000 seeds per game.

V1.7 is not on a slc-v* branch: it lives on feature/slc-v1.7-penalty-model-2026-11-12
(PR #42, commit 6ac6180c) and fix/slc-v1.7-fractional-state-precision-2026-11-13
(PR #43, commit 984751d5). It also needs the classified v1.7 game history, which
the WAS-NYG family run already built through week 9.

Uses the runtimes and metadata git dirs the WAS-NYG family run proved out, so the
producer commit/branch recorded per batch stays the same.
"""
import concurrent.futures, hashlib, json, subprocess, sys, threading
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/root/ot-sim-out/week10-family-2026-11-15")
SOURCE = Path("/root/slc-was-nyg-tnf-2026-11-12-final-0013Z")
SNAP_DIR = Path("/root/cutoff-captures/snapshots/week-10")
DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
STREAKS = SOURCE / "run-inputs/wl-streaks-through-week9.json"
V17_HISTORY = BASE / "inputs/slc-history-v17.sqlite"
MODELS = {"v1.7": "v17", "v1.7-pr43": "v17-pr43"}
BLOCKERS = ["run_scramble_backoff", "long_field_goal_feasibility", "blocked_kick_source_audit",
            "blocked_kick_geometry", "safety_free_kick_boundaries"]
CHUNK = 250
TOTAL = 1000
SEED_START = 300001
CONCURRENCY = 1
MANIFEST = BASE / "manifest-v17.json"
RUNS = BASE / "runs"
GIT_LOCK = threading.Lock()
GIT_READY = set()


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write(obj):
    MANIFEST.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def games_in_kickoff_order():
    out = []
    for d in sorted(SNAP_DIR.glob("2026_10_*")):
        files = sorted(d.glob("prospective-*.json"))
        if not files:
            continue
        sched = json.loads(files[0].read_text())["schedule"]
        out.append(((sched["gameday"], sched["gametime"]), d.name, files[0]))
    return sorted(out)


GAMES = {}


def paths(model):
    return SOURCE / ("runtime-" + MODELS[model]), SOURCE / (MODELS[model] + "-metadata.git")


def prepare(model):
    runtime, metadata = paths(model)
    env = {"GIT_DIR": str(metadata), "GIT_WORK_TREE": str(runtime), "PATH": "/usr/bin:/bin"}
    with GIT_LOCK:
        if model not in GIT_READY:
            subprocess.run(["git", "read-tree", "HEAD"], env=env, check=True)
            GIT_READY.add(model)
    return runtime, metadata, env


def command(model, game, start, count, out):
    runtime, _ = paths(model)
    cmd = [sys.executable, str(runtime / "scripts/nfl_sequence/simulate_pregame_batch.py"),
           "--snapshot-file", str(GAMES[game]), "--db", str(DB),
           "--slc-profile", "v1_full_stack",
           "--playcall-artifact", "docs/research/SLC-PLAYCALL-ARTIFACT-v1.json",
           "--playcall-streak-file", str(STREAKS),
           "--historical-streak-file", str(V17_HISTORY),
           "--playcall-pass-label-mode", "conditional", "--playcall-decision",
           "--games", str(count), "--seed-start", str(start),
           "--progress-every", "250", "--export-boxscores", "--out", str(out)]
    for blocker in BLOCKERS:
        cmd += ["--slc-blocker-fix", blocker]
    return cmd


def run_chunk(job):
    model, game, start, count = job
    runtime, metadata, env = prepare(model)
    out = RUNS / model / ("%s-seed-%06d-%06d.json" % (game, start, start + count - 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file() and out.stat().st_size > 0:
        return {"model": model, "game_id": game, "seed_start": start, "status": "already_present"}
    for suffix in (".seeds.jsonl", ".boxscores.jsonl"):
        ledger = out.with_suffix(suffix)
        if ledger.exists():
            ledger.unlink()
    log = out.with_suffix(".log")
    with log.open("w") as f:
        result = subprocess.run(command(model, game, start, count, out), cwd=runtime,
                                stdout=f, stderr=subprocess.STDOUT,
                                env={**env, "OPENBLAS_NUM_THREADS": "1",
                                     "OMP_NUM_THREADS": "1", "HOME": "/root"})
    if result.returncode:
        raise RuntimeError("%s %s %d exited %d; see %s"
                           % (model, game, start, result.returncode, log))
    report = json.loads(out.read_text())
    sim = report.get("simulation") if isinstance(report.get("simulation"), dict) else {}
    return {"model": model, "game_id": game, "seed_start": start, "games": count,
            "valid_games": sim.get("valid_games"), "out": str(out), "log": str(log)}


def main():
    only = sys.argv[1:] or None
    for p in (DB, STREAKS, V17_HISTORY):
        if not Path(p).is_file():
            raise FileNotFoundError(p)
    order = games_in_kickoff_order()
    for _, game, path in order:
        GAMES[game] = path
    manifest = {"status": "running", "started_at_utc": now(), "models": list(MODELS),
                "seeds_per_game_per_model": TOTAL, "seed_start": SEED_START,
                "chunk": CHUNK, "concurrency": CONCURRENCY, "blocker_fixes": BLOCKERS,
                "database": str(DB), "streaks": str(STREAKS), "v17_history": str(V17_HISTORY),
                "runtimes": {m: str(paths(m)[0]) for m in MODELS},
                "refs": {m: subprocess.check_output(
                    ["git", "--git-dir=" + str(paths(m)[1]), "rev-parse", "--short", "HEAD"],
                    text=True).strip() for m in MODELS},
                "results": [], "failures": []}
    write(manifest)
    jobs = []
    for _, game, _p in order:
        if only and game not in only:
            continue
        for model in MODELS:
            for start in range(SEED_START, SEED_START + TOTAL, CHUNK):
                jobs.append((model, game, start, min(CHUNK, SEED_START + TOTAL - start)))
    manifest["job_count"] = len(jobs)
    write(manifest)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(run_chunk, job): job for job in jobs}
        for future in concurrent.futures.as_completed(futures):
            job = futures[future]
            try:
                manifest["results"].append(future.result())
            except Exception as exc:
                manifest["failures"].append({"job": list(job), "error": repr(exc)})
            write(manifest)
    manifest.update({"status": "complete", "completed_at_utc": now()})
    write(manifest)


if __name__ == "__main__":
    main()
