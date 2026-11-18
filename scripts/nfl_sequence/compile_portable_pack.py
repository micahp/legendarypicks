#!/usr/bin/env python3
"""Compile a trusted SLC portable reference by reusing an existing model's own loader.

The expensive build runs once on the data host. The model's original
simulate_pregame_batch entrypoint resolves all of its flags and source
fixtures. This adapter captures the fully initialized Reference and the
final frozen snapshot and emits a portable pack. The CLI deliberately
accepts the ORIGINAL runner arguments after --, so V1/V1.5/V1.6/V1.7/V2/
PBV1 keep their own real code paths and policies.

This first-stage compiler runs a one-seed ordinary build as a smoke test.
The final no-DB parity gate is separate and mandatory before production.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from portable_model_pack import write_pack, ModelPackError


def _commit(root):
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def _clean(root):
    # Prevent a pack from claiming a code commit different from its build.
    return not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain",
                                        "--untracked-files=no"], text=True).strip()


def compile_model(engine_root, pack_path, model_id, forwarded_args):
    root = Path(engine_root).resolve()
    if not (root / "scripts" / "nfl_sequence" / "simulate_pregame_batch.py").exists():
        raise ModelPackError("ENGINE_SIMULATOR_ENTRYPOINT_MISSING")
    if not _clean(root):
        raise ModelPackError("DIRTY_MODEL_CODE: commit or stash tracked changes before compilation")
    commit = _commit(root)
    sys.path.insert(0, str(root / "scripts" / "nfl_sequence"))
    sys.path.insert(1, str(root / "backend"))
    batch = importlib.import_module("simulate_pregame_batch")
    captured = {}
    # Tap e2_reference.load for S0 and SLC code families.
    if not hasattr(batch, "er") or not hasattr(batch.er, "load"):
        raise ModelPackError("E2_REFERENCE_LOADER_NOT_FOUND")
    original_er_load = batch.er.load

    def capture_er_load(*args, **kwargs):
        result = original_er_load(*args, **kwargs)
        captured["reference"] = result[0]
        return result

    batch.er.load = capture_er_load

    # The SLC wrapper adds all enabled model layers AFTER e2_reference.load.
    # Capture it again here so the exported Reference includes every layer.
    slc = getattr(batch, "slc_engine", None)
    if slc is not None and hasattr(slc, "load_reference"):
        original_slc_load = slc.load_reference

        def capture_slc_load(*args, **kwargs):
            result = original_slc_load(*args, **kwargs)
            captured["reference"] = result[0]
            return result

        slc.load_reference = capture_slc_load

    if not hasattr(batch, "run_batch") or not hasattr(batch, "main"):
        raise ModelPackError("BATCH_RUNNER_API_NOT_FOUND")
    original_run_batch = batch.run_batch

    def capture_run_batch(args):
        result = original_run_batch(args)
        if not isinstance(result, dict) or not isinstance(result.get("pregame_snapshot"), dict):
            raise ModelPackError("BATCH_DID_NOT_RETURN_FROZEN_SNAPSHOT")
        reference = captured.get("reference")
        if reference is None:
            raise ModelPackError("BATCH_DID_NOT_LOAD_REFERENCE")
        sampler = getattr(reference, "contextual_sampler", None)
        if sampler is not None:
            if getattr(sampler, "participant_chooser", None) is not None:
                raise ModelPackError("MODEL_STILL_HAS_ACTIVE_PARTICIPANT_CHOOSER")
            # Strip memoized, per-game draws; all model parameters remain.
            if hasattr(sampler, "decisions"):
                sampler.decisions.clear()
            if hasattr(sampler, "_cells"):
                sampler._cells.clear()
            if hasattr(sampler, "_backoff_index"):
                sampler._backoff_index = None
        pack = write_pack(
            pack_path,
            reference=reference,
            snapshot=result["pregame_snapshot"],
            model_id=model_id,
            code_commit=commit,
            config={"build_args": forwarded_args, "build_result_model": result.get("simulation", {}).get("model"),
                    "reference_sha256": reference.model_inputs.get("sha256"),
                    "source": result.get("source"),
                    "model_profile": result.get("slc_profile")},
        )
        lock_path = Path(str(pack_path) + ".sha256")
        if lock_path.exists():
            raise FileExistsError(f"pack lock already exists: {lock_path}")
        lock_path.write_text(pack["sha256"] + "  " + Path(pack_path).name + "\n")
        print(json.dumps({"pack": str(pack_path), "pack_sha256": pack["sha256"],
                          "model_id": model_id, "code_commit": commit,
                          "reference_sha256": reference.model_inputs.get("sha256")}, indent=2))
        return result

    batch.run_batch = capture_run_batch
    # One build-time seed is a smoke check and does NOT train anything.
    with tempfile.TemporaryDirectory(prefix="lp-slc-pack-build-") as temp:
        argv = list(forwarded_args)
        if argv and argv[0] == "--":
            argv = argv[1:]
        argv += ["--games", "1", "--seed-start", "300001", "--out",
                 str(Path(temp) / "build-smoke.json")]
        batch.main(argv)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine-root", required=True, help="clean code checkout for this model version")
    ap.add_argument("--model-id", required=True, help="true variant name, e.g. v1.7-penalties-on or pbv1-label-only")
    ap.add_argument("--out", required=True, help="new .slcpack path; existing file is never overwritten")
    ap.add_argument("runner_args", nargs=argparse.REMAINDER,
                    help="original simulate_pregame_batch args after --; including source DB and fixtures")
    args = ap.parse_args(argv)
    if not args.runner_args:
        ap.error("pass original model's batch arguments after --")
    compile_model(args.engine_root, args.out, args.model_id, args.runner_args)


if __name__ == "__main__":
    main()
