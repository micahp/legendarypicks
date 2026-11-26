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
            module = getattr(factory, "__module__", None) if factory else None
            if factory is None:
                factory_tag = None
            elif module == "builtins" and name in {"int", "float", "list", "set", "dict"}:
                factory_tag = name
            elif factory is Counter:
                factory_tag = "collections.Counter"
            else:
                factory_label = (module + "." + getattr(factory, "__qualname__", name or "<unknown>"))
                raise ModelPackError("DEFAULT_FACTORY_UNSUPPORTED: " + factory_label)
            return {"$type": "defaultdict", "factory": factory_tag,
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


def _iter_state_json(value, active=None):
    """Yield the tagged state JSON incrementally to avoid a second model-sized copy."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (str, bool, int)):
        yield json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return
    if isinstance(value, float):
        if math.isfinite(value):
            yield json.dumps(value, separators=(",", ":"))
        else:
            token = "nan" if math.isnan(value) else "inf" if value > 0 else "-inf"
            yield '{"$type":"float","value":' + json.dumps(token) + '}'
        return
    identity = id(value)
    if identity in active:
        raise ModelPackError("MODEL_STATE_CYCLE_UNSUPPORTED")
    active.add(identity)
    try:
        if isinstance(value, bytes):
            yield '{"$type":"bytes","value":'
            yield json.dumps(base64.b64encode(value).decode("ascii"))
            yield '}'
            return
        if isinstance(value, Path):
            yield '{"$type":"path","value":' + json.dumps(str(value), ensure_ascii=False) + '}'
            return
        if isinstance(value, enum.Enum):
            yield '{"$type":"enum","class":'
            yield json.dumps(value.__class__.__module__ + ":" + value.__class__.__qualname__)
            yield ',"value":'
            yield from _iter_state_json(value.value, active)
            yield '}'
            return
        try:
            import numpy as np
        except ImportError:
            np = None
        if np is not None and isinstance(value, np.ndarray):
            if value.dtype.hasobject:
                raise ModelPackError("OBJECT_NUMPY_ARRAY_UNSUPPORTED")
            contiguous = np.ascontiguousarray(value)
            yield '{"$type":"ndarray","dtype":' + json.dumps(contiguous.dtype.str)
            yield ',"shape":' + json.dumps(list(contiguous.shape), separators=(",", ":"))
            yield ',"value":'
            yield json.dumps(base64.b64encode(contiguous.tobytes()).decode("ascii"))
            yield '}'
            return
        if np is not None and isinstance(value, np.generic):
            yield '{"$type":"numpy_scalar","dtype":' + json.dumps(value.dtype.str)
            yield ',"value":'
            yield from _iter_state_json(value.item(), active)
            yield '}'
            return
        if isinstance(value, (Counter, defaultdict, dict)):
            if isinstance(value, Counter):
                tag, entries = "counter", value.items()
            elif isinstance(value, defaultdict):
                factory = value.default_factory
                name = getattr(factory, "__name__", None) if factory else None
                module = getattr(factory, "__module__", None) if factory else None
                if factory is None:
                    factory_tag = None
                elif module == "builtins" and name in {"int", "float", "list", "set", "dict"}:
                    factory_tag = name
                elif factory is Counter:
                    factory_tag = "collections.Counter"
                else:
                    factory_label = module + "." + getattr(factory, "__qualname__", name or "<unknown>")
                    raise ModelPackError("DEFAULT_FACTORY_UNSUPPORTED: " + factory_label)
                tag, entries = "defaultdict", value.items()
            else:
                tag, entries = "dict", value.items()
            yield '{"$type":' + json.dumps(tag)
            if isinstance(value, defaultdict):
                yield ',"factory":' + json.dumps(factory_tag)
            yield ',"items":['
            for index, (key, item) in enumerate(entries):
                if index:
                    yield ','
                yield '['
                yield from _iter_state_json(key, active)
                yield ','
                yield from _iter_state_json(item, active)
                yield ']'
            yield ']}'
            return
        if isinstance(value, (tuple, list, set, frozenset)):
            if isinstance(value, tuple):
                tag, items = "tuple", value
            elif isinstance(value, list):
                tag, items = "list", value
            elif isinstance(value, frozenset):
                tag, items = "frozenset", sorted(value, key=repr)
            else:
                tag, items = "set", sorted(value, key=repr)
            yield '{"$type":' + json.dumps(tag) + ',"items":['
            for index, item in enumerate(items):
                if index:
                    yield ','
                yield from _iter_state_json(item, active)
            yield ']}'
            return
        if isinstance(value, deque):
            yield '{"$type":"deque","items":['
            for index, item in enumerate(value):
                if index:
                    yield ','
                yield from _iter_state_json(item, active)
            yield '],"maxlen":'
            yield from _iter_state_json(value.maxlen, active)
            yield '}'
            return
        attrs = getattr(value, "__dict__", None)
        if attrs is None:
            raise ModelPackError("MODEL_STATE_TYPE_UNSUPPORTED: " + type(value).__module__ + "." + type(value).__qualname__)
        cls = type(value)
        yield '{"$type":"object","attrs":'
        yield from _iter_state_json(attrs, active)
        yield ',"class":' + json.dumps(cls.__module__ + ":" + cls.__qualname__)
        yield '}'
    finally:
        active.remove(identity)


def _write_state_payload(stream, reference, snapshot, config):
    digest = hashlib.sha256()
    size = 0
    pending = bytearray()

    def flush():
        nonlocal size
        if pending:
            size += len(pending)
            if size > MAX_PAYLOAD_BYTES:
                raise ModelPackError("PAYLOAD_TOO_LARGE")
            digest.update(pending)
            stream.write(pending)
            pending.clear()

    # Match the canonical key order used by _json(sort_keys=True).
    chunks = iter((
        '{"config":', json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        ',"reference":',
    ))
    for chunk in chunks:
        pending.extend(chunk.encode("utf-8"))
    for chunk in _iter_state_json(reference):
        pending.extend(chunk.encode("utf-8"))
        if len(pending) >= 1 << 20:
            flush()
    pending.extend(b',"schema":"lp-slc-model-state-1","snapshot":')
    pending.extend(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    pending.extend(b'}\n')
    flush()
    return digest.hexdigest(), size


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
            tag = value.get("factory")
            if tag == "collections.Counter":
                factory = Counter
            else:
                factory = getattr(builtins, tag) if tag else None
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


class _HashingRawReader(io.RawIOBase):
    """Hash an uncompressed archive member as its streaming JSON parser reads it."""
    def __init__(self, source):
        self.source = source
        self.digest = hashlib.sha256()
        self.size = 0

    def readable(self):
        return True

    def readinto(self, target):
        chunk = self.source.read(len(target))
        if not chunk:
            return 0
        self.digest.update(chunk)
        self.size += len(chunk)
        if self.size > MAX_PAYLOAD_BYTES:
            raise ModelPackError("PAYLOAD_TOO_LARGE")
        target[:len(chunk)] = chunk
        return len(chunk)


class _StateJSONReader:
    """Incrementally parse tagged state JSON directly into runtime objects."""
    def __init__(self, stream, allowed_modules):
        self.stream = stream
        self.allowed_modules = allowed_modules
        self.decoder = json.JSONDecoder()
        self.buffer = ""
        self.pos = 0
        self.eof = False

    def _fill(self):
        if self.pos:
            self.buffer = self.buffer[self.pos:]
            self.pos = 0
        chunk = self.stream.read(65536)
        if chunk:
            self.buffer += chunk
        else:
            self.eof = True

    def _peek(self):
        while self.pos >= len(self.buffer) and not self.eof:
            self._fill()
        return self.buffer[self.pos] if self.pos < len(self.buffer) else ""

    def _take(self, expected):
        self._skip_ws()
        if self._peek() != expected:
            raise ModelPackError("MODEL_STATE_JSON_INVALID: expected %r, got %r" %
                                 (expected, self._peek()))
        self.pos += 1

    def _skip_ws(self):
        while True:
            ch = self._peek()
            if ch and ch in " \t\r\n":
                self.pos += 1
            else:
                return

    def _scalar(self):
        while True:
            self._skip_ws()
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.pos)
            except json.JSONDecodeError:
                if self.eof:
                    raise ModelPackError("MODEL_STATE_JSON_INVALID")
                self._fill()
                continue
            # JSONDecoder accepts a numeric prefix (`1` in `1.25`) when the
            # following byte is already buffered. Do not accept it until the
            # number's delimiter is visible. Also wait at chunk edges because
            # the next byte may continue the token.
            number_continuation = (end < len(self.buffer)
                                   and isinstance(value, (int, float))
                                   and not isinstance(value, bool)
                                   and self.buffer[end] in ".eE0123456789")
            if not self.eof and (end == len(self.buffer) or number_continuation):
                self._fill()
                continue
            self.pos = end
            return value

    def _field(self, expected):
        self._take(",")
        key = self._scalar()
        if key != expected:
            raise ModelPackError("MODEL_STATE_FIELD_ORDER_INVALID")
        self._take(":")

    def _array(self, convert=None):
        self._take("[")
        values = [] if convert is None else convert()
        self._skip_ws()
        if self._peek() == "]":
            self.pos += 1
            return values
        while True:
            value = self._value()
            if convert is None:
                values.append(value)
            else:
                convert(values, value)
            self._skip_ws()
            ch = self._peek()
            if ch == "]":
                self.pos += 1
                return values
            self._take(",")

    def _pairs(self, target):
        self._take("[")
        self._skip_ws()
        if self._peek() == "]":
            self.pos += 1
            return target
        while True:
            self._take("[")
            key = self._value()
            self._take(",")
            value = self._value()
            self._take("]")
            target[key] = value
            self._skip_ws()
            ch = self._peek()
            if ch == "]":
                self.pos += 1
                return target
            self._take(",")

    def _object(self):
        self._take("{")
        self._skip_ws()
        if self._peek() == "}":
            self.pos += 1
            return {}
        first_key = self._scalar()
        self._take(":")
        if first_key == "$type":
            return self._typed(self._scalar())
        result = {first_key: self._value()}
        self._skip_ws()
        while self._peek() == ",":
            self.pos += 1
            key = self._scalar()
            self._take(":")
            if key in result:
                raise ModelPackError("MODEL_STATE_DUPLICATE_JSON_KEY")
            result[key] = self._value()
            self._skip_ws()
        self._take("}")
        return result

    def _typed(self, kind):
        if kind == "float":
            self._field("value")
            token = self._scalar()
            self._take("}")
            if token not in {"nan", "inf", "-inf"}:
                raise ModelPackError("MODEL_STATE_FLOAT_INVALID")
            return {"nan": float("nan"), "inf": float("inf"), "-inf": -float("inf")}[token]
        if kind in {"bytes", "path"}:
            self._field("value")
            value = self._scalar()
            self._take("}")
            return base64.b64decode(value, validate=True) if kind == "bytes" else Path(value)
        if kind == "enum":
            self._field("class")
            class_name = self._scalar()
            self._field("value")
            value = self._value()
            self._take("}")
            return _resolve_class(class_name, self.allowed_modules)(value)
        if kind == "ndarray":
            self._field("dtype")
            dtype = self._scalar()
            self._field("shape")
            shape = self._array()
            self._field("value")
            value = self._scalar()
            self._take("}")
            import numpy as np
            array = np.frombuffer(base64.b64decode(value, validate=True), dtype=np.dtype(dtype))
            return array.reshape(tuple(shape)).copy()
        if kind == "numpy_scalar":
            self._field("dtype")
            dtype = self._scalar()
            self._field("value")
            value = self._value()
            self._take("}")
            import numpy as np
            return np.asarray(value, dtype=np.dtype(dtype))[()]
        if kind in {"dict", "counter", "defaultdict"}:
            factory_tag = None
            if kind == "defaultdict":
                self._field("factory")
                factory_tag = self._scalar()
            self._field("items")
            if kind == "counter":
                result = Counter()
            elif kind == "defaultdict":
                factories = {"int": int, "float": float, "list": list, "set": set,
                             "dict": dict, "collections.Counter": Counter}
                if factory_tag is not None and factory_tag not in factories:
                    raise ModelPackError("DEFAULT_FACTORY_TAG_INVALID")
                result = defaultdict(factories.get(factory_tag) if factory_tag else None)
            else:
                result = {}
            self._pairs(result)
            self._take("}")
            return result
        if kind in {"list", "tuple", "set", "frozenset"}:
            self._field("items")
            items = self._array()
            self._take("}")
            if kind == "tuple":
                return tuple(items)
            if kind == "set":
                return set(items)
            if kind == "frozenset":
                return frozenset(items)
            return items
        if kind == "deque":
            self._field("items")
            items = self._array()
            self._field("maxlen")
            maxlen = self._value()
            self._take("}")
            return deque(items, maxlen=maxlen)
        if kind == "object":
            self._field("attrs")
            attrs = self._value()
            self._field("class")
            class_name = self._scalar()
            self._take("}")
            cls = _resolve_class(class_name, self.allowed_modules)
            instance = types.SimpleNamespace() if cls is types.SimpleNamespace else object.__new__(cls)
            for key, value in attrs.items():
                object.__setattr__(instance, key, value)
            return instance
        raise ModelPackError("MODEL_STATE_TYPE_UNKNOWN: " + str(kind))

    def _value(self):
        ch = self._peek()
        if ch == "{":
            return self._object()
        if ch == "[":
            return self._array()
        return self._scalar()

    def read(self):
        value = self._value()
        self._skip_ws()
        if self._peek():
            raise ModelPackError("MODEL_STATE_TRAILING_DATA")
        return value


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
                (PurePosixPath(name).parent == PurePosixPath("scripts") and name.endswith(".py")) or
                (name.startswith("backend/") and name.endswith(".py")) or
                name.startswith("docs/rules/") or
                (name.startswith("docs/espn-") and
                 name.endswith("-codes-2026-07-27.json"))]
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


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    config = config or {}
    enabled = set(config.get("enabled_layers") or ())
    if model_id in ("v1.7", "v1.7-penalties-on"):
        adapter = (config.get("runtime_adapters") or {}).get("v1_7_penalty")
        if ("penalty_proposal_and_enforcement" not in enabled
                or not isinstance(adapter, dict)
                or getattr(reference, "portable_v1_7_penalty_sampler", None) is None
                or getattr(reference, "penalty_controller_factory", None) is not None):
            raise ModelPackError("V17_PENALTY_EXPORT_INCOMPLETE")
    if model_id == "v1.6":
        context = ((snapshot.get("model_reference") or {}).get("current_streak_context"))
        if ("current_streak_context" not in enabled
                or not isinstance(context, dict)
                or not isinstance(context.get("source_sha256"), str)
                or not SHA256_RE.fullmatch(context["source_sha256"])):
            raise ModelPackError("V16_STREAK_EXPORT_INCOMPLETE")
    engine_files = engine_files or {}
    if not engine_files or "scripts/nfl_sequence/game_state.py" not in engine_files:
        raise ModelPackError("BUNDLED_ENGINE_CODE_REQUIRED")
    engine_hashes = {name: _sha256(data) for name, data in sorted(engine_files.items())}
    source_hashes = _hash_fields(config or {})
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
            with archive.open("reference.json", "w") as payload_stream:
                payload_sha256, payload_bytes = _write_state_payload(
                    payload_stream, reference, snapshot, config)
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
                "payload_sha256": payload_sha256,
                "payload_bytes": payload_bytes,
                "engine_files_sha256": engine_hashes,
                "rules_policy": config.get("rules_policy"),
                "enabled_layers": config.get("enabled_layers", []),
                "experimental_flags": config.get("experimental_flags", {}),
                "training_cutoff": config.get("training_cutoff"),
                "runtime_dependencies": config.get("runtime_dependencies") or runtime_dependencies(),
                "source_artifact_sha256": source_hashes,
                "layer_manifest": config.get("model_profile", {}).get("layers", {}),
            }
            archive.writestr("manifest.json", _json(manifest))
            for name, data in sorted(engine_files.items()):
                archive.writestr("engine/" + name, data)
        data_sha = _sha256_file(temp_path)
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
    if _sha256_file(path) != expected_sha256:
        raise ModelPackError("PACK_SHA256_MISMATCH")
    with zipfile.ZipFile(path) as archive:
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
        if engine_dir is not None:
            engine_root = Path(engine_dir)
            sys.path.insert(0, str(engine_root / "scripts" / "nfl_sequence"))
            sys.path.insert(1, str(engine_root / "scripts"))
            sys.path.insert(2, str(engine_root / "backend"))
        allowed_modules = {PurePosixPath(name).stem for name in manifest["engine_files_sha256"]
                           if name.endswith(".py") and name.startswith(("scripts/", "backend/"))}
        allowed_modules.add("types")
        with archive.open("reference.json", "r") as payload_stream:
            hashing_stream = _HashingRawReader(payload_stream)
            with io.BufferedReader(hashing_stream) as buffered:
                with io.TextIOWrapper(buffered, encoding="utf-8") as text_stream:
                    loaded = _StateJSONReader(text_stream, allowed_modules).read()
        if (hashing_stream.size != manifest.get("payload_bytes")
                or hashing_stream.digest.hexdigest() != manifest.get("payload_sha256")):
            raise ModelPackError("PACK_PAYLOAD_HASH_MISMATCH")
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
