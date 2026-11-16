"""The observed safety free-kick table: its checksum, its usable rows, and the refusals kept out of the pool.

Run: python3 -m pytest scripts/nfl_sequence/test_safety_kick_outcomes.py
"""
import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402


class SafetyKickTable(unittest.TestCase):
    def manifest(self):
        return json.loads(er.SAFETY_KICKS.with_suffix('.csv.manifest.json').read_text())

    def test_the_pool_is_the_manifest_usable_rows_and_its_checksum_matches(self):
        pool, sha = er.load_safety_kick_pool()
        manifest = self.manifest()
        self.assertEqual(sha, manifest['output']['sha256'])
        self.assertEqual(len(pool), manifest['usable_count'])
        self.assertEqual(manifest['status_counts']['usable'], manifest['usable_count'])

    def test_every_usable_kick_has_a_legal_spot_and_clock_and_one_safety_each(self):
        pool, _ = er.load_safety_kick_pool()
        self.assertTrue(all(1 <= s['spot'] <= 99 and s['runoff'] >= 0 for s in pool))
        self.assertEqual(len({s['safety_play_id'] for s in pool}), len(pool))
        self.assertTrue(all(s['season'] in (2022, 2023, 2024, 2025) for s in pool))

    def test_refused_rows_stay_in_the_file_and_out_of_the_pool(self):
        with open(er.SAFETY_KICKS, newline='') as f:
            rows = list(csv.DictReader(f))
        refused = [r for r in rows if r['status'] != 'usable']
        self.assertEqual(len(refused), sum(n for status, n in self.manifest()['status_counts'].items()
                                           if status != 'usable'))
        self.assertEqual(len(rows), self.manifest()['record_count'])

    def test_a_changed_fixture_is_refused_before_any_row_is_read(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        copy = tmp / er.SAFETY_KICKS.name
        shutil.copy(er.SAFETY_KICKS, copy)
        shutil.copy(er.SAFETY_KICKS.with_suffix('.csv.manifest.json'), tmp / (er.SAFETY_KICKS.name + '.manifest.json'))
        copy.write_bytes(copy.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            er.load_safety_kick_pool(copy)


if __name__ == '__main__':
    unittest.main()
