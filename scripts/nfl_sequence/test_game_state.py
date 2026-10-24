"""Unit tests for the E2 first piece (game_state.py): coin-toss ledger, kickoffs, linkage, kick outcomes, validators.

Run: python3 -m unittest scripts/nfl_sequence/test_game_state.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_state as gs  # noqa: E402


class StaticPool:
    """A pool whose every cell holds the same observed-play entries: (event, row, runoff, spot)."""

    def __init__(self, event, yards, runoff, spot=None):
        row = {'game_id': 'G1', 'play_id': 1.0, 'game_date': '2025-01-01', 'yards_gained': yards,
               'touchdown': 0, 'play_type': 'run' if event == 'run' else event}
        self.entries = [(event, row, runoff, spot)] * 60

    def get(self, key, default=None):
        return self.entries


def kickoff_pool(spot=25, runoff=10):
    return [{'spot': spot, 'runoff': runoff, 'game_id': 'K', 'play_id': 1, 'game_date': '2025-01-01'}]


def certain_kicks(fg_made=True, ep_made=True):
    """A kick table in which every attempt in a cell has the same result. The two-point cell is empty."""
    fg = {b: (60, 0) if fg_made else (0, 60) for b in gs.FG_BUCKETS}
    ep = (60, 0) if ep_made else (0, 60)
    return {'field_goal': fg, 'extra_point': ep, 'two_point': (0, 0), 'source': 'test fixture'}


def spy_simulate(run):
    """Run `run()` with E1's simulate wrapped. Returns (result, calls), where each call holds the start and the id."""
    calls, real = [], gs.e1.simulate

    def spy(start, seed, pool, simulation_id):
        calls.append({'start': dict(start), 'seed': seed, 'simulation_id': simulation_id})
        return real(start, seed, pool, simulation_id)

    gs.e1.simulate = spy
    try:
        result = run()
    finally:
        gs.e1.simulate = real
    return result, calls


class Ledger(unittest.TestCase):
    def test_normal_mode_refuses_kick_and_defend_goal(self):
        for choice in ('kick', 'defend_goal'):
            with self.assertRaises(ValueError, msg=choice):
                gs.CoinTossLedger('A', 'B', choice)

    def test_exception_mode_is_not_implemented_in_this_piece(self):
        with self.assertRaises(NotImplementedError):
            gs.CoinTossLedger('A', 'B', 'receive', mode=gs.EXCEPTION_MODE)

    def test_receive_path_gives_one_kickoff_per_team(self):
        ledger = gs.CoinTossLedger('A', 'B', 'receive')
        kickoffs = ledger.half_start_kickoffs()
        self.assertEqual((kickoffs[0]['kicking_team'], kickoffs[0]['receiving_team']), ('B', 'A'))
        self.assertEqual((kickoffs[1]['kicking_team'], kickoffs[1]['receiving_team']), ('A', 'B'))
        gs.validate_half_start(kickoffs)

    def test_defer_path_gives_one_kickoff_per_team(self):
        ledger = gs.CoinTossLedger('A', 'B', 'defer')
        kickoffs = ledger.half_start_kickoffs()
        self.assertEqual((kickoffs[0]['kicking_team'], kickoffs[0]['receiving_team']), ('A', 'B'))
        self.assertEqual((kickoffs[1]['kicking_team'], kickoffs[1]['receiving_team']), ('B', 'A'))
        gs.validate_half_start(kickoffs)

    def test_second_half_first_choice_follows_the_deferral(self):
        self.assertEqual(gs.CoinTossLedger('A', 'B', 'defer').second_chooser, 'A')
        self.assertEqual(gs.CoinTossLedger('A', 'B', 'receive').second_chooser, 'B')


