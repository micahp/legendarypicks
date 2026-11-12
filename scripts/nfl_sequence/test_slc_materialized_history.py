"""Materialized E1 classification must reproduce the legacy simulator's history exactly."""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import e1_drive as e1
import slc_materialized_history as history


NUMBERS = {
    'play_id', 'season', 'week', 'qtr', 'down', 'ydstogo', 'yardline_100',
    'game_seconds_remaining', 'yards_gained', 'touchdown', 'interception',
    'fumble_lost', 'sack', 'complete_pass', 'qb_scramble', 'penalty', 'two_point_attempt',
}


def play(game_id, play_id, season, team, clock, **kwargs):
    row = {name: None for name in e1.COLUMNS}
    row.update(game_id=game_id, play_id=play_id, season=season, week=1, game_date=f'{season}-09-01',
               posteam=team, defteam='DAL' if team == 'ARI' else 'ARI', qtr=1, down=1,
               ydstogo=10, yardline_100=65, game_seconds_remaining=clock,
               play_type='run', yards_gained=3, touchdown=0, interception=0,
               fumble_lost=0, sack=0, complete_pass=0, qb_scramble=0,
               penalty=0, two_point_attempt=0)
    row.update(kwargs)
    return row


class MaterializedClassificationParity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / 'source.sqlite'
        self.artifact = Path(tmp.name) / 'preclassified.sqlite'
        games = [
            play('2024_01_ARI_DAL', 1, 2024, 'ARI', 900),
            play('2024_01_ARI_DAL', 2, 2024, 'ARI', 870, play_type='pass', sack=1,
                 fumble_lost=1, yards_gained=-8),
            play('2024_01_ARI_DAL', 3, 2024, 'DAL', 834),
            play('2024_01_ARI_DAL', 4, 2024, 'DAL', 810, play_type='punt', down=4),
            play('2024_01_ARI_DAL', 5, 2024, 'ARI', 785),
            play('2025_01_ARI_DAL', 1, 2025, 'ARI', 900, qb_scramble=1, yards_gained=8),
            play('2025_01_ARI_DAL', 2, 2025, 'ARI', 864, play_type='pass',
                 complete_pass=1, yards_gained=15),
            play('2025_01_ARI_DAL', 3, 2025, 'ARI', 821, play_type='pass',
                 complete_pass=0, penalty=1, yards_gained=0),
            play('2025_01_ARI_DAL', 4, 2025, 'ARI', 798, play_type='field_goal', down=4),
            play('2025_01_ARI_DAL', 5, 2025, 'DAL', 762),
        ]
        with sqlite3.connect(self.db) as con:
            columns = ','.join(f'{name} {"INTEGER" if name in NUMBERS else "TEXT"}'
                               for name in e1.COLUMNS)
            con.execute(f'CREATE TABLE nfl_pbp ({columns})')
            con.executemany(
                f'INSERT INTO nfl_pbp VALUES ({",".join("?" for _ in e1.COLUMNS)})',
                [tuple(row[name] for name in e1.COLUMNS) for row in games])
        history.build(self.db, self.artifact)

    def test_every_supported_runtime_variant_matches_old_classifier(self):
        for scrambles in (False, True):
            for separate_sack_fumbles in (False, True):
                for regulation_only in (False, True):
                    for known_clean in (False, True):
                        opts = dict(regulation_only=regulation_only,
                                    include_qb_scrambles=scrambles,
                                    separate_sack_fumbles=separate_sack_fumbles,
                                    known_clean_penalties=known_clean, team_before_season=2025)
                        legacy_rows = e1.load(self.db, eligible_before=(2025, 8))
                        old = e1.build_pools(copy.deepcopy(legacy_rows), **opts)
                        new_rows, *new = history.load_pools(
                            self.db, self.artifact, eligible_before=(2025, 8), **opts)
                        self.assertEqual(new_rows, legacy_rows)
                        self.assertEqual(tuple(new), old)

    def test_runtime_never_calls_historical_classifier(self):
        with mock.patch.object(e1, 'classify', side_effect=AssertionError('runtime classified history')):
            rows, pool, excluded, team = history.load_pools(
                self.db, self.artifact, eligible_before=(2025, 8),
                include_qb_scrambles=True, separate_sack_fumbles=True)
        self.assertTrue(rows)
        self.assertTrue(pool)
        self.assertIsNone(team)

    def test_source_database_mutation_invalidates_materialized_data(self):
        with sqlite3.connect(self.db) as con:
            con.execute('UPDATE nfl_pbp SET yards_gained = 100 WHERE play_id = 1 AND season = 2024')
        with self.assertRaisesRegex(ValueError, 'source DB changed'):
            history.load_pools(self.db, self.artifact, eligible_before=(2025, 8))

    def test_explicit_game_refresh_recovers_from_source_change(self):
        with sqlite3.connect(self.db) as con:
            con.execute('UPDATE nfl_pbp SET yards_gained = 6 WHERE play_id = 1 AND season = 2025')
        with self.assertRaisesRegex(ValueError, 'only-this-game-changed'):
            history.refresh_game(self.db, self.artifact, '2025_01_ARI_DAL')
        history.refresh_game(self.db, self.artifact, '2025_01_ARI_DAL', only_this_game_changed=True)
        rows, _pool, _excluded, _team = history.load_pools(
            self.db, self.artifact, eligible_before=(2025, 8))
        self.assertEqual(rows[-5]['yards_gained'], 6)

    def test_classifier_code_change_fails_closed(self):
        with mock.patch.object(history, '_classifier_identity', return_value={'changed': 'yes'}):
            with self.assertRaisesRegex(ValueError, 'classifier source changed'):
                history.load_pools(self.db, self.artifact, eligible_before=(2025, 8))


if __name__ == '__main__':
    unittest.main()
