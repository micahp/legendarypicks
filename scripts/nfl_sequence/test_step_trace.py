import json
import tempfile
import unittest
from pathlib import Path

import step_trace


def decision(down, intent, personnel, previous=None):
    return {'state': {'quarter': 1, 'clock': 845, 'down': down, 'togo': 10, 'yardline_100': 75, 'score_diff': 0,
                      'offense': 'A', 'defense': 'B', 'team': 'NYG'},
            'p_dropback': 0.58, 'point_shift': 0.0, 'streak_shift': 0.0, 'kick_share': 0.0,
            'draw_order': 'personnel_first', 'p_dropback_given_personnel': 0.41, 'previous_personnel': previous,
            'pbv1_package': None, 'personnel': personnel, 'formation': 'UNDER CENTER', 'intent': intent,
            'participants': {'rusher': '00-1', 'lineup': {'group': personnel, 'on_field': ['00-1', '00-2'],
                                                          'entrants': [], 'leavers': []}},
            'event': 'run', 'source': {'game_id': '2023_01_X_Y', 'play_id': 77}}


TRACE = {'schema': 'lp-nfl-slc-play-trace-1', 'seed': 5, 'game_id': '2026_10_WAS_NYG', 'error': None,
         'sides': {'A': 'NYG', 'B': 'WSH'},
         'decisions': [decision(1, 'run', '12', 'START'), decision(2, 'dropback', '11', '12'), decision(3, 'run', '12', '11')],
         'record': {'drives': [{'plays': [
             {'event_type': 'run', 'outcome': {'yards_gained': 4}, 'state_after': {'down': 2}},
             {'event_type': 'pass_complete', 'outcome': {'yards_gained': 12, 'touchdown': True}, 'state_after': {'down': 1}}]}],
             'stats': {'player': [{'gsis_id': '00-1', 'name': 'Cam Skattebo'}]}}}


class Render(unittest.TestCase):
    def test_the_steps_are_shown_in_the_engines_order(self):
        text = step_trace.render(0, 3, TRACE['decisions'][0], step_trace.plays_of(TRACE['record'])[0], TRACE['sides'],
                                 step_trace.player_names(TRACE['record']))
        steps = [text.index(f'  {n} ') for n in range(1, 7)]
        self.assertEqual(steps, sorted(steps))
        self.assertIn('NYG ball   1st & 10 at NYG 25', text)
        self.assertIn('previous START', text)
        self.assertIn('p(dropback | personnel, formation) 0.410', text)
        self.assertIn('rusher Cam Skattebo', text)
        self.assertIn('yards 4', text)

    def test_a_decision_with_no_play_says_so(self):
        text = step_trace.render(2, 3, TRACE['decisions'][2], None, TRACE['sides'], {})
        self.assertIn('no play record', text)


class Stepping(unittest.TestCase):
    def run_keys(self, keys, *extra):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'seed-5.json'
            path.write_text(json.dumps(TRACE))
            out, keys = [], iter(keys)
            step_trace.main([str(path), *extra], read=lambda prompt: next(keys), write=out.append)
        return [line.split('\n')[0] for line in out if line.startswith('Play ')]

    def test_next_back_jump_and_quit(self):
        shown = [line.split('   ')[0] for line in self.run_keys(['', 'b', '3', 'q'])]
        self.assertEqual(shown, ['Play 1 of 3', 'Play 2 of 3', 'Play 1 of 3', 'Play 3 of 3'])

    def test_all_prints_every_play_without_prompts(self):
        shown = [line.split('   ')[0] for line in self.run_keys([], '--all')]
        self.assertEqual(shown, ['Play 1 of 3', 'Play 2 of 3', 'Play 3 of 3'])

    def test_a_file_that_is_not_a_trace_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'run.json'
            path.write_text(json.dumps({'schema': 'something else'}))
            with self.assertRaises(ValueError):
                step_trace.main([str(path)], read=lambda prompt: 'q', write=lambda text: None)


class Writer(unittest.TestCase):
    def test_the_batch_writes_a_trace_the_viewer_reads(self):
        import simulate_pregame_batch as batch
        snapshot = {'schedule': {'game_id': '2026_10_WAS_NYG', 'home_team': 'NYG', 'away_team': 'WSH'}}
        with tempfile.TemporaryDirectory() as folder:
            batch._write_play_trace(Path(folder) / 'traces', 9, snapshot, TRACE['record'], TRACE['decisions'], 'boom')
            trace = step_trace.load(Path(folder) / 'traces' / 'seed-9.json')
        self.assertEqual(trace['sides'], {'A': 'NYG', 'B': 'WSH'})
        self.assertEqual(len(trace['decisions']), 3)
        self.assertEqual(trace['error'], 'boom')


if __name__ == '__main__':
    unittest.main()
