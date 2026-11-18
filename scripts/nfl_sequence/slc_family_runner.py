#!/usr/bin/env python3
"""Run one SLC model family over a slate of pregame games, in seed chunks.

Everything that varies between runs lives in a JSON config: paths, pinned file hashes, the models (each a git ref of
the SLC repo with its own extra flags), the shared flags, the blocker fixes and the seed plan. The runner itself has no
paths or hashes of its own.

Each model is extracted to its own runtime tree with a git dir, because simulate_pregame_batch records its producer
commit and branch and exits 128 without one. Work order: games in kickoff order, models inside each game, seed chunks
last, so the earliest kickoff finishes first. A chunk whose output already exists is skipped.

    python3 scripts/nfl_sequence/slc_family_runner.py CONFIG.json --dry-run
    python3 scripts/nfl_sequence/slc_family_runner.py CONFIG.json [--only GAME_ID ...]
"""
import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("out_dir", "db", "snapshot_dir", "game_glob", "source_repo", "models", "shared_args",
            "blocker_fixes", "seeds", "concurrency")
BATCH = "scripts/nfl_sequence/simulate_pregame_batch.py"
GIT_LOCK = threading.Lock()


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_config(path):
    cfg = json.loads(Path(path).read_text())
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise ValueError("config is missing %s" % ", ".join(missing))
    names = [m["name"] for m in cfg["models"]]
    if len(names) != len(set(names)):
        raise ValueError("model names must be unique")
    return cfg


def check_pins(cfg):
    """Refuse to run if a pinned input is missing or has changed."""
    for path in [cfg["db"]] + [p["path"] for p in cfg.get("pinned_files", [])]:
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    for pin in cfg.get("pinned_files", []):
        if sha256(pin["path"]) != pin["sha256"]:
            raise ValueError("%s hash mismatch" % pin["path"])


def games_in_kickoff_order(snapshot_dir, game_glob):
    """[(kickoff key, game id, snapshot path)] for every game folder that has a prospective snapshot."""
    out = []
    for d in sorted(Path(snapshot_dir).glob(game_glob)):
        files = sorted(d.glob("prospective-*.json"))
        if not files:
            continue
        sched = json.loads(files[0].read_text())["schedule"]
        out.append(((sched["gameday"], sched["gametime"]), d.name, files[0]))
    return sorted(out)


def plan_jobs(cfg, games, only=None):
    """One job per (game, model, seed chunk): (model, game id, snapshot path, seed start, seed count)."""
    seeds = cfg["seeds"]
    first, total, chunk = seeds["start"], seeds["total"], seeds["chunk"]
    jobs = []
    for _, game, path in games:
        if only and game not in only:
            continue
        for model in cfg["models"]:
            for start in range(first, first + total, chunk):
                jobs.append((model["name"], game, str(path), start, min(chunk, first + total - start)))
    return jobs


def build_command(cfg, model, snapshot, start, count, out):
    """The batch command for one chunk, run from the model's runtime tree."""
    cmd = [sys.executable, BATCH, "--snapshot-file", str(snapshot), "--db", cfg["db"]]
    cmd += cfg["shared_args"]
    cmd += ["--games", str(count), "--seed-start", str(start), "--out", str(out)]
    for blocker in cfg["blocker_fixes"]:
        cmd += ["--slc-blocker-fix", blocker]
    return cmd + list(model.get("extra_args", []))


def runtime_paths(cfg, model):
    base = Path(cfg["out_dir"])
    return base / (model["name"] + "-metadata.git"), base / ("runtime-" + model["name"])


GIT_READY = set()


