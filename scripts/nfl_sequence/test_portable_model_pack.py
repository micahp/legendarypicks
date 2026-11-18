"""Offline portable model-pack tests. No SLC database or fixture files required."""
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from portable_model_pack import ModelPackError, load_pack, write_pack


def _reference():
    return SimpleNamespace(
        pool={(1, 2, 3): [("run", {"play_id": "fixture"}, 8, 55)]},
        kickoff_pool=[{"spot": 70}],
        kicks={"field_goal": [1]},
        safety_kick_pool=[{"spot": 40}],
        overtime_pool=[{"winning_drive": True}],
        model_inputs={"sha256": "f" * 64},
        contextual_sampler=None,
    )


def _snapshot():
    return {
        "snapshot_sha256": "a" * 64,
        "as_of": "2026-11-18T22:00:00Z",
        "schedule": {"game_id": "2026_11_IND_HOU"},
        "rosters": {"home": {}, "away": {}},
    }


class PortablePack(unittest.TestCase):
    def test_round_trip_without_model_tables(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            original = _reference()
            result = write_pack(path, reference=original, snapshot=_snapshot(),
                                model_id="v1", code_commit="123456")
            assert result["manifest"]["full_game_capable"]
            ref, snapshot, manifest, config = load_pack(
                path, expected_sha256=result["sha256"], expected_code_commit="123456")
            self.assertEqual(ref.overtime_pool, original.overtime_pool)
            self.assertEqual(ref.model_inputs, original.model_inputs)
            self.assertEqual(snapshot["schedule"]["game_id"], "2026_11_IND_HOU")
            self.assertEqual(manifest["checks"]["overtime_pool_samples"], 1)
            self.assertEqual(config, {})

    def test_missing_overtime_fails_during_build(self):
        ref = _reference()
        ref.overtime_pool = None
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "MISSING_REQUIRED_OVERTIME_POOL"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v2", code_commit="123456")

    def test_missing_safety_kick_fails_during_build(self):
        ref = _reference()
        ref.safety_kick_pool = None
        with tempfile.TemporaryDirectory() as dirname:
            with self.assertRaisesRegex(ModelPackError, "MISSING_REQUIRED_SAFETY_KICK_POOL"):
                write_pack(Path(dirname) / "bad.slcpack", reference=ref,
                           snapshot=_snapshot(), model_id="v2", code_commit="123456")

    def test_wrong_external_hash_blocks_unpickle(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            write_pack(path, reference=_reference(), snapshot=_snapshot(),
                       model_id="v1", code_commit="123456")
            with self.assertRaisesRegex(ModelPackError, "PACK_SHA256_MISMATCH"):
                load_pack(path, expected_sha256="0" * 64, expected_code_commit="123456")

    def test_wrong_code_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            result = write_pack(path, reference=_reference(), snapshot=_snapshot(),
                                model_id="v1", code_commit="123456")
            with self.assertRaisesRegex(ModelPackError, "MODEL_CODE_COMMIT_MISMATCH"):
                load_pack(path, expected_sha256=result["sha256"], expected_code_commit="654321")

    def test_cannot_overwrite_immutable_pack(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "v1.slcpack"
            write_pack(path, reference=_reference(), snapshot=_snapshot(),
                       model_id="v1", code_commit="123456")
            with self.assertRaises(FileExistsError):
                write_pack(path, reference=_reference(), snapshot=_snapshot(),
                           model_id="v1", code_commit="123456")


if __name__ == "__main__":
    unittest.main()
