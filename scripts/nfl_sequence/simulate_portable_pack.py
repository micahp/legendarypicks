#!/usr/bin/env python3
"""Execute an SLC code-and-reference package without source tables.

The pack contains the in-memory reference and exact executable source. Supply a
fresh hash-pinned pregame snapshot; this command never constructs a model,
queries SQLite, or loads research fixtures. Produces JSON results and optional
per-seed game records for exact parity comparison.
"""
from __future__ import annotations

import argparse
import builtins
import copy
import io
from collections import defaultdict
import importlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import socket
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from portable_model_pack import load_pack, ModelPackError
from slc_model_registry import get_model
from slc_pregame_context import current_streaks_for_snapshot


def _forbid_source_table_reads():
    """Block DB connections AND external model fixture/table file opens."""
    def refused(*_args, **_kwargs):
        raise RuntimeError("PORTABLE_RUNTIME_SOURCE_TABLE_ACCESS")
    sqlite3.connect = refused
    socket.create_connection = refused
    socket.socket.connect = refused

    original_builtin_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open

    def forbidden_path(file):
        if not isinstance(file, (str, bytes, Path)):
            return False
        name = os.fsdecode(file).replace("\\", "/").lower()
        suffix = Path(name).suffix
        return (suffix in {".db", ".sqlite", ".sqlite3", ".csv", ".parquet"}
                or "/docs/fixtures/" in name or "/docs/research/" in name)

    def guard(original):
        def checked(file, mode="r", *args, **kwargs):
            # The compiled pack is always allowed. Source/training material is not.
            if "r" in str(mode) and forbidden_path(file):
                raise RuntimeError("PORTABLE_RUNTIME_SOURCE_FILE_ACCESS: " + os.fsdecode(file))
            return original(file, mode, *args, **kwargs)
        return checked

    def checked_os_open(file, flags, *args, **kwargs):
        if forbidden_path(file) and flags & (os.O_RDONLY | os.O_RDWR):
            raise RuntimeError("PORTABLE_RUNTIME_SOURCE_FILE_ACCESS: " + os.fsdecode(file))
        return original_os_open(file, flags, *args, **kwargs)

    builtins.open = guard(original_builtin_open)
    io.open = guard(original_io_open)
    os.open = checked_os_open


def _run_seed(seed, reference, snapshot, gs, slc_engine=None, rng_plan=None, decisions_out=None):
    if slc_engine is not None and slc_engine.is_slc(reference):
        play = slc_engine.play
        kwargs = {"paired_randomness": rng_plan.paired, "rng_plan": rng_plan}
        if rng_plan.scheme != "v1" and "rng_plan" not in inspect.signature(play).parameters:
            raise ModelPackError("PORTABLE_RNG_PROTOCOL_UNSUPPORTED_BY_ENGINE")
        kwargs = {key: value for key, value in kwargs.items()
                  if key in inspect.signature(play).parameters}
        record, decisions = play(seed, reference, copy.deepcopy(snapshot), **kwargs)
        if decisions_out is not None:
            decisions_out.extend(decisions)
    else:
        play = gs.play_game
        kwargs = {"pregame_snapshot": copy.deepcopy(snapshot),
                  "paired_randomness": rng_plan.paired,
                  "seed_root": rng_plan.seed_root(snapshot)}
        parameters = inspect.signature(play).parameters
        if rng_plan.scheme != "v1" and "seed_root" not in parameters:
            raise ModelPackError("PORTABLE_RNG_PROTOCOL_UNSUPPORTED_BY_ENGINE")
        kwargs = {key: value for key, value in kwargs.items() if key in parameters}
        record = play(seed, reference, **kwargs)
    gs.validate_game(record)
    return record


def _fingerprint_frozen_reference(reference, reference_loader):
    """Recompute legacy identity while reusing the pack's pinned fixture hash."""
    extras_hash = (getattr(reference, "model_inputs", None) or {}).get("play_extras_sha256")
    if not isinstance(extras_hash, str) or len(extras_hash) != 64:
        raise ModelPackError("PACKED_PLAY_EXTRAS_HASH_MISSING")
    original_hashlib = reference_loader.hashlib
    original_extras = reference_loader.PLAY_EXTRAS
    marker = b"portable-runtime-frozen-play-extras"

    class _FrozenDigest:
        def hexdigest(self):
            return extras_hash

    class _HashlibProxy:
        @staticmethod
        def sha256(data=b""):
            if data == marker:
                return _FrozenDigest()
            return original_hashlib.sha256(data)

    class _FrozenExtras:
        @staticmethod
        def read_bytes():
            return marker

    reference_loader.hashlib = _HashlibProxy
    reference_loader.PLAY_EXTRAS = _FrozenExtras
    try:
        return reference_loader._reference_fingerprint(reference)
    finally:
        reference_loader.hashlib = original_hashlib
        reference_loader.PLAY_EXTRAS = original_extras


