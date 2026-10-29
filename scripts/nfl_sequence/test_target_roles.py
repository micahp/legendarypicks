import collections
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pre_event as pe  # noqa: E402
import target_roles as tr  # noqa: E402
from test_pre_event import SNAPSHOT  # noqa: E402

DB = '/root/legendarypicks/backend/data/picks.dev.db'
CELL_STATE = {'down': 2, 'togo': 7, 'yl': 50}


def table(team_roles=None, league_roles=None):
    cell = tr.cell_of(2, 7, 50)
    return {'team': {('AAA', cell): collections.Counter(team_roles or {})},
            'league': {cell: collections.Counter(league_roles or {'WR': 1})}, 'seasons': [2024], 'k': tr.K}


class Distribution(unittest.TestCase):
    def test_the_distribution_sums_to_one(self):
        shares = tr.distribution(table({'TE': 30}, {'WR': 5, 'RB': 3}), 'AAA', 2, 7, 50)
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=9)

    def test_a_teams_own_history_moves_the_role_toward_it(self):
        shares = tr.distribution(table({'TE': 40}, {'WR': 5}), 'AAA', 2, 7, 50)
        self.assertGreater(shares['TE'], 0.5)

    def test_a_team_with_no_history_takes_the_league_shares(self):
        shares = tr.distribution(table({}, {'WR': 3, 'RB': 1}), 'NEW', 2, 7, 50)
        self.assertAlmostEqual(shares['WR'], 0.75 * (20 / 24) + 0.0, delta=0.4)
        self.assertGreater(shares['WR'], shares['RB'])

    def test_a_role_not_on_the_roster_is_never_drawn(self):
        t = table({'TE': 50}, {'WR': 1})
        drawn = {tr.draw(t, 'AAA', 2, 7, 50, f's{i}', available={'RB', 'WR'}) for i in range(100)}
        self.assertNotIn('TE', drawn)
        self.assertNotIn('Other', drawn)


class ReceiverChoice(unittest.TestCase):
    def test_the_pre_event_receiver_follows_the_drawn_role(self):
        shares = {'receive': {('AAA', 'ATE1'): 0.5, ('AAA', 'AWR1'): 0.5}, 'carry': {}, 'seasons': [2024]}
        t = table({'TE': 500}, {'WR': 1})
        receivers = collections.Counter()
        for seed in range(60):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, state=CELL_STATE, player_shares=shares,
                               role_table=t)
            receivers[chosen['target_role']] += 1
            if chosen['target_role'] == 'TE':
                self.assertEqual(chosen['receiver']['pos_abb'], 'TE')
        self.assertGreater(receivers['TE'], 50)


@unittest.skipUnless(Path(DB).exists(), 'database not present')
class Prior(unittest.TestCase):
    def test_the_prior_uses_only_seasons_before_the_cutoff(self):
        t = tr.load(DB, 2026)
        self.assertEqual(t['seasons'][0], 2016)
        self.assertEqual(t['seasons'][-1], 2025)
        shares = tr.distribution(t, 'GB', 2, 7, 50)
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=9)


if __name__ == '__main__':
    unittest.main()
