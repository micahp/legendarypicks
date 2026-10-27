import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import s0_baseline as s0  # noqa: E402


def game(gid, week, home, away, hs, as_):
    return (gid, 2010, week, home, away, hs, as_)


def history_games(with_week_four_for_a=True):
    """H has four earlier games with margins 10, -3, 17, 7 (mean 7.75). A has margins 7, 3, 0 and 0 (mean 2.5)."""
    games = [game('g1', 1, 'H', 'X', 10, 0), game('g2', 2, 'Y', 'H', 3, 0), game('g3', 3, 'H', 'Z', 17, 0),
             game('g4', 4, 'W', 'H', 0, 7), game('g6', 1, 'A', 'Q', 7, 0), game('g7', 2, 'R', 'A', 0, 3),
             game('g8', 3, 'A', 'S', 0, 0)]
    if with_week_four_for_a:
        games.append(game('g9', 4, 'T', 'A', 0, 0))
    games.append(game('g5', 5, 'H', 'A', 20, 10))
    return games


class PriorMargins(unittest.TestCase):
    def feature(self, games, gid):
        return next(f for f in s0.scored_features(games) if f['game_id'] == gid)

    def test_prior_margin_uses_earlier_weeks_only(self):
        f = self.feature(history_games(), 'g5')
        self.assertTrue(f['scored'])
        # The week 5 margin (+10 for H) is not in H's prior mean. Including it would give 5.7.
        self.assertAlmostEqual(f['x'], 7.75 - 2.5)

    def test_a_team_with_fewer_than_four_earlier_games_is_unscored(self):
        f = self.feature(history_games(with_week_four_for_a=False), 'g5')
        self.assertFalse(f['scored'])
        self.assertIsNone(f['x'])


if __name__ == '__main__':
    unittest.main()
