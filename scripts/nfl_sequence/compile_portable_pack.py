#!/usr/bin/env python3
"""Compile a versioned SLC executable package through the model's own loader.

The expensive build runs once on the data host. The model's original
simulate_pregame_batch entrypoint resolves all of its flags and source
fixtures. This adapter captures the fully initialized Reference, pinned code,
and final build snapshot. V1, V1.5, and V1.6 currently share this adapter;
the registry enables each family only after its exact policy inputs are wired.

This first-stage compiler runs a one-seed ordinary build as a smoke test.
The final no-DB parity gate is separate and mandatory before production.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import sqlite3
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from portable_model_pack import write_pack, collect_engine_files, ModelPackError
from slc_model_registry import get_model
from slc_pregame_context import freeze_current_streak_context
from batch_launch_gate import require_full_seed_census


def _commit(root):
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def _clean(root):
    # Prevent a pack from claiming a code commit different from its build.
    return not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain",
                                        "--untracked-files=all"], text=True).strip()


def _forwarded_option(args, name):
    for index, value in enumerate(args):
        if value == name and index + 1 < len(args):
            return args[index + 1]
        if value.startswith(name + "="):
            return value.split("=", 1)[1]
    return None


def _require_registered_build_inputs(model_spec, forwarded_args, environ=None):
    """Resolve required source artifacts before the historical loader runs.

    slc_cli already forwards these from environment variables, but direct
    compile_portable_pack invocations must enforce the same registry contract.
    Per-game streak values are still a separately frozen runtime overlay.
    """
    env = os.environ if environ is None else environ
    result = list(forwarded_args)
    if result and result[0] == "--":
        result = result[1:]
    for item in model_spec.get("build_inputs", ()):
        flag, variable = item["flag"], item["env"]
        count = sum(arg == flag or arg.startswith(flag + "=") for arg in result)
        if count > 1:
            raise ModelPackError("DUPLICATE_REQUIRED_BUILD_INPUT: " + flag)
        value = _forwarded_option(result, flag)
        if value is None:
            value = env.get(variable)
            if not value:
                raise ModelPackError("REQUIRED_MODEL_BUILD_INPUT_MISSING: " + flag + " (" + variable + ")")
            result.extend((flag, str(value)))
        if item.get("kind") != "value" and not Path(value).is_file():
            raise ModelPackError("REQUIRED_MODEL_BUILD_FILE_MISSING: " + flag + " (" + variable + ")")
    return result


def _export_enabled_layers(profile, model_spec, runtime_adapters):
    """Keep runtime-only layers, notably V1.7 penalties, visible in the pack."""
    layers = {name for name, on in (profile.get("enabled_layers") or {}).items() if on}
    if ("current_streak_context" in model_spec.get("enabled_layers", ())
            and "current_streak_context" not in layers):
        raise ModelPackError("REQUIRED_CURRENT_STREAK_LAYER_NOT_ENABLED")
    if model_spec.get("family") == "v1.7":
        penalty = (runtime_adapters or {}).get("v1_7_penalty")
        if not isinstance(penalty, dict):
            raise ModelPackError("REQUIRED_V17_PENALTY_ADAPTER_NOT_CAPTURED")
        layers.add("penalty_proposal_and_enforcement")
    return sorted(layers)


def _default_frame_cache_args(model_spec, forwarded_args):
    if not model_spec.get("use_playcall_frame_cache") or _forwarded_option(
            forwarded_args, "--playcall-point-splits-cache"):
        return list(forwarded_args)
    database = _forwarded_option(forwarded_args, "--db")
    snapshot_path = _forwarded_option(forwarded_args, "--snapshot-file")
    if not database or not snapshot_path:
        raise ModelPackError("PLAYCALL_FRAME_CACHE_NEEDS_DATABASE_AND_SNAPSHOT")
    payload = json.loads(Path(snapshot_path).read_text())
    snapshot = payload.get("pregame_snapshot", payload)
    season = int(snapshot["schedule"]["season"])
    cache = Path(str(Path(database).resolve()) + ".playcall-frame-{}-2010-{}.npz".format(
        model_spec["code_commit"][:12], season - 1))
    return list(forwarded_args) + ["--playcall-point-splits-cache", str(cache)]


def _prepare_frame_cache(engine_root, forwarded_args):
    cache_path = _forwarded_option(forwarded_args, "--playcall-point-splits-cache")
    if not cache_path or Path(cache_path).is_file():
        return
    database = _forwarded_option(forwarded_args, "--db")
    snapshot_path = _forwarded_option(forwarded_args, "--snapshot-file")
    snapshot_payload = json.loads(Path(snapshot_path).read_text())
    snapshot = snapshot_payload.get("pregame_snapshot", snapshot_payload)
    cutoff_season = int(snapshot["schedule"]["season"])
    playcall_model = importlib.import_module("playcall_model")
    if not hasattr(playcall_model, "load_frame_cached"):
        raise ModelPackError("PINNED_ENGINE_FRAME_CACHE_BUILDER_MISSING")
    playcall_model.load_frame_cached(
        Path(cache_path), range(2010, cutoff_season), db=database)


def _portable_runtime_adapters(reference, model_spec):
    """Replace run-local factories with data that the bundled runtime can rebind."""
    if model_spec["family"] != "v1.7":
        return {}
    factory = getattr(reference, "penalty_controller_factory", None)
    closure = getattr(factory, "__closure__", None)
    names = getattr(getattr(factory, "__code__", None), "co_freevars", ())
    values = {}
    for name, cell in zip(names, closure or ()):
        try:
            values[name] = cell.cell_contents
        except ValueError:
            continue
    sampler = values.get("penalty_sampler")
    if sampler is None:
        raise ModelPackError("V17_PENALTY_SAMPLER_CAPTURE_MISSING")
    ruling_book = values.get("ruling_book")
    ruling_policy = model_spec["experimental_flags"].get("penalty_ruling_policy")
    if ruling_policy not in ("research", "pinned"):
        raise ModelPackError("V17_PENALTY_RULING_POLICY_UNREGISTERED")
    if ruling_policy == "pinned" and not isinstance(getattr(ruling_book, "by_key", None), dict):
        raise ModelPackError("V17_PINNED_RULING_BOOK_CAPTURE_MISSING")
    reference.penalty_controller_factory = None
    reference.portable_v1_7_penalty_sampler = sampler
    rulings_by_key = getattr(ruling_book, "by_key", None)
    if rulings_by_key is not None:
        reference.portable_v1_7_penalty_rulings_by_key = rulings_by_key
    return {"v1_7_penalty": {
        "ruling_policy": ruling_policy,
        "sampler_attribute": "portable_v1_7_penalty_sampler",
        "rulings_attribute": ("portable_v1_7_penalty_rulings_by_key"
                              if rulings_by_key is not None else None),
    }}


def _freeze_backoff_support(sampler):
    artifact = getattr(sampler, "source_support_artifact", None)
    if not artifact:
        return
    # The pinned engine tests membership before indexing its cache. Install
    # a bundle-backed provider at load time for both populated and empty keys.
    groups = defaultdict(list)
    uri = Path(artifact).resolve(strict=True).as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        rows = connection.execute(
            "SELECT level, outcome_class, lookup_key, game_id, play_id "
            "FROM support WHERE variant=? ORDER BY rowid", (sampler.source_support_variant,))
        for level, outcome, encoded, game, play in rows:
            key = json.loads(encoded)
            groups[level, outcome, tuple(key) if isinstance(key, list) else key].append((game, play))
    if not groups:
        raise ModelPackError("EMPTY_MATERIALIZED_BACKOFF_SUPPORT")
    sampler.portable_backoff_groups = dict(groups)
    sampler._source_support_ids = {}
    sampler._source_support_lookup = None


def _require_build_policy(model_spec, forwarded):
    """Reject seed-plan escapes and registered variant conflicts before running legacy code."""
    names = {arg.split("=", 1)[0] for arg in forwarded if arg.startswith("--")}
    forbidden = names & {"--seed-list-file", "--seed-list", "--resume", "--register-dir"}
    if forbidden:
        raise ModelPackError("BUILD_SMOKE_UNSUPPORTED_ARGUMENT: " + ", ".join(sorted(forbidden)))
    for flag, expected in (("--games", "1"), ("--seed-start", "300001"),
                           ("--slc-profile", model_spec["profile"])):
        count = sum(arg == flag or arg.startswith(flag + "=") for arg in forwarded)
        if count > 1 or (count and _forwarded_option(forwarded, flag) != expected):
            raise ModelPackError("BUILD_POLICY_CONFLICT: " + flag)
    for flag in ("--rng-protocol", "--playcall-pass-label-mode", "--slc-penalty-ruling-policy"):
        if sum(arg == flag or arg.startswith(flag + "=") for arg in forwarded) > 1:
            raise ModelPackError("BUILD_POLICY_CONFLICT: " + flag)
    if model_spec["family"] == "v2":
        if "--slc-v2" not in names or _forwarded_option(forwarded, "--rng-protocol") != "v2":
            raise ModelPackError("BUILD_V2_POLICY_MISSING")
    elif "--slc-v2" in names:
        raise ModelPackError("BUILD_VARIANT_CONFLICT: --slc-v2")
    pbv1_expected = model_spec.get("experimental_flags", {}).get("pbv1_package_sampler") is True
    if ("--playcall-pbv1-package" in names) != pbv1_expected:
        raise ModelPackError("BUILD_PBV1_POLICY_CONFLICT")
    if model_spec["family"] == "v1.7":
        if _forwarded_option(forwarded, "--slc-penalty-ruling-policy") != model_spec["experimental_flags"]["penalty_ruling_policy"]:
            raise ModelPackError("BUILD_V17_RULING_POLICY_CONFLICT")
    if model_spec["family"] in ("v1.6", "v1.7", "v2"):
        if _forwarded_option(forwarded, "--playcall-pass-label-mode") != "conditional":
            raise ModelPackError("BUILD_CONDITIONAL_PASS_LABEL_POLICY_MISSING")


def _require_build_smoke(result):
    """Validate the actual requested seed instead of trusting a summary count."""
    sim = result.get("simulation") or {}
    if (sim.get("requested_games") != 1 or sim.get("seed_start") != 300001
            or sim.get("seed_end_inclusive") != 300001):
        raise ModelPackError("BUILD_SMOKE_SEED_PLAN_MISMATCH")
    try:
        require_full_seed_census((result.get("summary") or {}).get("outcomes"), 300001, 1)
    except ValueError as exc:
        raise ModelPackError("BUILD_SMOKE_INVALID: " + str(exc)) from exc


def compile_model(engine_root, pack_path, model_id, forwarded_args):
    model_spec = get_model(model_id)
    if not model_spec["build_supported"]:
        raise ModelPackError("MODEL_PACKAGE_NOT_ENABLED: " + model_id)
    if "--no-overtime-table" in forwarded_args:
        raise ModelPackError("OVERTIME_DISABLED_PROFILE_RETIRED: standard packages require full-game overtime support")
    forwarded_args = _require_registered_build_inputs(model_spec, forwarded_args)
    _require_build_policy(model_spec, forwarded_args)
    forwarded_args = _default_frame_cache_args(model_spec, forwarded_args)
    root = Path(engine_root).resolve()
    if not (root / "scripts" / "nfl_sequence" / "simulate_pregame_batch.py").exists():
        raise ModelPackError("ENGINE_SIMULATOR_ENTRYPOINT_MISSING")
    if not _clean(root):
        raise ModelPackError("DIRTY_MODEL_CODE: commit or stash tracked changes before compilation")
    commit = _commit(root)
    if commit != model_spec["code_commit"]:
        raise ModelPackError("MODEL_REGISTRY_CODE_COMMIT_MISMATCH")
    lock_path = Path(str(pack_path) + ".sha256")
    if Path(pack_path).exists() or lock_path.exists():
        raise FileExistsError(f"immutable pack or lock already exists: {pack_path}")
    engine_files = collect_engine_files(root, commit)
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
        _require_build_smoke(result)
        reference = captured.get("reference")
        if reference is None:
            raise ModelPackError("BATCH_DID_NOT_LOAD_REFERENCE")
        profile = result.get("slc_profile_manifest") or {}
        if profile.get("profile") != model_spec["profile"]:
            raise ModelPackError("MODEL_PROFILE_DOES_NOT_MATCH_REGISTRY")
        if (model_spec.get("profile_model_id")
                and profile.get("model_id") != model_spec["profile_model_id"]):
            raise ModelPackError("MODEL_VARIANT_DOES_NOT_MATCH_REGISTRY")
        if profile.get("disabled_layers"):
            raise ModelPackError("STANDARD_PACKAGE_HAS_DISABLED_LAYERS")
        sampler = getattr(reference, "contextual_sampler", None)
        enabled_layers = profile.get("enabled_layers") or {}
        if enabled_layers.get("current_streak_context") and sampler is None:
            raise ModelPackError("CURRENT_STREAK_SAMPLER_MISSING_FOR_ENABLED_LAYER")
        if sampler is not None:
            if getattr(sampler, "participant_chooser", None) is not None:
                raise ModelPackError("MODEL_STILL_HAS_ACTIVE_PARTICIPANT_CHOOSER")
            if enabled_layers.get("current_streak_context"):
                streak_path = _forwarded_option(forwarded_args, "--playcall-streak-file")
                if not streak_path:
                    raise ModelPackError("CURRENT_STREAK_FILE_REQUIRED_FOR_ENABLED_LAYER")
                if not hasattr(sampler, "current_streak"):
                    raise ModelPackError("CURRENT_STREAK_SAMPLER_STATE_MISSING")
                streak_splits = importlib.import_module("streak_splits")
                team_codes = importlib.import_module("nfl_team_codes")
                freeze_current_streak_context(streak_path, result["pregame_snapshot"],
                                              streak_splits, team_codes)
                # This field came from the build game's streak file. Keep the fitted
                # streak distributions, but make the context itself a game overlay.
                sampler.current_streak = {}
                reference.model_inputs = batch.er._reference_fingerprint(reference)
                result["pregame_snapshot"]["model_reference"]["observed_reference"] = reference.model_inputs
                importlib.import_module("pregame_snapshot").reseal(result["pregame_snapshot"])
            # Strip memoized, per-game draws; all reusable model parameters remain.
            if hasattr(sampler, "decisions"):
                sampler.decisions.clear()
            if hasattr(sampler, "_cells"):
                sampler._cells.clear()
            if hasattr(sampler, "_backoff_index"):
                sampler._backoff_index = None
        _freeze_backoff_support(sampler)
        runtime_adapters = _portable_runtime_adapters(reference, model_spec)
        export_layers = _export_enabled_layers(profile, model_spec, runtime_adapters)
        pack = write_pack(
            pack_path,
            reference=reference,
            snapshot=result["pregame_snapshot"],
            model_id=model_id,
            code_commit=commit,
            engine_files=engine_files,
            config={"build_args": forwarded_args, "build_result_model": result.get("simulation", {}).get("model"),
                    "reference_sha256": reference.model_inputs.get("sha256"),
                    "source": result.get("source"),
                    "model_profile": profile,
                    "rules_policy": model_spec["rules_policy"],
                    "enabled_layers": export_layers,
                    "rng_protocol": result.get("simulation", {}).get("rng_protocol") or {
                        "scheme": _forwarded_option(forwarded_args, "--rng-protocol") or "v1"},
                    "experimental_flags": model_spec["experimental_flags"],
                    "training_cutoff": {"eligible_before": [
                        int(result["pregame_snapshot"]["schedule"]["season"]),
                        (int(result["pregame_snapshot"]["schedule"]["week"])
                         if model_spec.get("training_cutoff_scope") == "before_game_week" else 1)]},
                    "runtime_adapters": runtime_adapters,
                    "runtime_dependencies": None},
        )
        lock_tmp = lock_path.with_name(lock_path.name + ".tmp")
        try:
            lock_tmp.write_text(pack["sha256"] + "  " + Path(pack_path).name + "\n")
            import os
            os.link(lock_tmp, lock_path)
        finally:
            lock_tmp.unlink(missing_ok=True)
        print(json.dumps({"pack": str(pack_path), "pack_sha256": pack["sha256"],
                          "model_id": model_id, "code_commit": commit,
                          "reference_sha256": reference.model_inputs.get("sha256")}, indent=2))
        return result

    batch.run_batch = capture_run_batch
    _prepare_frame_cache(root, forwarded_args)
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
