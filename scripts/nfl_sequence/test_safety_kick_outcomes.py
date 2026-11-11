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
import build_safety_kick_outcomes as builder  # noqa: E402


class SafetyKickTable(unittest.TestCase):
    def manifest(self):
        return json.loads(er.SAFETY_KICKS.with_suffix('.csv.manifest.json').read_text())

    def test_the_pool_is_the_manifest_usable_rows_and_its_checksum_matches(self):
        pool, sha = er.load_safety_kick_pool()
        manifest = self.manifest()
        self.assertEqual(sha, manifest['output']['sha256'])
        with open(er.SAFETY_KICKS, newline='') as f:
            rows = list(csv.DictReader(f))
        legacy_onside = sum(r['status'] == 'usable' and 'onside' in r['kick_desc'].lower() for r in rows)
        self.assertEqual(legacy_onside, 6)
        self.assertEqual(len(pool) + legacy_onside, manifest['usable_count'])
        self.assertEqual(manifest['status_counts']['usable'], manifest['usable_count'])

    def test_every_usable_kick_has_a_legal_spot_and_clock_and_one_safety_each(self):
        pool, _ = er.load_safety_kick_pool()
        self.assertTrue(all(1 <= s['spot'] <= 99 and s['runoff'] >= 0 for s in pool))
        self.assertEqual(len({s['safety_play_id'] for s in pool}), len(pool))
        self.assertTrue(all(s['season'] in (2022, 2023, 2024, 2025) for s in pool))

    def test_the_onside_recovery_cannot_be_sampled_as_a_receiving_free_kick(self):
        pool, _ = er.load_safety_kick_pool()
        self.assertEqual(len(pool), 40)
        self.assertNotIn(48, [row['runoff'] for row in pool])
        self.assertNotIn(('2025_08_CLE_NE', 3742), {
            (row['game_id'], row['kick_play_id']) for row in pool
        })

    def test_the_builder_does_not_skip_an_intervening_kicking_team_drive(self):
        kick = {'qtr': 4}
        kicker_snap = {'qtr': 4, 'posteam': 'CLE', 'play_type': 'run',
                       'kickoff_attempt': 0, 'punt_attempt': 0}
        receiving_snap = {'qtr': 4, 'posteam': 'NE', 'play_type': 'pass',
                          'kickoff_attempt': 0, 'punt_attempt': 0}
        self.assertIsNone(builder._snap_after([kick, kicker_snap, receiving_snap], 0, kick, 'NE'))
        self.assertIs(builder._snap_after([kick, receiving_snap], 0, kick, 'NE'), receiving_snap)
        another_kick = {'qtr': 4, 'posteam': 'NE', 'play_type': 'kickoff',
                        'kickoff_attempt': 1, 'punt_attempt': 0}
        self.assertIsNone(builder._snap_after([kick, another_kick, receiving_snap], 0, kick, 'NE'))

    def test_the_builder_refuses_onside_kicks(self):
        safety = {'play_id': 1, 'game_id': '2025_08_CLE_NE', 'game_date': '2025-10-26',
                  'season': 2025, 'week': 8, 'qtr': 4, 'posteam': 'CLE', 'defteam': 'NE'}
        kick = {'play_id': 2, 'qtr': 4, 'posteam': 'NE', 'play_type': 'kickoff',
                'kickoff_attempt': 1, 'punt_attempt': 0, 'kick_distance': 13,
                'touchback': 0, 'return_yards': 0, 'game_seconds_remaining': 246,
                'desc': 'kicks onside, RECOVERED by CLE'}
        self.assertEqual(
            builder.build_record([safety, kick], 0, 'source.parquet', 'sha')['status'],
            'onside_kick_not_modelled',
        )

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
