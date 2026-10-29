import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slc_playcall as slc  # noqa: E402
from test_slc_playcall import blank_artifact  # noqa: E402


def rows(yardlines):
    out = []
    for i, yl in enumerate(yardlines):
        out.append(('pass_complete', {'game_id': '2025_01_AAA_BBB', 'play_id': i, 'season': 2025, 'down': 1, 'ydstogo': 5,
                                      'yardline_100': yl, 'play_type': 'pass', 'posteam': 'AAA'}, 6.0, 52))
    return out


STATE = {'quarter': 2, 'clock': 500, 'down': 1, 'togo': 5, 'yl': 5, 'score_diff': 0}


class ExactYardline(unittest.TestCase):
    def test_inside_the_twenty_the_draw_uses_the_states_own_yard_line_when_available(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.exact_yardline = True
        cell = rows([5] * 10 + [9] * 10)
        drawn = {sampler.sample(random.Random(s), cell, 'A', 'B', state=STATE)[1]['yardline_100'] for s in range(200)}
        self.assertEqual(drawn, {5})

    def test_with_no_row_at_the_exact_yard_line_the_cell_is_used(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.exact_yardline = True
        cell = rows([9] * 10)
        drawn = {sampler.sample(random.Random(s), cell, 'A', 'B', state=STATE)[1]['yardline_100'] for s in range(50)}
        self.assertEqual(drawn, {9})

    def test_the_option_is_off_by_default_and_leaves_the_draw_unchanged(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        cell = rows([5] * 10 + [9] * 10)
        drawn = {sampler.sample(random.Random(s), cell, 'A', 'B', state=STATE)[1]['yardline_100'] for s in range(200)}
        self.assertEqual(drawn, {5, 9})


if __name__ == '__main__':
    unittest.main()
