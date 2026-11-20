"""Offline portable model-pack tests. No SLC database or fixture files required."""
import json
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from portable_model_pack import ModelPackError, load_pack, write_pack
from compile_portable_pack import (_default_frame_cache_args, _portable_runtime_adapters,
                                   compile_model)
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
