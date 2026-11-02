#!/usr/bin/env python3
"""Launch the five missing Week 8 SLC 10K runs on a clean pinned checkout."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PINNED_COMMIT = "c78b602868d61be56deb9111402f43826ff26df6"
MATCHUPS = ("LAC_LA", "LV_NYJ", "NE_MIA", "PHI_WAS", "TEN_CIN")
BLOCKERS = ("run_scramble_backoff", "long_field_goal_feasibility",
            "blocked_kick_source_audit", "blocked_kick_geometry", "safety_free_kick_boundaries")
PINNED_SHARED_INPUTS = {
    "database_sha256": "feb5179f1c6c2f8cd2265a25ff68f3552d6e68bbba00354e0688f22505aa028f",
    "playcall_artifact_sha256": "c8f16540931f6fddc61b6e62797ecd71dfff11897c393c531033eef623328ce5",
    "streak_file_sha256": "4d3e0d712134396ea91d1d9d8bca11ce9d6089674d9d6e2360696f44e311af5c",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compress_worker_artifacts(output_dir: Path) -> list[dict]:
    """Store byte-exact, verified gzip copies before releasing raw worker files."""
    artifacts = sorted(path for path in output_dir.glob("worker-*.json*")
                       if path.is_file() and not path.name.endswith(".gz"))
    if not artifacts:
        raise RuntimeError(f"no worker artifacts found to preserve in {output_dir}")
    manifest = []
    for source in artifacts:
        source_hash = sha256(source)
        stored = source.with_name(source.name + ".gz")
        temporary = stored.with_name(stored.name + ".partial")
        if stored.exists() or temporary.exists():
            raise FileExistsError(f"refusing to overwrite compressed artifact: {stored}")
        try:
            with source.open("rb") as input_handle, temporary.open("wb") as output_handle:
                with gzip.GzipFile(filename="", mode="wb", compresslevel=1,
                                   fileobj=output_handle, mtime=0) as compressed:
                    for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
                        compressed.write(chunk)
            with gzip.open(temporary, "rb") as restored:
                digest = hashlib.sha256()
                for chunk in iter(lambda: restored.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != source_hash:
                raise RuntimeError(f"gzip round-trip hash mismatch for {source}")
            os.replace(temporary, stored)
            manifest.append({
                "raw_name": source.name,
                "raw_sha256": source_hash,
                "raw_bytes": source.stat().st_size,
                "stored_name": stored.name,
                "stored_sha256": sha256(stored),
                "stored_bytes": stored.stat().st_size,
                "compression": "gzip-level-1",
            })
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    # Only release uncompressed copies once every stored artifact has passed a byte-for-byte check.
    for source in artifacts:
        source.unlink()
    return manifest


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _absolute_executable_path(path: Path) -> Path:
    """Make a path absolute without dereferencing venv Python symlinks."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def preflight(source_root: Path, python: Path, run_root: Path, run_id: str) -> list[dict]:
    source_root = source_root.resolve()
    python = _absolute_executable_path(python)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=source_root, text=True).strip()
    if commit != PINNED_COMMIT:
        raise RuntimeError(f"pinned source mismatch: expected {PINNED_COMMIT}, found {commit}")
    if dirty:
        raise RuntimeError("pinned simulator source checkout is dirty")
    if not python.is_file():
        raise FileNotFoundError(f"simulator Python interpreter is missing: {python}")
    disk_path = run_root if run_root.exists() else run_root.parent
    free_bytes = shutil.disk_usage(disk_path).free
    minimum_free_bytes = int(3.25 * 1024**3)
    if free_bytes < minimum_free_bytes:
        raise RuntimeError(f"fast-host output volume has only {free_bytes} free bytes; 3.25 GiB are required")

    scripts = source_root / "scripts" / "nfl_sequence"
    database = Path("/root/slc-week8-missing-10k-2026-10-29/data/simulation-input.sqlite")
    artifact = source_root / "docs/research/SLC-PLAYCALL-ARTIFACT-v1.json"
    streaks = source_root / "docs/research/slc-week8-2026/wl-streaks-2026-10-29.json"
    shared = {"database": database, "playcall_artifact": artifact, "streak_file": streaks}
    hashes = {name: sha256(path) for name, path in shared.items()}
    for name, pinned_key in (("database", "database_sha256"),
                             ("playcall_artifact", "playcall_artifact_sha256"),
                             ("streak_file", "streak_file_sha256")):
        expected = PINNED_SHARED_INPUTS[pinned_key]
        if hashes[name] != expected:
            raise RuntimeError(f"pinned {name} hash mismatch: expected {expected}, found {hashes[name]}")

    plans = []
    for matchup in MATCHUPS:
        game_id = f"2026_08_{matchup}"
        snapshot = source_root / "docs/research/slc-week8-2026/snapshots" / f"{game_id}.json"
        snapshot_data = json.loads(snapshot.read_text(encoding="utf-8"))
        snapshot_game_id = snapshot_data.get("game_id") or (snapshot_data.get("schedule") or {}).get("game_id")
        if snapshot_game_id != game_id or snapshot_data.get("evaluation", {}).get("verified") is not True:
            raise RuntimeError(f"snapshot identity or eligibility preflight failed: {snapshot}")
        output_dir = run_root / "artifacts" / matchup / run_id
        if output_dir.exists():
            raise FileExistsError(f"refusing to reuse existing run output: {output_dir}")
        plans.append({
            "matchup": matchup,
            "game_id": game_id,
            "snapshot": snapshot,
            "snapshot_sha256": sha256(snapshot),
            "snapshot_as_of": snapshot_data.get("as_of"),
            "output_dir": output_dir,
            "input_hashes": {**hashes, "snapshot": sha256(snapshot)},
        })
    return plans


