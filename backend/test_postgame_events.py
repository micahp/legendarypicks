import copy
import hashlib
import json
import unittest

from postgame_story_engine import generate_recap
from postgame_story_audit import audit
from test_postgame_rich import nba_fixture


def comeback_fixture():
    b = nba_fixture()
    b['players'] = []
    events = [{'id': '1', 'sequence': 1, 'period': 1, 'clock_seconds': 720,
               'kind': 'start', 'scores': {'10': 0, '7': 0}}]
    scores = {'10': 0, '7': 0}
    for period in (1, 2):
        number = len(events) + 1
        events.append({'id': str(number), 'sequence': number, 'period': period,
                       'clock_seconds': 0, 'kind': 'period_end', 'scores': scores.copy()})
    for period, team, count in [(3, '10', 25), (3, '7', 30), (4, '7', 20), (4, '10', 30)]:
        if period == 4 and events[-1]['period'] == 3:
            number = len(events) + 1
            events.append({'id': str(number), 'sequence': number, 'period': 3,
                           'clock_seconds': 0, 'kind': 'period_end', 'scores': scores.copy()})
        for _ in range(count):
            scores[team] += 2
            number = len(events) + 1
            events.append({'id': str(number), 'sequence': number, 'period': period,
                           'clock_seconds': 720 - number, 'kind': 'score', 'scores': scores.copy()})
    number = len(events) + 1
    events.append({'id': str(number), 'sequence': number, 'period': 4,
                   'clock_seconds': 0, 'kind': 'end', 'scores': scores.copy()})
    digest = hashlib.sha256(json.dumps(events, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    b['sources'].append({'id': 'pbp:g1', 'source_event_id': 'g1', 'captured_at': '2026-11-01T21:45:00Z',
                         'kind': 'final_pbp', 'status': 'final', 'coverage': 'complete',
                         'event_count': len(events), 'events_sha256': digest, 'teams': {'10': 110, '7': 100}})
    b['events'] = events
    b['event_sequence'] = {'source_id': 'pbp:g1'}
    return b


class EventTests(unittest.TestCase):
    def test_complete_chronological_sequence_yields_supported_angle(self):
        b = comeback_fixture(); out = generate_recap(b)
        self.assertEqual(out['gate'], 'eligible')
        self.assertIn('fourth quarter', out['headline'])
        self.assertTrue(audit(b, out)['claims_recomputed'])

    def test_missing_unordered_or_tampered_sequence_falls_back(self):
        for change in ('coverage', 'order', 'final', 'digest'):
            b = comeback_fixture()
            if change == 'coverage': b['sources'][-1]['coverage'] = 'partial'
            if change == 'order': b['events'][2], b['events'][3] = b['events'][3], b['events'][2]
            if change == 'final': b['events'][-1]['scores']['10'] = 109
            if change == 'digest': b['sources'][-1]['events_sha256'] = '0' * 64
            if change in ('order', 'final'):
                b['sources'][-1]['events_sha256'] = hashlib.sha256(json.dumps(b['events'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            out = generate_recap(b)
            self.assertEqual(out['gate'], 'eligible_score_only')
            self.assertNotIn('fourth quarter', out['headline'])

    def test_tampered_narrative_and_claim_fail_independent_audit(self):
        b = comeback_fixture(); out = generate_recap(b)
        bad = copy.deepcopy(out); bad['headline'] = 'Denver takes charge in the fourth quarter'
        self.assertFalse(audit(b, bad)['result_and_margin_recomputed'])
        bad = copy.deepcopy(out); bad['claims'][-1]['event_id'] = '1'
        self.assertFalse(audit(b, bad)['claims_recomputed'])

    def test_audited_scoring_run_with_no_late_lead_change(self):
        b = comeback_fixture(); events = b['events']; score = {'10': 0, '7': 0}
        # Winner builds a lead and never trails; both teams finish at the original totals.
        for i, event in enumerate(events):
            if event['kind'] == 'score':
                if score['10'] < 110: score['10'] += 2
                else: score['7'] += 2
            event['scores'] = score.copy()
        b['sources'][-1]['events_sha256'] = hashlib.sha256(json.dumps(events, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        out = generate_recap(b)
        self.assertEqual(out['gate'], 'eligible')
        self.assertIn('straight points', out['lede'])
        self.assertTrue(audit(b, out)['claims_recomputed'])

    def test_event_headline_keeps_a_supported_player_in_recap(self):
        b = comeback_fixture(); b['players'] = nba_fixture()['players']
        out = generate_recap(b)
        self.assertEqual(out['gate'], 'eligible')
        self.assertIn('fourth quarter', out['headline'])
        self.assertIn('Alex Example scored 35 points', ' '.join(out['paragraphs']))
        self.assertTrue(audit(b, out)['claims_recomputed'])
