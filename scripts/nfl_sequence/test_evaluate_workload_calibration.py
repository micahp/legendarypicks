import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate_workload_calibration as ev  # noqa: E402


def build_db(path, plays):
    """plays: (season, week, game_id, team, role_column_value) as pass plays by receiver."""
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE nfl_pbp (season INT, week INT, game_id TEXT, posteam TEXT, play_type TEXT, '
                'receiver_player_id TEXT, rusher_player_id TEXT)')
    con.execute('CREATE TABLE players (nfl_gsis_id TEXT, position TEXT, league TEXT)')
    for season, week, game_id, team, player, n in plays:
        con.executemany('INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?)',
                        [(season, week, game_id, team, 'pass', player, None)] * n)
    for player in {p for *_, p, _ in plays}:
        con.execute('INSERT INTO players VALUES (?,?,?)', (player, 'WR', 'nfl'))
    con.commit()
    con.close()


PLAYS = [
    (2024, 1, '2024_01_AAA_BBB', 'AAA', 'P1', 6), (2024, 1, '2024_01_AAA_BBB', 'AAA', 'P2', 4),
    (2024, 2, '2024_02_AAA_CCC', 'AAA', 'P1', 5), (2024, 2, '2024_02_AAA_CCC', 'AAA', 'P2', 5),
    (2024, 1, '2024_01_AAA_BBB', 'BBB', 'Q1', 7), (2024, 1, '2024_01_AAA_BBB', 'BBB', 'Q2', 3),
    (2025, 1, '2025_01_AAA_BBB', 'AAA', 'P1', 3), (2025, 1, '2025_01_AAA_BBB', 'AAA', 'P2', 2),
    (2025, 1, '2025_01_AAA_BBB', 'BBB', 'Q1', 4), (2025, 1, '2025_01_AAA_BBB', 'BBB', 'Q2', 2),
    (2025, 2, '2025_02_AAA_CCC', 'AAA', 'P1', 2), (2025, 2, '2025_02_AAA_CCC', 'AAA', 'P2', 1),
    (2025, 2, '2025_02_AAA_CCC', 'AAA', 'X', 2),
    (2025, 3, '2025_03_AAA_DDD', 'AAA', 'X', 3), (2025, 3, '2025_03_AAA_DDD', 'AAA', 'P1', 1),
]


class Evaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handle, cls.path = tempfile.mkstemp(suffix='.db')
        os.close(handle)
        build_db(cls.path, PLAYS)
        cls.results, cls.fit = ev.evaluate(cls.path, 2025, 'receive')

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.path)

    def row(self, week, team='AAA'):
        return next(r for r in self.results if r['week'] == week and r['team'] == team)

    def test_a_player_first_seen_in_the_game_is_other_not_a_known_candidate(self):
        # X appears for the first time in week 2, so before that game nobody could name him
        self.assertEqual(self.row(2)['other'], 2)

    def test_a_player_from_an_earlier_week_is_a_candidate_for_a_later_game(self):
        self.assertEqual(self.row(3)['other'], 0)
        self.assertIn(self.row(3)['candidates'], (3,))  # P1, P2 and X

    def test_candidates_with_zero_real_count_stay_in_the_score(self):
        # P2 has no week 3 count but is a candidate: the game scores three candidates, not the two who played
        self.assertEqual(self.row(3)['candidates'], 3)

    def test_the_real_total_is_the_sum_of_candidate_and_other_counts(self):
        self.assertEqual(self.row(2)['total'], 5)
        self.assertEqual(self.row(3)['total'], 4)

    def test_every_model_scores_every_team_game(self):
        for result in self.results:
            self.assertEqual(set(result['models']), set(ev.MODELS))

    def test_a_same_week_game_does_not_feed_the_prediction(self):
        # BBB's week 1 game is another team's history and must not change AAA's candidates
        self.assertEqual(self.row(1)['candidates'], 2)

    def test_predicted_shares_sum_to_one(self):
        games = ev.load_games(sqlite3.connect(self.path), 2025, 'receive')
        prior = ev.team_totals(ev.load_games(sqlite3.connect(self.path), 2024, 'receive'))
        made = ev.predictions(games[0], {}, prior, prior, {}, {}, 10.0)
        _, inputs = made
        for model, (share, _phi) in inputs.items():
            self.assertAlmostEqual(sum(share.values()), 1.0, places=9, msg=model)


class Helpers(unittest.TestCase):
    def test_week_one_uses_prior_season_only_for_the_adaptive_model(self):
        prior = {'AAA': {'P1': 6, 'P2': 4}}
        made = ev.predictions({'team': 'AAA', 'counts': {}}, {}, prior, prior, {}, {}, 10.0)
        _, inputs = made
        self.assertEqual(inputs['D'][0], inputs['C'][0])

    def test_the_adaptive_weight_moves_toward_the_current_season(self):
        prior = {'AAA': {'P1': 10}}
        earlier = {'AAA': [{'counts': {'P2': 10}, 'week': 1}] * 4}
        _, inputs = ev.predictions({'team': 'AAA', 'counts': {}}, earlier, prior, prior, {}, {}, 10.0)
        self.assertAlmostEqual(inputs['D'][0]['P1'], 0.5, places=1)  # w = 4 / (4 + 4)
        self.assertGreater(inputs['D'][0]['P2'], 0.4)

    def test_the_dirichlet_loglik_is_a_probability_over_counts(self):
        import itertools
        import math
        alphas = {'a': 1.5, 'b': 2.5}
        total = 3
        mass = sum(math.exp(ev.dm_loglik({'a': k, 'b': total - k}, total, alphas)) for k in range(total + 1))
        self.assertAlmostEqual(mass, 1.0, places=9)
        self.assertTrue(list(itertools.chain([mass])))


if __name__ == '__main__':
    unittest.main()
