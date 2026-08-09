#!/usr/bin/env python3
"""Tests for name_aliases: gate alias matching + the consolidation artifact."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import name_aliases


class NameAliasesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="alias-test-")
        self._orig_aliases = name_aliases.ALIASES_PATH
        self._orig_consol = name_aliases.CONSOLIDATIONS_PATH
        name_aliases.ALIASES_PATH = Path(self.tempdir.name) / "name-aliases.json"
        name_aliases.CONSOLIDATIONS_PATH = Path(self.tempdir.name) / "consolidations.jsonl"
        name_aliases._ALIASES_CACHE = None

    def tearDown(self):
        name_aliases.ALIASES_PATH = self._orig_aliases
        name_aliases.CONSOLIDATIONS_PATH = self._orig_consol
        name_aliases._ALIASES_CACHE = None
        self.tempdir.cleanup()

    def _write_aliases(self, data: dict):
        name_aliases.ALIASES_PATH.write_text(json.dumps(data))

    def test_alias_matches_accepted_spelling(self):
        self._write_aliases({"nfl": {"00-0036919": ["Kenneth Gainwell", "Kenny Gainwell"]}})
        # Row holds the nickname, publisher holds the legal form: accepted.
        self.assertTrue(name_aliases.matches_published(
            "nfl", "00-0036919", "Kenneth Gainwell", "Kenny Gainwell"))
        # Row holds the published form directly: accepted without the alias.
        self.assertTrue(name_aliases.matches_published(
            "nfl", "00-0036919", "Kenny Gainwell", "Kenny Gainwell"))

    def test_alias_does_not_admit_different_person(self):
        self._write_aliases({"nfl": {"00-0036919": ["Kenny Gainwell"]}})
        self.assertFalse(name_aliases.matches_published(
            "nfl", "00-0036919", "Kyle Harrison", "Kenny Gainwell"))
        self.assertFalse(name_aliases.matches_published(
            "nfl", "00-0036919", "Jalen Hurts", "Kenny Gainwell"))

    def test_id_without_alias_has_no_alternates(self):
        self._write_aliases({"nfl": {"00-0036919": ["Kenny Gainwell"]}})
        self.assertEqual(name_aliases.aliases_for("nfl", "00-9999999"), set())
        self.assertFalse(name_aliases.matches_published(
            "nfl", "00-9999999", "Some Name", "Published Name"))

    def test_missing_file_is_empty(self):
        self.assertEqual(name_aliases.load_aliases(), {})

    def test_record_consolidation_appends(self):
        name_aliases.record_consolidation({"ts": "a", "script": "x", "note": "one"})
        name_aliases.record_consolidation({"ts": "b", "script": "y", "note": "two"})
        lines = name_aliases.CONSOLIDATIONS_PATH.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["note"], "one")
        self.assertEqual(json.loads(lines[1])["note"], "two")

    def test_record_consolidation_never_truncates(self):
        name_aliases.record_consolidation({"ts": "a"})
        first = name_aliases.CONSOLIDATIONS_PATH.read_text()
        name_aliases.record_consolidation({"ts": "b"})
        second = name_aliases.CONSOLIDATIONS_PATH.read_text()
        self.assertTrue(second.startswith(first))
        self.assertEqual(len(second.strip().splitlines()), 2)

    def test_real_alias_file_covers_the_known_rows(self):
        # The checked-in alias file must accept every currently-flagged name.
        path = Path(__file__).resolve().parent / "data" / "name-aliases.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertIn("nba", data)
        self.assertIn("nfl", data)
        self.assertIn("nhl", data)
        # NBA: row 'Nate Williams' vs publisher 'Jeenathan Williams'
        self.assertIn("4397821", data["nba"])
        # NFL: row 'Kenneth Gainwell' vs publisher 'Kenny Gainwell'
        self.assertIn("00-0036919", data["nfl"])
        # NHL: row 'Josh Dunne' vs publisher 'Joshua Dunne'
        self.assertIn("8482623", data["nhl"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
