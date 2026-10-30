import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from scripts.nfl_sequence import e3_football_realism_joint_reference as joint
from scripts.nfl_sequence import e3_observed_distributions as e3


def _frame(*, score_differential=0, play_id=1):
    return pd.DataFrame([{
        'season': 2025, 'season_type': 'REG', 'week': 1, 'game_id': '2025_01_BUF_LA',
        'play_id': play_id, 'posteam': 'LA', 'play_type': 'run', 'down': 1, 'ydstogo': 10,
        'yardline_100': 5, 'qtr': 1, 'game_seconds_remaining': 3600, 'posteam_score': 0,
        'defteam_score': 0, 'score_differential': score_differential, 'pass_attempt': 0,
        'rush_attempt': 1, 'receiver_player_id': None, 'pass_touchdown': 0, 'rush_touchdown': 1,
        'field_goal_result': None, 'series_result': 'Touchdown', 'drive': 1,
    }])


def _sqlite_with_one_pbp_row(path):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE nfl_pbp(season INTEGER, week INTEGER, game_id TEXT, play_id INTEGER)')
    con.execute('INSERT INTO nfl_pbp VALUES(2025, 1, ?, 1)', ('2025_01_BUF_LA',))
    con.commit()
    con.close()


class JointReferenceSourceValidation(unittest.TestCase):
    def test_schedule_team_aliases_match_official_pbp_codes(self):
        self.assertEqual(joint._canonical_team_code('LA'), 'LAR')
        self.assertEqual(joint._canonical_team_code('WAS'), 'WSH')
        self.assertEqual(joint._canonical_team_code('CLE'), 'CLE')

    def test_official_score_differential_must_match_presnap_team_scores(self):
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE nfl_pbp(season INTEGER, week INTEGER, game_id TEXT, play_id INTEGER)')
        con.execute('INSERT INTO nfl_pbp VALUES(2025, 1, ?, 1)', ('2025_01_BUF_LA',))
        with mock.patch.object(joint.e3, 'validate_source', return_value={'nfl_pbp_sha256': 'a', 'nfl_schedule_sha256': 'b'}):
            with self.assertRaisesRegex(joint.JointReferenceError, 'score differentials disagree'):
                joint._validate_and_measure(con, _frame(score_differential=3))
        con.close()

    def test_official_and_retained_e3_play_keys_must_match_exactly(self):
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE nfl_pbp(season INTEGER, week INTEGER, game_id TEXT, play_id INTEGER)')
        con.execute('INSERT INTO nfl_pbp VALUES(2025, 1, ?, 1)', ('2025_01_BUF_LA',))
        with mock.patch.object(joint.e3, 'validate_source', return_value={'nfl_pbp_sha256': 'a', 'nfl_schedule_sha256': 'b'}):
            with self.assertRaisesRegex(joint.JointReferenceError, 'not key-identical'):
                joint._validate_and_measure(con, _frame(play_id=2))
        con.close()

    def test_export_is_read_only_hash_pinned_and_resolves_la_to_lar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / 'source.sqlite'
            con = sqlite3.connect(db)
            con.executescript('''
                CREATE TABLE nfl_pbp(season INTEGER, week INTEGER, game_id TEXT, play_id INTEGER);
                INSERT INTO nfl_pbp VALUES(2025, 1, '2025_01_BUF_LA', 1);
                CREATE TABLE nfl_schedule(
                    season INTEGER, week INTEGER, game_type TEXT, game_id TEXT,
                    home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER
                );
                INSERT INTO nfl_schedule VALUES(2025, 1, 'REG', '2025_01_BUF_LA', 'LAR', 'BUF', 7, 0);
            ''')
            con.commit()
            con.close()
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            source_hashes = {f'play_by_play_{season}.parquet': str(season) * 64
                             for season in joint.SEASONS}
            source = {'nfl_pbp_sha256': 'b' * 64, 'nfl_schedule_sha256': 'c' * 64}
            out = root / 'joint-output'
            with mock.patch.object(joint, '_source_frames', return_value=(_frame(), source_hashes)), \
                    mock.patch.object(joint.e3, 'validate_source', return_value=source):
                manifest = joint.export(db, root, out)

            self.assertEqual(manifest['source_measurements']['official_regular_season_rows'], 1)
            self.assertEqual(manifest['source_measurements']['score_differential_mismatches'], 0)
            self.assertIn('joint_distribution.csv', manifest['table_sha256'])
            with (out / 'joint_distribution.csv').open(encoding='utf-8', newline='') as handle:
                joint_rows = list(csv.DictReader(handle))
            red_zone = [row for row in joint_rows if row['pair_id'] == 'red_zone_trips_vs_touchdowns']
            self.assertEqual(len(red_zone), 1)
            self.assertEqual((red_zone[0]['x_value'], red_zone[0]['y_value']), ('1', '1'))
            after = hashlib.sha256(db.read_bytes()).hexdigest()
            self.assertEqual(after, before, 'the E3 SQLite source must remain unchanged')
            parsed = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(parsed['official_pbp_source']['sha256'], source_hashes)
            read_only = e3.open_readonly(db)
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly|read-only'):
                    read_only.execute("UPDATE nfl_pbp SET week=2")
            finally:
                read_only.close()


if __name__ == '__main__':
    unittest.main()
