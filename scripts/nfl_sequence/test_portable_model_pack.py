"""Offline portable model-pack tests. No SLC database or fixture files required."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from portable_model_pack import ModelPackError, load_pack, write_pack
from compile_portable_pack import compile_model


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
        from portable_model_pack import _decode_state, _encode_state

        value = {("home", 1): Counter({"pass": 2}), "groups": defaultdict(list, {"11": [1, 2]}),
                 "unordered": {3, 1, 2}}
        restored = _decode_state(_encode_state(value))
        self.assertEqual(restored, value)
        self.assertIsInstance(restored[("home", 1)], Counter)
        self.assertIsInstance(restored["groups"], defaultdict)

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
