import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_uncertainty as pu  # noqa: E402


class Bootstrap(unittest.TestCase):
    def test_identical_losses_have_no_difference_and_no_width(self):
        losses = np.full(200, 0.6)
        games = np.repeat(np.arange(10), 20).astype(str)
        result = pu.paired(losses, losses, games)
        self.assertEqual(result['mean_difference'], 0.0)
        self.assertEqual(result['ci95'], [0.0, 0.0])
        self.assertEqual(result['games'], 10)

    def test_a_difference_that_alternates_between_games_has_an_interval_around_zero(self):
        games = np.repeat(np.arange(10), 20).astype(str)
        first = np.where(np.arange(200) // 20 % 2 == 0, 0.7, 0.5)
        result = pu.paired(first, np.full(200, 0.6), games)
        low, high = result['ci95']
        self.assertAlmostEqual(result['mean_difference'], 0.0)
        self.assertLess(low, 0.0)
        self.assertGreater(high, 0.0)

    def test_resampling_whole_games_is_wider_than_resampling_plays_when_plays_share_a_game(self):
        first = np.where(np.arange(200) // 20 % 2 == 0, 0.7, 0.5)
        second = np.full(200, 0.6)
        clustered = pu.paired(first, second, np.repeat(np.arange(10), 20).astype(str))['ci95']
        per_play = pu.paired(first, second, np.arange(200).astype(str))['ci95']
        self.assertGreater(clustered[1] - clustered[0], per_play[1] - per_play[0])


class ClusteredCalibration(unittest.TestCase):
    def test_the_game_based_z_is_calibrated_when_plays_share_a_game_effect(self):
        rng = np.random.default_rng(5)
        games = np.repeat(np.arange(200), 60).astype(str)
        marginal = float(np.mean(1 / (1 + np.exp(-(np.log(0.6 / 0.4) + rng.normal(0.0, 0.5, 200000))))))
        p = np.full(len(games), marginal)  # the model is right on average: its probability is the marginal rate
        squared_by_game, squared_independent = [], []
        for _ in range(400):
            effect = np.repeat(rng.normal(0.0, 0.5, 200), 60)
            y = (rng.random(len(games)) < 1 / (1 + np.exp(-(np.log(0.6 / 0.4) + effect)))).astype(float)
            squared_by_game.append(pu.game_z(y, p, games) ** 2)
            squared_independent.append(pu.independent_z(y, p, games) ** 2)
        self.assertAlmostEqual(np.mean(squared_by_game), 1.0, delta=0.2)
        self.assertGreater(np.mean(squared_independent), 2.0)


if __name__ == '__main__':
    unittest.main()
