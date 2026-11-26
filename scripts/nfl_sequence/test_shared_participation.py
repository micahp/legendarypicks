import unittest
from unittest.mock import Mock
from shared_participation import Policy

class PersistentLineupTest(unittest.TestCase):
    def test_stints_persist_by_team_and_prepare_does_not_commit(self):
        field = Mock()
        field.sha256 = 'test'
        def advance(team, lineup, group, roster, draw, prev_group=None, slots=None):
            pid = team + '-rb'
            return {pid: lineup.get(pid, 0) + 1}, {'status':'ok','slots':{pid:'RB'}}
        field.advance.side_effect = advance
        policy = Policy.__new__(Policy)
        policy.field = field
        policy.rosters = {t: [{'gsis_id':t+'-rb'}] for t in ('MIN','BUF')}
        policy.qbs = {t:t+'-qb' for t in ('MIN','BUF')}
        policy.previous = {}
        policy.update = None
        policy.provenance = {'entry_current':False}
        state = {'down':1,'togo':10,'yl':60}
        one = policy.prepare('MIN', state, 1, group='11')
        self.assertEqual(one['lineup']['MIN-rb'], 1)
        self.assertFalse(policy.previous)
        policy.commit(one)
        other = policy.prepare('BUF', state, 2, group='11')
        self.assertEqual(other['lineup']['BUF-rb'], 1)
        policy.commit(other)
        two = policy.prepare('MIN', state, 3, group='11')
        self.assertEqual(two['lineup']['MIN-rb'], 2)

if __name__ == '__main__':
    unittest.main()
