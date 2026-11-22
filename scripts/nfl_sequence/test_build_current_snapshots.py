"""The QB check in build_current_snapshots: a snapshot QB1 must be the QB the market prices."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_current_snapshots as builder  # noqa: E402


def snapshot(lv_qb1):
    def roster(team, qb):
        return {'team': team, 'players': [{'pos_abb': 'QB', 'pos_rank': 1, 'player_name': qb[0], 'gsis_id': qb[1]},
                                          {'pos_abb': 'QB', 'pos_rank': 2, 'player_name': 'Backup', 'gsis_id': 'B'}]}
    return {'schedule': {'game_id': '2026_11_LV_DEN'},
            'rosters': {'away': roster('LV', lv_qb1), 'home': roster('DEN', ('Bo Nix', '00-0039732'))}}


class QbCheck(unittest.TestCase):
    def test_matching_qbs_pass(self):
        qbs = {'LV': {'00-0041562'}, 'DEN': {'00-0039732'}}
        self.assertEqual(builder.check_qbs(snapshot(('Fernando Mendoza', '00-0041562')), qbs), [])

    def test_a_stale_qb1_is_refused(self):
        qbs = {'LV': {'00-0041562'}, 'DEN': {'00-0039732'}}
        problems = builder.check_qbs(snapshot(('Kirk Cousins', '00-0029604')), qbs)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith('QB1_NOT_MARKET_QB 2026_11_LV_DEN: LV depth QB1 Kirk Cousins'))

    def test_no_priced_qb_is_refused_not_passed(self):
        problems = builder.check_qbs(snapshot(('Fernando Mendoza', '00-0041562')), {'DEN': {'00-0039732'}})
        self.assertEqual(problems, ['NO_MARKET_QB 2026_11_LV_DEN: no passing-yards prop for LV yet'])


if __name__ == '__main__':
    unittest.main()
