import sqlite3
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import qb_decisions as qbd  # noqa: E402
import e1_drive as e1  # noqa: E402


class QbDecisionModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'model.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE players (nfl_gsis_id TEXT, league TEXT, position TEXT)')
        con.executemany('INSERT INTO players VALUES (?,?,?)', [
            ('QA', 'nfl', 'QB'), ('QB', 'nfl', 'QB'), ('QNEW', 'nfl', 'QB'),
            ('RWR', 'nfl', 'WR'), ('RRB', 'nfl', 'RB'), ('RTE', 'nfl', 'TE'),
        ])
        con.execute('''CREATE TABLE nfl_pbp (
            season INT, game_id TEXT, play_id INT, posteam TEXT, passer_player_id TEXT, rusher_player_id TEXT,
            qb_dropback INT, qb_scramble INT, pass_attempt INT, receiver_player_id TEXT,
            down INT, ydstogo INT, yardline_100 INT, week INT)''')
        rows = []
        for i in range(20):
            scramble = int(i < 10)
            rows.append((2024, 'g24', i + 1, 'AAA', 'QA', 'QA' if scramble else None, 1, scramble, 0 if scramble else 1,
                         None if scramble else 'RWR', 1, 10, 75, 3))
        for i in range(10):
            rows.append((2024, 'g24b', i + 1, 'AAA', 'QB', None, 1, 0, 1, 'RRB', 1, 10, 75, 3))
        rows.append((2024, 'g24c', 1, 'BBB', 'QA', None, 1, 0, 1, 'RTE', 1, 10, 75, 3))
        rows.append((2025, 'g25', 1, 'AAA', 'QA', None, 1, 0, 1, 'RTE', 1, 10, 75, 3))
        con.executemany('INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fit_is_chronological_and_keeps_qb_histories_team_specific(self):
        table = qbd.load(self.db, 2025)
        self.assertEqual(table['source_seasons'], [2022, 2023, 2024])
        self.assertNotIn(('g25', 1), table['row_target_roles'])
        cell = qbd.cell_of(1, 10, 75)
        result = qbd.draw(table, 'AAA', 'QA', 1, 10, 75, {'WR', 'RB'}, 'seed-a')
        self.assertEqual(result['target_role_history_n'], 10)
        self.assertEqual(result['scramble_history_n'], 20)
        moved = qbd.draw(table, 'BBB', 'QA', 1, 10, 75, {'TE', 'WR'}, 'seed-a')
        self.assertEqual(moved['target_role_history_n'], 1)
        self.assertEqual(table['target_qb_cell'][('AAA', 'QA', cell)]['WR'], 10)

    def test_target_role_draw_uses_qb_history_and_restricts_to_available_roles(self):
        table = qbd.load(self.db, 2025)
        table['scramble_cells'] = set()
        draws = [qbd.draw(table, 'AAA', 'QA', 1, 10, 75, {'WR', 'RB'}, f'seed-{i}')
                 for i in range(300)]
        roles = [result['target_role'] for result in draws if result['action'] == 'pass']
        self.assertGreater(roles.count('WR'), roles.count('RB'))
        only_rb = qbd.draw(table, 'AAA', 'QA', 1, 10, 75, {'RB'}, 'one-role')
        self.assertEqual(only_rb['target_role'], 'RB')
        with self.assertRaises(ValueError):
            qbd.draw(table, 'AAA', 'QA', 1, 10, 75, set(), 'empty-role-group')

    def test_new_qb_backs_off_and_unsupported_scrambles_are_disabled(self):
        table = qbd.load(self.db, 2025)
        table['scramble_cells'] = set()
        result = qbd.draw(table, 'AAA', 'QNEW', 1, 10, 75, {'WR', 'RB'}, 'seed')
        self.assertEqual(result['scramble_probability'], 0.0)
        self.assertEqual(result['scramble_fallback'], 'no_eligible_scramble_rows_in_cell')
        self.assertIn(result['target_role'], ('WR', 'RB'))

    def test_scramble_rows_stay_out_of_the_control_pool(self):
        row = {'game_id': 'g', 'play_id': 1, 'qtr': 1, 'down': 1, 'ydstogo': 10, 'yardline_100': 75,
               'game_seconds_remaining': 800, 'play_type': 'run', 'yards_gained': 6, 'penalty': 0,
               'two_point_attempt': 0, 'qb_scramble': 1, 'interception': 0, 'fumble_lost': 0, 'sack': 0,
               'complete_pass': 0}
        nxt = {'game_id': 'g', 'qtr': 1, 'game_seconds_remaining': 790, 'play_type': 'run', 'posteam': 'AAA'}
        self.assertIsNone(e1.classify(row, nxt, Counter()))
        self.assertEqual(e1.classify(row, nxt, Counter(), include_qb_scrambles=True), ('run', 10, None))


if __name__ == '__main__':
    unittest.main()
