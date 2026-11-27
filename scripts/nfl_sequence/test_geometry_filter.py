"""The V1.6 geometry filter: a fumble source row whose net gain crosses a goal line is left out at the live state.

The two states are the week 11 seeds that stopped with `sack_fumble_lost loss N carries the ball past its own goal
line`: MIA at BUF seed 300081 (3rd and 8 at 97, loss of 9) and MIN at SF seed 300097 (3rd and 7 at 92, loss of 10).
"""
import inspect
import unittest

import e1_drive
import reducer


def sample(event, yards):
    return (event, {'yards_gained': yards, 'game_id': 'g', 'play_id': 1}, 5, None)


class TurnoverGeometry(unittest.TestCase):
    def test_week11_sack_fumbles_behind_own_goal_line_are_ineligible(self):
        self.assertFalse(e1_drive._turnover_geometry_eligible(sample('sack_fumble_lost', -9), {'yl': 97}))
        self.assertFalse(e1_drive._turnover_geometry_eligible(sample('sack_fumble_lost', -10), {'yl': 92}))

    def test_the_same_rows_stay_eligible_where_they_fit(self):
        self.assertTrue(e1_drive._turnover_geometry_eligible(sample('sack_fumble_lost', -9), {'yl': 60}))
        self.assertTrue(e1_drive._turnover_geometry_eligible(sample('fumble_lost', 4), {'yl': 30}))

    def test_a_fumble_gain_past_the_opponent_goal_line_is_ineligible(self):
        self.assertFalse(e1_drive._turnover_geometry_eligible(sample('fumble_lost', 12), {'yl': 8}))

    def test_other_events_are_never_filtered(self):
        for event in ('run', 'pass_complete', 'sack', 'interception', 'punt'):
            self.assertTrue(e1_drive._turnover_geometry_eligible(sample(event, -30), {'yl': 95}))

    def test_the_reducer_still_refuses_the_state_so_the_filter_is_what_prevents_it(self):
        st = {'offense': 'A', 'defense': 'B', 'down': 3, 'togo': 8, 'yl': 97}
        with self.assertRaisesRegex(ValueError, 'past its own goal line'):
            reducer.apply_play(st, 'sack_fumble_lost', -9, spot=20)

    def test_the_filter_is_off_by_default(self):
        self.assertIs(inspect.signature(e1_drive.simulate).parameters['geometry_filter'].default, False)


if __name__ == '__main__':
    unittest.main()
