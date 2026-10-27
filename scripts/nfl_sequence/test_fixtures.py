"""The committed E2 fixtures are immutable: their SHA-256 values match docs/fixtures/e2/MANIFEST.json, and the seed-1 shared
document is checked against the contract. Run: python3 -m unittest scripts/nfl_sequence/test_fixtures.py
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shared_v1 as sv  # noqa: E402

FIXTURES = HERE.parents[1] / 'docs' / 'fixtures' / 'e2'
UNSOURCED = {'V-mode', 'V-unresolved-game_id', 'V-unresolved-scheduled_kickoff_utc', 'V-unresolved-as_of_utc',
             'V-unresolved-snapshot_hash', 'V-unresolved-roster_snapshot_id', 'V-duration-seconds'}


class Immutable(unittest.TestCase):
    def test_every_manifest_hash_matches_its_file(self):
        manifest = json.loads((FIXTURES / 'MANIFEST.json').read_text())
        for name, entry in manifest['fixtures'].items():
            digest = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
            self.assertEqual(digest, entry['sha256'], name)

    def test_the_contract_hash_is_pinned(self):
        manifest = json.loads((FIXTURES / 'MANIFEST.json').read_text())
        self.assertEqual(manifest['contract']['sha256'], sv.CONTRACT_SHA256)

    def test_the_seed1_document_has_only_the_unsourced_violations(self):
        doc = json.loads((FIXTURES / 'e2-game-seed1.v1.json').read_text())
        self.assertEqual({v['id'] for v in sv.check_document(doc)}, UNSOURCED)
        self.assertFalse(doc['summary']['valid_full_game'])


if __name__ == '__main__':
    unittest.main()
