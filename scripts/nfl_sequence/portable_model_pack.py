#!/usr/bin/env python3
"""Versioned SLC reference and executable-code package for offline inference.

The reference state uses a tagged, schema-checked JSON codec. It never calls
any reference builder, SQLite loader, fixture loader, or pickle deserializer.

A production pack is emitted by a trusted model-build process *after* all
reference layers and game overlays have been resolved. Missing overtime support
is a build-time failure, not a per-seed regulation-only downgrade.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib
import base64
import builtins
from collections import Counter, defaultdict, deque
import enum
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import types
import zipfile
from pathlib import PurePosixPath


SCHEMA = "lp-slc-portable-model-pack-1"
MAX_PAYLOAD_BYTES = 1 << 30  # 1 GiB uncompressed hard cap; validate before allocating.
MAX_ARCHIVE_BYTES = 2 << 30
RUNTIME_DISTRIBUTIONS = ("numpy", "scipy")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ModelPackError(ValueError):
    """A portable reference is incomplete, incompatible or untrusted."""


def runtime_dependencies():
    try:
        return {name: importlib.metadata.version(name) for name in RUNTIME_DISTRIBUTIONS}
    except importlib.metadata.PackageNotFoundError as exc:
        raise ModelPackError("RUNTIME_DEPENDENCY_MISSING: " + exc.name) from exc


def _encode_state(value, active=None):
    """Encode supported runtime state as tagged JSON data, never executable pickle."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"$type": "float", "value": "nan" if math.isnan(value) else "inf" if value > 0 else "-inf"}
    identity = id(value)
    if identity in active:
        raise ModelPackError("MODEL_STATE_CYCLE_UNSUPPORTED")
    active.add(identity)
    try:
        if isinstance(value, bytes):
            return {"$type": "bytes", "value": base64.b64encode(value).decode("ascii")}
        if isinstance(value, Path):
            return {"$type": "path", "value": str(value)}
        if isinstance(value, enum.Enum):
            return {"$type": "enum", "class": value.__class__.__module__ + ":" + value.__class__.__qualname__,
                    "value": _encode_state(value.value, active)}
        try:
            import numpy as np
        except ImportError:
            np = None
        if np is not None and isinstance(value, np.ndarray):
            if value.dtype.hasobject:
                raise ModelPackError("OBJECT_NUMPY_ARRAY_UNSUPPORTED")
            contiguous = np.ascontiguousarray(value)
            return {"$type": "ndarray", "dtype": contiguous.dtype.str,
                    "shape": list(contiguous.shape),
                    "value": base64.b64encode(contiguous.tobytes()).decode("ascii")}
        if np is not None and isinstance(value, np.generic):
            return {"$type": "numpy_scalar", "dtype": value.dtype.str,
                    "value": _encode_state(value.item(), active)}
        if isinstance(value, Counter):
            return {"$type": "counter", "items": [[_encode_state(k, active), _encode_state(v, active)]
                                                    for k, v in value.items()]}
        if isinstance(value, defaultdict):
            factory = value.default_factory
            name = getattr(factory, "__name__", None) if factory else None
            if factory is not None and (getattr(factory, "__module__", None) != "builtins"
                                        or name not in {"int", "list", "set", "dict"}):
                raise ModelPackError("DEFAULT_FACTORY_UNSUPPORTED")
            return {"$type": "defaultdict", "factory": name,
                    "items": [[_encode_state(k, active), _encode_state(v, active)]
                              for k, v in value.items()]}
        if isinstance(value, dict):
            return {"$type": "dict", "items": [[_encode_state(k, active), _encode_state(v, active)]
                                               for k, v in value.items()]}
        if isinstance(value, tuple):
            return {"$type": "tuple", "items": [_encode_state(x, active) for x in value]}
        if isinstance(value, list):
            return {"$type": "list", "items": [_encode_state(x, active) for x in value]}
        if isinstance(value, (set, frozenset)):
            return {"$type": "frozenset" if isinstance(value, frozenset) else "set",
                    "items": [_encode_state(x, active) for x in sorted(value, key=repr)]}
        if isinstance(value, deque):
            return {"$type": "deque", "items": [_encode_state(x, active) for x in value], "maxlen": value.maxlen}
        attrs = getattr(value, "__dict__", None)
        if attrs is None:
            raise ModelPackError("MODEL_STATE_TYPE_UNSUPPORTED: " + type(value).__module__ + "." + type(value).__qualname__)
        cls = type(value)
        return {"$type": "object", "class": cls.__module__ + ":" + cls.__qualname__,
                "attrs": _encode_state(attrs, active)}
    finally:
        active.remove(identity)


