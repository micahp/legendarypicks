"""Non-gating file inventory for SLC runs; never part of model or RNG identity."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

SCHEMA = "lp-nfl-slc-input-inventory-1"
MAX_HASH_BYTES = 32 * 1024 * 1024
INPUT_NAMES = (
    "db", "snapshot_file", "playcall_artifact", "playcall_streak_file",
    "historical_streak_file", "roster_snapshot", "roster_provenance",
    "availability_snapshot", "availability_store", "readiness_matrix",
    "archive_manifest", "archive_root", "seed_list_file",
    "participation_field", "participation_snap_counts",
    "playcall_fg_kicker", "playcall_pbv1_package", "workload_adaptive_input",
    "workload_concentrations", "game_info_snapshot", "paired_layer_baseline_ledger",
    "paired_workload_baseline_ledger", "paired_lineup_baseline_ledger",
    "playcall_point_splits_cache", "playcall_streak_cache",
)


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def observe(path, *, max_hash_bytes=MAX_HASH_BYTES):
    """Missing/unreadable inputs are recorded, not raised by the inventory."""
    path = Path(path).expanduser().absolute()
    record = {"path": str(path)}
    try:
        stat = path.stat()
        record.update(status="directory" if path.is_dir() else "file",
                      size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
                      mtime_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                      .isoformat().replace("+00:00", "Z"), sha256=None)
        if path.is_file() and stat.st_size <= max_hash_bytes:
            h = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    h.update(block)
            record.update(sha256=h.hexdigest(), hash_status="computed")
        else:
            record["hash_status"] = ("skipped_large_input" if path.is_file()
                                     else "not_a_regular_file")
    except OSError as exc:
        record.update(status="unavailable", sha256=None, hash_status="unavailable",
                      error=f"{type(exc).__name__}: {exc}")
    return record


def inspect_args(args):
    result = {}
    for name in INPUT_NAMES:
        value = getattr(args, name, None)
        if value is None or value == "":
            continue
        record = observe(value)
        expected = getattr(args, name + "_sha256", None)
        if expected is not None:
            record["expected_sha256_from_command"] = str(expected)
        result[name] = record
    return result


def git_head(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def begin(args, *, root=None):
    """Write STARTED evidence before model setup. A repeat run gets its own file."""
    if not getattr(args, "out", None):
        return None, None
    target = Path(args.out)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = target.with_name(f"{target.stem}.inputs.{suffix}-{time.time_ns()}.json")
    record = {
        "schema": SCHEMA, "purpose": "observation_only_no_new_model_or_rng_gate",
        "started_at_utc": now(), "status": "started",
        "output": str(target),
        "git_head": git_head(root or Path(__file__).resolve().parents[2]),
        "inputs_before": inspect_args(args), "inputs_after": None,
        "files_changed_during_run": [],
        "note": ("mtime is not source publication time; large inputs are not hashed "
                 "by this diagnostic; model-specific input checks remain unchanged."),
    }
    write(path, record)
    return path, record


def finish(args, path, record, *, status):
    after = inspect_args(args)
    changed = []
    for name, old in record["inputs_before"].items():
        new = after.get(name)
        if new and any(old.get(k) != new.get(k) for k in
                       ("status", "size_bytes", "mtime_ns", "sha256")):
            changed.append(name)
    updated = {**record, "status": status, "finished_at_utc": now(),
               "inputs_after": after, "files_changed_during_run": changed}
    write(path, updated)
    return updated
