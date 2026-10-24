"""Small source-shaped checks for the read-only E3 distribution exporter."""
import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.nfl_sequence import e3_observed_distributions as e3


PBP_COLUMNS = list(e3.PBP_FINGERPRINT_COLUMNS)
SCHEDULE_COLUMNS = list(e3.SCHEDULE_FINGERPRINT_COLUMNS)


def _play(game_id, play_id, season, **values):
    row = {column: None for column in PBP_COLUMNS}
    row.update({
        'game_id': game_id, 'play_id': play_id, 'season': season, 'week': 1, 'posteam': 'HOM', 'defteam': 'AWY',
        'home_team': 'HOM', 'away_team': 'AWY', 'qtr': 1, 'down': 1, 'ydstogo': 10, 'yardline_100': 75,
        'game_seconds_remaining': 3600 - play_id * 10, 'play_type': 'run', 'series': 1, 'series_result': 'First down',
        'drive': 1, 'yards_gained': 0, 'epa': 0.0, 'success': 0, 'pass_attempt': 0, 'rush_attempt': 0,
        'qb_dropback': 0, 'complete_pass': 0, 'sack': 0, 'interception': 0, 'fumble_lost': 0,
        'touchdown': 0, 'penalty': 0, 'pass_touchdown': 0, 'rush_touchdown': 0,
    })
    row.update(values)
    return row


def _make_db(path):
    con = sqlite3.connect(path)
    pbp_ddl = ', '.join(f'"{column}"' for column in PBP_COLUMNS)
    schedule_ddl = ', '.join(f'"{column}"' for column in SCHEDULE_COLUMNS)
    con.execute(f'CREATE TABLE nfl_pbp ({pbp_ddl})')
    con.execute(f'CREATE TABLE nfl_schedule ({schedule_ddl})')
    for season in range(e3.SEASON_MIN, e3.SEASON_MAX + 1):
        game_id = f'{season}_01_HOM_AWY'
        rows = [
            _play(game_id, 1, season, play_type='pass', down=1, ydstogo=10, yards_gained=12,
                  pass_attempt=1, qb_dropback=1, complete_pass=1, passer_player_id=f'QB{season}',
                  receiver_player_id=f'WR{season}', passing_yards=12, receiving_yards=12),
            _play(game_id, 2, season, play_type='punt', down=4, ydstogo=1, series=2,
                  series_result='Punt', drive=1, qb_dropback=0),
            _play(game_id, 3, season, play_type='run', down=1, ydstogo=5, series=3,
                  series_result='Touchdown', drive=2, rush_attempt=1, rusher_player_id=f'RB{season}',
                  yards_gained=3, rushing_yards=3, touchdown=1, rush_touchdown=1),
            _play(game_id, 4, season, play_type='extra_point', down=None, ydstogo=None, series=3,
                  series_result='Touchdown', drive=2, yardline_100=None),
            _play(game_id, 5, season, play_type='kickoff', down=None, ydstogo=None, series=None,
                  series_result=None, drive=None, yardline_100=None, game_seconds_remaining=3500),
        ]
        con.executemany(f'INSERT INTO nfl_pbp ({pbp_ddl}) VALUES ({", ".join("?" for _ in PBP_COLUMNS)})',
                        [[row[column] for column in PBP_COLUMNS] for row in rows])
        schedule = {column: None for column in SCHEDULE_COLUMNS}
        schedule.update({'game_id': game_id, 'season': season, 'game_type': 'REG', 'week': 1,
                         'gameday': f'{season}-09-10', 'away_team': 'AWY', 'home_team': 'HOM',
                         'away_score': 7, 'home_score': 10})
        con.execute(f'INSERT INTO nfl_schedule ({schedule_ddl}) VALUES ({", ".join("?" for _ in SCHEDULE_COLUMNS)})',
                    [schedule[column] for column in SCHEDULE_COLUMNS])
    con.commit()
    con.close()


def _csv(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


class ObservedDistributionExport(unittest.TestCase):
    def test_exports_four_levels_and_keeps_the_database_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'source.db'
            out = Path(temp) / 'tables'
            _make_db(db)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            manifest = e3.export(db, out)
            after = hashlib.sha256(db.read_bytes()).hexdigest()

            self.assertEqual(before, after)
            self.assertFalse(manifest['sources']['lp_game_payload_used'])
            self.assertEqual(manifest['source_measurements']['nfl_pbp_rows'], 20)
            self.assertEqual(manifest['source_measurements']['nfl_pbp_games'], 4)
            self.assertEqual(manifest['source_measurements']['nfl_pbp_nonnull_drive_groups'], 8)
            plays = _csv(out / 'play_distribution.csv')
            self.assertTrue(any(row['metric'] == 'play_type' and row['value'] == 'pass' and row['count'] == '4'
                                for row in plays))
            drives = _csv(out / 'drive_distribution.csv')
            self.assertTrue(any(row['metric'] == 'final_source_series_result' and row['value'] == 'Touchdown'
                                and row['count'] == '4' for row in drives))
            games = _csv(out / 'game_distribution.csv')
            self.assertTrue(any(row['metric'] == 'total_points' and row['value'] == '17' and row['count'] == '4'
                                for row in games))
            players = _csv(out / 'player_stat_distribution.csv')
            self.assertTrue(any(row['role'] == 'passing' and row['metric'] == 'passing_yards'
                                and row['value'] == '12' and row['count'] == '4' for row in players))
            for filename, expected_hash in manifest['table_sha256'].items():
                self.assertEqual(hashlib.sha256((out / filename).read_bytes()).hexdigest(), expected_hash)
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['schema'],
                             'lp.nfl.e3-observed-distributions.v1')

    def test_fails_closed_when_a_pbp_game_has_no_regular_schedule_row(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'source.db'
            _make_db(db)
            con = sqlite3.connect(db)
            bad = _play('unmatched_game', 1, 2022, drive=None, series=None, series_result=None)
            con.execute(f'INSERT INTO nfl_pbp ({", ".join(PBP_COLUMNS)}) VALUES ({", ".join("?" for _ in PBP_COLUMNS)})',
                        [bad[column] for column in PBP_COLUMNS])
            con.commit()
            con.close()
            with self.assertRaisesRegex(e3.SourceInvariantError, 'PBP-only=1'):
                e3.export(db, Path(temp) / 'tables')

    def test_refuses_to_overwrite_existing_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'source.db'
            out = Path(temp) / 'tables'
            _make_db(db)
            e3.export(db, out)
            with self.assertRaisesRegex(FileExistsError, 'refusing to overwrite'):
                e3.export(db, out)


if __name__ == '__main__':
    unittest.main()
