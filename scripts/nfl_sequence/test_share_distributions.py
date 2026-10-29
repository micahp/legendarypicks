"""Per-game target and carry share distributions (Dirichlet-multinomial), drawn once per game and used for every play in it.

Tests are written before share_distributions.py. They check the draw's shape (sums to one, eligible players only, deterministic per
game), its mean (the prior-season base share), its spread (the Dirichlet variance), and its effect on the pre-event receiver.
"""
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pre_event as pe  # noqa: E402
import share_distributions as sd  # noqa: E402
from test_pre_event import SNAPSHOT  # noqa: E402

ROSTER = [('AAA', 'AWR1'), ('AAA', 'AWR2'), ('AAA', 'ATE1'), ('AAA', 'ARB1')]
BASE = {'AWR1': 0.5, 'AWR2': 0.3, 'ATE1': 0.15, 'ARB1': 0.05}


def table(phi):
    return {'phi': {'receive': phi, 'carry': phi}, 'base': {'receive': {('AAA', g): b for g, b in BASE.items()}, 'carry': {}}}


class Draw(unittest.TestCase):
    def test_the_shares_sum_to_one_and_cover_only_the_eligible_players(self):
        shares = sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'AWR2', 'ATE1'], 'receive', 'seed-1')
        self.assertEqual(set(shares), {'AWR1', 'AWR2', 'ATE1'})
        self.assertAlmostEqual(sum(shares.values()), 1.0)

    def test_the_same_game_and_seed_give_the_same_shares_and_another_game_differs(self):
        a = sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'AWR2'], 'receive', 'seed-1')
        self.assertEqual(a, sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'AWR2'], 'receive', 'seed-1'))
        self.assertNotEqual(a, sd.game_shares(table(17.0), 'AAA', 'g2', ['AWR1', 'AWR2'], 'receive', 'seed-1'))

    def test_the_mean_over_games_is_the_base_share(self):
        totals = {g: 0.0 for g in BASE}
        n = 3000
        for i in range(n):
            shares = sd.game_shares(table(17.0), 'AAA', f'g{i}', list(BASE), 'receive', 'seed-1')
            for g in BASE:
                totals[g] += shares[g]
        for g, b in BASE.items():
            self.assertAlmostEqual(totals[g] / n, b, delta=0.02, msg=g)

    def test_the_spread_over_games_is_the_dirichlet_variance(self):
        phi = 17.0
        xs = [sd.game_shares(table(phi), 'AAA', f'g{i}', list(BASE), 'receive', 'seed-1')['AWR1'] for i in range(3000)]
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
        self.assertAlmostEqual(var, BASE['AWR1'] * (1 - BASE['AWR1']) / (phi + 1), delta=0.01)

    def test_a_player_with_no_base_gets_the_floor_and_still_has_a_share(self):
        shares = sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'NOBODY'], 'receive', 'seed-1')
        self.assertGreater(shares['NOBODY'], 0.0)


class Receiver(unittest.TestCase):
    """Within one game the receiver follows that game's shares. A near one-hot draw means every play in the game goes to one player."""

    def test_within_a_game_the_receiver_follows_the_game_share(self):
        players = [p for p in SNAPSHOT['rosters']['home']['players'] if p['pos_abb'] in ('WR', 'TE', 'RB')]
        receivers = set()
        for index in range(30):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=index, player_shares={'receive': {}, 'carry': {}},
                               share_table=table(0.01))
            receivers.add(chosen['receiver']['gsis_id'])
        self.assertEqual(len(receivers), 1)
        self.assertIn(receivers.pop(), {p['gsis_id'] for p in players})

    def test_without_a_share_table_the_receiver_is_unchanged(self):
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=0, player_shares={'receive': {}, 'carry': {}})
        self.assertIn('receiver', chosen)


if __name__ == '__main__':
    unittest.main()
