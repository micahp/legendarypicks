import unittest

import nfl_matchup_reconciliation as recon


def upd(update_id, published, status='', headline='', notes='', analysis=''):
    return {'update_id': update_id, 'published_utc': published, 'injury_status': status,
            'headline': headline, 'notes': notes, 'analysis': analysis}


class ProjectionRuleTests(unittest.TestCase):
    def test_negative_count_mean_is_a_problem(self):
        self.assertEqual('negative mean for a count or yardage stat',
                         recon.projection_problem({'stat': 'rec_td', 'mean': -0.05, 'p10': None, 'p90': None}))

    def test_negative_yardage_lower_bound_is_a_problem(self):
        self.assertEqual('negative lower bound for a count or yardage stat',
                         recon.projection_problem({'stat': 'rec_yds', 'mean': 40.0, 'p10': -3.0, 'p90': 90.0}))

    def test_mean_outside_its_range_is_a_problem(self):
        self.assertEqual('mean outside its p10 to p90 range',
                         recon.projection_problem({'stat': 'rec', 'mean': 9.0, 'p10': 1.0, 'p90': 6.0}))

    def test_point_estimate_without_a_range_passes(self):
        self.assertIsNone(recon.projection_problem({'stat': 'rec', 'mean': 5.7, 'p10': None, 'p90': None}))

    def test_implausible_touchdown_mean_is_a_problem(self):
        self.assertIn('implausible', recon.projection_problem({'stat': 'rush_td', 'mean': 6.0, 'p10': None, 'p90': None}))

    def test_missing_mean_is_a_problem(self):
        self.assertEqual('no mean', recon.projection_problem({'stat': 'rec', 'mean': None, 'p10': None, 'p90': None}))


class InjuryTests(unittest.TestCase):
    def test_later_good_to_go_update_contradicts_the_designation(self):
        state = recon.injury_state([
            upd(1, '2026-11-03T21:57:00+00:00', status='QUESTIONABLE', headline='Limited'),
            upd(2, '2026-11-04T20:32:00+00:00', headline='Good to go for TNF')])
        self.assertEqual('contradicted', state['state'])
        self.assertEqual('QUESTIONABLE', state['designation'])
        self.assertEqual([2], [c['update_id'] for c in state['clears']])

    def test_a_later_update_with_no_injury_text_does_not_clear_anything(self):
        state = recon.injury_state([
            upd(1, '2026-11-03T21:57:00+00:00', status='QUESTIONABLE', headline='Limited'),
            upd(2, '2026-11-04T20:32:00+00:00', headline='Named Week 9 starter')])
        self.assertEqual('designation', state['state'])

    def test_conflicting_designations_inside_the_window_are_reported(self):
        state = recon.injury_state([
            upd(1, '2026-11-03T20:47:00+00:00', status='DOUBTFUL'),
            upd(2, '2026-11-04T14:00:00+00:00', status='OUT')])
        self.assertEqual('designations_disagree', state['state'])
        self.assertEqual(['DOUBTFUL', 'OUT'], [d['status'] for d in state['disagreements']])

    def test_no_designation_is_unknown_not_healthy(self):
        state = recon.injury_state([upd(1, '2026-11-03T20:47:00+00:00', headline='Practices fully')])
        self.assertEqual('no_designation_recorded', state['state'])
        self.assertIsNone(state['designation'])

    def test_one_repeated_designation_is_not_a_disagreement(self):
        state = recon.injury_state([
            upd(1, '2026-11-03T20:47:00+00:00', status='QUESTIONABLE'),
            upd(2, '2026-11-04T14:00:00+00:00', status='QUESTIONABLE')])
        self.assertEqual('designation', state['state'])
        self.assertEqual([], state['disagreements'])


class RosterAndStarterTests(unittest.TestCase):
    def test_news_team_outside_the_matchup_conflicts_with_the_roster(self):
        state = recon.roster_state({'JAX', 'BAL'}, None, 'JAX', 'MIN', 'JAX')
        self.assertEqual('conflict', state['state'])
        self.assertIn('latest news says MIN', state['conflicts'][0])

    def test_depth_chart_on_the_matchup_with_matching_news_is_current(self):
        state = recon.roster_state({'JAX', 'BAL'}, 'BAL', None, 'BAL', 'BAL')
        self.assertEqual('current_depth_chart', state['state'])
        self.assertEqual([], state['conflicts'])

    def test_player_on_no_matchup_roster_is_not_treated_as_available(self):
        state = recon.roster_state({'JAX', 'BAL'}, None, None, None, 'DAL')
        self.assertEqual('not_on_matchup_roster', state['state'])

    def test_starter_state_is_unknown_without_a_claim(self):
        self.assertEqual('none_recorded', recon.starter_state([])['state'])

    def test_named_starter_is_announced_and_expected_alone_is_expected(self):
        announced = recon.starter_state([
            {'claim_class': 'starter_expected', 'published_utc': '2026-11-04T00:00:00+00:00', 'update_id': 1},
            {'claim_class': 'starter_named', 'published_utc': '2026-11-03T00:00:00+00:00', 'update_id': 2}])
        expected = recon.starter_state([
            {'claim_class': 'starter_expected', 'published_utc': '2026-11-04T00:00:00+00:00', 'update_id': 1}])
        self.assertEqual('announced', announced['state'])
        self.assertEqual('expected', expected['state'])


class ContradictionListTests(unittest.TestCase):
    def test_collects_every_kind_of_conflict_for_one_player(self):
        record = {
            'injury': {'state': 'contradicted', 'designation': 'QUESTIONABLE',
                       'designation_published_utc': '2026-11-03T21:57:00+00:00',
                       'clears': [{'update_id': 2, 'published_utc': '2026-11-04T20:32:00+00:00', 'text': 'Good to go'}]},
            'roster': {'conflicts': ['latest news says MIN, roster says JAX']},
            'projection_problems': ['rec_td (espn/espn-weekly): negative mean'],
            'projected_but_not_rostered': True,
        }
        lines = recon.contradictions(record)
        self.assertEqual(4, len(lines))
        self.assertTrue(lines[0].startswith('injury:'))

    def test_clean_player_has_no_contradictions(self):
        record = {'injury': {'state': 'designation', 'clears': []}, 'roster': {'conflicts': []},
                  'projection_problems': [], 'projected_but_not_rostered': False}
        self.assertEqual([], recon.contradictions(record))


if __name__ == '__main__':
    unittest.main()
