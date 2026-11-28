#!/usr/bin/env python3
"""Registry-backed SLC package build and offline simulation commands."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from slc_model_registry import MODELS, get_model
import simulate_portable_pack


def _env_path(name, *, required=True):
    value = os.environ.get(name)
    if not value and required:
        raise RuntimeError(f"BUILD_CONFIGURATION_MISSING: set {name}")
    return Path(value).resolve() if value else None


def _manifest(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("manifest.json"))


def _index_path(models_dir):
    return models_dir / "registry.json"


def _snapshot_season(path):
    payload = json.loads(path.read_text())
    if "pregame_snapshot" in payload:
        payload = payload["pregame_snapshot"]
    return int(payload["schedule"]["season"])


def _check_python(model_id, spec, version_info=None):
    minimum = spec.get("minimum_python")
    if minimum is None:
        return
    current = tuple(version_info or sys.version_info[:2])
    required = tuple(minimum)
    if current < required:
        raise RuntimeError(
            "MODEL_PYTHON_VERSION_UNSUPPORTED: model={} requires Python {}.{}+, got {}.{}"
            .format(model_id, required[0], required[1], current[0], current[1]))


def build(args):
    if args.all:
        unsupported = [model_id for model_id, spec in MODELS.items() if not spec["build_supported"]]
        if unsupported:
            raise RuntimeError("BUILD_ALL_INCOMPLETE: no packages built; unsupported models: "
                               + ", ".join(unsupported))
        selected = list(MODELS)
    else:
        selected = [args.model]
        if not get_model(args.model)["build_supported"]:
            raise RuntimeError("MODEL_BUILD_NOT_IMPLEMENTED: " + args.model)

    snapshot = _env_path("SLC_GAME_SNAPSHOT", required=not args.snapshot)
    if args.snapshot:
        snapshot = args.snapshot.resolve()
    if not snapshot.is_file():
        raise RuntimeError(f"GAME_SNAPSHOT_NOT_FOUND: {snapshot}")
    database = _env_path("SLC_SOURCE_DB")
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    index_path = _index_path(output)
    if index_path.exists():
        index = json.loads(index_path.read_text())
    else:
        index = {"schema": "lp-slc-installed-models-1", "packages": []}
    entries = {(entry["model_id"], entry["training_season"]): entry for entry in index["packages"]}
    build_season = _snapshot_season(snapshot)

    for model_id in selected:
        spec = get_model(model_id)
        _check_python(model_id, spec)
        if (model_id, build_season) in entries:
            raise FileExistsError(f"model package is already registered: {(model_id, build_season)}")
        source_root = _env_path(spec["source_root_env"])
        with tempfile.TemporaryDirectory(prefix="slc-pack-smoke-") as temp:
            pack_path = output / (model_id + "--season-" + str(build_season) + ".slcpkg")
            forwarded = [
                "--snapshot-file", str(snapshot), "--db", str(database),
                "--slc-profile", spec["profile"],
            ]
            for item in spec.get("build_inputs", []):
                if item.get("kind") == "value":
                    value = os.environ.get(item["env"])
                    if not value:
                        raise RuntimeError(f"BUILD_CONFIGURATION_MISSING: set {item['env']}")
                else:
                    value = _env_path(item["env"])
                    if not value.is_file():
                        raise RuntimeError(f"BUILD_INPUT_FILE_NOT_FOUND: {item['env']}={value}")
                forwarded.extend([item["flag"], str(value)])
            forwarded.extend(spec.get("build_args", []))
            forwarded += ["--games", "1", "--seed-start", "300001",
                          "--out", str(Path(temp) / "build-smoke.json")]
            subprocess.run([
                sys.executable, str(HERE / "compile_portable_pack.py"),
                "--engine-root", str(source_root), "--model-id", model_id,
                "--out", str(pack_path), "--", *forwarded,
            ], check=True)
        manifest = _manifest(pack_path)
        key = (model_id, build_season)
        lock = Path(str(pack_path) + ".sha256")
        digest = lock.read_text().split()[0]
        entry = {
            "model_id": model_id,
            "training_season": build_season,
            "build_game_id": manifest["game_id"],
            "package": pack_path.name,
            "sha256": digest,
            "code_commit": manifest["model_code_commit"],
            "reference_sha256": manifest["reference_sha256"],
            "snapshot_sha256": manifest["snapshot_sha256"],
            "rules_policy": manifest["rules_policy"],
            "enabled_layers": manifest["enabled_layers"],
            "experimental_flags": manifest["experimental_flags"],
            "training_cutoff": manifest["training_cutoff"],
            "artifact_hashes": {
                "package_sha256": digest,
                "payload_sha256": manifest["payload_sha256"],
                "engine_files_sha256": manifest["engine_files_sha256"],
            },
        }
        index["packages"].append(entry)
        entries[key] = entry

    temp_index = index_path.with_name(index_path.name + ".tmp")
    temp_index.write_text(json.dumps(index, sort_keys=True, indent=2) + "\n")
    os.replace(temp_index, index_path)
    print(f"registered {len(selected)} package(s) in {index_path}")


def simulate(args):
    models_dir = args.models_dir.resolve()
    snapshot = args.snapshot or _env_path("SLC_GAME_SNAPSHOT", required=False)
    if not snapshot:
        raise RuntimeError("RUNTIME_SNAPSHOT_REQUIRED: pass --snapshot or set SLC_GAME_SNAPSHOT")
    if not snapshot.is_file():
        raise RuntimeError(f"RUNTIME_SNAPSHOT_NOT_FOUND: {snapshot}")
    season = _snapshot_season(snapshot)
    index = json.loads(_index_path(models_dir).read_text())
    canonical = args.model
    entries = [entry for entry in index["packages"]
               if entry["model_id"] == canonical and entry["training_season"] == season]
    if len(entries) != 1:
        raise RuntimeError(f"MODEL_PACKAGE_NOT_FOUND: model={canonical} training_season={season}")
    entry = entries[0]
    pack = models_dir / entry["package"]
    digest_state = hashlib.sha256()
    with pack.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest_state.update(chunk)
    digest = digest_state.hexdigest()
    if digest != entry["sha256"]:
        raise RuntimeError("MODEL_PACKAGE_HASH_MISMATCH")
    run_args = [
        "--model", canonical, "--game", args.game,
        "--snapshot", str(snapshot.resolve()),
        "--pack", str(pack), "--pack-sha256", digest,
        "--games", str(args.seeds), "--seed-start", str(args.seed_start),
        "--workers", str(args.workers),
        "--out", str(args.out.resolve()),
    ]
    run_args.append("--with-player-lines" if args.with_player_lines else "--no-player-lines")
    if args.records_out:
        run_args += ["--records-out", str(args.records_out.resolve())]
    return simulate_portable_pack.main(run_args)


def repack(args):
    from portable_model_pack import repack_shared_pool
    result = repack_shared_pool(args.pack, args.out, expected_sha256=args.pack_sha256,
                                expected_code_commit=args.code_commit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="slc")
    commands = parser.add_subparsers(dest="command", required=True)
    pack_cmd = commands.add_parser("pack")
    pack_ops = pack_cmd.add_subparsers(dest="pack_command", required=True)
    build_cmd = pack_ops.add_parser("build")
    selection = build_cmd.add_mutually_exclusive_group()
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--model", choices=tuple(MODELS), default="v1")
    build_cmd.add_argument("--snapshot", type=Path)
    build_cmd.add_argument("--out-dir", type=Path, default=Path(os.environ.get("SLC_MODELS_DIR", "models")))
    build_cmd.set_defaults(func=build)
    repack_cmd = pack_ops.add_parser("repack-shared-pool",
                                     help="convert one immutable legacy package; no model refit")
    repack_cmd.add_argument("--pack", type=Path, required=True)
    repack_cmd.add_argument("--pack-sha256", required=True)
    repack_cmd.add_argument("--code-commit", required=True)
    repack_cmd.add_argument("--out", type=Path, required=True)
    repack_cmd.set_defaults(func=repack)

    sim_cmd = commands.add_parser("simulate")
    sim_cmd.add_argument("--model", required=True, choices=tuple(MODELS))
    sim_cmd.add_argument("--game", required=True)
    sim_cmd.add_argument("--snapshot", type=Path,
                         help="hash-pinned pregame roster/injury snapshot for this game")
    sim_cmd.add_argument("--seeds", type=int, required=True)
    sim_cmd.add_argument("--seed-start", type=int, default=0)
    sim_cmd.add_argument("--workers", type=int, default=1,
                         help="Linux seed workers sharing one loaded model")
    sim_cmd.add_argument("--models-dir", type=Path, default=Path(os.environ.get("SLC_MODELS_DIR", "models")))
    sim_cmd.add_argument("--out", type=Path, default=Path("slc-results.json"))
    sim_cmd.add_argument("--with-player-lines", dest="with_player_lines", action="store_true", default=True,
                         help="retain player box stats for each seed (the default)")
    sim_cmd.add_argument("--no-player-lines", dest="with_player_lines", action="store_false")
    sim_cmd.add_argument("--records-out", type=Path,
                         help="write full per-seed records for exact legacy parity comparison")
    sim_cmd.set_defaults(func=simulate)
    args = parser.parse_args(argv)
    if getattr(args, "seeds", 1) < 1 or getattr(args, "seed_start", 0) < 0:
        parser.error("seeds must be positive and seed-start nonnegative")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
