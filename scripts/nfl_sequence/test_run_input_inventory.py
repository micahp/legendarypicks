from argparse import Namespace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import run_input_inventory as inventory


class InventoryTests(unittest.TestCase):
    def test_small_file_observed_with_hash_and_mtime(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "a.json"
            path.write_bytes(b"test")
            record = inventory.observe(path)
            self.assertEqual(record["sha256"], hashlib.sha256(b"test").hexdigest())
            self.assertEqual(record["size_bytes"], 4)
            self.assertIn("mtime_utc", record)

    def test_large_input_does_not_force_hash(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "a.db"
            path.write_bytes(b"test")
            record = inventory.observe(path, max_hash_bytes=1)
            self.assertEqual(record["hash_status"], "skipped_large_input")
            self.assertIsNone(record["sha256"])

    def test_missing_file_is_reported_without_failure(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(inventory.observe(Path(root) / "missing")["status"], "unavailable")

    def test_before_after_flags_source_change_and_never_changes_input(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "live.db"
            path.write_bytes(b"old")
            args = Namespace(out=str(Path(root) / "run.json"), db=str(path))
            sidecar, started = inventory.begin(args, root=root)
            self.assertTrue(sidecar.exists())
            path.write_bytes(b"new version")
            result = inventory.finish(args, sidecar, started, status="completed")
            self.assertEqual(result["files_changed_during_run"], ["db"])
            self.assertEqual(json.loads(sidecar.read_text())["status"], "completed")
            self.assertEqual(path.read_bytes(), b"new version")

    def test_model_hash_identity_is_copied_from_result_when_present(self):
        with tempfile.TemporaryDirectory() as root:
            args = Namespace(out=str(Path(root) / "run.json"), db=Path(root) / "missing.db")
            path, started = inventory.begin(args, root=root)
            payload = {"slc_profile_manifest": {
                "model_id": "SLC_v1_full_stack", "configuration_hash": "abc",
                "reference_sha256": "refhash", "snapshot_sha256": "snaphash",
                "playcall_artifact_sha256": "artifacthash", "source_cutoff": [2026, 10],
                "integration_code_sha256": {"slc_playcall.py": "codehash"},
            }}
            result = inventory.finish(args, path, started, status="completed", run_payload=payload)
            self.assertEqual(result["model_identity_from_result"]["reference_sha256"], "refhash")
            self.assertEqual(result["model_identity_from_result"]["configuration_hash"], "abc")

    def test_new_invocation_never_overwrites_prior_sidecar(self):
        with tempfile.TemporaryDirectory() as root:
            args = Namespace(out=str(Path(root) / "run.json"), db=Path(root) / "missing.db")
            one, _ = inventory.begin(args, root=root)
            two, _ = inventory.begin(args, root=root)
            self.assertNotEqual(one, two)
            self.assertTrue(one.exists() and two.exists())


if __name__ == "__main__":
    unittest.main()