def _resolve_class(name, allowed_modules=None):
    module_name, separator, qualname = name.partition(":")
    if not separator or not module_name or not qualname or module_name.startswith("_"):
        raise ModelPackError("MODEL_STATE_CLASS_INVALID")
    if allowed_modules is not None and module_name not in allowed_modules:
        raise ModelPackError("MODEL_STATE_CLASS_OUTSIDE_BUNDLE")
    module = importlib.import_module(module_name)
    cls = module
    for part in qualname.split("."):
        cls = getattr(cls, part)
    if not isinstance(cls, type):
        raise ModelPackError("MODEL_STATE_CLASS_INVALID")
    return cls


def _decode_state(value, allowed_modules=None):
    if not isinstance(value, dict) or "$type" not in value:
        return value
    kind = value["$type"]
    if kind == "float":
        return {"nan": float("nan"), "inf": float("inf"), "-inf": -float("inf")}[value["value"]]
    if kind == "bytes":
        return base64.b64decode(value["value"], validate=True)
    if kind == "path":
        return Path(value["value"])
    if kind == "ndarray":
        import numpy as np
        array = np.frombuffer(base64.b64decode(value["value"], validate=True), dtype=np.dtype(value["dtype"]))
        return array.reshape(tuple(value["shape"])).copy()
    if kind == "numpy_scalar":
        import numpy as np
        return np.asarray(_decode_state(value["value"]), dtype=np.dtype(value["dtype"]))[()]
    if kind == "enum":
        return _resolve_class(value["class"], allowed_modules)(_decode_state(value["value"], allowed_modules))
    if kind in {"dict", "counter", "defaultdict"}:
        items = [(_decode_state(k, allowed_modules), _decode_state(v, allowed_modules)) for k, v in value["items"]]
        if kind == "counter":
            return Counter(dict(items))
        if kind == "defaultdict":
            factory = getattr(builtins, value["factory"]) if value.get("factory") else None
            return defaultdict(factory, dict(items))
        return dict(items)
    if kind == "tuple":
        return tuple(_decode_state(x, allowed_modules) for x in value["items"])
    if kind == "list":
        return [_decode_state(x, allowed_modules) for x in value["items"]]
    if kind == "set":
        return set(_decode_state(x, allowed_modules) for x in value["items"])
    if kind == "frozenset":
        return frozenset(_decode_state(x, allowed_modules) for x in value["items"])
    if kind == "deque":
        return deque((_decode_state(x, allowed_modules) for x in value["items"]), maxlen=value.get("maxlen"))
    if kind == "object":
        cls = _resolve_class(value["class"], allowed_modules)
        instance = types.SimpleNamespace() if cls is types.SimpleNamespace else object.__new__(cls)
        for key, child in _decode_state(value["attrs"], allowed_modules).items():
            object.__setattr__(instance, key, child)
        return instance
    raise ModelPackError("MODEL_STATE_TYPE_UNKNOWN: " + str(kind))


