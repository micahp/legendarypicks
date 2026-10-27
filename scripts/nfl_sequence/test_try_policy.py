"""Tests for the two-point decision policy: period cells, shrinkage, thin-cell fallback, the committed situation fixture, and
the opt-in path through a game. Run: python3 -m unittest scripts/nfl_sequence/test_try_policy.py
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_state as gs  # noqa: E402
import try_policy as tp  # noqa: E402
from test_game_state import StaticPool, certain_kicks, kickoff_pool  # noqa: E402


def row(two, margin, period, opening=0, first=0, season_type='REG'):
    return {'season_type': season_type, 'two': two, 'margin': margin, 'period': period, 'opening_drive': opening,
            'first_td': first}


class PeriodCells(unittest.TestCase):
    def test_periods_match_the_five_minute_split(self):
        self.assertEqual(tp.period_of(1, 900), 'H1')
        self.assertEqual(tp.period_of(2, 10), 'H1')
        self.assertEqual(tp.period_of(3, 0), 'Q3')
        self.assertEqual(tp.period_of(4, 301), 'Q4_gt5')
        self.assertEqual(tp.period_of(4, 300), 'Q4_le5')
        self.assertEqual(tp.period_of(4, 0), 'Q4_le5')
        self.assertEqual(tp.period_of(5, 100), 'OT')


class Shrinkage(unittest.TestCase):
    def setUp(self):
        rows = ([row(1, 0, 'H1')] * 4 + [row(0, 0, 'H1')] * 36       # 4 of 40 tied, first half, not opening
                + [row(1, 1, 'H1')] * 12 + [row(0, 1, 'H1')] * 48      # 12 of 60 up 1, first half, not opening
                + [row(0, 0, 'Q3')] * 20                                # 0 of 20 tied, Q3, not opening
                + [row(0, 0, 'H1', opening=1)] * 20)                    # 0 of 20 tied, first half, opening
        self.policy = tp.TryPolicy(rows, structure='margin_period_opening', k=25)
        self.league = 16 / 140
        self.opening0 = (16 + 25 * self.league) / (120 + 25)            # not opening: 16 of 120
        self.opening0_h1 = (16 + 25 * self.opening0) / (100 + 25)       # not opening, first half: 16 of 100
        self.opening1 = (0 + 25 * self.league) / (20 + 25)              # opening: 0 of 20

    def test_cell_shrinks_through_each_level(self):
        tied_h1 = (4 + 25 * self.opening0_h1) / (40 + 25)               # tied, not opening, first half: 4 of 40
        self.assertAlmostEqual(self.policy.p_two(0, 2, 600, 0, 0), tied_h1, places=12)

    def test_unseen_margin_takes_its_parent(self):
        self.assertAlmostEqual(self.policy.p_two(5, 2, 600, 0, 0), self.opening0_h1, places=12)

    def test_unseen_period_takes_the_opening_flag_rate(self):
        self.assertAlmostEqual(self.policy.p_two(0, 4, 100, 0, 0), self.opening0, places=12)

    def test_opening_period_without_tries_takes_the_flag_rate_not_the_league(self):
        p = self.policy.p_two(0, 3, 600, 1, 0)                          # opening, Q3: no tries
        self.assertAlmostEqual(p, self.opening1, places=12)
        self.assertNotAlmostEqual(p, self.league, places=3)

    def test_constant_structure_is_the_league_rate(self):
        constant = tp.TryPolicy(self.policy_rows(), structure='constant')
        self.assertEqual(constant.p_two(0, 1, 900, 1, 1), constant.league_rate)

    def policy_rows(self):
        return [row(1, 0, 'H1')] * 4 + [row(0, 0, 'H1')] * 36

    def test_unknown_structure_is_refused(self):
        with self.assertRaises(ValueError):
            tp.TryPolicy(self.policy_rows(), structure='not_a_structure')


class Fixture(unittest.TestCase):
    def test_committed_fixture_matches_its_manifest_and_counts(self):
        rows, sha = tp.load_rows()
        manifest = json.loads(Path(str(tp.FIXTURE) + '.manifest.json').read_text())
        self.assertEqual(sha, manifest['output']['sha256'])
        reg = [r for r in rows if r['season_type'] == 'REG']
        self.assertEqual(len(reg), 5368)
        self.assertEqual(sum(r['two'] for r in reg), 509)
        self.assertEqual(len(rows) - len(reg), 287)

    def test_period_column_agrees_with_the_rule(self):
        rows, _ = tp.load_rows()
        for r in rows:
            self.assertEqual(tp.period_of(r['qtr'], r['clock']), r['period'], (r['game_id'], r['play_id']))

    def test_first_touchdown_on_the_opening_drive_is_rare_in_the_candidate(self):
        policy = tp.TryPolicy.from_fixture()
        self.assertLess(policy.p_two(0, 2, 600, 1, 1), 0.05)
        self.assertLess(policy.p_two(-8, 1, 600, 1, 1), 0.05)
        self.assertGreater(policy.p_two(-8, 4, 200, 0, 0), 0.3)

    def test_a_fixture_that_does_not_match_its_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / 'situation.csv'
            shutil.copy(tp.FIXTURE, csv_path)
            shutil.copy(str(tp.FIXTURE) + '.manifest.json', str(csv_path) + '.manifest.json')
            with csv_path.open('a') as f:
                f.write('\n')
            with self.assertRaises(ValueError):
                tp.load_rows(csv_path)


class Always:
    """A stand-in policy: the same two-point probability in every situation."""

    def __init__(self, p):
        self.p = p

    def p_two(self, **situation):
        self.seen = situation
        return self.p


def touchdown_reference(policy):
    kicks = certain_kicks()
    kicks['two_point'] = (60, 0)
    pool = StaticPool('run', 80, 20)
    return gs.Reference(pool, kickoff_pool(), kicks, {}, try_policy=policy)


class Game(unittest.TestCase):
    def first_touchdown(self, record):
        return next(d for d in record['drives'] if d.get('touchdown_scored_by'))

    def test_probability_one_goes_for_two_and_records_the_situation(self):
        policy = Always(1.0)
        record = gs.play_game(1, touchdown_reference(policy), winner_choice='receive', max_drives=1)
        drive = self.first_touchdown(record)
        self.assertEqual(drive['points_scored_on_drive']['try']['kind'], 'two_point')
        self.assertEqual(drive['try_policy']['kind'], 'two_point')
        self.assertEqual(drive['try_policy']['margin'], 6)
        self.assertEqual(drive['try_policy']['quarter'], 1)
        self.assertTrue(drive['try_policy']['opening_drive'])
        self.assertTrue(drive['try_policy']['first_td'])
        self.assertEqual(policy.seen['margin'], 6)

    def test_probability_zero_kicks_the_extra_point(self):
        record = gs.play_game(1, touchdown_reference(Always(0.0)), winner_choice='receive', max_drives=1)
        self.assertEqual(self.first_touchdown(record)['points_scored_on_drive']['try']['kind'], 'extra_point')

    def test_the_published_share_draws_the_same_kind_as_the_unconditional_policy(self):
        kicks = certain_kicks()
        kicks['two_point'] = (60, 0)
        kicks['extra_point'] = (60, 0)
        share = 60 / 120
        base = gs.Reference(StaticPool('run', 80, 20), kickoff_pool(), kicks, {})
        same = gs.Reference(StaticPool('run', 80, 20), kickoff_pool(), kicks, {}, try_policy=Always(share))
        for seed in range(1, 25):
            a = gs.play_game(seed, base, winner_choice='receive', max_drives=1)
            b = gs.play_game(seed, same, winner_choice='receive', max_drives=1)
            self.assertEqual(self.first_touchdown(a)['points_scored_on_drive']['try']['kind'],
                             self.first_touchdown(b)['points_scored_on_drive']['try']['kind'], seed)


if __name__ == '__main__':
    unittest.main()
