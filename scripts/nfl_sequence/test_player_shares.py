import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import player_shares as ps  # noqa: E402
import pre_event as pe  # noqa: E402
from test_pre_event import SNAPSHOT  # noqa: E402

DB = '/root/legendarypicks/backend/data/picks.dev.db'


def table(receive=None, carry=None):
    return {'receive': receive or {}, 'carry': carry or {}, 'seasons': [2024, 2025]}


class Weights(unittest.TestCase):
    def test_a_player_with_a_larger_prior_share_is_drawn_more_often(self):
        players = ps.eligible(SNAPSHOT['rosters']['home']['players'], ps.TARGET_POSITIONS)
        shares = table(receive={('AAA', players[0]['gsis_id']): 0.7, ('AAA', players[1]['gsis_id']): 0.1})
        draw = random.Random(3)
        counts = {}
        for _ in range(2000):
            chosen = draw.choices(players, weights=[ps.weight(shares, 'AAA', p['gsis_id'], 'receive') for p in players], k=1)[0]
            counts[chosen['gsis_id']] = counts.get(chosen['gsis_id'], 0) + 1
        self.assertGreater(counts[players[0]['gsis_id']], counts.get(players[1]['gsis_id'], 0) * 3)

    def test_a_rostered_player_with_no_history_keeps_the_floor_weight(self):
        self.assertEqual(ps.weight(table(), 'AAA', 'nobody', 'receive'), ps.FLOOR)

    def test_only_rostered_players_in_the_right_positions_are_eligible(self):
        players = SNAPSHOT['rosters']['home']['players']
        names = {p['gsis_id'] for p in ps.eligible(players, ps.TARGET_POSITIONS)}
        self.assertNotIn('AQB1', names)  # a quarterback is not a receiver
        self.assertTrue(names <= {p['gsis_id'] for p in players})


class Choice(unittest.TestCase):
    def test_a_dropback_target_is_a_rostered_receiver_and_the_passer_is_the_starter(self):
        shares = table(receive={('AAA', 'AWR1'): 0.9})
        for seed in range(30):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=seed, index=0, player_shares=shares)
            self.assertEqual(chosen['passer']['gsis_id'], 'AQB1')
            self.assertIn(chosen['receiver']['pos_abb'], ps.TARGET_POSITIONS)
            self.assertIn(chosen['receiver']['gsis_id'], {p['gsis_id'] for p in SNAPSHOT['rosters']['home']['players']})

    def test_the_same_inputs_give_the_same_target(self):
        shares = table(receive={('AAA', 'AWR1'): 0.5})
        self.assertEqual(pe.choose(SNAPSHOT, 'home', 'dropback', 7, 2, player_shares=shares)['receiver'],
                         pe.choose(SNAPSHOT, 'home', 'dropback', 7, 2, player_shares=shares)['receiver'])

    def test_a_run_names_a_rostered_carrier(self):
        shares = table(carry={('AAA', 'ARB1'): 0.8})
        chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=4, index=1, player_shares=shares)
        self.assertIn(chosen['rusher']['pos_abb'], ps.CARRY_POSITIONS)


@unittest.skipUnless(Path(DB).exists(), 'database not present')
class Prior(unittest.TestCase):
    def test_the_shares_use_only_seasons_before_the_cutoff(self):
        shares = ps.load(DB, 2026)
        self.assertEqual(shares['seasons'], [2022, 2023, 2024, 2025])

    def test_a_cutoff_with_no_prior_season_is_refused(self):
        with self.assertRaises(ValueError):
            ps.load(DB, 2022)

    def test_each_teams_shares_sum_to_one(self):
        shares = ps.load(DB, 2026)
        by_team = {}
        for (team, _player), share in shares['receive'].items():
            by_team[team] = by_team.get(team, 0.0) + share
        for team, total in by_team.items():
            self.assertAlmostEqual(total, 1.0, places=6, msg=team)


if __name__ == '__main__':
    unittest.main()
