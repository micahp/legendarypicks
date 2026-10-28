"""2026 pregame inputs fail closed: a backtest needs verified availability for every input, and post-cutoff rows never count."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import holdout  # noqa: E402
import pregame_snapshot as ps  # noqa: E402

GAME = '2026_08_BBB_AAA'
CUTOFF = '2026-10-20T12:00:00Z'


def make_db(tmp, schedule_observed='2026-10-01 00:00:00', depth_snapshot='2026-10-01T12:00:00Z', gameday='2026-10-29'):
    db = str(Path(tmp) / 'nfl.sqlite3')
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE nfl_schedule_versions (game_id TEXT, season INTEGER, game_type TEXT, week INTEGER, '
                'gameday TEXT, weekday TEXT, gametime TEXT, away_team TEXT, home_team TEXT, location TEXT, away_score INTEGER, '
                'home_score INTEGER, result TEXT, total INTEGER, source TEXT, observed_at TEXT)')
    con.execute("INSERT INTO nfl_schedule_versions VALUES (?, 2026, 'REG', 8, ?, 'Thursday', '20:15', 'BBB', 'AAA', 'Home', "
                "NULL, NULL, NULL, NULL, 'test', ?)", (GAME, gameday, schedule_observed))
    con.execute('CREATE TABLE nfl_depth_chart (season INTEGER, team TEXT, player_id TEXT, gsis_id TEXT, player_name TEXT, '
                'pos_abb TEXT, pos_rank INTEGER, snapshot_at TEXT, source TEXT)')
    for team in ('AAA', 'BBB'):
        for pos in ('QB', 'RB', 'WR'):
            con.execute("INSERT INTO nfl_depth_chart VALUES (2026, ?, ?, ?, ?, ?, 1, ?, 'nflverse_depth_charts')",
                        (team, f'{team}{pos}', f'g{team}{pos}', f'{team} {pos}', pos, depth_snapshot))
    con.commit()
    con.close()
    return db


class BacktestFailsClosed(unittest.TestCase):
    def test_a_2026_backtest_with_unverified_inputs_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                ps.build(make_db(tmp), GAME, CUTOFF)
            message = str(caught.exception)
            self.assertIn('backtest refused', message)
            self.assertIn('artifact date', message)      # depth provenance
            self.assertIn('loader import', message)      # schedule provenance

    def test_an_exploratory_replay_is_built_and_labelled_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = ps.build(make_db(tmp), GAME, CUTOFF, evaluation='exploratory_replay')
        self.assertEqual(snapshot['evaluation']['class'], 'exploratory_replay')
        self.assertFalse(snapshot['evaluation']['verified'])
        self.assertTrue(snapshot['evaluation']['unverified_inputs'])

    def test_an_unknown_evaluation_class_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ps.build(make_db(tmp), GAME, CUTOFF, evaluation='prospective')


class PostCutoffInformationIsExcluded(unittest.TestCase):
    def test_a_schedule_first_observed_after_the_cutoff_is_not_used(self):
        # the 2026 Weeks 1-7 rows were all first observed on 2026-10-27, after the games
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                ps.build(make_db(tmp, schedule_observed='2026-10-27 22:39:53'), GAME, CUTOFF, evaluation='exploratory_replay')
            self.assertIn('no schedule version was observed', str(caught.exception))

    def test_a_depth_chart_published_after_the_cutoff_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                ps.build(make_db(tmp, depth_snapshot='2026-10-25T12:00:00Z'), GAME, CUTOFF, evaluation='exploratory_replay')
            self.assertIn('no pregame depth-chart rows', str(caught.exception))

    def test_a_cutoff_on_or_after_the_game_day_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                ps.build(make_db(tmp, gameday='2026-10-29'), GAME, '2026-10-29T12:00:00Z', evaluation='exploratory_replay')
            self.assertIn('must precede scheduled game day', str(caught.exception))


class MissingCutoffFailsClosed(unittest.TestCase):
    def test_a_2026_read_without_a_cutoff_is_refused(self):
        with self.assertRaises(ValueError):
            holdout.refuse_unless_cutoff(2026, 'pregame snapshot', None)
        with self.assertRaises(ValueError):
            holdout.refuse_if_holdout(2026, 'unbounded read')

    def test_a_2026_game_needs_its_cutoff_as_an_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TypeError):
                ps.build(make_db(tmp), GAME)  # noqa: missing as_of


if __name__ == '__main__':
    unittest.main()
