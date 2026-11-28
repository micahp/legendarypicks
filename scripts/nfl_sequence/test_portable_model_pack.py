"""Offline portable model-pack tests. No SLC database or fixture files required."""
import json
import io
import tempfile
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import unittest

from portable_model_pack import ModelPackError, load_pack, write_pack
from compile_portable_pack import (_default_frame_cache_args, _freeze_backoff_support, _portable_runtime_adapters,
                                   _require_registered_build_inputs, _export_enabled_layers, compile_model,
                                   _require_build_policy, _require_build_smoke)
from simulate_portable_pack import _attach_runtime_adapters, _run_seed


def _reference():
    return SimpleNamespace(
        pool={(1, 2, 3): [("run", {"play_id": "fixture"}, 8, 55)]},
        kickoff_pool=[{"spot": 70}],
        kicks={"field_goal": [1], "field_goal_outcomes": {"short": (1, 1, 0)},
               "extra_point": [1], "two_point": [1]},
        participants={("g", "p"): {}},
        missed_field_goal_pool={"short": [{"spot_adjustment_yards": 0}]},
        safety_kick_pool=[{"spot": 40}],
        overtime_pool=[{"winning_drive": True}],
        overtime_try_p_two={key: 0.05 for key in ("<=-9", "-8..-5", "-4..-1", "0", "1..4", "5..8", ">=9")},
        overtime_p_kick=0.0,
        blocked_kicks={"rates": {"punt_blocked": {"rate": 0.01},
                                  "field_goal_blocked_by_snap_bucket": {"short": {"rate": 0.01}}},
                       "records": {"punt": [{"spot": 50}], "field_goal": []}},
        model_inputs={"sha256": "f" * 64},
        contextual_sampler=None,
    )


def _engine_files():
    return {"scripts/nfl_sequence/game_state.py": b"# pinned engine\n",
            "scripts/nfl_sequence/slc_engine.py": b"# pinned SLC engine\n"}


def _snapshot():
    return {
        "snapshot_sha256": "a" * 64,
        "as_of": "2026-11-18T22:00:00Z",
        "schedule": {"game_id": "2026_11_IND_HOU"},
        "rosters": {"home": {}, "away": {}},
    }