def collect_engine_files(engine_root, code_commit):
    """Read the pinned Python runtime tree from git, never from a dirty checkout."""
    root = Path(engine_root).resolve()
    status = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], text=True
    )
    if status.strip():
        raise ModelPackError("DIRTY_MODEL_CODE: commit tracked changes before packaging")
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if actual != code_commit:
        raise ModelPackError("MODEL_CODE_COMMIT_MISMATCH")
    names = subprocess.check_output(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", code_commit], text=True
    ).splitlines()
    selected = [name for name in names if
                (name.startswith("scripts/nfl_sequence/") and name.endswith(".py")) or
                (name.startswith("backend/") and name.endswith(".py")) or
                name.startswith("docs/rules/")]
    if not any(name == "scripts/nfl_sequence/game_state.py" for name in selected):
        raise ModelPackError("BUNDLED_ENGINE_ENTRYPOINT_MISSING")
    result = {}
    for name in selected:
        result[name] = subprocess.check_output(
            ["git", "-C", str(root), "show", f"{code_commit}:{name}"]
        )
    return result


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _hash_fields(value, prefix=""):
    found = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if "sha256" in str(key).lower() and isinstance(child, str) and len(child) == 64:
                found[name] = child
            else:
                found.update(_hash_fields(child, name))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.update(_hash_fields(child, f"{prefix}[{index}]"))
    return found


def _required_reference(reference):
    """Validate the minimum full-game closure before serializing or simulating."""
    missing = []
    overtime = getattr(reference, "overtime_pool", None)
    if overtime is None:
        missing.append("MISSING_REQUIRED_OVERTIME_POOL")
    else:
        try:
            if len(overtime) == 0:
                missing.append("EMPTY_REQUIRED_OVERTIME_POOL")
        except TypeError:
            missing.append("INVALID_REQUIRED_OVERTIME_POOL")
    safety = getattr(reference, "safety_kick_pool", None)
    if not safety:
        missing.append("MISSING_REQUIRED_SAFETY_KICK_POOL")
    if not getattr(reference, "pool", None):
        missing.append("MISSING_REQUIRED_PLAY_POOL")
    if not getattr(reference, "kickoff_pool", None):
        missing.append("MISSING_REQUIRED_KICKOFF_POOL")
    kicks = getattr(reference, "kicks", None) or {}
    if not kicks:
        missing.append("MISSING_REQUIRED_KICK_OUTCOMES")
    elif (not kicks.get("field_goal_outcomes") or not kicks.get("extra_point")
          or not kicks.get("two_point")):
        missing.append("INCOMPLETE_REQUIRED_KICK_OUTCOMES")
    if not getattr(reference, "participants", None):
        missing.append("MISSING_REQUIRED_PARTICIPANT_REFERENCE")
    if not getattr(reference, "missed_field_goal_pool", None):
        missing.append("MISSING_REQUIRED_MISSED_FIELD_GOAL_POOL")
    try_fallback = getattr(reference, "overtime_try_p_two", None)
    required_try_buckets = {"<=-9", "-8..-5", "-4..-1", "0", "1..4", "5..8", ">=9"}
    if not isinstance(try_fallback, dict) or not required_try_buckets.issubset(try_fallback):
        missing.append("MISSING_REQUIRED_OVERTIME_TRY_FALLBACK")
    elif any(not isinstance(try_fallback[key], (int, float))
             or not math.isfinite(float(try_fallback[key]))
             or not 0.0 <= float(try_fallback[key]) <= 1.0
             for key in required_try_buckets):
        missing.append("INVALID_REQUIRED_OVERTIME_TRY_FALLBACK")
    choice_probability = getattr(reference, "overtime_p_kick", None)
    if (not isinstance(choice_probability, (int, float))
            or not math.isfinite(float(choice_probability))
            or not 0.0 <= float(choice_probability) <= 1.0):
        missing.append("MISSING_OR_INVALID_REQUIRED_OVERTIME_KICK_MODEL")
    blocked = getattr(reference, "blocked_kicks", None) or {}
    rates = blocked.get("rates") or {}
    records = blocked.get("records") or {}
    if (not rates.get("punt_blocked") or not rates.get("field_goal_blocked_by_snap_bucket")
            or "punt" not in records or "field_goal" not in records):
        missing.append("MISSING_REQUIRED_BLOCKED_KICK_SUPPORT")
    if missing:
        raise ModelPackError("; ".join(missing))
    sampler = getattr(reference, "contextual_sampler", None)
    if sampler is not None and getattr(sampler, "participant_chooser", None) is not None:
        raise ModelPackError("REFERENCE_HAS_ACTIVE_GAME_STATE: compile before executing seeds")
    return {
        "overtime_pool_samples": len(overtime),
        "safety_kick_pool_samples": len(safety),
        "play_cells": len(reference.pool),
        "kickoff_pool_samples": len(reference.kickoff_pool),
    }


