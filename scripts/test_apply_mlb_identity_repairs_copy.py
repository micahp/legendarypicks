#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_mlb_identity_repairs_copy as applier


class CopyGuardTests(unittest.TestCase):
    def test_accepts_single_link_regular_file_under_tmp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copy.db"
            path.write_bytes(b"sqlite-copy")
            self.assertEqual(applier.require_copy_path(str(path)), path.resolve())

    def test_refuses_paths_outside_tmp(self):
        with self.assertRaisesRegex(applier.InvariantError, "outside /tmp"):
            applier.require_copy_path(__file__)

    def test_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.db"
            link = Path(directory) / "link.db"
            target.write_bytes(b"sqlite-copy")
            link.symlink_to(target)
            with self.assertRaisesRegex(applier.InvariantError, "symlink"):
                applier.require_copy_path(str(link))

    def test_refuses_hard_link(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.db"
            link = Path(directory) / "link.db"
            target.write_bytes(b"sqlite-copy")
            os.link(target, link)
            with self.assertRaisesRegex(applier.InvariantError, "hard-linked"):
                applier.require_copy_path(str(link))

    def test_sha256_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "copy.db"
            path.write_bytes(b"identity-repair")
            self.assertEqual(
                applier.file_sha256(path),
                "4cb967b50ce0ffd9ad43cb1618467c2a589d0dae8bc9359a9f44f3fc27558da9",
            )


if __name__ == "__main__":
    unittest.main()