class Validators(unittest.TestCase):
    def test_same_team_kicking_twice_is_a_hard_failure(self):
        bad = [{'quarter': 1, 'kicking_team': 'A', 'receiving_team': 'B', 'reason': 'half_start'},
               {'quarter': 3, 'kicking_team': 'A', 'receiving_team': 'B', 'reason': 'half_start'}]
        with self.assertRaises(AssertionError):
            gs.validate_half_start(bad)

    def test_recorded_kickoffs_must_match_the_ledger(self):
        record = gs.play_game(3, _empty_e1_pool(), kickoff_pool(), certain_kicks(), winner_choice='receive')
        record['kickoffs'][0]['kicking_team'] = 'A'
        record['kickoffs'][0]['receiving_team'] = 'B'
        with self.assertRaises(AssertionError):
            gs.validate_game(record)

    def test_the_kick_table_is_required(self):
        with self.assertRaises(TypeError):
            gs.play_game(3, _empty_e1_pool(), kickoff_pool(), winner_choice='receive')

    def test_a_touchdown_whose_points_disagree_with_its_try_is_refused(self):
        record = gs.play_game(1, StaticPool('run', 80, 20), kickoff_pool(), certain_kicks(), winner_choice='receive',
                              max_drives=1)
        record['drives'][0]['points_scored_on_drive']['points'] = 6  # the try was made, so the points must be 7
        with self.assertRaises(AssertionError):
            gs.validate_game(record)


class KickoffPool(unittest.TestCase):
    def test_receiving_team_is_posteam_and_its_next_snap_gives_the_spot(self):
        rows = [
            {'game_id': 'g', 'play_id': 1.0, 'posteam': 'R', 'defteam': 'K', 'qtr': 1.0, 'yardline_100': 35.0,
             'game_seconds_remaining': 3600.0, 'play_type': 'kickoff', 'game_date': '2025-09-01'},
            {'game_id': 'g', 'play_id': 2.0, 'posteam': 'R', 'defteam': 'K', 'qtr': 1.0, 'yardline_100': 75.0,
             'game_seconds_remaining': 3596.0, 'play_type': 'pass', 'game_date': '2025-09-01'},
        ]
        pool, excluded = gs.build_kickoff_pool(rows)
        self.assertEqual([(p['spot'], p['runoff']) for p in pool], [(75, 4)])
        self.assertEqual(sum(excluded.values()), 0)

    def test_a_kickoff_followed_by_the_kicking_team_is_excluded(self):
        rows = [
            {'game_id': 'g', 'play_id': 1.0, 'posteam': 'R', 'defteam': 'K', 'qtr': 1.0, 'yardline_100': 35.0,
             'game_seconds_remaining': 3600.0, 'play_type': 'kickoff', 'game_date': '2025-09-01'},
            {'game_id': 'g', 'play_id': 2.0, 'posteam': 'K', 'defteam': 'R', 'qtr': 1.0, 'yardline_100': 60.0,
             'game_seconds_remaining': 3596.0, 'play_type': 'run', 'game_date': '2025-09-01'},
        ]
        pool, excluded = gs.build_kickoff_pool(rows)
        self.assertEqual(pool, [])
        self.assertEqual(excluded['kickoff without a clean receiving snap'], 1)


class FieldGoalBuckets(unittest.TestCase):
    def test_buckets_match_the_published_labels(self):
        cases = {9: '1-9', 10: '10-19', 19.5: '10-19', 20: '20-29', 39: '30-39', 40: '40-49', 49: '40-49', 50: '50+',
                 65: '50+'}
        for yl, label in cases.items():
            self.assertEqual(gs.fg_bucket(yl), label, yl)


