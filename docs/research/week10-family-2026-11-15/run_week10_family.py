"""Week 10, whole SLC model family, 1000 seeds per game per model.

Family members are separate git refs of lp-slc-v2 (the same four the WAS-NYG
model-family comparison used): slc-v1, slc-v1.5, slc-v1.6, slc-v2. Each is
extracted into its own runtime tree, and each takes the flags its own CLI
supports - only slc-v2 accepts the v2 extras (--slc-v2, rng v2, fg-kicker table,
snap counts).

Work order: games in kickoff order, models inside each game, seed chunks last,
so the earliest kickoff finishes first.
"""
import concurrent.futures, hashlib, json, subprocess, sys, threading
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/root/ot-sim-out/week10-family-2026-11-15")
SNAP_DIR = Path("/root/cutoff-captures/snapshots/week-10")
DB = Path("/root/legendarypicks/backend/data/picks.dev.db")
STREAKS = Path("/root/slc-was-nyg-tnf-2026-11-12-final-0013Z/run-inputs/wl-streaks-through-week9.json")
SNAP_COUNTS = Path("/root/ot-sim-out/slc-v2-tnf-10-2026-11-12/docs/research/"
                   "slc-was-nyg-tnf-2026-11-12/participation-snap-counts-through-week9.json")
KICKER = SNAP_DIR / "inputs/kicker-table-through-week10-la.json"
KICKER_SHA = "b330b9666be5a9c0fe3e8a66c305fc079c8a20df46aadba2413a9ecd8c319257"
SNAP_SHA = "4e35e2b6d6da0f43edd971ee18b0887c55531564f763e8a17692c1425ca25d98"
MODELS = ("v1", "v1.5", "v1.6", "v2")
BLOCKERS = ["run_scramble_backoff", "long_field_goal_feasibility", "blocked_kick_source_audit",
            "blocked_kick_geometry", "safety_free_kick_boundaries"]
CHUNK = 250
TOTAL = 1000
SEED_START = 300001
CONCURRENCY = 4
MANIFEST = BASE / "manifest.json"
RUNS = BASE / "runs"
GIT_LOCK = threading.Lock()
GIT_READY = set()


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


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


def git_metadata(model):
    """Give each extracted runtime a git dir, the way the WAS-NYG family run did.

    simulate_pregame_batch records its producer commit and branch, so a runtime
    tree that is not a git checkout dies with exit 128 before the first seed.
    """
    repo = Path("/root/lp-slc-v2")
    runtime = BASE / ("runtime-" + model)
    metadata = BASE / (model + "-metadata.git")
    ref = "refs/heads/slc-" + model
    if not (metadata / "HEAD").is_file():
        subprocess.run(["git", "init", "--bare", "-q", str(metadata)], check=True)
        (metadata / "objects/info").mkdir(parents=True, exist_ok=True)
        (metadata / "objects/info/alternates").write_text(str(repo / ".git/objects") + "\n")
        commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "origin/slc-" + model],
                                         text=True).strip()
        subprocess.run(["git", "--git-dir=" + str(metadata), "update-ref", ref, commit], check=True)
        subprocess.run(["git", "--git-dir=" + str(metadata), "symbolic-ref", "HEAD", ref], check=True)
    env = {"GIT_DIR": str(metadata), "GIT_WORK_TREE": str(runtime), "PATH": "/usr/bin:/bin"}
    with GIT_LOCK:
        if model not in GIT_READY:
            subprocess.run(["git", "read-tree", "HEAD"], env=env, check=True)
            GIT_READY.add(model)
    return metadata, runtime


