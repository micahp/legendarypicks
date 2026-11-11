import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_pass_label_outcomes as evaluator


class PassLabelEvaluationEligibilityTest(unittest.TestCase):
    def test_sack_fumble_is_first_stage_turnover_not_conditional_pass_outcome(self):
        event = evaluator.event_of({
            'sack': 1, 'fumble_lost': 1, 'interception': 0,
            'complete_pass': 0, 'pass_attempt': 1,
        })
        self.assertEqual(event, 'sack_fumble_lost')
        self.assertTrue(evaluator.is_turnover_event(event))
        self.assertFalse(evaluator.is_conditional_pass_outcome(event))

    def test_sack_without_lost_fumble_is_not_a_turnover(self):
        event = evaluator.event_of({
            'sack': 1, 'fumble_lost': 0, 'interception': 0,
            'complete_pass': 0, 'pass_attempt': 1,
        })
        self.assertEqual(event, 'sack')
        self.assertFalse(evaluator.is_turnover_event(event))
        self.assertFalse(evaluator.is_conditional_pass_outcome(event))

    def test_only_known_clean_penalty_rows_are_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'pbp.sqlite'
            connection = sqlite3.connect(database)
            connection.execute(
                """CREATE TABLE nfl_pbp (
                   game_id TEXT, play_id INTEGER, season INTEGER, week INTEGER, qtr INTEGER,
                   posteam TEXT, down INTEGER, ydstogo INTEGER, yardline_100 INTEGER,
                   sack INTEGER, complete_pass INTEGER, interception INTEGER,
                   fumble_lost INTEGER, pass_attempt INTEGER, play_type TEXT, penalty INTEGER
                )""")
            common = ('G1', 1, 2025, 1, 1, 'AAA', 3, 8, 50, 1, 0, 0, 1, 1, 'pass')
            connection.execute('INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (*common, 0))
            connection.execute('INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               ('G1', 2, 2025, 1, 1, 'AAA', 3, 8, 50, 0, 1, 0, 0, 1,
                                'pass', None))
            connection.execute('INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               ('G1', 3, 2025, 1, 1, 'AAA', 3, 8, 50, 0, 1, 0, 0, 1,
                                'pass', 1))
            connection.commit()
            connection.close()

            rows, eligibility = evaluator.load_plays(database, 2025, 2025)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['event'], 'sack_fumble_lost')
        self.assertEqual(eligibility['included_known_clean_rows'], 1)
        self.assertEqual(eligibility['excluded_unknown_penalty_status_rows'], 1)
        self.assertEqual(eligibility['excluded_penalty_tagged_rows'], 1)


if __name__ == '__main__':
    unittest.main()
