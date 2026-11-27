#!/usr/bin/env python3
"""Run one SLC model family over a slate of pregame games, in seed chunks.

Everything that varies between runs lives in a JSON config: paths, pinned file hashes, the models (each a git ref of
the SLC repo with its own extra flags), the shared flags, the blocker fixes and the seed plan. The runner itself has no
paths or hashes of its own.

Each model is extracted to its own runtime tree with a git dir, because simulate_pregame_batch records its producer
commit and branch and exits 128 without one. Work order: games in kickoff order, models inside each game, seed chunks
last. Every game/model must pass a one-seed smoke before any full batch.
Full runs use bounded chunks and refuse existing outputs; no blind resume.

    python3 scripts/nfl_sequence/slc_family_runner.py CONFIG.json --dry-run
    python3 scripts/nfl_sequence/slc_family_runner.py CONFIG.json [--only GAME_ID ...]
"""
import argparse
import os
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
MAX_CHUNK = 25  # bound work lost when a frozen engine cannot abort within a chunk

from batch_launch_gate import run_stage, require_full_seed_census
import pregame_snapshot
import roster_preflight
from prop_identity import validated_priced_qbs


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
    if not names or len(names) != len(set(names)):
        raise ValueError("model names must be nonempty and unique")
    seeds = cfg['seeds']
    if (any(type(seeds[k]) is not int for k in ('start', 'total', 'chunk'))
            or seeds['start'] < 0 or seeds['total'] < 1 or seeds['chunk'] < 1
            or type(cfg['concurrency']) is not int or cfg['concurrency'] < 1):
        raise ValueError('invalid seed plan or concurrency')
    for key in ('out_dir', 'db', 'snapshot_dir', 'source_repo'):
        cfg[key] = str(Path(cfg[key]).resolve())
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
        if len(files) != 1:
            raise ValueError(f"AMBIGUOUS_SNAPSHOT: {d}")
        payload = json.loads(files[0].read_text())
        sched = payload.get("pregame_snapshot", payload)["schedule"]
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
    controlled = {"--snapshot-file", "--db", "--games", "--seed-start", "--seed-list", "--out",
                  "--resume", "--register-dir", "--game-id", "--as-of"}
    for flag in cfg["shared_args"] + list(model.get("extra_args", [])):
        if flag.split("=", 1)[0] in controlled:
            raise ValueError("RUNNER_CONTROLLED_ARGUMENT: " + flag)
    cmd += cfg["shared_args"]
    cmd += ["--games", str(count), "--seed-start", str(start), "--out", str(out)]
    for blocker in cfg["blocker_fixes"]:
        cmd += ["--slc-blocker-fix", blocker]
    return cmd + list(model.get("extra_args", []))


def runtime_paths(cfg, model):
    base = Path(cfg["out_dir"])
    return base / (model["name"] + "-metadata.git"), base / ("runtime-" + model["name"])


def ensure_runtime(cfg, model):
    """Materialize the exact pinned tree; refuse dirty or stale existing runtimes."""
    metadata, runtime = runtime_paths(cfg, model)
    source = cfg["source_repo"]
    commit = model["commit"]
    with GIT_LOCK:
        if not (metadata / "HEAD").is_file():
            if runtime.exists():
                raise ValueError(f"UNOWNED_RUNTIME: {runtime}")
            subprocess.run(["git", "init", "--bare", "-q", str(metadata)], check=True)
            objects = subprocess.check_output(
                ["git", "-C", source, "rev-parse", "--path-format=absolute", "--git-path", "objects"],
                text=True).strip()
            (metadata / "objects/info/alternates").write_text(objects + "\n")
            ref = "refs/heads/" + model["name"]
            subprocess.run(["git", "--git-dir=" + str(metadata), "update-ref", ref, commit], check=True)
            subprocess.run(["git", "--git-dir=" + str(metadata), "symbolic-ref", "HEAD", ref], check=True)
            runtime.mkdir()
            git = ["git", "--git-dir=" + str(metadata), "--work-tree=" + str(runtime)]
            subprocess.run(git + ["read-tree", "HEAD"], check=True)
            subprocess.run(git + ["checkout-index", "-a"], check=True)
        git = ["git", "--git-dir=" + str(metadata), "--work-tree=" + str(runtime)]
        if subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() != commit:
            raise ValueError(f"RUNTIME_PIN_MISMATCH: {model['name']}")
        if subprocess.check_output(git + ["status", "--porcelain", "--untracked-files=normal"], text=True).strip():
            raise ValueError(f"RUNTIME_DIRTY: {runtime}")
    return metadata, runtime


