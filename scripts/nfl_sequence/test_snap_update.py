"""The current-season update from published snap counts: grouping tilt, player weights, the player leave hazard, and that
nothing from the game's week or later is read."""
import math
import random
import unittest
from collections import Counter

import participation_field as pf
import snap_update as su
from test_participation_field import _data, _roster


def _field(**overrides):
    data = _data(team_transitions=[['KC', '1|long|red', '11', {'11': 2.0}]],
                 team_plays=[['KC', '11', 40.0], ['KC', '12', 10.0]],
                 appearances=[['wr1', 'KC', '11', 38.0], ['wr2', 'KC', '11', 36.0], ['wr3', 'KC', '11', 30.0],
                              ['wr4', 'KC', '11', 4.0], ['rb1', 'KC', '11', 30.0], ['te1', 'KC', '11', 35.0]],
                 position_prior=[['RB', '11', 0.5], ['WR', '11', 0.25], ['TE', '11', 0.5], ['FB', '11', 0.1]],
                 **overrides)
    return pf.Field(data, 'h' * 64)


def _snaps(weeks=(1, 2, 3)):
    """KC played weeks 1 to 3 with 60 snaps each; wr4 played every snap, wr1 none (active), te1 and te2 every snap."""
    data = {'schema': su.SCHEMA, 'season': 2026,
            'team_snaps': [['KC', w, 60.0] for w in weeks],
            'player_snaps': [x for w in weeks for x in (['KC', w, 'wr4', 'WR', 60.0], ['KC', w, 'te1', 'TE', 60.0],
                                                        ['KC', w, 'te2', 'TE', 60.0], ['KC', w, 'rb1', 'RB', 60.0],
                                                        ['KC', w, 'wr2', 'WR', 60.0])],
            'active': [['KC', w, ['wr1', 'wr2', 'wr3', 'wr4', 'te1', 'te2', 'rb1', 'rb2']] for w in weeks]}
    return su.SnapCounts(data, 's' * 64)


class SnapCounts(unittest.TestCase):
    def test_only_weeks_before_the_game_are_read(self):
        snaps = _snaps()
        self.assertEqual(snaps.weeks_before('KC', 3), [1, 2])
        self.assertEqual(snaps.player_share('KC', 3, 'wr4'), (2, 1.0))
        self.assertEqual(snaps.player_share('KC', 3, 'wr1'), (2, 0.0))  # active, no snap: a zero, not a missing game
        self.assertEqual(snaps.player_share('KC', 1, 'wr4'), (0, 0.0))

    def test_class_shares_count_rb_te_wr_per_team_snap(self):
        games, shares = _snaps().class_shares('KC', 4)
        self.assertEqual((games, shares), (3, [1.0, 2.0, 2.0]))

    def test_a_wrong_schema_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'schema'):
            su.SnapCounts({'schema': 'x'}, 'h')


class Tilt(unittest.TestCase):
    def test_the_tilt_moves_the_mix_mean_to_the_target(self):
        mix = Counter({'11': 60.0, '12': 30.0, '21': 10.0})
        target = [1.05, 1.6, 2.35]  # reachable: 35% 11, 60% 12, 5% 21
        lam = su.tilt_lambda(mix, target)
        w = {g: mix[g] * math.exp(sum(l * x for l, x in zip(lam, pf.class_vector(g)))) for g in mix}
        z = sum(w.values())
        for i, want in enumerate(target):
            self.assertAlmostEqual(sum(w[g] * pf.class_vector(g)[i] for g in w) / z, want, places=4)

    def test_a_two_te_team_draws_more_two_te_groupings(self):
        field = _field()
        before = field.group_probs('KC', '1|long|red', '11')
        field.group_tilt['KC'] = tuple(su.group_lambda(field, _snaps(), 'KC', 4, n0=1.0))
        after = field.group_probs('KC', '1|long|red', '11')
        self.assertGreater(after['12'], before['12'])
        self.assertAlmostEqual(sum(after.values()), 1.0)

    def test_no_earlier_game_no_tilt(self):
        self.assertIsNone(su.group_lambda(_field(), _snaps(), 'KC', 1))


class PlayerWeights(unittest.TestCase):
    def test_a_player_playing_more_than_the_table_says_is_weighted_up(self):
        field = _field()
        players = [p for p in _roster() if p['pos_abb'] in su.SNAP_CLASS]
        weights, status = su.player_weights(field, _snaps(), 'KC', 4, players, n0=2.0)
        self.assertGreater(weights[('KC', 'wr4')], 1.0)
        self.assertLess(weights[('KC', 'wr1')], 1.0)
        self.assertNotIn(('KC', 'fb1'), weights)  # no earlier active game: no weight, counted
        self.assertEqual(status['no_earlier_active_game'], 1)

    def test_apply_records_what_it_used_and_resets_between_games(self):
        field = _field()
        record = su.apply(field, _snaps(), 4, {'KC': _roster()}, player_n0=2.0)
        self.assertEqual(record['teams']['KC']['last_week_used'], 3)
        self.assertIn('KC', field.group_tilt)
        su.apply(field, _snaps(), 1, {'KC': _roster()}, player_n0=2.0)
        self.assertEqual((field.group_tilt, field.player_weight), ({}, {}))

    def test_the_weight_moves_who_enters(self):
        field = _field()
        field.player_weight[('KC', 'wr4')] = 20.0
        picks = Counter()
        for seed in range(200):
            lineup, _ = field.advance('KC', {}, '11', _roster(), random.Random(seed))
            picks.update(p for p in lineup if p.startswith('wr'))
        self.assertGreater(picks['wr4'], 150)


class LeaveHazard(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(_field().leave_power, 0.0)

    def test_a_regular_stays_longer_than_a_backup(self):
        field = _field(leave_power=1.0, leave_reference_rate={'RB': 0.5, 'TE': 0.5, 'WR': 0.5})
        self.assertLess(field.leave_factor('wr1', 'KC', '11', 'WR', 'WR'), 1.0)
        self.assertGreater(field.leave_factor('wr4', 'KC', '11', 'WR', 'WR'), 1.0)

    def test_leave_power_needs_a_reference(self):
        with self.assertRaisesRegex(ValueError, 'leave_reference_rate'):
            _field(leave_power=1.0)

    def test_reference_rate_is_the_on_field_mean(self):
        ref = pf.leave_reference_rate({('a', 'KC', '11'): 30.0, ('b', 'KC', '11'): 10.0}, {('KC', '11'): 40.0},
                                      {('WR', '11'): 0.5}, {'a': 'WR', 'b': 'WR'})
        rate_a, rate_b = (30 + 20 * 0.5) / 60, (10 + 20 * 0.5) / 60
        self.assertAlmostEqual(ref['WR'], (30 * rate_a + 10 * rate_b) / 40)


if __name__ == '__main__':
    unittest.main()