def _reference_sha(reference):
    model_inputs = getattr(reference, "model_inputs", None)
    if not isinstance(model_inputs, dict) or not isinstance(model_inputs.get("sha256"), str):
        raise ModelPackError("REFERENCE_FINGERPRINT_MISSING: compile after reference fingerprinting")
    return model_inputs["sha256"]


def write_pack(path, *, reference, snapshot, model_id, code_commit, config=None, engine_files=None):
    """Write an immutable, internally trusted single-file pack; return its SHA-256.

    Call after the existing data-host loader has finished ALL model and
    rules-specific initialization, and before any seed changes the reference.
    Does not refit, fetch, or independently reinterpret inputs.
    """
    if not model_id or not isinstance(code_commit, str) or not GIT_COMMIT_RE.fullmatch(code_commit):
        raise ModelPackError("MODEL_ID_AND_CODE_COMMIT_REQUIRED")
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("snapshot_sha256"), str)
            or not SHA256_RE.fullmatch(snapshot["snapshot_sha256"])):
        raise ModelPackError("FROZEN_GAME_SNAPSHOT_REQUIRED")
    if not (snapshot.get("schedule") or {}).get("game_id") or not snapshot.get("as_of"):
        raise ModelPackError("SNAPSHOT_GAME_ID_AND_CUTOFF_REQUIRED")
    checks = _required_reference(reference)
    ref_hash = _reference_sha(reference)
    if not isinstance(ref_hash, str) or not SHA256_RE.fullmatch(ref_hash):
        raise ModelPackError("REFERENCE_FINGERPRINT_INVALID")
    # A game overlay is part of this execution pack, preventing an accidentally
    # reused week/roster from being treated as the same fitted reference.
    payload = _json({"schema": "lp-slc-model-state-1", "reference": _encode_state(reference),
                     "snapshot": snapshot, "config": config or {}})
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ModelPackError("PAYLOAD_TOO_LARGE")
    engine_files = engine_files or {}
    if not engine_files or "scripts/nfl_sequence/game_state.py" not in engine_files:
        raise ModelPackError("BUNDLED_ENGINE_CODE_REQUIRED")
    engine_hashes = {name: _sha256(data) for name, data in sorted(engine_files.items())}
    source_hashes = _hash_fields(config or {})
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
        "engine_files_sha256": engine_hashes,
        "rules_policy": (config or {}).get("rules_policy"),
        "enabled_layers": (config or {}).get("enabled_layers", []),
        "experimental_flags": (config or {}).get("experimental_flags", {}),
        "training_cutoff": (config or {}).get("training_cutoff"),
        "runtime_dependencies": (config or {}).get("runtime_dependencies") or runtime_dependencies(),
        "source_artifact_sha256": source_hashes,
        "layer_manifest": (config or {}).get("model_profile", {}).get("layers", {}),
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
            archive.writestr("reference.json", payload)
            for name, data in sorted(engine_files.items()):
                archive.writestr("engine/" + name, data)
        data_sha = _sha256(temp_path.read_bytes())
        # Atomic create-only publication on the same filesystem.
        # os.replace() would overwrite if another builder won the race.
        os.link(temp_path, destination)
        return {"sha256": data_sha, "manifest": manifest, "path": str(destination)}
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def load_pack(path, *, expected_sha256, expected_code_commit, engine_dir=None):
    """Load an externally SHA-pinned pack with matching code/ABI."""
    if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256):
        raise ModelPackError("EXTERNAL_PACK_SHA256_REQUIRED")
    if not isinstance(expected_code_commit, str) or not GIT_COMMIT_RE.fullmatch(expected_code_commit):
        raise ModelPackError("EXPECTED_CODE_COMMIT_REQUIRED")
    if Path(path).stat().st_size > MAX_ARCHIVE_BYTES:
        raise ModelPackError("PACK_TOO_LARGE")
    package = Path(path).read_bytes()
    if _sha256(package) != expected_sha256:
        raise ModelPackError("PACK_SHA256_MISMATCH")
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        entries = archive.namelist()
        if len(entries) < 3 or len(entries) != len(set(entries)):
            raise ModelPackError("PACK_ENTRIES_UNEXPECTED")
        if not {"manifest.json", "reference.json"}.issubset(entries):
            raise ModelPackError("PACK_ENTRIES_UNEXPECTED")
        file_info = archive.getinfo("reference.json")
        if file_info.file_size > MAX_PAYLOAD_BYTES:
            raise ModelPackError("PAYLOAD_TOO_LARGE")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != SCHEMA:
            raise ModelPackError("PACK_SCHEMA_MISMATCH")
        if manifest.get("model_code_commit") != expected_code_commit:
            raise ModelPackError("MODEL_CODE_COMMIT_MISMATCH")
        if manifest.get("python_abi") != list(sys.version_info[:2]):
            raise ModelPackError("PYTHON_ABI_MISMATCH")
        if manifest.get("runtime_dependencies") != runtime_dependencies():
            raise ModelPackError("RUNTIME_DEPENDENCY_MISMATCH")
        if manifest.get("full_game_capable") is not True:
            raise ModelPackError("NOT_A_FULL_GAME_MODEL")
        engine_hashes = manifest.get("engine_files_sha256")
        if (not isinstance(engine_hashes, dict) or not engine_hashes
                or any(not isinstance(name, str) or not isinstance(digest, str)
                       or not SHA256_RE.fullmatch(digest) for name, digest in engine_hashes.items())):
            raise ModelPackError("BUNDLED_ENGINE_MANIFEST_MISSING")
        expected_names = {"engine/" + name for name in engine_hashes}
        if set(entries) != expected_names | {"manifest.json", "reference.json"}:
            raise ModelPackError("BUNDLED_ENGINE_FILE_MISSING")
        extracted_root = Path(engine_dir) if engine_dir is not None else None
        if extracted_root is None:
            raise ModelPackError("BUNDLED_ENGINE_DESTINATION_REQUIRED")
        extracted_root.mkdir(parents=True, exist_ok=True)
        unpacked_bytes = 0
        for name, expected_hash in engine_hashes.items():
            relative = PurePosixPath(name)
            if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                    or "\\" in name or ":" in name):
                raise ModelPackError("BUNDLED_ENGINE_PATH_INVALID")
            info = archive.getinfo("engine/" + name)
            if info.file_size > MAX_PAYLOAD_BYTES:
                raise ModelPackError("BUNDLED_ENGINE_FILE_TOO_LARGE")
            unpacked_bytes += info.file_size
            if unpacked_bytes > MAX_ARCHIVE_BYTES:
                raise ModelPackError("BUNDLED_ENGINE_TOTAL_TOO_LARGE")
            data = archive.read("engine/" + name)
            if _sha256(data) != expected_hash:
                raise ModelPackError("BUNDLED_ENGINE_HASH_MISMATCH: " + name)
            target = extracted_root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        payload = archive.read("reference.json")
        if len(payload) != manifest.get("payload_bytes") or _sha256(payload) != manifest.get("payload_sha256"):
            raise ModelPackError("PACK_PAYLOAD_HASH_MISMATCH")
    if engine_dir is not None:
        engine_root = Path(engine_dir)
        sys.path.insert(0, str(engine_root / "scripts" / "nfl_sequence"))
        sys.path.insert(1, str(engine_root / "backend"))
    allowed_modules = {PurePosixPath(name).stem for name in manifest["engine_files_sha256"]
                       if name.endswith(".py") and name.startswith(("scripts/nfl_sequence/", "backend/"))}
    allowed_modules.add("types")
    loaded = json.loads(payload)
    if loaded.get("schema") != "lp-slc-model-state-1":
        raise ModelPackError("MODEL_STATE_SCHEMA_MISMATCH")
    if set(loaded) != {"schema", "reference", "snapshot", "config"}:
        raise ModelPackError("MODEL_STATE_FIELDS_MISMATCH")
    ref, snapshot = _decode_state(loaded["reference"], allowed_modules), loaded["snapshot"]
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
