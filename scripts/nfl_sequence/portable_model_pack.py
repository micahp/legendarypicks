#!/usr/bin/env python3
"""Trusted, hash-pinned SLC in-memory reference snapshot for offline inference.

This is an internal transport format, not an untrusted interchange format:
reference.pkl uses pickle and MUST NOT be loaded unless the entire pack matches
an independently supplied SHA-256 and the code commit is pinned. It never calls
any reference builder, SQLite loader, or fixture loader.

A production pack is emitted by a trusted model-build process *after* all
reference layers and game overlays have been resolved. Missing overtime support
is a build-time failure, not a per-seed regulation-only downgrade.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import pickle
import sys
import tempfile
import zipfile


SCHEMA = "lp-slc-portable-model-pack-1"
ARCHIVE_FILES = frozenset(("manifest.json", "reference.pkl"))
MAX_PAYLOAD_BYTES = 1 << 30  # 1 GiB uncompressed hard cap; validate before allocating.


class ModelPackError(ValueError):
    """A portable reference is incomplete, incompatible or untrusted."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _required_reference(reference):
    """Validate the minimum full-game closure before serializing or simulating."""
    missing = []
    overtime = getattr(reference, "overtime_pool", None)
    if not overtime:
        missing.append("MISSING_REQUIRED_OVERTIME_POOL")
    if getattr(reference, "safety_kick_pool", None) is None:
        missing.append("MISSING_REQUIRED_SAFETY_KICK_POOL")
    if not getattr(reference, "pool", None):
        missing.append("MISSING_REQUIRED_PLAY_POOL")
    if not getattr(reference, "kickoff_pool", None):
        missing.append("MISSING_REQUIRED_KICKOFF_POOL")
    if not getattr(reference, "kicks", None):
        missing.append("MISSING_REQUIRED_KICK_OUTCOMES")
    if missing:
        raise ModelPackError("; ".join(missing))
    sampler = getattr(reference, "contextual_sampler", None)
    if sampler is not None and getattr(sampler, "participant_chooser", None) is not None:
        raise ModelPackError("REFERENCE_HAS_ACTIVE_GAME_STATE: compile before executing seeds")
    return {
        "overtime_pool_samples": len(overtime),
        "safety_kick_pool_samples": len(reference.safety_kick_pool),
        "play_cells": len(reference.pool),
        "kickoff_pool_samples": len(reference.kickoff_pool),
    }


def _reference_sha(reference):
    model_inputs = getattr(reference, "model_inputs", None)
    if not isinstance(model_inputs, dict) or not isinstance(model_inputs.get("sha256"), str):
        raise ModelPackError("REFERENCE_FINGERPRINT_MISSING: compile after reference fingerprinting")
    return model_inputs["sha256"]