class PortablePack(unittest.TestCase):
    def test_backoff_freeze_preserves_group_membership_and_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "support.sqlite"
            with sqlite3.connect(str(path)) as db:
                db.execute("CREATE TABLE support(variant,level,outcome_class,lookup_key,game_id,play_id)")
                db.executemany("INSERT INTO support VALUES (?,?,?,?,?,?)", [
                    ("11", "down_field", "run", '[1,"own"]', "A", 8),
                    ("00", "down_field", "run", '[1,"own"]', "A", 3),
                    ("11", "down_field", "run", '[1,"own"]', "B", 2)])
            sampler = SimpleNamespace(source_support_artifact=str(path), source_support_variant="11")
            _freeze_backoff_support(sampler)
            self.assertEqual(sampler.portable_backoff_groups,
                             {("down_field", "run", (1, "own")): [("A", 8), ("B", 2)]})

    def test_v17_penalty_factory_is_frozen_as_model_state_not_a_closure(self):
        sampler = object()
        ruling_book = None

        def make_factory(penalty_sampler, pinned_ruling_book):
            def factory(*, seed, snapshot, ledger):
                return penalty_sampler, pinned_ruling_book
            return factory

        reference = SimpleNamespace(penalty_controller_factory=make_factory(sampler, ruling_book))
        adapters = _portable_runtime_adapters(
            reference, {"family": "v1.7", "experimental_flags": {"penalty_ruling_policy": "research"}})
        self.assertIsNone(reference.penalty_controller_factory)
        self.assertIs(reference.portable_v1_7_penalty_sampler, sampler)
        self.assertEqual(adapters["v1_7_penalty"]["sampler_attribute"],
                         "portable_v1_7_penalty_sampler")
        self.assertEqual(adapters["v1_7_penalty"]["ruling_policy"], "research")
        json.dumps(adapters)

    def test_v17_runtime_rejects_missing_penalty_model_state(self):
        with self.assertRaisesRegex(ModelPackError, "PACKED_V17_PENALTY_RUNTIME_MISSING"):
            _attach_runtime_adapters(SimpleNamespace(), {}, "v1.7")
        with self.assertRaisesRegex(ModelPackError, "PACKED_V17_PENALTY_RUNTIME_MISSING"):
            _attach_runtime_adapters(SimpleNamespace(), {}, "v1.7-penalties-on")

    def test_v16_streak_file_is_auto_forwarded_from_registered_environment(self):
        with tempfile.TemporaryDirectory() as dirname:
            streak = Path(dirname) / "frozen-streaks.json"
            streak.write_text('{"teams": {}}')
            model = {"family": "v1.6", "enabled_layers": ["current_streak_context"],
                     "build_inputs": [{"flag": "--playcall-streak-file", "env": "SLC_V1_6_STREAK_FILE"}]}
            flags = _require_registered_build_inputs(
                model, ["--snapshot-file", "snap.json"],
                {"SLC_V1_6_STREAK_FILE": str(streak)})
            self.assertEqual(flags[-2:], ["--playcall-streak-file", str(streak)])
            self.assertEqual(_require_registered_build_inputs(model, flags, {}),
                             flags)

    def test_required_streak_file_fails_before_model_build_if_missing(self):
        model = {"family": "v1.6", "build_inputs": [
            {"flag": "--playcall-streak-file", "env": "SLC_V1_6_STREAK_FILE"}]}
        with self.assertRaisesRegex(ModelPackError, "REQUIRED_MODEL_BUILD_INPUT_MISSING"):
            _require_registered_build_inputs(model, [], {})
        with self.assertRaisesRegex(ModelPackError, "REQUIRED_MODEL_BUILD_FILE_MISSING"):
            _require_registered_build_inputs(
                model, ["--playcall-streak-file", "/no/such/frozen-streaks.json"], {})
        with tempfile.TemporaryDirectory() as dirname:
            streak = Path(dirname) / "streak.json"
            streak.write_text("{}")
            with self.assertRaisesRegex(ModelPackError, "DUPLICATE_REQUIRED_BUILD_INPUT"):
                _require_registered_build_inputs(
                    model, ["--playcall-streak-file", str(streak),
                            "--playcall-streak-file", str(streak)], {})

    def test_v17_export_lists_penalties_and_rejects_missing_adapter(self):
        profile = {"enabled_layers": {"score_clock_playcalling": True,
                                      "current_streak_context": True}}
        spec = {"family": "v1.7", "enabled_layers": [
            "current_streak_context", "penalty_proposal_and_enforcement"]}
        adapter = {"v1_7_penalty": {"ruling_policy": "research"}}
        self.assertEqual(_export_enabled_layers(profile, spec, adapter), [
            "current_streak_context", "penalty_proposal_and_enforcement",
            "score_clock_playcalling"])
        with self.assertRaisesRegex(ModelPackError, "REQUIRED_V17_PENALTY_ADAPTER_NOT_CAPTURED"):
            _export_enabled_layers(profile, spec, {})

    def test_v16_package_cannot_omit_current_streak_layer(self):
        spec = {"family": "v1.6", "enabled_layers": ["current_streak_context"]}
        with self.assertRaisesRegex(ModelPackError, "REQUIRED_CURRENT_STREAK_LAYER_NOT_ENABLED"):
            _export_enabled_layers({"enabled_layers": {}}, spec, {})

    def test_compiler_uses_a_commit_and_cutoff_scoped_default_frame_cache(self):
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            snapshot = root / "snapshot.json"
            snapshot.write_text(json.dumps({"schedule": {"season": 2026}}))
            args = ["--snapshot-file", str(snapshot), "--db", str(root / "frozen.db")]
            spec = {"use_playcall_frame_cache": True, "code_commit": "a" * 40}
            actual = _default_frame_cache_args(spec, args)
            self.assertEqual(actual[-2], "--playcall-point-splits-cache")
            self.assertEqual(actual[-1], str(root / "frozen.db.playcall-frame-aaaaaaaaaaaa-2010-2025.npz"))

    def test_legacy_rng_runs_with_pinned_engine_api_without_rng_plan_parameter(self):
        seen = {}

        def legacy_play(seed, reference, snapshot, *, paired_randomness=False):
            seen.update(seed=seed, snapshot=snapshot, paired=paired_randomness)
            return {"status": "complete_regulation"}, []

        engine = SimpleNamespace(is_slc=lambda _reference: True, play=legacy_play)
        game_state = SimpleNamespace(validate_game=lambda _record: None)
        plan = SimpleNamespace(scheme="v1", paired=False, seed_root=lambda _snapshot: None)
        record = _run_seed(17, object(), {"schedule": {}}, game_state, engine, plan)
        self.assertEqual(record["status"], "complete_regulation")
        self.assertEqual(seen, {"seed": 17, "snapshot": {"schedule": {}}, "paired": False})

    def test_rng_v2_fails_by_name_when_pinned_engine_has_no_rng_plan_api(self):
        def legacy_play(seed, reference, snapshot, *, paired_randomness=False):
            raise AssertionError("must fail before calling the engine")

        engine = SimpleNamespace(is_slc=lambda _reference: True, play=legacy_play)
        game_state = SimpleNamespace(validate_game=lambda _record: None)
        plan = SimpleNamespace(scheme="v2", paired=True, seed_root=lambda _snapshot: "root")
        with self.assertRaisesRegex(ModelPackError, "PORTABLE_RNG_PROTOCOL_UNSUPPORTED_BY_ENGINE"):
            _run_seed(17, object(), {"schedule": {}}, game_state, engine, plan)

    def test_build_smoke_requires_actual_valid_requested_seed(self):
        row = {"seed": 300001, "valid_full_game": True, "complete_game": True,
               "score_scope": "valid_final", "home_points": 21, "away_points": 17}
        result = {"simulation": {"requested_games": 1, "seed_start": 300001, "seed_end_inclusive": 300001},
                  "summary": {"valid_full_games": 1, "outcomes": [row]}}
        _require_build_smoke(result)
        for rows in ([], [{**row, "seed": 2}], [{**row, "complete_game": False}]):
            result["summary"]["outcomes"] = rows
            with self.assertRaisesRegex(ModelPackError, "BUILD_SMOKE_INVALID"):
                _require_build_smoke(result)

    def test_build_policy_refuses_explicit_seed_file_and_wrong_variant(self):
        from slc_model_registry import get_model
        v2 = get_model("v2")
        args = list(v2["build_args"]) + ["--slc-profile", v2["profile"]]
        _require_build_policy(v2, args)
        for extra in (["--seed-list-file", "many.json"], ["--resume"], ["--games", "1000"],
                      ["--rng-protocol", "v1"], ["--playcall-pass-label-mode=unconditional"]):
            with self.assertRaises(ModelPackError):
                _require_build_policy(v2, args + extra)
        with self.assertRaisesRegex(ModelPackError, "BUILD_V2_POLICY_MISSING"):
            _require_build_policy(v2, [])
        with self.assertRaisesRegex(ModelPackError, "BUILD_PBV1_POLICY_CONFLICT"):
            _require_build_policy(get_model("pbv1-off"), ["--playcall-pbv1-package", "x"])

    def test_regulation_only_build_option_is_rejected_by_name(self):
        with self.assertRaisesRegex(ModelPackError, "OVERTIME_DISABLED_PROFILE_RETIRED"):
            compile_model("/does/not/matter", "/tmp/unused.slcpack", "v1", ["--no-overtime-table"])

    def test_round_trip_without_model_tables(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            original = _reference()
            result = write_pack(path, reference=original, snapshot=_snapshot(),
                                model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            assert result["manifest"]["full_game_capable"]
            engine_dir = Path(dirname) / "engine"
            ref, snapshot, manifest, config = load_pack(
                path, expected_sha256=result["sha256"], expected_code_commit="1" * 40, engine_dir=engine_dir)
            self.assertEqual(ref.overtime_pool, original.overtime_pool)
            self.assertEqual(ref.model_inputs, original.model_inputs)
            self.assertEqual(snapshot["schedule"]["game_id"], "2026_11_IND_HOU")
            self.assertEqual(manifest["checks"]["overtime_pool_samples"], 1)
            self.assertEqual((engine_dir / "scripts/nfl_sequence/game_state.py").read_bytes(),
                             _engine_files()["scripts/nfl_sequence/game_state.py"])
            with __import__("zipfile").ZipFile(path) as archive:
                self.assertIn("reference.json", archive.namelist())
                self.assertNotIn("reference.pkl", archive.namelist())
            self.assertEqual(config, {})

    def test_v17_writer_rejects_pack_without_penalty_layer_and_sampler(self):
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "V17_PENALTY_EXPORT_INCOMPLETE"):
                write_pack(Path(dirname) / "bad.slcpack", reference=_reference(),
                           snapshot=_snapshot(), model_id="v1.7", code_commit="1" * 40,
                           engine_files=_engine_files(),
                           config={"enabled_layers": ["score_clock_playcalling"]})

    def test_v16_writer_rejects_missing_streak_game_overlay(self):
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "V16_STREAK_EXPORT_INCOMPLETE"):
                write_pack(Path(dirname) / "bad.slcpack", reference=_reference(),
                           snapshot=_snapshot(), model_id="v1.6", code_commit="1" * 40,
                           engine_files=_engine_files(),
                           config={"enabled_layers": ["current_streak_context"]})

    def test_missing_overtime_fails_during_build(self):
        ref = _reference()
        ref.overtime_pool = None
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "MISSING_REQUIRED_OVERTIME_POOL"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v2", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_missing_safety_kick_fails_during_build(self):
        ref = _reference()
        ref.safety_kick_pool = None
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "MISSING_REQUIRED_SAFETY_KICK_POOL"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v2", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_missing_missed_field_goal_return_support_fails_during_build(self):
        ref = _reference()
        ref.missed_field_goal_pool = {}
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "MISSING_REQUIRED_MISSED_FIELD_GOAL_POOL"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v1", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_incomplete_kick_outcomes_fail_during_build(self):
        ref = _reference()
        ref.kicks["extra_point"] = None
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "INCOMPLETE_REQUIRED_KICK_OUTCOMES"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v1", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_missing_overtime_policy_fails_during_build(self):
        ref = _reference()
        ref.overtime_try_p_two = None
        ref.overtime_p_kick = None
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "MISSING_REQUIRED_OVERTIME_TRY_FALLBACK"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v1", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_empty_overtime_pool_fails_during_build(self):
        ref = _reference()
        ref.overtime_pool = []
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "EMPTY_REQUIRED_OVERTIME_POOL"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v1", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_forced_choice_does_not_replace_observed_kick_model(self):
        ref = _reference()
        ref.overtime_p_kick = None
        ref.overtime_choice = "receive"
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "MISSING_OR_INVALID_REQUIRED_OVERTIME_KICK_MODEL"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v1", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_invalid_overtime_try_probability_fails_during_build(self):
        ref = _reference()
        ref.overtime_try_p_two["0"] = float("nan")
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "INVALID_REQUIRED_OVERTIME_TRY_FALLBACK"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v1", code_commit="1" * 40,
                           engine_files=_engine_files())

    def test_state_codec_round_trips_typed_containers(self):
        from collections import Counter, defaultdict
        from portable_model_pack import (_StateJSONReader, _decode_state, _encode_state,
                                         _iter_state_json, _write_state_payload)
        import numpy as np

        value = {("home", 1): Counter({"pass": 2}), "groups": defaultdict(list, {"11": [1, 2]}),
                 "counter_groups": defaultdict(Counter, {"team": Counter({"run": 3})}),
                 "weights": defaultdict(float, {"pass": 0.75}), "unordered": {3, 1, 2},
                 "array": np.asarray([[1, 2], [3, 4]], dtype=np.int16), "object": SimpleNamespace(x=1)}
        restored = _decode_state(_encode_state(value))
        for key in ("home", "groups", "counter_groups", "weights", "unordered", "object"):
            if key == "home":
                self.assertEqual(restored[("home", 1)], value[("home", 1)])
            else:
                self.assertEqual(restored[key], value[key])
        np.testing.assert_array_equal(restored["array"], value["array"])
        self.assertIsInstance(restored[("home", 1)], Counter)
        self.assertIsInstance(restored["groups"], defaultdict)
        self.assertEqual(restored["counter_groups"]["missing"], Counter())
        self.assertEqual(restored["weights"]["missing"], 0.0)
        streamed = _StateJSONReader(io.StringIO("".join(_iter_state_json(value))), {"types"}).read()
        self.assertEqual(streamed["counter_groups"]["team"], Counter({"run": 3}))
        self.assertEqual(streamed["groups"]["11"], [1, 2])
        self.assertEqual(streamed["object"].x, 1)
        np.testing.assert_array_equal(streamed["array"], value["array"])

        payload = io.BytesIO()
        digest, size = _write_state_payload(payload, _reference(), _snapshot(), {})
        encoded = payload.getvalue()
        self.assertEqual(size, len(encoded))
        self.assertEqual(digest, __import__("hashlib").sha256(encoded).hexdigest())
        decoded = _StateJSONReader(io.StringIO(encoded.decode("utf-8")), {"types"}).read()
        self.assertEqual(decoded["schema"], "lp-slc-model-state-1")
        self.assertEqual(decoded["reference"].overtime_pool, _reference().overtime_pool)

    def test_stream_reader_does_not_accept_numeric_prefixes_at_chunk_boundaries(self):
        from portable_model_pack import _StateJSONReader

        class ChunkedText:
            def __init__(self, value):
                self.value = value
                self.offset = 0

            def read(self, size):
                end = min(self.offset + 1, len(self.value))
                chunk = self.value[self.offset:end]
                self.offset = end
                return chunk

        parsed = _StateJSONReader(ChunkedText('{"decimal":1.25,"integer":123}'), set()).read()
        self.assertEqual(parsed, {"decimal": 1.25, "integer": 123})

    def test_shared_pool_is_serialized_once_and_restored_by_identity(self):
        import zipfile
        from collections import defaultdict
        from portable_model_pack import SHARED_POOL_SCHEMA
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            ref = _reference()
            ref.pool = defaultdict(list, {
                (1, 2, 3): [("run", {"play_id": "unique-pool-marker-123", "nested": [1, 2]}, 8, 55)],
                (2, 3, 4): [("pass", {"play_id": "second"}, 5, 60)]})
            ref.contextual_sampler = SimpleNamespace(source_pool=ref.pool, other={"kept": 1})
            original_keys = list(vars(ref.contextual_sampler))
            result = write_pack(root / "new.slcpkg", reference=ref, snapshot=_snapshot(),
                                model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            self.assertEqual(result["manifest"]["schema"], SHARED_POOL_SCHEMA)
            self.assertIs(ref.contextual_sampler.source_pool, ref.pool)
            self.assertEqual(list(vars(ref.contextual_sampler)), original_keys)
            with zipfile.ZipFile(root / "new.slcpkg") as archive:
                payload = archive.read("reference.json")
                self.assertEqual(payload.count(b"unique-pool-marker-123"), 1)
            loaded, snap, manifest, config = load_pack(
                root / "new.slcpkg", expected_sha256=result["sha256"],
                expected_code_commit="1" * 40, engine_dir=root / "engine")
            self.assertIs(loaded.pool, loaded.contextual_sampler.source_pool)
            self.assertEqual(list(loaded.pool.items()), list(ref.pool.items()))
            self.assertIsInstance(loaded.pool, defaultdict)
            self.assertIs(loaded.pool.default_factory, list)
            self.assertEqual(loaded.contextual_sampler.other, {"kept": 1})
            self.assertEqual(snap, _snapshot())
            self.assertEqual(config, {})
            self.assertEqual(manifest["reference_sha256"], ref.model_inputs["sha256"])

    def test_legacy_equal_but_distinct_pools_are_not_implicitly_merged(self):
        import copy
        from portable_model_pack import SCHEMA, repack_shared_pool
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            ref = _reference()
            ref.contextual_sampler = SimpleNamespace(source_pool=copy.deepcopy(ref.pool))
            old = write_pack(root / "old.slcpkg", reference=ref, snapshot=_snapshot(),
                             model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            self.assertEqual(old["manifest"]["schema"], SCHEMA)
            loaded, _, _, _ = load_pack(root / "old.slcpkg", expected_sha256=old["sha256"],
                                        expected_code_commit="1" * 40, engine_dir=root / "old-engine")
            self.assertIsNot(loaded.pool, loaded.contextual_sampler.source_pool)
            self.assertEqual(loaded.pool, loaded.contextual_sampler.source_pool)
            new = repack_shared_pool(root / "old.slcpkg", root / "new.slcpkg",
                                     expected_sha256=old["sha256"], expected_code_commit="1" * 40)
            loaded, _, _, _ = load_pack(root / "new.slcpkg", expected_sha256=new["sha256"],
                                        expected_code_commit="1" * 40, engine_dir=root / "new-engine")
            self.assertIs(loaded.pool, loaded.contextual_sampler.source_pool)
            self.assertEqual(loaded.pool, ref.pool)
            self.assertLess(new["manifest"]["payload_bytes"], old["manifest"]["payload_bytes"])
            self.assertEqual(new["original_pack_sha256"], old["sha256"])
            self.assertTrue((root / "old.slcpkg").is_file())

    def test_repack_refuses_different_source_content_or_order(self):
        from portable_model_pack import repack_shared_pool
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            ref = _reference()
            ref.pool[(2, 3, 4)] = [("run", {"play_id": "other"}, 4, 40)]
            ref.contextual_sampler = SimpleNamespace(source_pool=dict(reversed(list(ref.pool.items()))))
            old = write_pack(root / "old.slcpkg", reference=ref, snapshot=_snapshot(),
                             model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            with self.assertRaisesRegex(ModelPackError, "REPACK_SOURCE_POOL_CONTENT_MISMATCH"):
                repack_shared_pool(root / "old.slcpkg", root / "new.slcpkg",
                                   expected_sha256=old["sha256"], expected_code_commit="1" * 40)
            self.assertFalse((root / "new.slcpkg").exists())

    def test_shared_pool_schema_refuses_missing_or_duplicate_alias_fields(self):
        from portable_model_pack import _restore_shared_source_pool
        for ref in (SimpleNamespace(pool={}, contextual_sampler=None),
                    SimpleNamespace(pool={}, contextual_sampler=SimpleNamespace(source_pool={})),
                    SimpleNamespace(pool=None, contextual_sampler=SimpleNamespace())):
            with self.assertRaisesRegex(ModelPackError, "SHARED_SOURCE_POOL_STATE_INVALID"):
                _restore_shared_source_pool(ref)

    def test_repack_cli_preserves_snapshot_config_and_engine_hashes(self):
        import copy
        import contextlib
        import slc_cli
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            ref = _reference()
            ref.contextual_sampler = SimpleNamespace(source_pool=copy.deepcopy(ref.pool))
            old = write_pack(root / "old.slcpkg", reference=ref, snapshot=_snapshot(),
                             model_id="v1", code_commit="1" * 40, engine_files=_engine_files(),
                             config={"training_cutoff": {"eligible_before": [2026, 1]},
                                     "enabled_layers": ["test"], "source": {"sha256": "b" * 64}})
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(slc_cli.main(["pack", "repack-shared-pool",
                    "--pack", str(root / "old.slcpkg"), "--pack-sha256", old["sha256"],
                    "--code-commit", "1" * 40, "--out", str(root / "new.slcpkg")]), 0)
            new = json.loads(output.getvalue())
            _, snap, manifest, config = load_pack(
                root / "new.slcpkg", expected_sha256=new["sha256"],
                expected_code_commit="1" * 40, engine_dir=root / "engine")
            self.assertEqual(snap, _snapshot())
            self.assertEqual(config["source"], {"sha256": "b" * 64})
            for key in old["manifest"]:
                if key not in {"schema", "payload_sha256", "payload_bytes"}:
                    self.assertEqual(manifest[key], old["manifest"][key])

    def test_schema2_reader_shares_repeated_short_strings(self):
        from portable_model_pack import _StateJSONReader, _iter_state_json
        value = [{"long_key_for_historical_row": "a_repeated_game_identifier"} for _ in range(20)]
        encoded = "".join(_iter_state_json(value))
        restored = _StateJSONReader(io.StringIO(encoded), {"types"}, share_strings=True).read()
        self.assertEqual(value, restored)
        self.assertIs(next(iter(restored[0])), next(iter(restored[-1])))
        self.assertIs(restored[0]["long_key_for_historical_row"], restored[-1]["long_key_for_historical_row"])

    def test_describe_memo_is_not_serialized_in_either_format(self):
        from portable_model_pack import _write_state_payload, _StateJSONReader
        for shared_pool in (False, True):
            with self.subTest(shared_pool=shared_pool):
                ref = _reference()
                sampler = SimpleNamespace(source_pool=ref.pool, layer=SimpleNamespace(artifact={"x": 1}))
                ref.contextual_sampler = sampler
                ref._describe_memo = ((sampler, ref.model_inputs, sampler.layer.artifact),
                                      {"derived": "never-serialize-this-memo-marker"})
                payload = io.BytesIO()
                _write_state_payload(payload, ref, _snapshot(), {}, shared_pool=shared_pool)
                raw = payload.getvalue()
                self.assertNotIn(b"_describe_memo", raw)
                self.assertNotIn(b"never-serialize-this-memo-marker", raw)
                self.assertIs(ref._describe_memo[0][0], sampler)
                self.assertIs(ref.contextual_sampler.source_pool, ref.pool)
                restored = _StateJSONReader(io.StringIO(raw.decode()), {"types"}).read()["reference"]
                self.assertFalse(hasattr(restored, "_describe_memo"))
                self.assertEqual(restored.model_inputs, ref.model_inputs)
                self.assertEqual(restored.contextual_sampler.layer.artifact, sampler.layer.artifact)
                self.assertEqual(restored.pool, ref.pool)

    def test_repack_removes_actual_legacy_memo_and_duplicate_pool(self):
        import copy
        import hashlib
        import zipfile
        from portable_model_pack import repack_shared_pool, _iter_state_json
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            ref = _reference()
            sampler = SimpleNamespace(source_pool=copy.deepcopy(ref.pool),
                                      layer=SimpleNamespace(artifact={"x": 1}))
            ref.contextual_sampler = sampler
            ref._describe_memo = ((sampler, ref.model_inputs, sampler.layer.artifact),
                                  {"derived": "legacy-memo-marker"})
            old = write_pack(root / "base.slcpkg", reference=ref, snapshot=_snapshot(),
                             model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            # Construct a genuine old-schema archive using the original raw
            # tagged serializer, not the new writer which omits the memo.
            raw = ('{"config":{},"reference":' + "".join(_iter_state_json(ref))
                   + ',"schema":"lp-slc-model-state-1","snapshot":'
                   + json.dumps(_snapshot(), sort_keys=True, separators=(",", ":")) + '}\n').encode()
            manifest = dict(old["manifest"], payload_bytes=len(raw),
                            payload_sha256=hashlib.sha256(raw).hexdigest())
            legacy = root / "legacy.slcpkg"
            with zipfile.ZipFile(legacy, "w") as archive:
                archive.writestr("reference.json", raw)
                archive.writestr("manifest.json", json.dumps(manifest))
                for name, content in _engine_files().items():
                    archive.writestr("engine/" + name, content)
            digest = hashlib.sha256(legacy.read_bytes()).hexdigest()
            new = repack_shared_pool(legacy, root / "new.slcpkg",
                                     expected_sha256=digest, expected_code_commit="1" * 40)
            restored, _, _, _ = load_pack(root / "new.slcpkg", expected_sha256=new["sha256"],
                                          expected_code_commit="1" * 40, engine_dir=root / "engine")
            self.assertFalse(hasattr(restored, "_describe_memo"))
            self.assertIs(restored.pool, restored.contextual_sampler.source_pool)
            self.assertEqual(restored.pool, ref.pool)
            self.assertEqual(restored.model_inputs, ref.model_inputs)
            with zipfile.ZipFile(root / "new.slcpkg") as archive:
                self.assertNotIn(b"legacy-memo-marker", archive.read("reference.json"))

    def test_wrong_external_hash_blocks_package_load(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            write_pack(path, reference=_reference(), snapshot=_snapshot(),
                       model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            with self.assertRaisesRegex(ModelPackError, "PACK_SHA256_MISMATCH"):
                load_pack(path, expected_sha256="0" * 64, expected_code_commit="1" * 40)

    def test_wrong_code_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            result = write_pack(path, reference=_reference(), snapshot=_snapshot(),
                                model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            with self.assertRaisesRegex(ModelPackError, "MODEL_CODE_COMMIT_MISMATCH"):
                load_pack(path, expected_sha256=result["sha256"], expected_code_commit="2" * 40)

    def test_cannot_overwrite_immutable_pack(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            write_pack(path, reference=_reference(), snapshot=_snapshot(),
                       model_id="v1", code_commit="1" * 40, engine_files=_engine_files())
            with self.assertRaises(FileExistsError):
                write_pack(path, reference=_reference(), snapshot=_snapshot(),
                           model_id="v1", code_commit="1" * 40, engine_files=_engine_files())


if __name__ == "__main__":
    unittest.main()
