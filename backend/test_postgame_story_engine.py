import copy
import json
import unittest
from unittest.mock import patch

from postgame_story_engine import generate_recap
from postgame_feed_adapter import build_feed


def fixture():
    return {'game': {'league':'nfl','game_id':'g1','status':'final','start_utc':'2026-11-01T17:00:00Z'},
            'teams': [{'id':'JAX','name':'Jacksonville Jaguars','score':33}, {'id':'BAL','name':'Baltimore Ravens','score':10}],
            'sources':[{'id':'scoreboard:g1','captured_at':'2026-11-01T21:00:00Z'}],
            'as_of_utc':'2026-11-01T22:00:00Z','players':[],'events':[]}

class PostgameTests(unittest.TestCase):
    def test_deterministic_and_no_network(self):
        with patch('socket.socket',side_effect=AssertionError('network')):
            a=generate_recap(fixture()); b=generate_recap(fixture())
            self.assertEqual(json.dumps(a,sort_keys=True),json.dumps(b,sort_keys=True))
            self.assertEqual(build_feed(fixture(),a),build_feed(fixture(),b))
    def test_score_only(self):
        out=generate_recap(fixture()); self.assertEqual(out['gate'],'eligible_score_only')
        self.assertIn('33-10',out['headline']); self.assertIn('23',out['lede'])
        self.assertNotIn('comeback',json.dumps(out).lower())
    def test_nonfinal_and_bad_scores_block(self):
        for status in ('in','suspended','postponed','retired'):
            b=fixture();b['game']['status']=status;self.assertEqual(generate_recap(b)['gate'],'blocked')
        for score in (None,-1,'33'):
            b=fixture();b['teams'][0]['score']=score;self.assertEqual(generate_recap(b)['gate'],'blocked')
    def test_future_capture_blocked(self):
        b=fixture();b['sources'][0]['captured_at']='2027-01-01T00:00:00Z';self.assertEqual(generate_recap(b)['gate'],'blocked')
    def test_tie_does_not_invent_winner(self):
        b=fixture();b['teams'][0]['score']=10;out=generate_recap(b)
        self.assertNotIn('beats',out['headline']);self.assertIn('tie',out['headline'].lower())
    def test_player_wrong_game_and_incomplete_events_are_omitted(self):
        b=fixture();b['players']=[{'game_id':'other','team_id':'JAX','name':'X','points':100}];b['events']=[{'id':'p1','game_id':'g1','sequence':1}]
        out=generate_recap(b);self.assertNotIn('X',out['lede']);self.assertNotIn('comeback',json.dumps(out))
    def test_wrong_source_game_and_nba_tie_blocked(self):
        b=fixture();b['sources'][0]['source_event_id']='other';self.assertEqual(generate_recap(b)['gate'],'blocked')
        b=fixture();b['game']['league']='nba';b['teams'][0]['score']=10;self.assertEqual(generate_recap(b)['gate'],'blocked')
    def test_independent_audit_rejects_changed_winner(self):
        from postgame_story_audit import audit
        b=fixture();out=generate_recap(b);out['headline']='Baltimore Ravens beats Jacksonville Jaguars, 33-10'
        self.assertFalse(audit(b,out)['result_and_margin_recomputed'])
    def test_feed_ids_and_evidence(self):
        b=fixture();a=generate_recap(b);posts=build_feed(b,a)
        self.assertEqual(len({p['post_id'] for p in posts}),len(posts))
        self.assertTrue(all(p['source_ids'] for p in posts))
        self.assertTrue(all(p['audit_status']=='eligible_score_only' for p in posts))