def command(model, game, start, count, out):
    runtime = BASE / ("runtime-" + model)
    cmd = [sys.executable, str(runtime / "scripts/nfl_sequence/simulate_pregame_batch.py"),
           "--snapshot-file", str(GAMES[game]),
           "--db", str(DB),
           "--slc-profile", "v1_full_stack",
           "--playcall-artifact", "docs/research/SLC-PLAYCALL-ARTIFACT-v1.json",
           "--playcall-streak-file", str(STREAKS),
           "--games", str(count), "--seed-start", str(start),
           "--progress-every", "250", "--export-boxscores", "--out", str(out)]
    for blocker in BLOCKERS:
        cmd += ["--slc-blocker-fix", blocker]
    if model == "v2":
        cmd += ["--slc-v2", "--rng-protocol", "v2",
                "--playcall-pass-label-mode", "conditional", "--playcall-decision",
                "--playcall-fg-kicker", str(KICKER),
                "--playcall-fg-kicker-sha256", KICKER_SHA,
                "--participation-snap-counts", str(SNAP_COUNTS),
                "--participation-snap-counts-sha256", SNAP_SHA,
                "--no-export-plays"]
    return cmd


def run_chunk(job):
    model, game, start, count = job
    runtime = BASE / ("runtime-" + model)
    out = RUNS / model / ("%s-seed-%06d-%06d.json" % (game, start, start + count - 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.with_suffix(".log")
    if out.is_file() and out.stat().st_size > 0:
        return {"model": model, "game_id": game, "seed_start": start, "games": count,
                "status": "already_present", "out": str(out)}
    for suffix in (".seeds.jsonl", ".boxscores.jsonl"):
        ledger = out.with_suffix(suffix)
        if ledger.exists():
            ledger.unlink()
    metadata, runtime = git_metadata(model)
    with log.open("w") as f:
        result = subprocess.run(command(model, game, start, count, out), cwd=runtime,
                                stdout=f, stderr=subprocess.STDOUT,
                                env={"PATH": "/usr/bin:/bin", "OPENBLAS_NUM_THREADS": "1",
                                     "OMP_NUM_THREADS": "1", "HOME": "/root",
                                     "GIT_DIR": str(metadata), "GIT_WORK_TREE": str(runtime)})
    if result.returncode:
        raise RuntimeError("%s %s %d exited %d; see %s"
                           % (model, game, start, result.returncode, log))
    report = json.loads(out.read_text())
    sim = report.get("simulation") if isinstance(report.get("simulation"), dict) else {}
    return {"model": model, "game_id": game, "seed_start": start, "games": count,
            "valid_games": sim.get("valid_games"), "errors": sim.get("errors"),
            "runtime": str(runtime), "out": str(out), "log": str(log),
            "bytes": out.stat().st_size}


def main():
    only = sys.argv[1:] or None
    for p in (DB, STREAKS, SNAP_COUNTS, KICKER):
        if not Path(p).is_file():
            raise FileNotFoundError(p)
    if sha(KICKER) != KICKER_SHA:
        raise ValueError("kicker table hash mismatch")
    for model in MODELS:
        runtime = BASE / ("runtime-" + model)
        if not (runtime / "scripts/nfl_sequence/simulate_pregame_batch.py").is_file():
            raise FileNotFoundError(runtime)
        git_metadata(model)
    order = games_in_kickoff_order()
    for _, game, path in order:
        GAMES[game] = path
    manifest = {"status": "running", "started_at_utc": now(),
                "models": list(MODELS), "seeds_per_game_per_model": TOTAL,
                "seed_start": SEED_START, "order_kickoff_et": [[k[0], k[1], g] for k, g, _ in order],
                "chunk": CHUNK, "concurrency": CONCURRENCY,
                "blocker_fixes": BLOCKERS,
                "database": str(DB), "database_sha256": sha(DB),
                "streaks": str(STREAKS), "streaks_sha256": sha(STREAKS),
                "kicker_table": str(KICKER), "kicker_table_sha256": KICKER_SHA,
                "snap_counts_sha256": SNAP_SHA,
                "refs": {m: subprocess.check_output(
                    ["git", "-C", "/root/lp-slc-v2", "rev-parse", "--short", "origin/slc-" + m],
                    text=True).strip() for m in MODELS},
                "results": [], "failures": []}
    write(manifest)
    jobs = []
    for _, game, _path in order:
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
    manifest.update({"status": "complete", "completed_at_utc": now(),
                     "completed_chunks": len(manifest["results"])})
    write(manifest)


if __name__ == "__main__":
    main()