def require_report(report, game, snapshot_sha, commit, start, count):
    sim = report.get("simulation") or {}
    summary = report.get("summary") or {}
    if (report.get("game_id") != game
            or (report.get("data_sources") or {}).get("source_snapshot_sha256") != snapshot_sha
            or (report.get("source") or {}).get("base_commit") != commit
            or (report.get("source") or {}).get("producer_worktree_dirty") is not False
            or (report.get("pregame_snapshot", {}).get("evaluation") or {}).get("verified") is not True):
        raise ValueError("RUN_IDENTITY_OR_PROVENANCE_MISMATCH")
    if (sim.get("requested_games") != count or sim.get("seed_start") != start
            or sim.get("seed_end_inclusive") != start + count - 1):
        raise ValueError("RUN_SEED_PLAN_MISMATCH")
    require_full_seed_census(summary.get("outcomes"), start, count)
    # Some frozen aggregators omit completed overtime games. The actual seed census
    # is authoritative; retain the historical summary count as a separate diagnostic.
    return count


def run_chunk(cfg, job, smoke=False):
    name, game, snapshot, start, count = job
    model = next(m for m in cfg["models"] if m["name"] == name)
    root = "smoke" if smoke else "runs"
    out = Path(cfg["out_dir"]) / root / name / ("%s-seed-%06d-%06d.json" % (game, start, start + count - 1))
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.with_suffix(".log")
    if any(path.exists() for path in (out, log, out.with_suffix(".seeds.jsonl"),
                                      out.with_suffix(".boxscores.jsonl"))):
        raise ValueError(f"EXISTING_OUTPUT_REFUSED: {out}")
    if sha256(snapshot) != cfg["snapshot_pins"][snapshot]["file_sha256"]:
        raise ValueError(f"SNAPSHOT_CHANGED_AFTER_PREFLIGHT: {snapshot}")
    metadata, runtime = runtime_paths(cfg, model)
    with log.open("x") as handle:
        result = subprocess.run(build_command(cfg, model, snapshot, start, count, out), cwd=runtime,
                                stdout=handle, stderr=subprocess.STDOUT,
                                env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                                     "GIT_DIR": str(metadata), "GIT_WORK_TREE": str(runtime)})
    if result.returncode:
        raise RuntimeError(f"{name} {game} {start} exited {result.returncode}; see {log}")
    report = json.loads(out.read_text())
    valid = require_report(report, game, cfg["snapshot_pins"][snapshot]["snapshot_sha256"],
                           model["commit"], start, count)
    return {"model": name, "game_id": game, "seed_start": start, "games": count,
            "valid_games": valid, "reported_valid_games": report["summary"].get("valid_full_games"),
            "status": "completed", "out": str(out), "log": str(log), "bytes": out.stat().st_size}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config")
    ap.add_argument("--only", nargs="*", help="game ids to run; default all games in the snapshot folder")
    ap.add_argument("--dry-run", action="store_true", help="check the pins and print the plan; run nothing")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    check_pins(cfg)
    games = games_in_kickoff_order(cfg["snapshot_dir"], cfg["game_glob"])
    cfg["seeds"]["chunk"] = min(cfg["seeds"]["chunk"], MAX_CHUNK)
    jobs = plan_jobs(cfg, games, a.only)
    if not jobs or (a.only and set(a.only) != {j[1] for j in jobs}):
        raise ValueError("NO_JOBS_OR_MISSING_SELECTED_GAME")
    if a.dry_run:
        print("games %d, models %d, jobs %d" % (len(games), len(cfg["models"]), len(jobs)))
        print(" ".join(build_command(cfg, cfg["models"][0], jobs[0][2], jobs[0][3], jobs[0][4],
                                     Path(cfg["out_dir"]) / "runs" / "example.json")) if jobs else "no jobs")
        return
    base = Path(cfg["out_dir"])
    base.mkdir(parents=True, exist_ok=True)
    manifest_path = base / "manifest.json"
    # Freeze branch refs once, before any model process starts.
    for model in cfg["models"]:
        model["commit"] = subprocess.check_output(
            ["git", "-C", cfg["source_repo"], "rev-parse", model["ref"] + "^{commit}"],
            text=True).strip()
    cfg["snapshot_pins"] = {}
    for _, game, path, _, _ in jobs:
        if path in cfg["snapshot_pins"]:
            continue
        file_hash = sha256(path)
        snap = pregame_snapshot.load_frozen_snapshot(path)
        if (snap["schedule"]["game_id"] != game
                or (snap.get("evaluation") or {}).get("verified") is not True):
            raise ValueError(f"SNAPSHOT_IDENTITY_OR_EVIDENCE_INVALID: {path}")
        checks, resolved = roster_preflight.check(snap, validated_priced_qbs(snap))
        checks.append(roster_preflight.exclusions_applied(snap, resolved))
        if (snap.get("roster_resolution") or {}).get("content_hash") != resolved["content_hash"]:
            raise ValueError(f"SNAPSHOT_ROSTER_RESOLUTION_MISMATCH: {path}")
        failed = roster_preflight.failed(checks)
        if failed:
            raise ValueError(f"SNAPSHOT_ROSTER_PREFLIGHT_FAILED: {path}: {failed}")
        if sha256(path) != file_hash:
            raise ValueError(f"SNAPSHOT_CHANGED_DURING_PREFLIGHT: {path}")
        cfg["snapshot_pins"][path] = {"file_sha256": file_hash, "snapshot_sha256": snap["snapshot_sha256"]}
    manifest = {"status": "preflight", "started_at_utc": now(), "config": a.config,
                "models": [{"name": m["name"], "commit": m["commit"]} for m in cfg["models"]],
                "job_count": len(jobs), "max_chunk": MAX_CHUNK, "snapshot_pins": cfg["snapshot_pins"],
                "pins": [{"path": p, "sha256": sha256(p)} for p in [cfg["db"]] + [
                    pin["path"] for pin in cfg.get("pinned_files", [])]],
                "smoke": [], "results": [], "failures": []}
    with manifest_path.open("x") as handle:
        handle.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def save():
        tmp = manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, manifest_path)

    try:
        for model in cfg["models"]:
            ensure_runtime(cfg, model)
    except Exception as exc:
        manifest["status"] = "blocked_by_runtime_preflight"
        manifest["failures"].append({"error": repr(exc)})
        save()
        return 1

    def collect(stage):
        def on_result(job, result, error):
            if error is not None:
                manifest["failures"].append({"stage": stage, "job": list(job), "error": repr(error)})
                print(f"FAILED {stage} {job}: {error}", file=sys.stderr, flush=True)
            else:
                manifest[stage].append(result)
            save()
            return error is None
        return on_result

    smoke = list(dict.fromkeys((name, game, snapshot, cfg["seeds"]["start"], 1)
                               for name, game, snapshot, _, _ in jobs))
    manifest["status"] = "smoke"
    save()
    if not run_stage(smoke, lambda job: run_chunk(cfg, job, smoke=True), collect("smoke"), cfg["concurrency"]):
        manifest["status"] = "blocked_by_smoke_test"
        save()
        return 1
    manifest["status"] = "running"
    save()
    ok = run_stage(jobs, lambda job: run_chunk(cfg, job), collect("results"), cfg["concurrency"])
    manifest.update({"status": "complete" if ok else "aborted_invalid_chunk", "completed_at_utc": now()})
    save()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