def ensure_runtime(cfg, model):
    """Give the model a git dir and a checked-out runtime tree at its ref. Returns (metadata, runtime)."""
    metadata, runtime = runtime_paths(cfg, model)
    source = cfg["source_repo"]
    if not (metadata / "HEAD").is_file():
        subprocess.run(["git", "init", "--bare", "-q", str(metadata)], check=True)
        (metadata / "objects/info").mkdir(parents=True, exist_ok=True)
        (metadata / "objects/info/alternates").write_text(str(Path(source) / ".git/objects") + "\n")
        commit = subprocess.check_output(["git", "-C", source, "rev-parse", model["ref"]], text=True).strip()
        ref = "refs/heads/" + model["name"]
        subprocess.run(["git", "--git-dir=" + str(metadata), "update-ref", ref, commit], check=True)
        subprocess.run(["git", "--git-dir=" + str(metadata), "symbolic-ref", "HEAD", ref], check=True)
    env = {"GIT_DIR": str(metadata), "GIT_WORK_TREE": str(runtime), "PATH": "/usr/bin:/bin"}
    with GIT_LOCK:
        if model["name"] not in GIT_READY:
            subprocess.run(["git", "read-tree", "HEAD"], env=env, check=True)
            GIT_READY.add(model["name"])
    return metadata, runtime


def run_chunk(cfg, job):
    name, game, snapshot, start, count = job
    model = next(m for m in cfg["models"] if m["name"] == name)
    out = Path(cfg["out_dir"]) / "runs" / name / ("%s-seed-%06d-%06d.json" % (game, start, start + count - 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file() and out.stat().st_size > 0:
        return {"model": name, "game_id": game, "seed_start": start, "games": count,
                "status": "already_present", "out": str(out)}
    for suffix in (".seeds.jsonl", ".boxscores.jsonl"):
        ledger = out.with_suffix(suffix)
        if ledger.exists():
            ledger.unlink()
    metadata, runtime = ensure_runtime(cfg, model)
    log = out.with_suffix(".log")
    with log.open("w") as f:
        result = subprocess.run(build_command(cfg, model, snapshot, start, count, out), cwd=runtime,
                                stdout=f, stderr=subprocess.STDOUT,
                                env={"PATH": "/usr/bin:/bin", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                                     "HOME": "/root", "GIT_DIR": str(metadata), "GIT_WORK_TREE": str(runtime)})
    if result.returncode:
        raise RuntimeError("%s %s %d exited %d; see %s" % (name, game, start, result.returncode, log))
    report = json.loads(out.read_text())
    sim = report.get("simulation") if isinstance(report.get("simulation"), dict) else {}
    return {"model": name, "game_id": game, "seed_start": start, "games": count,
            "valid_games": sim.get("valid_games"), "errors": sim.get("errors"),
            "out": str(out), "log": str(log), "bytes": out.stat().st_size}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config")
    ap.add_argument("--only", nargs="*", help="game ids to run; default all games in the snapshot folder")
    ap.add_argument("--dry-run", action="store_true", help="check the pins and print the plan; run nothing")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    check_pins(cfg)
    games = games_in_kickoff_order(cfg["snapshot_dir"], cfg["game_glob"])
    jobs = plan_jobs(cfg, games, a.only)
    if a.dry_run:
        print("games %d, models %d, jobs %d" % (len(games), len(cfg["models"]), len(jobs)))
        print(" ".join(build_command(cfg, cfg["models"][0], jobs[0][2], jobs[0][3], jobs[0][4],
                                     Path(cfg["out_dir"]) / "runs" / "example.json")) if jobs else "no jobs")
        return
    base = Path(cfg["out_dir"])
    base.mkdir(parents=True, exist_ok=True)
    for model in cfg["models"]:
        ensure_runtime(cfg, model)
    manifest = {"status": "running", "started_at_utc": now(), "config": a.config,
                "models": [m["name"] for m in cfg["models"]], "job_count": len(jobs),
                "pins": [{"path": p, "sha256": sha256(p)} for p in [cfg["db"]] + [
                    pin["path"] for pin in cfg.get("pinned_files", [])]],
                "results": [], "failures": []}
    manifest_path = base / "manifest.json"

    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    save()
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["concurrency"]) as pool:
        futures = {pool.submit(run_chunk, cfg, job): job for job in jobs}
        for future in concurrent.futures.as_completed(futures):
            job = futures[future]
            try:
                manifest["results"].append(future.result())
            except Exception as exc:
                manifest["failures"].append({"job": list(job), "error": repr(exc)})
            save()
    manifest.update({"status": "complete", "completed_at_utc": now()})
    save()


if __name__ == "__main__":
    main()
