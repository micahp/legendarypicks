import unittest
from types import SimpleNamespace
from unittest import mock

import source_preflight
import starter_consistency as sc


def snapshot(home_qb='00-FAG', away_qb='00-LAW'):
    return {'rosters': {
        'away': {'team': 'JAX', 'players': [
            {'gsis_id': away_qb, 'player_name': 'Trevor Lawrence', 'pos_abb': 'QB', 'pos_rank': 1},
            {'gsis_id': '00-EWE', 'player_name': 'Quinn Ewers', 'pos_abb': 'QB', 'pos_rank': 2}]},
        'home': {'team': 'BAL', 'players': [
            {'gsis_id': home_qb, 'player_name': 'Joe Fagnano', 'pos_abb': 'QB', 'pos_rank': 1},
            {'gsis_id': '00-SLO', 'player_name': 'Kedon Slovis', 'pos_abb': 'QB', 'pos_rank': 2},
            {'gsis_id': '00-WR1', 'player_name': 'Rashee Rice', 'pos_abb': 'WR', 'pos_rank': 1}]}}}


def item(update_id, team, gsis, name, position, classes):
    return {'update_id': update_id, 'team': team,
            'player': {'gsis_id': gsis, 'name': name, 'position': position},
            'classes': [{'class': c, 'span': 'x'} for c in classes]}


class ConsistencyRules(unittest.TestCase):
    def test_announced_starter_that_matches_rank_one_agrees(self):
        result = sc.check(snapshot(), [item(645777, 'BAL', '00-FAG', 'Joe Fagnano', 'QB', ['starter_named'])])
        self.assertEqual(1, result['counts']['announced agrees'])
        self.assertEqual([], result['conflicts'])

    def test_announced_starter_that_differs_from_rank_one_is_a_conflict(self):
        result = sc.check(snapshot(), [item(645777, 'BAL', '00-SLO', 'Kedon Slovis', 'QB', ['starter_named'])])
        self.assertEqual(1, result['counts']['announced differs'])
        self.assertEqual('Joe Fagnano', result['conflicts'][0]['depth_rank_one_name'])

    def test_coach_confirmation_counts_as_announced(self):
        result = sc.check(snapshot(), [item(645777, 'BAL', '00-SLO', 'Kedon Slovis', 'QB',
                                            ['coach_confirmation_reported'])])
        self.assertEqual(1, len(result['conflicts']))

    def test_expected_starter_that_differs_is_a_note_not_a_conflict(self):
        result = sc.check(snapshot(), [item(645952, 'BAL', '00-SLO', 'Kedon Slovis', 'QB', ['starter_expected'])])
        self.assertEqual([], result['conflicts'])
        self.assertEqual(1, result['counts']['expected differs'])
        self.assertEqual(1, len(result['notes']))

    def test_multi_starter_position_is_not_checked_rather_than_agreed(self):
        result = sc.check(snapshot(), [item(1, 'BAL', '00-WR2', 'Some Receiver', 'WR', ['starter_named'])])
        self.assertEqual(1, result['counts']['announced not checked (multi-starter position)'])
        self.assertEqual(0, result['counts']['announced agrees'])

    def test_no_rank_one_for_the_position_is_unverified_not_agreement(self):
        result = sc.check(snapshot(), [item(2, 'BAL', '00-TE', 'Some Tight End', 'TE', ['starter_named'])])
        self.assertEqual(0, result['counts'].get('announced agrees', 0))

    def test_item_without_a_starter_class_is_ignored(self):
        result = sc.check(snapshot(), [item(3, 'BAL', '00-FAG', 'Joe Fagnano', 'QB', ['injury_designation'])])
        self.assertEqual(0, result['counts']['announced checked'] + result['counts']['expected checked'])

    def test_two_rank_one_players_for_one_position_fail_loudly(self):
        bad = snapshot()
        bad['rosters']['home']['players'].append({'gsis_id': '00-X', 'player_name': 'Dup', 'pos_abb': 'QB', 'pos_rank': 1})
        with self.assertRaises(ValueError):
            sc.check(bad, [])

    def test_every_count_is_reported_even_when_zero(self):
        result = sc.check(snapshot(), [])
        self.assertIn('announced checked', result['counts'])
        self.assertEqual(0, result['counts']['announced checked'])
        line = sc.summary_line(result)
        self.assertIn('announced 0 checked', line)
        self.assertIn('expected 0 checked', line)