def write_pack(path, *, reference, snapshot, model_id, code_commit, config=None):
    """Write an immutable, internally trusted single-file pack; return its SHA-256.

    Call after the existing data-host loader has finished ALL model and
    rules-specific initialization, and before any seed changes the reference.
    Does not refit, fetch, or independently reinterpret inputs.
    """
    if not model_id or not code_commit:
        raise ModelPackError("MODEL_ID_AND_CODE_COMMIT_REQUIRED")
    if not isinstance(snapshot, dict) or "snapshot_sha256" not in snapshot:
        raise ModelPackError("FROZEN_GAME_SNAPSHOT_REQUIRED")
    if not (snapshot.get("schedule") or {}).get("game_id") or not snapshot.get("as_of"):
        raise ModelPackError("SNAPSHOT_GAME_ID_AND_CUTOFF_REQUIRED")
    checks = _required_reference(reference)
    ref_hash = _reference_sha(reference)
    # A game overlay is part of this execution pack, preventing an accidentally
    # reused week/roster from being treated as the same fitted reference.
    payload = pickle.dumps(
        {"reference": reference, "snapshot": snapshot, "config": config or {}},
        protocol=pickle.HIGHEST_PROTOCOL,
    )
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ModelPackError("PAYLOAD_TOO_LARGE")
    manifest = {
        "schema": SCHEMA,
        "model_id": str(model_id),
        "model_code_commit": str(code_commit),
        "game_id": snapshot["schedule"]["game_id"],
        "as_of_utc": snapshot["as_of"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "reference_sha256": ref_hash,
        "python_abi": list(sys.version_info[:2]),
        "full_game_capable": True,
        "checks": checks,
        "payload_sha256": _sha256(payload),
        "payload_bytes": len(payload),
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"immutable pack exists: {destination}")
    # Atomic no-overwrite publication. A racing writer is rejected.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=destination.name + ".", suffix=".tmp",
                                         dir=destination.parent, delete=False) as handle:
            temp_path = Path(handle.name)
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            archive.writestr("manifest.json", _json(manifest))
            archive.writestr("reference.pkl", payload)
        data_sha = _sha256(temp_path.read_bytes())
        # Atomic create-only publication on the same filesystem.
        # os.replace() would overwrite if another builder won the race.
        os.link(temp_path, destination)
        return {"sha256": data_sha, "manifest": manifest, "path": str(destination)}
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def load_pack(path, *, expected_sha256, expected_code_commit):
    """Load only an externally SHA-pinned pack with matching code/ABI.

    WARNING: Python pickle can execute code on unpickle. Packs must be produced
    by the trusted internal builder, with the pack SHA pinned OUTSIDE the pack.
    """
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ModelPackError("EXTERNAL_PACK_SHA256_REQUIRED")
    if not expected_code_commit:
        raise ModelPackError("EXPECTED_CODE_COMMIT_REQUIRED")
    package = Path(path).read_bytes()
    if _sha256(package) != expected_sha256:
        raise ModelPackError("PACK_SHA256_MISMATCH")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        entries = archive.namelist()
        if len(entries) != len(ARCHIVE_FILES) or set(entries) != ARCHIVE_FILES:
            raise ModelPackError("PACK_ENTRIES_UNEXPECTED")
        file_info = archive.getinfo("reference.pkl")
        if file_info.file_size > MAX_PAYLOAD_BYTES:
            raise ModelPackError("PAYLOAD_TOO_LARGE")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != SCHEMA:
            raise ModelPackError("PACK_SCHEMA_MISMATCH")
        if manifest.get("model_code_commit") != expected_code_commit:
            raise ModelPackError("MODEL_CODE_COMMIT_MISMATCH")
        if manifest.get("python_abi") != list(sys.version_info[:2]):
            raise ModelPackError("PYTHON_ABI_MISMATCH")
        if manifest.get("full_game_capable") is not True:
            raise ModelPackError("NOT_A_FULL_GAME_MODEL")
        payload = archive.read("reference.pkl")
        if len(payload) != manifest.get("payload_bytes") or _sha256(payload) != manifest.get("payload_sha256"):
            raise ModelPackError("PACK_PAYLOAD_HASH_MISMATCH")
    loaded = pickle.loads(payload)  # safe only under the externally pinned, trusted-pack requirement above
    ref, snapshot = loaded["reference"], loaded["snapshot"]
    checks = _required_reference(ref)
    if any(manifest["checks"].get(k) != v for k, v in checks.items()):
        raise ModelPackError("REFERENCE_SUPPORT_COUNTS_CHANGED")
    if _reference_sha(ref) != manifest["reference_sha256"]:
        raise ModelPackError("REFERENCE_HASH_CHANGED")
    if (snapshot.get("snapshot_sha256") != manifest["snapshot_sha256"]
            or snapshot.get("as_of") != manifest["as_of_utc"]
            or (snapshot.get("schedule") or {}).get("game_id") != manifest["game_id"]):
        raise ModelPackError("GAME_OVERLAY_CHANGED")
    return ref, snapshot, manifest, loaded.get("config") or {}
