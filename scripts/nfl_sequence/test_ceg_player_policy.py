import collections
import unittest
from ceg_player_policy import Opportunity, tally

class TestOpportunity(unittest.TestCase):
    def test_eligible_lineup_only(self):
        model = Opportunity({'schema':'ceg-opportunity-m3-v1','k':160,'season':2026,'week':11,
            'prior_team':[['receive','MIN','excluded',1.0]],'prior_player':[],
            'factors':[],'counts':[['receive','MIN','excluded',9999]]}, 'test')
        selected = {'qb1':'qb','slots':{'rb':'RB','wr':'WR'}}
        state = {'yl':50,'down':1,'score_diff':0}
        for seed in range(40):
            self.assertIn(model.choose('receive','MIN',selected,state,seed), ('rb','wr'))
    def test_commit_only_after_accepted_play_callback(self):
        from unittest.mock import Mock
        from ceg_harness import Provider
        provider = Provider.__new__(Provider)
        provider.players = Mock()
        lineup = {'team': 'MIN'}
        provider.accept_play({'ceg_event': 'penalty'})
        provider.players.commit.assert_not_called()
        provider.accept_play({'_ceg_pending_lineup': lineup})
        provider.players.commit.assert_called_once_with(lineup)

    def test_stats_no_penalty_and_reconcile(self):
        box = collections.defaultdict(collections.Counter)
        tally(box, {'yards_gained':0})
        self.assertFalse(box)
        tally(box, {'yards_gained':12,'touchdown':False,'ceg_player_facts':
            {'event':'pass_complete','passer':'qb','receiver':'wr','rusher':None,
             'qb1':'qb','slots':{'wr':'WR'},'fumble':False}})
        self.assertEqual(box['qb']['passing_yards'], box['wr']['receiving_yards'])
        self.assertEqual(box['wr']['intended_targets'], 1)

if __name__ == '__main__':
    unittest.main()
