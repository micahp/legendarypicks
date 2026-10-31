"""Tests for cutoff-pinned share-model holdout inputs."""
import csv
import gzip
import hashlib
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validate_share_distributions as validator  # noqa: E402


class PinnedPbpInputs(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def write_pbp(self, rows):
        path = self.data_dir / 'pbp_2025.csv.gz'
        columns = ('game_id', 'play_id', 'season', 'season_type', 'week', 'posteam', 'play_type',
                   'rusher_player_id', 'receiver_player_id', 'pass_attempt', 'rush_attempt', 'sack',
                   'qb_kneel', 'qb_spike', 'two_point_attempt')
        with gzip.open(path, 'wt', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_role_counts_use_only_regular_season_cutoff_rows(self):
        self.write_pbp([
            {'game_id': '2025_01_AAA_BBB', 'play_id': '1', 'season': '2025', 'season_type': 'REG',
             'week': '1', 'posteam': 'AAA', 'play_type': 'pass', 'receiver_player_id': 'A'},
            {'game_id': '2025_01_AAA_BBB', 'play_id': '2', 'season': '2025', 'season_type': 'REG',
             'week': '1', 'posteam': 'AAA', 'play_type': 'run', 'rusher_player_id': 'B'},
            {'game_id': '2025_01_AAA_BBB', 'play_id': '3', 'season': '2025', 'season_type': 'POST',
             'week': '1', 'posteam': 'AAA', 'play_type': 'pass', 'receiver_player_id': 'C'},
            {'game_id': '2025_01_AAA_BBB', 'play_id': '4', 'season': '2025', 'season_type': 'REG',
             'week': '19', 'posteam': 'AAA', 'play_type': 'pass', 'receiver_player_id': 'D'},
        ])
        games, season_counts = validator.team_game_counts(self.data_dir, 2025, 'receive')
        self.assertEqual(games['AAA']['2025_01_AAA_BBB'], {'A': 1})
        self.assertEqual(season_counts['AAA'], {'A': 1})

    def test_participation_eligibility_uses_only_matched_scrimmage_offense_players(self):
        self.write_pbp([
            {'game_id': '2025_01_AAA_BBB', 'play_id': '1', 'season': '2025', 'season_type': 'REG',
             'week': '1', 'posteam': 'AAA', 'play_type': 'pass'},
            {'game_id': '2025_01_AAA_BBB', 'play_id': '2', 'season': '2025', 'season_type': 'REG',
             'week': '1', 'posteam': 'AAA', 'play_type': 'kickoff'},
        ])
        path = self.data_dir / 'pbp_participation_2025.csv'
        columns = ('nflverse_game_id', 'play_id', 'possession_team', 'offense_players')
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows([
                {'nflverse_game_id': '2025_01_AAA_BBB', 'play_id': '1', 'possession_team': 'AAA',
                 'offense_players': 'A;B'},
                {'nflverse_game_id': '2025_01_AAA_BBB', 'play_id': '2', 'possession_team': 'AAA',
                 'offense_players': 'SPECIAL'},
                {'nflverse_game_id': '2025_01_AAA_BBB', 'play_id': '3', 'possession_team': 'AAA',
                 'offense_players': ''},
            ])
        eligible, metadata = validator.load_offensive_game_eligibility(self.data_dir, 2025)
        self.assertEqual(eligible, {('AAA', '2025_01_AAA_BBB'): {'A', 'B'}})
        self.assertEqual(metadata['scrimmage_rows_joined'], 1)
        self.assertEqual(metadata['eligible_team_games'], 1)

    def test_position_map_uses_the_pinned_database_export(self):
        path = self.data_dir / 'positions.csv'
        path.write_text('gsis_id,position\nA,RB\nB,QB\n', encoding='utf-8')
        self.assertEqual(validator.player_positions(path), {'A': 'RB', 'B': 'QB'})

    def test_source_file_hash_must_match_the_reference_manifest(self):
        source = self.data_dir / 'pbp_2025.csv.gz'
        source.write_bytes(b'pinned bytes')
        manifest = self.data_dir / 'manifest.json'
        expected = hashlib.sha256(b'pinned bytes').hexdigest()
        manifest.write_text(json.dumps({'sources': {'local_source_files': {'pbp_2025.csv.gz': expected}}}))
        self.assertEqual(validator.verify_pinned_inputs(self.data_dir, manifest, ['pbp_2025.csv.gz']),
                         {'pbp_2025.csv.gz': expected})
        source.write_bytes(b'changed bytes')
        with self.assertRaisesRegex(ValueError, 'does not match pinned'):
            validator.verify_pinned_inputs(self.data_dir, manifest, ['pbp_2025.csv.gz'])


class MultiSeasonConcentration(unittest.TestCase):
    @staticmethod
    def synthetic_season(seed):
        rng = random.Random(seed)
        games = {'AAA': {}}
        season_counts = {'AAA': {'A': 0, 'B': 0}}
        for index in range(90):
            share = rng.betavariate(12.0, 8.0)
            a = sum(rng.random() < share for _ in range(50))
            counts = {'A': a, 'B': 50 - a}
            games['AAA'][f'G{seed}-{index}'] = counts
            for player, count in counts.items():
                season_counts['AAA'][player] += count
        return games, season_counts

    def test_common_phi_uses_independent_season_bases_and_recovers_shared_dispersion(self):
        datasets = [self.synthetic_season(17), self.synthetic_season(29), self.synthetic_season(41)]
        fitted = validator.fit_pooled_concentration(datasets)
        self.assertGreater(fitted['phi'], 12.0, fitted['phi'])
        self.assertLess(fitted['phi'], 32.0, fitted['phi'])
        self.assertLessEqual(fitted['phi_interval'][0], fitted['phi'])
        self.assertGreaterEqual(fitted['phi_interval'][1], fitted['phi'])
        self.assertEqual(fitted['team_games'], 270)

    def test_one_season_pooled_fit_matches_the_existing_concentration_estimator(self):
        games, counts = self.synthetic_season(73)
        pooled = validator.fit_pooled_concentration([(games, counts)])
        current = validator.sdm.fit_from_counts(games, counts, 2025)
        self.assertEqual(pooled['phi'], current['phi'])
        self.assertEqual(pooled['phi_interval'], current['phi_interval'])


if __name__ == '__main__':
    unittest.main()