def _attach_runtime_adapters(reference, config, model_id):
    adapters = config.get("runtime_adapters") or {}
    penalty = adapters.get("v1_7_penalty")
    if get_model(model_id)["family"] != "v1.7":
        if penalty is not None:
            raise ModelPackError("UNEXPECTED_V17_PENALTY_RUNTIME_ADAPTER")
        return
    if not isinstance(penalty, dict):
        raise ModelPackError("PACKED_V17_PENALTY_RUNTIME_MISSING")
    sampler_attr = penalty.get("sampler_attribute")
    sampler = getattr(reference, sampler_attr, None) if isinstance(sampler_attr, str) else None
    if sampler is None:
        raise ModelPackError("PACKED_V17_PENALTY_SAMPLER_MISSING")
    if getattr(reference, "penalty_controller_factory", None) is not None:
        raise ModelPackError("PACKED_V17_CONTAINS_NONPORTABLE_PENALTY_FACTORY")
    from penalty_game import PenaltyGameController, PenaltyResolutionUnavailable
    from penalty_rulings import ResearchPenaltyRulingPolicy

    ruling_policy = penalty.get("ruling_policy")
    rulings_attr = penalty.get("rulings_attribute")
    rulings_by_key = getattr(reference, rulings_attr, None) if isinstance(rulings_attr, str) else None
    if ruling_policy == "pinned" and not isinstance(rulings_by_key, dict):
        raise ModelPackError("PACKED_V17_PINNED_RULING_BOOK_MISSING")
    if ruling_policy not in ("research", "pinned"):
        raise ModelPackError("PACKED_V17_RULING_POLICY_INVALID")

    def penalty_factory(*, seed, snapshot, ledger):
        if ruling_policy == "research":
            provider = ResearchPenaltyRulingPolicy(seed)
        else:
            def provider(proposal, *, phase, state, event, after):
                key = (seed, proposal.opportunity_key, phase)
                matched = rulings_by_key.get(key)
                if matched is None:
                    return None
                if matched[0] != proposal.outcome:
                    raise PenaltyResolutionUnavailable("pinned ruling outcome mismatch: " + repr(key))
                return dict(matched[1])

        return PenaltyGameController(
            sampler=sampler, game_seed=seed,
            team_identity={"A": snapshot["schedule"]["home_team"],
                           "B": snapshot["schedule"]["away_team"]},
            ruling_provider=provider, rule_era=int(snapshot["schedule"]["season"]))

    reference.penalty_controller_factory = penalty_factory


