import unittest
from unittest.mock import Mock
from shared_participation import Policy, roster_feasible_groups


def roster(team, positions):
    rows = []
    for i, pos in enumerate(positions):
        suffix = 'qb' if pos == 'QB' else 'rb' if pos == 'RB' and i == 1 else str(i)
        rows.append({'gsis_id': f'{team}-{suffix}', 'pos_abb': pos, 'pos_rank': i})
    return rows

class PersistentLineupTest(unittest.TestCase):
    def test_stints_persist_by_team_and_prepare_does_not_commit(self):
        field = Mock()
        field.sha256 = 'test'
        field.position_prior = {('RB', '11'): 1.0}
        def advance(team, lineup, group, roster, draw, prev_group=None, slots=None):
            pid = team + '-rb'
            return {pid: lineup.get(pid, 0) + 1}, {'status':'ok','slots':{pid:'RB'}}
        field.advance.side_effect = advance
        policy = Policy.__new__(Policy)
        policy.field = field
        policy.rosters = {t: roster(t, ['QB', 'RB', 'TE', 'WR', 'WR', 'WR'])
                          for t in ('MIN','BUF')}
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

    def test_unavailable_personnel_group_is_excluded(self):
        available = roster('CHI', ['QB', 'RB', 'TE', 'TE', 'TE', 'WR', 'WR', 'WR', 'WR'])
        self.assertEqual(roster_feasible_groups(available, ('13', '14')), {'13'})

    def test_group_draw_conditions_on_roster_feasibility(self):
        field = Mock()
        field.sha256 = 'test'
        field.position_prior = {('TE', '13'): 1.0}
        field.supported_cell.return_value = '1|xl|mid'
        field.group_probs.return_value = {'13': 0.5, '14': 0.5}
        field.advance.return_value = ({}, {'status': 'ok', 'slots': {}})
        policy = Policy.__new__(Policy)
        policy.field = field
        policy.rosters = {'CHI': roster('CHI', ['QB', 'RB', 'TE', 'TE', 'TE', 'WR', 'WR', 'WR', 'WR'])}
        policy.qbs = {'CHI': 'CHI-qb'}
        policy.previous = {}
        policy.update = None
        policy.provenance = {'entry_current': False}
        selected = policy.prepare('CHI', {'down': 1, 'togo': 10, 'yl': 60}, 7)
        self.assertEqual(selected['group'], '13')
        self.assertEqual(selected['selection']['group_feasibility']['excluded_groups'], ['14'])
        self.assertEqual(selected['selection']['group_feasibility']['excluded_probability_mass'], 0.5)

    def test_forced_infeasible_group_fails_by_name(self):
        field = Mock()
        policy = Policy.__new__(Policy)
        policy.field = field
        policy.rosters = {'CHI': roster('CHI', ['QB', 'RB', 'TE', 'TE', 'TE', 'WR'])}
        policy.previous = {}
        with self.assertRaisesRegex(ValueError, 'shared_participation_roster_group_infeasible:CHI:14'):
            policy.prepare('CHI', {'down': 1, 'togo': 10, 'yl': 60}, 7, group='14')

    def test_a_multi_role_player_cannot_fill_two_slots(self):
        available = roster('TST', ['QB', 'TE', 'WR', 'WR'])
        available.append({'gsis_id': 'TST-hybrid', 'pos_abb': 'RB', 'pos_rank': 5})
        available.append({'gsis_id': 'TST-hybrid', 'pos_abb': 'WR', 'pos_rank': 5})
        self.assertNotIn('11', roster_feasible_groups(available, ('11',)))

if __name__ == '__main__':
    unittest.main()
