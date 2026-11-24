"""CEG penalty layer: half-distance applied once, and pass interference as a spot foul (backlog E13)."""
import random
import unittest

import numpy as np
import pandas as pd

import ceg_game as g


class _OneType:
    def __init__(self, t):
        self.classes = [t]

    def predict(self, f):
        return np.array([[1.0]])


def next_spot(typ, yards, yl, side='defense'):
    prov = g.PenaltyProvider(None, {'K9': _OneType(typ), 'penalty_yards': {typ: [yards]}, 'first_down_rate': {typ: 1.0}})
    rec = prov._foul('live', side, 'dropback', {'yl': yl, 'togo': 10, 'down': 2, 'offense': 'A', 'defense': 'B'},
                     random.Random(1))
    return rec['penalty_after']['yl']


class PenaltyTests(unittest.TestCase):
    def test_pass_interference_goes_to_the_one_not_half_distance(self):
        self.assertEqual(next_spot('Defensive Pass Interference', 20, 10), 1)

    def test_pass_interference_runs_to_the_spot(self):
        self.assertEqual(next_spot('Defensive Pass Interference', 30, 60), 30)

    def test_fifteen_yard_foul_is_halved_once_near_the_goal(self):
        self.assertEqual(next_spot('Unnecessary Roughness', 15, 10), 5)

    def test_fifteen_yard_foul_is_full_at_midfield(self):
        self.assertEqual(next_spot('Unnecessary Roughness', 15, 50), 35)

    def test_offense_foul_is_halved_near_its_own_goal(self):
        self.assertEqual(next_spot('Offensive Holding', 10, 95, side='offense'), 97)

    def test_yard_lists_use_only_midfield_fouls(self):
        pen = pd.DataFrame({'y': ['Unnecessary Roughness'] * 3, 'yardline_100': [10, 50, 60],
                            'penalty_yards': [5.0, 15.0, 15.0]})
        self.assertEqual(g.penalty_yard_lists(pen)['Unnecessary Roughness'], [15, 15])

    def test_yard_lists_keep_a_type_with_no_midfield_foul(self):
        pen = pd.DataFrame({'y': ['Delay of Game'], 'yardline_100': [3], 'penalty_yards': [1.0]})
        self.assertEqual(g.penalty_yard_lists(pen)['Delay of Game'], [1])


if __name__ == '__main__':
    unittest.main()
