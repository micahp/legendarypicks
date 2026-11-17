"""V1.7 geometry-conditioned source sampling for transported goal-line fumbles.

This is a research eligibility filter, NOT a model of end-zone fumble
recovery, scoring or safety probability.  A V1.6 replay remains unchanged.
"""
import unittest
from collections import Counter

import e0_single_play as e0
import e1_drive as e1
import football_assertions
from penalty_game import PenaltyGameController
from penalty_sampler import PenaltyProposal


class NoFoulSampler:
    enabled = True

    def propose(self, context, *, game_seed, opportunity_key):
        return PenaltyProposal(opportunity_key, context.phase, 'none',
                               'fixture-model', 'fixture-source', 'fixture')


class ChooseFirst:
    allow_sparse_cells = True

    def sample(self, rng, cell, *, offense, defense, state):
        return cell[0]


class GoalLineFumbleGeometryTests(unittest.TestCase):
    def source_pool(self):
        bad = {
            'game_id': '2024_01_WAS_NYG', 'play_id': 11,
            'game_date': '2024-09-08', 'play_type': 'pass',
            'yards_gained': -3, 'touchdown': 0,
            'sack': 1, 'fumble_lost': 1, 'penalty': 0,
        }
        good = {
            'game_id': '2024_01_WAS_NYG', 'play_id': 12,
            'game_date': '2024-09-08', 'play_type': 'punt',
            'yards_gained': 0, 'touchdown': 0,
            'sack': 0, 'fumble_lost': 0, 'penalty': 0,
        }
        st = {'quarter': 4, 'clock': 420, 'offense': 'A', 'defense': 'B',
              'yl': 99, 'down': 4, 'togo': 1, 'dir': 1}
        key = (4, e0.ydstogo_bucket(1), e0.yardline_bucket(99))
        pool = {key: [('sack_fumble_lost', bad, 8, 20),
                      ('punt', good, 8, 75)]}
        return st, pool

    def test_no_cross_goal_recovery_geometry_is_fabricated(self):
        st, pool = self.source_pool()
        disabled = PenaltyGameController(
            sampler=NoFoulSampler(), game_seed=61,
            team_identity={'A': 'WAS', 'B': 'NYG'},
            ruling_provider=lambda *args, **kwargs: None)
        plays, terminal = e1.simulate(
            st, 61, pool, 'test-fumble-v17',
            sampling_policy=ChooseFirst(),
            penalty_controller=disabled)
        self.assertEqual(terminal, 'punt')
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]['event_type'], 'punt')
        self.assertEqual(
            plays[0]['sampling']['research_turnover_geometry_rejected_source_rows'], 1)
        self.assertEqual(e1.check_drive(plays, terminal)['punts'], 1)

    def test_frozen_v16_still_exposes_the_incompatible_sample(self):
        st, pool = self.source_pool()
        with self.assertRaises(football_assertions.FootballAssertionError):
            e1.simulate(st, 61, pool, 'test-fumble-v16',
                        sampling_policy=ChooseFirst())

    def test_sack_fumble_defensive_score_is_not_mislabeled_as_clean_turnover(self):
        row = dict(self.source_pool()[1][(
            4, e0.ydstogo_bucket(1), e0.yardline_bucket(99))][0][1])
        row.update({
            'penalty': 0, 'two_point_attempt': 0, 'qb_scramble': 0,
            'down': 4, 'ydstogo': 1, 'yardline_100': 99,
            'game_seconds_remaining': 420, 'qtr': 4,
            'posteam': 'WAS', 'defteam': 'NYG', 'touchdown': 1,
        })
        next_snap = {'game_id': row['game_id'], 'qtr': 4,
                     'game_seconds_remaining': 400, 'posteam': 'NYG',
                     'play_type': 'run', 'yardline_100': 80}
        excluded = Counter()
        result = e1.classify(row, next_snap, excluded, separate_sack_fumbles=True)
        self.assertIsNone(result)
        self.assertEqual(
            excluded['sack-fumble return touchdown lacks modeled recovery geometry'], 1)


if __name__ == '__main__':
    unittest.main()