def _run(args, engine_dir):
    model = get_model(args.model)
    if not model.get("runtime_supported", False):
        raise ModelPackError("MODEL_PACKAGE_NOT_ENABLED: " + args.model)
    engine_root = Path(engine_dir)
    reference, snapshot, manifest, config = load_pack(
        args.pack, expected_sha256=args.pack_sha256,
        expected_code_commit=model["code_commit"], engine_dir=engine_root)
    if manifest["model_id"] != args.model:
        raise ModelPackError("MODEL_ID_MISMATCH")
    enabled = set(manifest.get("enabled_layers") or ())
    if model["family"] == "v1.7" and "penalty_proposal_and_enforcement" not in enabled:
        raise ModelPackError("PACKED_V17_PENALTY_LAYER_MISSING: rebuild package")
    if model["family"] == "v1.6" and "current_streak_context" not in enabled:
        raise ModelPackError("PACKED_V16_STREAK_LAYER_MISSING: rebuild package")
    sampler = getattr(reference, "contextual_sampler", None)
    if getattr(sampler, "source_support_artifact", None):
        groups = getattr(sampler, "portable_backoff_groups", None)
        if not groups:
            raise ModelPackError("MATERIALIZED_BACKOFF_SUPPORT_MISSING: rebuild package")
        history = importlib.import_module("slc_materialized_history")

        def bundled_backoff_ids(artifact, variant, level, outcome_class, key):
            if (artifact, variant) != (sampler.source_support_artifact, sampler.source_support_variant):
                raise ModelPackError("MATERIALIZED_BACKOFF_VARIANT_MISMATCH")
            return groups.get((level, outcome_class, key), ())

        history.backoff_ids = bundled_backoff_ids
    _attach_runtime_adapters(reference, config, args.model)
    snapshot_loader = importlib.import_module("pregame_snapshot")
    try:
        snapshot_payload = json.loads(args.snapshot.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelPackError("RUNTIME_SNAPSHOT_UNREADABLE: " + str(exc)) from exc
    runtime_model_inputs = (snapshot_payload.get("runtime_model_inputs")
                            if isinstance(snapshot_payload, dict) else None)
    runtime_snapshot = snapshot_loader.load_frozen_snapshot(args.snapshot)
    # RNG v2's pregame identity is captured before the reference attaches or
    # reseals model metadata. Keep the supplied snapshot hash for the RNG plan;
    # the mutable snapshot below may be resealed to record the loaded reference.
    pregame_state_sha256 = runtime_snapshot["snapshot_sha256"]
    runtime_schedule = runtime_snapshot["schedule"]
    if runtime_schedule["game_id"] != args.game:
        raise ModelPackError("RUNTIME_SNAPSHOT_GAME_ID_MISMATCH")
    cutoff = manifest.get("training_cutoff") or {}
    eligible_before = cutoff.get("eligible_before") or []
    if len(eligible_before) != 2 or int(runtime_schedule["season"]) != int(eligible_before[0]):
        raise ModelPackError("RUNTIME_SNAPSHOT_TRAINING_SEASON_MISMATCH")
    if int(runtime_schedule["week"]) < int(eligible_before[1]):
        raise ModelPackError("RUNTIME_SNAPSHOT_BEFORE_TRAINING_CUTOFF")
    snapshot = runtime_snapshot
    # The model implementation is imported only from the extracted package tree.
    gs = importlib.import_module("game_state")
    try:
        slc_engine = importlib.import_module("slc_engine")
    except ModuleNotFoundError as e:
        if e.name != "slc_engine":
            raise
        slc_engine = None
    if slc_engine is not None and slc_engine.is_slc(reference):
        reference.contextual_sampler.side_teams = slc_engine.side_teams(snapshot)
    if "current_streak_context" in manifest.get("enabled_layers", []):
        sampler = getattr(reference, "contextual_sampler", None)
        if sampler is None or not hasattr(sampler, "current_streak"):
            raise ModelPackError("PACKED_CURRENT_STREAK_SAMPLER_MISSING")
        streak_splits = importlib.import_module("streak_splits")
        team_codes = importlib.import_module("nfl_team_codes")
        sampler.current_streak = current_streaks_for_snapshot(
            snapshot, team_codes, streak_splits, runtime_model_inputs)
        streak_context = snapshot["model_reference"]["current_streak_context"]
        optional_hashes = getattr(sampler, "optional_input_sha256", None)
        if not isinstance(optional_hashes, dict) or not streak_context.get("source_sha256"):
            raise ModelPackError("PACKED_CURRENT_STREAK_PROVENANCE_MISSING")
        optional_hashes["current_streak_file"] = streak_context["source_sha256"]
    if slc_engine is not None and slc_engine.is_slc(reference):
        # The legacy loader builds this manifest after binding the matchup to
        # the play-call sampler. A pack carries the build game's manifest, so
        # refresh its matchup-specific metadata before resealing the snapshot.
        describe_sampler = getattr(reference.contextual_sampler, "describe", None)
        if callable(describe_sampler):
            reference.contextual_pool_manifest = describe_sampler()
    # Legacy loading fingerprints the fully resolved reference after attaching
    # matchup context, then binds that fingerprint into the frozen snapshot.
    # Reproduce that step without reopening any historical source tables.
    packed_inputs = getattr(reference, "model_inputs", None) or {}
    if "play_extras_sha256" in packed_inputs:
        reference_loader = importlib.import_module("e2_reference")
        reference.model_inputs = _fingerprint_frozen_reference(reference, reference_loader)
        snapshot["model_reference"]["observed_reference"] = reference.model_inputs
        snapshot["model_reference"]["pool_scope"] = reference.pool_scope
        snapshot_loader.reseal(snapshot)
    try:
        rng_protocol = importlib.import_module("rng_protocol")
    except ModuleNotFoundError as exc:
        if exc.name != "rng_protocol":
            raise
        # Older pinned engines predate the optional RNG v2 module. Their exact
        # legacy behavior is v1: seed-local draws key directly from the snapshot.
        class _LegacyRngProtocol:
            V1 = "v1"

            @staticmethod
            def plan(scheme, _pregame_sha, _reference, _description):
                if scheme != "v1":
                    raise ModelPackError("PORTABLE_RNG_PROTOCOL_UNSUPPORTED_BY_ENGINE")

                class _Plan:
                    scheme = "v1"
                    paired = False

                    @staticmethod
                    def seed_root(_snapshot):
                        return None

                    @staticmethod
                    def manifest():
                        return {"scheme": "v1", "stream_key": "snapshot_sha256 (legacy engine behavior)"}

                return _Plan()

        rng_protocol = _LegacyRngProtocol
    configured_rng = (config.get("rng_protocol") or {}).get("scheme") or rng_protocol.V1
    scheme = args.rng_protocol or configured_rng
    playcall_description = slc_engine.describe(reference) if slc_engine is not None else None
    rng_plan = rng_protocol.plan(scheme, pregame_state_sha256, reference,
                                 playcall_description)
    rng_manifest = rng_plan.manifest()
    if (args.expected_stream_root_sha256 is not None
            and rng_manifest.get("stream_root_sha256") != args.expected_stream_root_sha256):
        reference_digest = getattr(rng_protocol, "reference_data_sha256", lambda _ref: "unavailable")
        layer_digest = getattr(rng_protocol, "layer_table_sha256", lambda _description: "unavailable")
        raise ModelPackError(
            "EXPECTED_STREAM_ROOT_MISMATCH: expected="
            + str(args.expected_stream_root_sha256)
            + " actual=" + str(rng_manifest.get("stream_root_sha256"))
            + " pregame_state_sha256=" + str(rng_manifest.get("pregame_state_sha256"))
            + " model_input_sha256=" + str(rng_manifest.get("model_input_sha256"))
            + " reference_data_sha256=" + reference_digest(reference)
            + " layer_tables_sha256=" + layer_digest(playcall_description))
    aggregation = importlib.import_module("pregame_batch")
    rows = []
    details = []
    records = []
    decision_records = []
    if getattr(args, "decisions_out", None):
        sampler = getattr(reference, "contextual_sampler", None)
        if sampler is None:
            raise ModelPackError("DECISION_TRACE_SAMPLER_MISSING")
        if hasattr(sampler, "trace_outcome_probabilities"):
            sampler.trace_outcome_probabilities = True
    for seed in range(args.seed_start, args.seed_start + args.games):
        record = None
        record_error = None
        seed_decisions = []
        try:
            record = _run_seed(seed, reference, snapshot, gs, slc_engine, rng_plan,
                               seed_decisions if getattr(args, "decisions_out", None) else None)
            status = record.get("status", "unknown")
            blocker = record.get("blocker")
            valid = bool(record.get("valid_full_game") and record.get("complete_game"))
            reached_reg = bool(record.get("regulation_end_reached"))
            # The overtime subrecord captures the score at the end of regulation.
            # Keep that diagnostic independent from the final, possibly overtime,
            # score and from snapshot evidence classification.
            regulation_points = ((record.get("overtime") or {}).get("regulation_points")
                                 or record.get("points", {}))
            regulation_home = regulation_points.get("A")
            regulation_away = regulation_points.get("B")
            tied_reg = bool(reached_reg and regulation_home is not None
                            and regulation_away is not None
                            and regulation_home == regulation_away)
            row = {
                "seed": seed, "status": status, "blocker": blocker,
                "valid_full_game": valid, "complete_game": bool(record.get("complete_game")),
                "regulation_end_reached": reached_reg, "tied_at_regulation_end": tied_reg,
                "regulation_home_points": regulation_home,
                "regulation_away_points": regulation_away,
                "home_points": record["points"]["A"], "away_points": record["points"]["B"],
                "score_scope": "valid_final" if valid else "regulation_end_only" if reached_reg else "partial"
            }
            if args.with_player_lines:
                details.append({"seed": seed, "players": (record.get("stats") or {}).get("player", [])})
        except Exception as exc:
            # Table-access attempts are packaging defects, not per-seed model failures.
            if "PORTABLE_RUNTIME_SOURCE_" in str(exc):
                raise
            record_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            row = {
                "seed": seed, "status": "simulation_error", "blocker": None,
                "valid_full_game": False, "complete_game": False,
                "regulation_end_reached": False, "tied_at_regulation_end": False,
                "regulation_home_points": None, "regulation_away_points": None,
                "home_points": None, "away_points": None, "score_scope": "none",
                "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            }
        rows.append(row)
        if getattr(args, "decisions_out", None):
            decision_records.append({"seed": seed, "model_id": args.model,
                                     "decisions": seed_decisions, "error": record_error})
        if args.records_out:
            records.append({"seed": seed, "record": record, "error": record_error})
    summary = aggregation.summarize_outcomes(rows, args.games)
    regulation_diagnostics = {
        "games_reaching_regulation_end": sum(row["regulation_end_reached"] for row in rows),
        "games_tied_at_regulation_end": sum(row["tied_at_regulation_end"] for row in rows),
        "regulation_scores_by_seed": [
            {"seed": row["seed"], "home_points": row["regulation_home_points"],
             "away_points": row["regulation_away_points"]}
            for row in rows if row["regulation_end_reached"]
        ],
    }
    payload = {
        "schema": "lp-slc-portable-simulation-1",
        "pack": {"sha256": args.pack_sha256, "model_id": manifest["model_id"],
                 "source_commit": manifest["model_code_commit"],
                 "reference_sha256": manifest["reference_sha256"],
                 "build_game_id": manifest["game_id"],
                 "build_snapshot_sha256": manifest["snapshot_sha256"]},
        "game_id": args.game, "as_of_utc": snapshot["as_of"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "rng_protocol": rng_manifest,
        "simulation": {"requested_games": args.games, "valid_full_games": summary["valid_full_games"],
                       "seed_start": args.seed_start, "seed_end_inclusive": args.seed_start + args.games - 1},
        "summary": summary,
        "regulation_end_diagnostics": regulation_diagnostics,
    }
    if args.with_player_lines:
        payload["player_boxscores_by_seed"] = details
    if args.records_out:
        records_path = Path(args.records_out)
        records_path.parent.mkdir(parents=True, exist_ok=True)
        if records_path.exists():
            raise FileExistsError(f"immutable records file exists: {records_path}")
        records_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records))
    if getattr(args, "decisions_out", None):
        decisions_path = Path(args.decisions_out)
        decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with decisions_path.open("x") as stream:
            for row in decision_records:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"immutable output exists: {output}")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {output}: {summary['valid_full_games']}/{args.games} complete valid games")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="registered model ID")
    ap.add_argument("--game", required=True, help="game ID for this simulation")
    ap.add_argument("--snapshot", type=Path, required=True,
                    help="hash-pinned pregame snapshot, optionally wrapped with frozen runtime_model_inputs")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--pack-sha256", required=True, help="independent pack hash from trusted build manifest")
    ap.add_argument("--games", type=int, required=True)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument("--rng-protocol", choices=("v1", "v2"), default=None,
                    help="override the pack's recorded RNG scheme; V1 default remains unchanged")
    ap.add_argument("--expected-stream-root-sha256", default=None,
                    help="for RNG v2, reject the run before seeds if its computed stream root differs")
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-player-lines", dest="with_player_lines", action="store_true", default=True,
                    help="retain player box stats for each seed in output (the default)")
    ap.add_argument("--no-player-lines", dest="with_player_lines", action="store_false",
                    help="leave player box stats out of the output")
    ap.add_argument("--records-out", type=Path,
                    help="write each full per-seed game record as JSONL for exact parity checks")
    ap.add_argument("--decisions-out", type=Path,
                    help="write per-seed play-call decisions and available probability stages as JSONL")
    args = ap.parse_args(argv)
    if args.games < 1 or args.seed_start < 0:
        ap.error("games must be positive and seed-start nonnegative")
    # Fail if imports or any seed execution tries to reach source data.
    _forbid_source_table_reads()
    with tempfile.TemporaryDirectory(prefix="slc-model-runtime-") as temporary:
        return _run(args, temporary)


if __name__ == "__main__":
    raise SystemExit(main())