class PreflightWiring(unittest.TestCase):
    def args(self):
        return SimpleNamespace(news_evidence_dir='captures', db='db', roster_snapshot=None,
                               availability_snapshot=None, availability_store=None)

    def test_announced_conflict_stops_the_run(self):
        evidence = {'items': [item(645777, 'BAL', '00-SLO', 'Kedon Slovis', 'QB', ['starter_named'])],
                    'captures_before_cutoff': ['c'], 'captures_after_cutoff_count': 0, 'counts': {},
                    'evidence_sha256': 'abc', 'workload_effect': 'none'}
        with mock.patch('news_evidence.build', return_value=evidence):
            with self.assertRaises(source_preflight.PreflightError) as ctx:
                source_preflight.validate_news_evidence(self.args(), snapshot())
        self.assertIn('differs from depth rank 1 Joe Fagnano', str(ctx.exception))

    def test_agreement_passes_and_records_the_check(self):
        evidence = {'items': [item(645777, 'BAL', '00-FAG', 'Joe Fagnano', 'QB', ['starter_named'])],
                    'captures_before_cutoff': ['c'], 'captures_after_cutoff_count': 0, 'counts': {},
                    'evidence_sha256': 'abc', 'workload_effect': 'none'}
        with mock.patch('news_evidence.build', return_value=evidence):
            result = source_preflight.validate_news_evidence(self.args(), snapshot())
        self.assertEqual(1, result['starter_consistency']['counts']['announced agrees'])


if __name__ == '__main__':
    unittest.main()


class PinnedFlags(unittest.TestCase):
    def flagged_snapshot(self, bal_qb='00-FAG', jax_qb='00-LAW'):
        snap = snapshot(bal_qb, jax_qb)
        for side in ('away', 'home'):
            for p in snap['rosters'][side]['players']:
                p['starter'] = p['pos_abb'] == 'QB' and p['pos_rank'] == 1
        return snap

    def test_pinned_flag_is_read_instead_of_rank_one_when_the_overlay_is_applied(self):
        snap = self.flagged_snapshot(bal_qb='00-SLO')
        snap['rosters']['home']['players'][0]['starter'] = False
        snap['rosters']['home']['players'][1]['starter'] = True
        result = sc.check(snap, [item(9, 'BAL', '00-SLO', 'Kedon Slovis', 'QB', ['starter_named'])])
        self.assertEqual('pinned starter flag', result['starter_source'])
        self.assertEqual(1, result['counts']['announced agrees'])

    def test_a_flagged_starter_that_differs_from_the_announcement_is_a_conflict(self):
        snap = self.flagged_snapshot()
        result = sc.check(snap, [item(9, 'BAL', '00-SLO', 'Kedon Slovis', 'QB', ['starter_named'])])
        self.assertEqual(1, len(result['conflicts']))

    def test_a_qb_with_no_flagged_starter_is_unverified_not_agreement(self):
        snap = self.flagged_snapshot()
        for p in snap['rosters']['home']['players']:
            p['starter'] = False
        result = sc.check(snap, [item(9, 'BAL', '00-FAG', 'Joe Fagnano', 'QB', ['starter_named'])])
        self.assertEqual(1, result['counts']['announced unverified'])
        self.assertEqual(0, result['counts'].get('announced agrees', 0))

    def test_two_flagged_quarterbacks_fail_loudly(self):
        snap = self.flagged_snapshot()
        snap['rosters']['home']['players'][1]['starter'] = True
        with self.assertRaises(ValueError):
            sc.check(snap, [])

    def test_the_summary_says_which_roster_was_read(self):
        result = sc.check(self.flagged_snapshot(), [])
        self.assertIn('against pinned starter flag', sc.summary_line(result))
        self.assertIn('against depth rank 1 (preview)', sc.summary_line(sc.check(snapshot(), [])))
