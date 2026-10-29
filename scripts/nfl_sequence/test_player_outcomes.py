import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import player_outcomes as po  # noqa: E402


class PlayerOutcomeModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'model.db')
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE players (nfl_gsis_id TEXT, league TEXT, position TEXT)')
        con.executemany('INSERT INTO players VALUES (?,?,?)', [
            ('QGOOD', 'nfl', 'QB'), ('QBAD', 'nfl', 'QB'), ('QOTHER', 'nfl', 'QB'), ('QFUTURE', 'nfl', 'QB'),
            ('RGOOD', 'nfl', 'WR'), ('RBAD', 'nfl', 'WR'), ('ROTHER', 'nfl', 'WR'),
            ('RBIG', 'nfl', 'RB'), ('RBSMALL', 'nfl', 'RB'),
        ])
        con.execute('''CREATE TABLE nfl_pbp (
            season INT, posteam TEXT, passer_player_id TEXT, rusher_player_id TEXT,
            receiver_player_id TEXT, qb_dropback INT, qb_scramble INT, pass_attempt INT,
            rush_attempt INT, complete_pass INT, sack INT, interception INT, fumble_lost INT,
            yards_gained INT, pass_touchdown INT, rush_touchdown INT, game_id TEXT, play_id INT, week INT,
            passing_yards INT, receiving_yards INT, rushing_yards INT, touchdown INT)''')
        rows = []
        play = 0
        for _ in range(100):
            play += 1
            rows.append((2024, 'AAA', 'QGOOD', None, 'RGOOD', 1, 0, 1, 0, 1, 0, 0, 0, 20, 1, 0, 'g24', play, 4))
        for _ in range(40):
            play += 1
            rows.append((2024, 'AAA', 'QBAD', None, 'RBAD', 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 'g24', play, 4))
        for _ in range(40):
            play += 1
            rows.append((2024, 'AAA', 'QOTHER', None, 'ROTHER', 1, 0, 1, 0, 1, 0, 0, 0, 3, 0, 0, 'g24', play, 4))
        for _ in range(50):
            play += 1
            rows.append((2024, 'AAA', None, 'RBIG', None, 0, 0, 0, 1, None, 0, 0, 0, 15, 0, 0, 'g24', play, 4))
        for _ in range(30):
            play += 1
            rows.append((2024, 'AAA', None, 'RBSMALL', None, 0, 0, 0, 1, None, 0, 0, 0, 5, 0, 0, 'g24', play, 4))
        for _ in range(2):
            play += 1
            rows.append((2024, 'BBB', None, 'RBIG', None, 0, 0, 0, 1, None, 0, 0, 1, 2, 0, 0, 'g24b', play, 4))
        rows.append((2025, 'AAA', 'QFUTURE', None, 'RFUTURE', 1, 0, 1, 0, 1, 0, 0, 0, 50, 1, 0, 'g25', 1, 4))
        con.executemany('''INSERT INTO nfl_pbp (
            season,posteam,passer_player_id,rusher_player_id,receiver_player_id,qb_dropback,qb_scramble,
            pass_attempt,rush_attempt,complete_pass,sack,interception,fumble_lost,yards_gained,pass_touchdown,
            rush_touchdown,game_id,play_id,week) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', rows)
        con.execute('''UPDATE nfl_pbp SET passing_yards=yards_gained, receiving_yards=yards_gained,
            rushing_yards=yards_gained, touchdown=pass_touchdown''')
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_cutoff_and_transfers_are_explicit(self):
        table = po.load(self.db, 2025)
        self.assertEqual(table['source_seasons'], [2022, 2023, 2024])
        self.assertEqual(po.support(table, 'qb', 'QFUTURE'), 0)
        self.assertEqual(table['transferred_player_units']['rusher'], 1)
        self.assertEqual(po.support(table, 'rusher', 'RBIG'), 52)

    def test_event_distributions_change_for_players_with_real_history(self):
        table = po.load(self.db, 2025)
        self.assertGreater(po.event_ratio(table, 'qb', 'QGOOD', 'pass_complete'), 1.0)
        self.assertLess(po.event_ratio(table, 'qb', 'QGOOD', 'pass_incomplete'), 1.0)
        self.assertEqual(po.event_ratio(table, 'qb', 'QFUTURE', 'pass_complete'), 1.0)
        self.assertEqual(po.event_ratio(table, 'qb', None, 'pass_complete'), 1.0)

    def test_joint_yards_and_touchdown_distribution_changes_the_outcome_weight(self):
        table = po.load(self.db, 2025)
        participants = {'passer': {'gsis_id': 'QGOOD'}, 'receiver': {'gsis_id': 'RGOOD'}}
        row = {'yards_gained': 20, 'touchdown': 0}
        weight = po.row_weight(table, 'pass_complete', row, participants, state={'yl': 20})
        self.assertGreater(weight, 1.0)
        self.assertEqual(po.row_weight(table, 'pass_complete', row, {'passer': None, 'receiver': None},
                                       state={'yl': 20}), 1.0)

    def test_rushing_outcomes_are_conditioned_on_the_selected_rusher(self):
        table = po.load(self.db, 2025)
        participant = {'rusher': {'gsis_id': 'RBIG'}}
        row = {'yards_gained': 15, 'touchdown': 0}
        self.assertGreater(po.row_weight(table, 'run', row, participant, state={'yl': 30}), 1.0)
        self.assertGreater(po.event_ratio(table, 'rusher', 'RBIG', 'fumble_lost'), 1.0)


if __name__ == '__main__':
    unittest.main()
