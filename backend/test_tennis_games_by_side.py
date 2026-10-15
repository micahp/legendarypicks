"""games_by_side: the exact per-player games add up to the exact total, and match a point-by-point simulation."""
import random
import unittest

import tennis_match_sim as sim


class GamesBySideTest(unittest.TestCase):
    def test_the_two_sides_add_up_to_expected_games(self):
        for serve_a, serve_b in ((0.65, 0.62), (0.70, 0.60), (0.58, 0.66)):
            exact = sim.match_distribution(serve_a, serve_b)
            games_a, games_b = sim.games_by_side(exact)
            self.assertAlmostEqual(games_a + games_b, exact["expected_games"], places=3)

    def test_matches_a_point_by_point_simulation(self):
        serve_a, serve_b = 0.65, 0.62
        games_a, games_b = sim.games_by_side(sim.match_distribution(serve_a, serve_b))
        rng = random.Random(7)
        n = 5000
        sum_a = sum_b = 0.0
        for _ in range(n):
            for _, winner, winner_games, loser_games in sim.simulate_match(rng, serve_a, serve_b)["set_log"]:
                if winner == "A":
                    sum_a += winner_games
                    sum_b += loser_games
                else:
                    sum_b += winner_games
                    sum_a += loser_games
        self.assertAlmostEqual(sum_a / n, games_a, delta=0.15)
        self.assertAlmostEqual(sum_b / n, games_b, delta=0.15)


if __name__ == "__main__":
    unittest.main()
