"""Adversarial tests for postgame evidence, eligibility, and editorial output."""
import copy
import unittest

from postgame_story_engine import generate_recap
from postgame_story_audit import audit
from postgame_rubric import grade_postgame
from postgame_feed_adapter import build_feed, rank_feed
from test_postgame_story_engine import fixture


def nba_fixture():
    b = fixture()
    b['game'].update(league='nba', game_id='g1')
    b['teams'][0].update(id='HOU', name='Houston Rockets', score=110)
    b['teams'][1].update(id='DEN', name='Denver Nuggets', score=100)
    b['teams'][0]['publisher_team_id'] = '10'
    b['teams'][1]['publisher_team_id'] = '7'
    b['sources'].append({'id': 'box:g1', 'source_event_id': 'g1',
                         'captured_at': '2026-11-01T21:30:00Z',
                         'kind': 'final_boxscore', 'status': 'final',
                         'teams': {'10': 110, '7': 100}})
    b['players'] = [{'id': 'p1', 'name': 'Alex Example', 'team_id': 'HOU',
                     'publisher_team_id': '10',
                     'game_id': 'g1', 'source_id': 'box:g1',
                     'stats': {'points': 35, 'rebounds': 8, 'assists': 7}}]
    return b


class RichStoryTests(unittest.TestCase):
    def test_player_highlight_has_source_and_independent_claim_check(self):
        b = nba_fixture(); result = generate_recap(b)
        self.assertEqual(result['gate'], 'eligible')
        self.assertIn('Alex Example', result['headline'])
        self.assertIn('35', result['lede'])
        self.assertTrue(result['audit']['claims_recomputed'])
        self.assertTrue(any(c['type'] == 'player_stat' for c in result['claims']))

    def test_wrong_game_team_source_or_late_capture_omitted(self):
        for field, value in [('game_id', 'g2'), ('team_id', 'OTHER'), ('source_id', 'missing')]:
            b = nba_fixture(); b['players'][0][field] = value
            self.assertNotIn('Alex Example', str(generate_recap(b)))
        b = nba_fixture(); b['sources'][1]['captured_at'] = '2026-11-01T23:00:00Z'
        result = generate_recap(b)
        self.assertEqual(result['gate'], 'eligible_score_only')
        self.assertNotIn('Alex Example', result['headline'])
        b = nba_fixture(); b['sources'][1]['captured_at'] = '2026-11-01T16:00:00Z'
        self.assertEqual(generate_recap(b)['gate'], 'eligible_score_only')

    def test_boxscore_team_and_result_must_reconcile(self):
        b = nba_fixture(); b['players'][0]['publisher_team_id'] = '7'
        self.assertEqual(generate_recap(b)['gate'], 'eligible_score_only')
        b = nba_fixture(); b['sources'][1]['teams']['10'] = 111
        self.assertEqual(generate_recap(b)['gate'], 'eligible_score_only')

    def test_changed_stat_or_player_attribution_fails_audit(self):
        b = nba_fixture(); result = generate_recap(b)
        bad = copy.deepcopy(result)
        bad['claims'][-1]['value'] = 36
        self.assertFalse(audit(b, bad)['claims_recomputed'])
        bad = copy.deepcopy(result)
        bad['claims'][-1]['team_id'] = 'DEN'
        self.assertFalse(audit(b, bad)['claims_recomputed'])

    def test_rubric_na_and_hard_gate(self):
        b = fixture(); result = generate_recap(b)
        graded = grade_postgame(b, result)
        self.assertEqual(len(graded['dimensions']), 6)
        self.assertIsNone(graded['dimensions']['sequence']['score'])
        bad = copy.deepcopy(result); bad['audit']['final_status'] = False
        self.assertEqual(grade_postgame(b, bad)['status'], 'blocked')

    def test_score_tampering_fails_even_when_claims_unchanged(self):
        b = nba_fixture(); result = generate_recap(b)
        result['headline'] = 'Denver wins 100-110'
        self.assertFalse(audit(b, result)['result_and_margin_recomputed'])

    def test_double_double_uses_both_boxscore_values(self):
        b = nba_fixture()
        b['players'][0]['stats'].update(points=23, rebounds=12)
        result = generate_recap(b)
        self.assertEqual(result['gate'], 'eligible')
        self.assertIn('23 points and 12 rebounds', result['lede'])
        self.assertTrue(result['audit']['claims_recomputed'])
        result['claims'][-1]['value'] = 13
        self.assertFalse(audit(b, result)['claims_recomputed'])

    def test_rich_feed_only_reuses_audited_claims(self):
        b = nba_fixture(); result = generate_recap(b)
        posts = build_feed(b, result)
        self.assertTrue(any(p['kind'] == 'player_spotlight' for p in posts))
        self.assertTrue(all(p['source_ids'] for p in posts))
        self.assertTrue(any(p['kind'] == 'chart' and p['graphic_spec']['unit'] == 'points' for p in posts))
        result['audit']['claims_recomputed'] = False
        self.assertEqual(build_feed(b, result), [])

    def test_halftime_context_recomputed_from_complete_quarter_scores(self):
        b = nba_fixture()
        b['segments'] = {'source_id': 'box:g1', 'period_scores': {'10': [32, 22, 23, 33], '7': [24, 16, 28, 32]}}
        result = generate_recap(b)
        self.assertEqual(result['gate'], 'eligible')
        self.assertIn('54-40 at halftime', ' '.join(result['paragraphs']))
        bad = copy.deepcopy(result); bad['paragraphs'][0] = 'Denver led 54-40 at halftime.'
        self.assertFalse(audit(b, bad)['claims_recomputed'])
        b['segments']['period_scores']['10'][0] = 33
        self.assertEqual(generate_recap(b)['paragraphs'], [])

    def test_contradictory_status_and_unsupported_finals_block(self):
        for detail in ('Suspended', 'Postponed', 'Canceled', 'Retired', 'In progress'):
            b = fixture(); b['game']['status_detail'] = detail
            self.assertEqual(generate_recap(b)['gate'], 'blocked')
        b = fixture(); b['game']['league'] = 'nhl'
        self.assertEqual(generate_recap(b)['gate'], 'blocked')

    def test_ranking_is_deterministic_diverse_and_blocks_ineligible(self):
        b = nba_fixture(); posts = build_feed(b, generate_recap(b))
        second = copy.deepcopy(posts[0]); second.update(game_id='g2', post_id='nba:g2:final_score:v1')
        bad = copy.deepcopy(second); bad.update(post_id='bad', audit_status='blocked')
        ranked = rank_feed(posts + [second, bad], favorite_teams=['HOU'], as_of_utc=b['as_of_utc'])
        self.assertEqual(ranked, rank_feed(posts + [second, bad], favorite_teams=['HOU'], as_of_utc=b['as_of_utc']))
        self.assertNotIn('bad', [p['post_id'] for p in ranked])
        self.assertEqual(len({p['game_id'] for p in ranked[:2]}), 2)
        self.assertIn('duplicate_penalty', ranked[0]['rank_components'])

    def test_nfl_passing_line_requires_final_boxscore(self):
        b = fixture()
        b['teams'][0]['publisher_team_id'] = '30'; b['teams'][1]['publisher_team_id'] = '33'
        b['sources'].append({'id': 'box:g1', 'source_event_id': 'g1', 'captured_at': '2026-11-01T21:30:00Z',
                             'kind': 'final_boxscore', 'status': 'final', 'teams': {'30': 33, '33': 10}})
        b['players'] = [{'id': 'p1', 'name': 'Alex Example', 'team_id': 'JAX', 'publisher_team_id': '30',
                         'game_id': 'g1', 'source_id': 'box:g1', 'stats': {'passing_yards': 242, 'passing_touchdowns': 1}}]
        result = generate_recap(b)
        self.assertEqual(result['gate'], 'eligible')
        self.assertIn('242 yards and 1 touchdown', ' '.join(result['paragraphs']))
        self.assertTrue(any(p['kind'] == 'player_spotlight' for p in build_feed(b, result)))
        bad = copy.deepcopy(result); bad['paragraphs'][0] = 'Alex Example threw for 243 yards and 1 touchdown.'
        self.assertFalse(audit(b, bad)['claims_recomputed'])


if __name__ == '__main__':
    unittest.main()