def launch(args: argparse.Namespace) -> int:
    source_root = args.source_root.resolve()
    python = _absolute_executable_path(args.python)
    run_root = args.run_root.resolve()
    plans = preflight(source_root, python, run_root, args.run_id)
    print(json.dumps({"status": "preflight_passed", "run_id": args.run_id,
                      "source_commit": PINNED_COMMIT,
                      "matchups": [{"game_id": item["game_id"], "snapshot_sha256": item["snapshot_sha256"],
                                    "output_dir": str(item["output_dir"])} for item in plans]}, sort_keys=True),
          flush=True)
    if args.dry_run:
        return 0

    batch_script = source_root / "scripts/nfl_sequence/simulate_pregame_batch.py"
    audit_script = source_root / "scripts/nfl_sequence/audit_week8_matchup_batch.py"
    report_script = source_root / "scripts/nfl_sequence/render_slc_run_report.py"
    audit_root = run_root.parent / "run-audits"
    report_root = run_root / "reports" / args.run_id
    audit_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)

    for plan in plans:
        output_dir = plan["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=False)
        log_dir = output_dir / "logs"
        log_dir.mkdir()
        partitions = []
        seed = args.seed_start
        for worker in range(1, args.workers + 1):
            count = args.games // args.workers + (1 if worker <= args.games % args.workers else 0)
            partitions.append({"worker": worker, "seed_start": seed, "games": count,
                              "seed_end_inclusive": seed + count - 1})
            seed += count
        header = {
            "schema": "lp.nfl.week8-slc-run-header.v1",
            "run_id": args.run_id,
            "game_id": plan["game_id"],
            "matchup": plan["matchup"],
            "profile": "v1_full_stack",
            "source_commit": PINNED_COMMIT,
            "source_worktree_dirty": False,
            "database_path": "/root/slc-week8-missing-10k-2026-10-29/data/simulation-input.sqlite",
            "snapshot_path": str(plan["snapshot"]),
            "playcall_artifact_path": str(source_root / "docs/research/SLC-PLAYCALL-ARTIFACT-v1.json"),
            "streak_file_path": str(source_root / "docs/research/slc-week8-2026/wl-streaks-2026-10-29.json"),
            "input_sha256": plan["input_hashes"],
            "snapshot_as_of": plan["snapshot_as_of"],
            "requested_games": args.games,
            "seed_start": args.seed_start,
            "workers": args.workers,
            "worker_partitions": partitions,
            "blocker_fixes": list(BLOCKERS),
            "field_goal_ordinary_cutoff_yards": 60.0,
            "boxscore_export": True,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "artifact_location": str(output_dir),
        }
        write_json(output_dir / "run-header.json", header)
        processes = []
        for partition in partitions:
            worker = partition["worker"]
            stem = f"worker-{worker:02d}"
            command = [
                str(python), str(batch_script),
                "--snapshot-file", str(plan["snapshot"]),
                "--slc-profile", "v1_full_stack",
                "--playcall-artifact", header["playcall_artifact_path"],
                "--playcall-streak-file", header["streak_file_path"],
                "--db", header["database_path"],
                "--slc-fg-ordinary-cutoff", "60.0",
                "--export-boxscores",
                "--games", str(partition["games"]),
                "--seed-start", str(partition["seed_start"]),
                "--progress-every", "250",
                "--max-simulation-errors", "0",
                "--out", str(output_dir / f"{stem}.json"),
            ]
            for blocker in BLOCKERS:
                command.extend(("--slc-blocker-fix", blocker))
            log_handle = (log_dir / f"{stem}.log").open("w", encoding="utf-8")
            process = subprocess.Popen(command, cwd=source_root, stdout=log_handle,
                                       stderr=subprocess.STDOUT, env=os.environ.copy())
            processes.append((partition, process, log_handle))
            print(f"started {plan['game_id']} {stem}: seeds {partition['seed_start']}–"
                  f"{partition['seed_end_inclusive']} pid={process.pid}", flush=True)

        failures = []
        for partition, process, log_handle in processes:
            status = process.wait()
            log_handle.close()
            if status:
                failures.append({"worker": partition["worker"], "exit_code": status})
                print(f"failed {plan['game_id']} worker-{partition['worker']:02d}: exit {status}",
                      flush=True)
            else:
                print(f"finished {plan['game_id']} worker-{partition['worker']:02d}", flush=True)
        if failures:
            header.update({"status": "worker_failure", "worker_failures": failures,
                           "finished_at_utc": datetime.now(timezone.utc).isoformat()})
            write_json(output_dir / "run-header.json", header)
            return 1

        audit_path = audit_root / f"{args.run_id}-{plan['matchup']}.json"
        audit_cmd = [str(python), str(audit_script), "--run-root", str(run_root),
                     "--matchup", plan["matchup"], "--games", str(args.games),
                     "--workers", str(args.workers), "--seed-start", str(args.seed_start),
                     "--artifact-directory", args.run_id, "--output", str(audit_path)]
        audit = subprocess.run(audit_cmd, cwd=source_root, capture_output=True, text=True)
        if audit.returncode:
            header.update({"status": "audit_failed", "audit_output": audit.stdout + audit.stderr,
                           "audit_path": str(audit_path),
                           "finished_at_utc": datetime.now(timezone.utc).isoformat()})
            write_json(output_dir / "run-header.json", header)
            print(audit.stdout + audit.stderr, file=sys.stderr, flush=True)
            return audit.returncode
        audit_summary = json.loads(audit_path.read_text(encoding="utf-8"))
        matchup_audit = audit_summary["matchups"][0]
        if audit_summary.get("status") != "complete" or matchup_audit.get("accounted_seed_count") != args.games:
            header.update({"status": "audit_incomplete", "audit_path": str(audit_path),
                           "audit_status": audit_summary.get("status"),
                           "accounted_seed_count": matchup_audit.get("accounted_seed_count"),
                           "finished_at_utc": datetime.now(timezone.utc).isoformat()})
            write_json(output_dir / "run-header.json", header)
            return 1

        report_cmd = [str(python), str(report_script), "--run", str(output_dir),
                      "--output-dir", str(report_root / plan["matchup"])]
        report = subprocess.run(report_cmd, cwd=source_root, capture_output=True, text=True)
        if report.returncode:
            header.update({"status": "report_failed", "report_output": report.stdout + report.stderr,
                           "finished_at_utc": datetime.now(timezone.utc).isoformat()})
            write_json(output_dir / "run-header.json", header)
            print(report.stdout + report.stderr, file=sys.stderr, flush=True)
            return report.returncode

        hashes = {path.name: sha256(path) for path in sorted(output_dir.glob("worker-*.json*"))
                  if path.is_file() and not path.name.endswith(".gz")}
        try:
            compressed_manifest = _compress_worker_artifacts(output_dir)
        except Exception as exc:
            header.update({"status": "artifact_compression_failed", "worker_artifact_sha256": hashes,
                           "compression_error": f"{type(exc).__name__}: {exc}",
                           "finished_at_utc": datetime.now(timezone.utc).isoformat()})
            write_json(output_dir / "run-header.json", header)
            raise
        header.update({"status": "completed_10k_accounted", "accounted_seed_count": args.games,
                       "audit_path": str(audit_path), "audit_sha256": sha256(audit_path),
                       "report_root": str(report_root / plan["matchup"]),
                       "worker_artifact_sha256": hashes,
                       "stored_worker_artifact_sha256": {
                           row["stored_name"]: row["stored_sha256"] for row in compressed_manifest
                       },
                       "worker_artifact_storage": compressed_manifest,
                       "finished_at_utc": datetime.now(timezone.utc).isoformat()})
        write_json(output_dir / "run-header.json", header)
        print(f"completed {plan['game_id']}: {args.games} seeds; audit={audit_path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("/root/legendarypicks-slc-yardage-fix-2026-11-01"))
    parser.add_argument("--python", type=Path, default=Path("/root/slc-week1-7/.venv/bin/python"))
    parser.add_argument("--run-root", type=Path, default=Path("/root/slc-week8-player-workload-10k-2026-10-30"))
    parser.add_argument("--run-id", default="realism-followup-v1-full-stack-2026-11-01-r3")
    parser.add_argument("--games", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.games != 10000 or args.workers != 6 or args.seed_start != 1:
        parser.error("this launch is pinned to six workers and seeds 1–10,000")
    try:
        return launch(args)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
