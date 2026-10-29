"""A pregame snapshot from a raw capture fails closed on every break in the chain: hash, acquisition time, kickoff, feed time, QB1."""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pregame_capture as pc  # noqa: E402

GAME = '2026_08_CAR_GB'
CUTOFF = '2026-10-29T00:02:21Z'


def write_capture(root, depth_rows=None, games_acquired='2026-10-29T00:00:26Z', depth_dt='2026-10-28T13:58:02Z',
                  gameday='2026-10-29', gametime='20:15'):
    cap = Path(root) / 'capture'
    cap.mkdir()
    games = pd.DataFrame([{'game_id': GAME, 'season': 2026, 'game_type': 'REG', 'week': 8, 'gameday': gameday,
                           'gametime': gametime, 'away_team': 'CAR', 'home_team': 'GB'}])
    depth = depth_rows if depth_rows is not None else [
        {'dt': depth_dt, 'team': team, 'player_name': f'{team} {pos}', 'gsis_id': f'{team}{pos}', 'pos_abb': pos,
         'pos_rank': rank} for team in ('CAR', 'GB') for pos, rank in (('QB', 1), ('RB', 1), ('WR', 1))]
    injuries = pd.DataFrame([{'team': 'CAR', 'week': 8, 'gsis_id': 'x', 'report_status': None, 'practice_status': 'DNP'}])
    names = {'games.parquet': games, 'depth_charts_2026.parquet': pd.DataFrame(depth),
             'injuries_2026.parquet': injuries}
    files = []
    for name, frame in names.items():
        frame.to_parquet(cap / name)
        files.append({'name': name, 'url': f'https://example.test/{name}', 'acquired_at_utc': (
            games_acquired if name == 'games.parquet' else '2026-10-28T23:59:53Z'), 'last_modified_utc': None,
            'sha256': hashlib.sha256((cap / name).read_bytes()).hexdigest()})
    (cap / 'manifest.json').write_text(json.dumps({'schema': 'test', 'frozen_at_utc': '2026-10-29T00:02:21Z',
                                                   'files': files}))
    return str(cap)


def write_db(root):
    db = str(Path(root) / 'players.sqlite3')
    Path(db).unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE players (id INTEGER, league TEXT, nfl_gsis_id TEXT, espn_id TEXT)')
    for i, key in enumerate(('CARQB', 'CARRB', 'CARWR', 'GBQB', 'GBRB', 'GBWR'), start=1):
        con.execute("INSERT INTO players VALUES (?, 'nfl', ?, NULL)", (i, key))
    con.commit()
    con.close()
    return db


class Chain(unittest.TestCase):
    def test_a_verified_capture_builds_a_verified_prospective_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = pc.build(write_db(tmp), write_capture(tmp), GAME, CUTOFF)
        self.assertEqual(snap['evaluation'], {'class': 'prospective_forecast', 'verified': True, 'unverified_inputs': []})
        self.assertEqual(snap['schedule']['scheduled_kickoff_utc'], '2026-10-30T00:15:00Z')

    def test_a_changed_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cap = write_capture(tmp)
            Path(cap, 'depth_charts_2026.parquet').write_bytes(Path(cap, 'depth_charts_2026.parquet').read_bytes() + b'x')
            with self.assertRaises(ValueError):
                pc.build(write_db(tmp), cap, GAME, CUTOFF)

    def test_a_schedule_acquired_after_the_cutoff_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                pc.build(write_db(tmp), write_capture(tmp, games_acquired='2026-10-29T00:30:00Z'), GAME, CUTOFF)
            self.assertIn('acquired after', str(caught.exception))  # caught by the frozen-manifest check first

    def test_a_cutoff_at_or_after_kickoff_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                pc.build(write_db(tmp), write_capture(tmp), GAME, '2026-10-30T00:15:00Z')
            self.assertIn('not before the kickoff', str(caught.exception))

    def test_a_depth_row_published_after_the_cutoff_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            # the only QB1 rows are published after the cutoff, so none may be used
            rows = [{'dt': '2026-10-29T06:00:00Z', 'team': team, 'player_name': 'x', 'gsis_id': f'{team}QB', 'pos_abb': 'QB',
                     'pos_rank': 1} for team in ('CAR', 'GB')]
            with self.assertRaises(ValueError) as caught:
                pc.build(write_db(tmp), write_capture(tmp, depth_rows=rows), GAME, CUTOFF)
            self.assertIn('no depth rows', str(caught.exception))

    def test_a_team_without_exactly_one_qb1_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{'dt': '2026-10-28T13:58:02Z', 'team': 'CAR', 'player_name': 'x', 'gsis_id': 'CARRB', 'pos_abb': 'RB',
                     'pos_rank': 1}, {'dt': '2026-10-28T13:58:02Z', 'team': 'GB', 'player_name': 'y', 'gsis_id': 'GBQB',
                                      'pos_abb': 'QB', 'pos_rank': 1}]
            with self.assertRaises(ValueError) as caught:
                pc.build(write_db(tmp), write_capture(tmp, depth_rows=rows), GAME, CUTOFF)
            self.assertIn('exactly one QB1', str(caught.exception))

    def test_a_capture_cannot_build_a_backtest_or_an_exploratory_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            for evaluation in ('backtest', 'exploratory_replay'):
                with self.subTest(evaluation=evaluation), tempfile.TemporaryDirectory() as each:
                    with self.assertRaises(ValueError):
                        pc.build(write_db(each), write_capture(each), GAME, CUTOFF, evaluation=evaluation)


class DatabaseBuilderNeverMakesAForecast(unittest.TestCase):
    def test_the_database_builder_refuses_the_prospective_class(self):
        import pregame_snapshot as ps
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ps.build(str(Path(tmp) / 'none.sqlite3'), GAME, CUTOFF, evaluation='prospective_forecast')


if __name__ == '__main__':
    unittest.main()
