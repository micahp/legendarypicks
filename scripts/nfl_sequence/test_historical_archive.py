import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import historical_archive as archive  # noqa: E402
import pregame_snapshot as snapshots  # noqa: E402


class HistoricalArchiveValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.asset_root = self.root / 'assets'
        self.tag = 'archive-2026-10-08'
        (self.asset_root / self.tag).mkdir(parents=True)
        self.cutoff = '2026-10-09T10:41:38Z'
        self.kickoff = '2026-10-10T00:15:00Z'
        self.files = {
            'schedule': ('s', 'games.rds', 'schedule_sha256', 'schedule_observed_utc', b'schedule'),
            'depth': ('d', 'depth_charts_2026.rds', 'depth_sha256', 'depth_published_utc', b'depth'),
            'roster': ('r', 'roster_weekly_2026.rds', 'roster_sha256', 'roster_published_utc', b'roster'),
            'injury': ('i', 'injuries_2026.rds', 'injury_sha256', 'injury_published_utc', b'injury'),
        }
        hashes = {}
        for name, (_code, filename, _sha_field, _time_field, content) in self.files.items():
            (self.asset_root / self.tag / filename).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        self.readiness = self.root / 'readiness.csv'
        row = {
            'game_id': '2026_05_CHI_GB', 'week': '5', 'readiness_class': 'cutoff-valid',
            'cutoff_basis': 'recorded LP lock', 'cutoff_utc': self.cutoff, 'kickoff_utc': self.kickoff,
            'archive_tag': self.tag, 'simulation_ready_with_committed_loader': 'False',
            'schedule_sha256': hashes['schedule'], 'depth_sha256': hashes['depth'],
            'roster_sha256': hashes['roster'], 'injury_sha256': hashes['injury'],
            'schedule_observed_utc': '2026-10-08T20:42:13Z',
            'depth_published_utc': '2026-10-08T20:45:33Z',
            'roster_published_utc': '2026-10-08T20:43:27Z',
            'injury_published_utc': '2026-10-08T21:09:05Z',
        }
        with self.readiness.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        release = {}
        for name, (code, filename, _sha_field, time_field, _content) in self.files.items():
            release[code] = [row[time_field], hashes[name]]
        self.manifest = self.root / 'archive_manifest.json'
        self.manifest.write_text(json.dumps({'archives': {'2026-10-08': release}}, sort_keys=True))
        self.streak_file = self.root / 'streak.json'
        teams = {'CHI': {'streak': 'W1'}, 'GB': {'streak': 'L1'}}
        streak = {'game_id': row['game_id'], 'cutoff_utc': self.cutoff, 'teams': teams}
        self.streak_file.write_text(json.dumps(streak, sort_keys=True))
        source_assets = {}
        for name, (code, filename, sha_field, time_field, _content) in self.files.items():
            source_assets[name] = {'archive_tag': self.tag, 'file_name': filename,
                                   'published_at_utc': row[time_field], 'sha256': row[sha_field],
                                   'source': 'official_nflverse_dated_archive',
                                   'path': f'{self.tag}/{filename}'}
        manifest_sha = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        readiness_sha = hashlib.sha256(self.readiness.read_bytes()).hexdigest()
        streak_sha = hashlib.sha256(self.streak_file.read_bytes()).hexdigest()
        builder_sha = hashlib.sha256((HERE / 'build_historical_archive_snapshots.py').read_bytes()).hexdigest()
        snapshot = {
            'schema': snapshots.SCHEMA, 'as_of': self.cutoff,
            'evaluation': {'class': archive.MODE, 'verified': False},
            'roster_snapshot_id': 'test-roster',
            'schedule': {'game_id': row['game_id'], 'season': 2026, 'week': 5, 'game_type': 'REG',
                         'home_team': 'GB', 'away_team': 'CHI', 'scheduled_kickoff_utc': self.kickoff,
                         'availability_classification': archive.MODE},
            'rosters': {'home': {'team': 'GB', 'players': []}, 'away': {'team': 'CHI', 'players': []}},
            'model_reference': {},
            'archive_reconstruction': {
                'schema': archive.SCHEMA, 'mode': archive.MODE, 'prospective_eligible': False,
                'archive_tag': self.tag, 'archive_manifest_sha256': manifest_sha,
                'readiness_matrix_sha256': readiness_sha, 'builder_sha256': builder_sha,
                'source_assets': source_assets,
                'streak_context': {'game_id': row['game_id'], 'cutoff_utc': self.cutoff,
                                   'teams': teams, 'file_sha256': streak_sha, 'file': 'streak.json'},
            },
        }
        self.snapshot = snapshots.reseal(snapshot)

    def tearDown(self):
        self.tmp.cleanup()

    def _validate(self):
        return archive.validate_snapshot(self.snapshot, readiness_matrix=self.readiness,
                                         archive_manifest=self.manifest, archive_root=self.asset_root,
                                         streak_file=self.streak_file, expected_game_id='2026_05_CHI_GB')

    def test_exact_pre_cutoff_archive_versions_validate_as_retrospective_only(self):
        result = self._validate()
        self.assertFalse(result['prospective'])
        self.assertEqual(result['classification'], archive.MODE)
        self.assertEqual(set(result['source_assets']), set(archive.ASSETS))
        self.assertEqual(result['local_capture_observed_utc'], None)

    def test_prospective_claim_on_archive_snapshot_is_refused(self):
        self.snapshot['archive_reconstruction']['prospective_eligible'] = True
        snapshots.reseal(self.snapshot)
        with self.assertRaisesRegex(ValueError, 'cannot be marked eligible'):
            self._validate()

    def test_unlabelled_archive_snapshot_is_refused(self):
        self.snapshot['evaluation']['class'] = 'prospective'
        snapshots.reseal(self.snapshot)
        with self.assertRaisesRegex(ValueError, 'labelled retrospective'):
            self._validate()

    def test_changed_archive_contents_are_refused(self):
        path = self.asset_root / self.tag / self.files['depth'][1]
        path.write_bytes(b'replaced with a later or modified source')
        with self.assertRaisesRegex(ValueError, 'no local file matches'):
            self._validate()

    def test_publication_time_must_match_matrix_and_precede_cutoff(self):
        with self.readiness.open('r', newline='') as handle:
            rows = list(csv.DictReader(handle))
        rows[0]['depth_published_utc'] = '2026-10-10T12:00:00Z'
        with self.readiness.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        manifest = json.loads(self.manifest.read_text())
        manifest['archives']['2026-10-08']['d'][0] = '2026-10-10T12:00:00Z'
        self.manifest.write_text(json.dumps(manifest, sort_keys=True))
        self.snapshot['archive_reconstruction']['archive_manifest_sha256'] = hashlib.sha256(
            self.manifest.read_bytes()).hexdigest()
        self.snapshot['archive_reconstruction']['readiness_matrix_sha256'] = hashlib.sha256(
            self.readiness.read_bytes()).hexdigest()
        self.snapshot['archive_reconstruction']['source_assets']['depth']['published_at_utc'] = '2026-10-10T12:00:00Z'
        snapshots.reseal(self.snapshot)
        with self.assertRaisesRegex(ValueError, 'depth archive version was published after'):
            self._validate()

    def test_only_the_locked_week_5_to_7_source_valid_population_is_admitted(self):
        with self.readiness.open('r', newline='') as handle:
            rows = list(csv.DictReader(handle))
        rows[0]['readiness_class'] = 'exploratory'
        with self.readiness.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.snapshot['archive_reconstruction']['readiness_matrix_sha256'] = hashlib.sha256(
            self.readiness.read_bytes()).hexdigest()
        snapshots.reseal(self.snapshot)
        with self.assertRaisesRegex(ValueError, 'only cutoff-valid'):
            self._validate()

    def _rewrite_row(self, **fields):
        with self.readiness.open('r', newline='') as handle:
            rows = list(csv.DictReader(handle))
        rows[0].update(fields)
        with self.readiness.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.snapshot['archive_reconstruction']['readiness_matrix_sha256'] = hashlib.sha256(
            self.readiness.read_bytes()).hexdigest()

    def _supplement(self, published_after_cutoff=True, published='2026-10-15T21:00:00Z'):
        tag = 'archive-2026-10-15'
        (self.asset_root / tag).mkdir(exist_ok=True)
        (self.asset_root / tag / 'injuries_2026.rds').write_bytes(b'later injury release')
        return {'archive_tag': tag, 'file_name': 'injuries_2026.rds', 'published_at_utc': published,
                'sha256': hashlib.sha256(b'later injury release').hexdigest(), 'rows': 7,
                'published_after_cutoff': published_after_cutoff, 'source': 'official_nflverse_dated_archive'}

    def test_a_refused_game_validates_only_in_the_labelled_secondary_tier(self):
        self._rewrite_row(readiness_class='refused')
        snapshots.reseal(self.snapshot)
        with self.assertRaisesRegex(ValueError, 'only cutoff-valid'):
            self._validate()
        self.snapshot['archive_reconstruction']['tier'] = 'secondary'
        self.snapshot['archive_reconstruction']['injury_supplements'] = {'home': self._supplement()}
        snapshots.reseal(self.snapshot)
        result = self._validate()
        self.assertEqual((result['tier'], result['readiness_class']), ('secondary', 'refused'))
        self.assertTrue(result['injury_supplements']['home']['published_after_cutoff'])

    def test_a_supplement_that_hides_its_late_publication_is_refused(self):
        self._rewrite_row(readiness_class='refused')
        self.snapshot['archive_reconstruction']['tier'] = 'secondary'
        self.snapshot['archive_reconstruction']['injury_supplements'] = {'home': self._supplement(False)}
        snapshots.reseal(self.snapshot)
        with self.assertRaisesRegex(ValueError, 'mislabels its publication'):
            self._validate()

    def test_the_primary_tier_never_takes_an_injury_report_from_another_release(self):
        self.snapshot['archive_reconstruction']['injury_supplements'] = {'home': self._supplement()}
        snapshots.reseal(self.snapshot)
        with self.assertRaisesRegex(ValueError, 'only the secondary tier'):
            self._validate()

    def test_without_a_recorded_lock_the_cutoff_is_the_audit_boundary(self):
        row = {'cutoff_basis': 'kickoff-1s proxy; no recorded LP lock', 'cutoff_utc': '',
               'audit_boundary_utc': '2026-10-10T00:14:59Z', 'game_id': 'g'}
        self.assertEqual(archive.row_cutoff(row), '2026-10-10T00:14:59Z')
        with self.assertRaisesRegex(ValueError, 'neither a recorded lock'):
            archive.row_cutoff({**row, 'audit_boundary_utc': ''})


if __name__ == '__main__':
    unittest.main()