class Linkage(unittest.TestCase):
    def test_a_touchdown_takes_its_try_then_the_scoring_team_kicks_off(self):
        # Q1 opening: B receives (A kicks) in the receive path. The first play scores, so the scorer kicks next.
        record = gs.play_game(1, StaticPool('run', 80, 20), kickoff_pool(), certain_kicks(), winner_choice='receive',
                              max_drives=2)
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_score']
        scorer = record['drives'][0]['offense_team']
        self.assertGreaterEqual(len(post), 1)
        self.assertEqual(post[0]['kicking_team'], scorer, 'the team that scored kicks off next')
        self.assertEqual(record['points'][scorer], 7, 'a touchdown and a made extra point')
        self.assertEqual(record['drives'][0]['points_scored_on_drive']['try'], {'kind': 'extra_point', 'made': True})
        gs.validate_game(record)

    def test_a_missed_extra_point_scores_six(self):
        record = gs.play_game(1, StaticPool('run', 80, 20), kickoff_pool(), certain_kicks(ep_made=False),
                              winner_choice='receive', max_drives=1)
        scorer = record['drives'][0]['offense_team']
        self.assertEqual(record['points'][scorer], 6)
        gs.validate_game(record)

    def test_a_two_point_try_scores_eight_when_it_is_chosen_and_made(self):
        kicks = certain_kicks()
        kicks['two_point'], kicks['extra_point'] = (60, 0), (0, 0)  # every post-touchdown attempt is a two-point try
        record = gs.play_game(1, StaticPool('run', 80, 20), kickoff_pool(), kicks, winner_choice='receive',
                              max_drives=1)
        scorer = record['drives'][0]['offense_team']
        self.assertEqual(record['points'][scorer], 8)
        self.assertEqual(record['drives'][0]['points_scored_on_drive']['try']['kind'], 'two_point')
        gs.validate_game(record)

    def test_a_made_field_goal_scores_three_and_the_kicker_kicks_off(self):
        record = gs.play_game(1, StaticPool('field_goal_attempt', 0, 20), kickoff_pool(), certain_kicks(fg_made=True),
                              winner_choice='receive', max_drives=2)
        kicker = record['drives'][0]['offense_team']
        self.assertTrue(record['drives'][0]['field_goal_made'])
        self.assertEqual(record['points'][kicker], 3)
        post = [k for k in record['kickoffs'] if k['kind'] == 'post_field_goal']
        self.assertEqual(post[0]['kicking_team'], kicker)
        gs.validate_game(record)

    def test_a_missed_field_goal_gives_the_other_team_the_spot_of_the_kick(self):
        # The kickoff lands at the 25 and the FG is kicked from there, so the other team starts at yardline_100 75.
        record, calls = spy_simulate(lambda: gs.play_game(
            1, StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25), certain_kicks(fg_made=False),
            winner_choice='receive', max_drives=2))
        self.assertFalse(record['drives'][0]['field_goal_made'])
        self.assertEqual(record['points'], {'A': 0, 'B': 0})
        self.assertEqual(calls[0]['start']['yl'], 25)
        self.assertEqual(calls[1]['start']['offense'], calls[0]['start']['defense'])
        self.assertEqual(calls[1]['start']['yl'], 75)
        gs.validate_game(record)

    def test_a_thin_published_cell_blocks_the_game_and_is_not_filled(self):
        kicks = certain_kicks()
        kicks['field_goal']['20-29'] = (5, 5)  # 10 attempts, below the floor
        record = gs.play_game(1, StaticPool('field_goal_attempt', 0, 20), kickoff_pool(spot=25), kicks,
                              winner_choice='receive')
        self.assertEqual(record['status'], 'blocked')
        self.assertEqual(record['blocker'], 'thin_kick_cell:field_goal:20-29')
        self.assertFalse(record['valid_full_game'])
        gs.validate_game(record)

    def test_halftime_ends_the_first_half_and_the_second_half_kickoff_is_generated(self):
        # Each play runs 450 seconds, so Q1 and then Q2 expire inside the same drive. The drive ends at halftime.
        record = gs.play_game(1, StaticPool('run', 10, 450), kickoff_pool(), certain_kicks(), winner_choice='receive',
                              max_drives=3)
        self.assertIn('halftime', [d['terminal'] for d in record['drives']])
        half = [k for k in record['kickoffs'] if k['kind'] == 'half_start']
        self.assertEqual(sorted(k['quarter'] for k in half), [1, 3])
        self.assertEqual(half[1]['kicking_team'], record['ledger']['winner'])
        gs.validate_game(record)


class ProfileId(unittest.TestCase):
    def test_each_drive_passes_an_e2_profile_id_to_e1(self):
        # E1 emits play ids as <simulation_id>:<sequence>. E2 passes its own profile id, one per drive.
        record, calls = spy_simulate(lambda: gs.play_game(
            3, StaticPool('run', 10, 30), kickoff_pool(), certain_kicks(), winner_choice='receive', max_drives=2))
        ids = [c['simulation_id'] for c in calls]
        self.assertEqual(ids[0], 'e2-3-drive1')
        self.assertTrue(all(s.startswith('e2-3-drive') for s in ids), ids)


def _empty_e1_pool():
    return StaticPool('run', 0, 1)


if __name__ == '__main__':
    unittest.main()
