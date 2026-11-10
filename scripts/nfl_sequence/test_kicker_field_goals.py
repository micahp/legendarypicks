import random
import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import field_goal_feasibility as fg  # noqa: E402
import kicker_field_goals as kfg  # noqa: E402
import measure_kick_outcomes as mk  # noqa: E402
import slc_playcall as slc  # noqa: E402
from test_slc_blocker_resolution import layer, sample  # noqa: E402

TABLE = {'schema': kfg.SCHEMA, 'fit_seasons': [2024, 2025], 'sigma': 0.3, 'recency': 0.5,
         'kickers': {'K_GOOD': {'offset': 0.4, 'attempts': 120, 'career_long': 61}},
         'assignments': [[2026, 8, 'KC', 'K_GOOD'], [2026, 8, 'LA', 'K_ROOKIE']]}
MODEL = {'intercept': 1.0, 'distance_slope_per_10_yards': -1.0, 'distance_center_yards': 40.0,
         'max_observed_attempt_yards': 70, 'global_block_rate': 0.02, 'attempted_n': 100,
         'block_counts_by_distance': {'40.0': {'attempts': 100, 'blocked': 2}}}


def sampler_with_flag(flag=True):
    sampler = slc.PlayCallSampler(layer(-100.0), side_teams={'A': 'KC', 'B': 'LA'})
    sampler.blocker_fixes = frozenset({'long_field_goal_feasibility'})
    sampler.fg_ordinary_cutoff = 60.0
    sampler.field_goal_distance_model = MODEL
    if flag:
        sampler.fg_kicker = {'table': kfg.KickerTable(TABLE, 'test'), 'kickers': {'A': 'K_GOOD', 'B': 'K_ROOKIE'}}
    return sampler


def fourth_down_cell():
    """One 4th-and-10 cell (pool_key field 30-49): field goals from the 34, punts from the 47, runs from the 40.
    The kernel is 2 yards wide, so the runs sit 6 and 7 yards from the two snap spots the test draws from.
    The 20-29 rows are not in this cell: pool_key splits the 20s from the 30s and 40s."""
    rows = [sample('field_goal_attempt', index=i, play_type='field_goal', down=4, togo=10, yl=34) for i in range(10)]
    rows += [sample('punt', index=10 + i, play_type='punt', down=4, togo=10, yl=47) for i in range(10)]
    rows += [sample('run', index=20 + i, play_type='run', down=4, togo=10, yl=40, yards=2) for i in range(10)]
    return rows


class Feasibility(unittest.TestCase):
    def test_the_pinned_rule_is_unchanged(self):
        out = fg.evaluate(43)
        self.assertEqual((out['kick_distance_yards'], out['historical_ceiling_yards'], out['eligible']), (60, 70, True))
        self.assertNotIn('rule', out)
        self.assertEqual(fg.evaluate(53)['eligible'], True)
        self.assertEqual(fg.evaluate(54)['eligible'], False)
        self.assertEqual(fg.evaluate(55)['historical_bucket_kick_distance_range_yards'], '67+')

    def test_the_record_rule_adds_eighteen_and_stops_at_seventy_six(self):
        out = fg.evaluate(58, rule=fg.RECORD_RULE)
        self.assertEqual((out['kick_distance_yards'], out['eligible'], out['rule']), (76, True, fg.RECORD_RULE))
        self.assertFalse(fg.evaluate(59, rule=fg.RECORD_RULE)['eligible'])

    def test_an_unknown_rule_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'unknown field-goal feasibility rule'):
            fg.evaluate(30, rule='sixty')


class KickDecision(unittest.TestCase):
    def draw(self, sampler, yl, n=60):
        state = {'quarter': 1, 'clock': 500, 'down': 4, 'togo': 10, 'yl': yl, 'score_diff': 0}
        return Counter(sampler.sample(random.Random(seed), fourth_down_cell(), 'A', 'B', state=state)[0]
                       for seed in range(n))

    def test_the_kick_follows_the_rows_near_the_snap_spot(self):
        sampler = sampler_with_flag()
        far = self.draw(sampler, 47)  # 65 yards: the rows at the 47 are punts
        self.assertEqual(far['field_goal_attempt'], 0)
        self.assertGreater(far['punt'], 55)
        near = self.draw(sampler, 34)  # 51 yards: the rows at the 34 are field goals
        self.assertGreater(near['field_goal_attempt'], 55)
        self.assertEqual(sampler.decisions[-1]['fg_rule'], fg.RECORD_RULE)
        self.assertEqual(sampler.decisions[-1]['fg_kicker'], 'K_GOOD')

    def test_flag_off_keeps_the_whole_cell_share(self):
        sampler = sampler_with_flag(flag=False)
        near = self.draw(sampler, 34)  # the cell's share: two thirds kicks, half of them field goals
        self.assertGreater(near['run'], 5)
        self.assertGreater(near['punt'], 5)
        self.assertNotIn('fg_rule', sampler.decisions[-1])

    def test_beyond_the_record_no_field_goal(self):
        sampler = sampler_with_flag()
        allowed, rejected, exception = sampler._field_goal_actions(
            {'base': Counter({('kick', 'field_goal_attempt'): 1, ('kick', 'punt'): 1})},
            {'quarter': 2, 'clock': 5, 'yl': 59, 'score_diff': -21})
        self.assertEqual((allowed, rejected, exception), ({'punt'}, True, False))
        allowed, rejected, _ = sampler._field_goal_actions(
            {'base': Counter({('kick', 'field_goal_attempt'): 1, ('kick', 'punt'): 1})},
            {'quarter': 1, 'clock': 500, 'yl': 48, 'score_diff': 0})  # 66 yards, no 60-yard cutoff
        self.assertIn('field_goal_attempt', allowed)
        self.assertFalse(rejected)


class MakeProbability(unittest.TestCase):
    def test_the_offset_moves_the_league_curve(self):
        league = mk.field_goal_distribution(MODEL, 50)
        same = kfg.distribution(MODEL, 50, 0.0)
        self.assertAlmostEqual(same['made'], league['made'])
        self.assertAlmostEqual(same['blocked'], league['blocked'])
        better = kfg.distribution(MODEL, 50, 0.4)
        self.assertGreater(better['made'], league['made'])
        self.assertAlmostEqual(better['made'] + better['missed'] + better['blocked'], 1.0)

    def test_up_to_the_record_beyond_the_observed_maximum(self):
        self.assertGreater(kfg.distribution(MODEL, 74, 0.0)['made'], 0.0)
        with self.assertRaisesRegex(ValueError, 'record ceiling'):
            kfg.distribution(MODEL, 77, 0.0)

    def test_the_sampler_uses_the_offense_kicker(self):
        sampler = sampler_with_flag()
        _r, good = sampler._field_goal_probability_result(55, random.Random(1), 'A')
        _r, rookie = sampler._field_goal_probability_result(55, random.Random(1), 'B')
        self.assertEqual((good['kicker'], good['fallback_level']), ('K_GOOD', 'kicker_logit_offset'))
        self.assertEqual((rookie['kicker'], rookie['fallback_level']), ('K_ROOKIE', 'league_curve_no_kicker_history'))
        self.assertGreater(good['made'], rookie['made'])


class Table(unittest.TestCase):
    def test_v2_pinned_table_has_week_9_kickers(self):
        import simulate_pregame_batch as batch
        repo = HERE.parents[1]
        path, sha = batch.SLC_V2_TABLES['playcall_fg_kicker']
        table = kfg.KickerTable.load(repo / path, sha)
        self.assertTrue(table.kicker(2026, 9, 'BUF'))
        self.assertTrue(table.kicker(2026, 9, 'MIN'))

    def test_a_team_without_an_active_kicker_is_refused(self):
        table = kfg.KickerTable(TABLE, 'test')
        self.assertEqual(table.kicker(2026, 8, 'KC'), 'K_GOOD')
        with self.assertRaisesRegex(ValueError, 'no active kicker'):
            table.kicker(2026, 9, 'KC')

    def test_either_spelling_finds_the_club(self):
        table = kfg.KickerTable(TABLE, 'test')
        self.assertEqual(table.kicker(2026, 8, 'LAR'), 'K_ROOKIE')  # the table says LA, the engine asks LAR
        self.assertEqual(table.kicker(2026, 8, 'LA'), 'K_ROOKIE')
        with self.assertRaisesRegex(ValueError, 'unknown NFL team code'):
            table.kicker(2026, 8, 'XYZ')

    def test_the_pinned_table_answers_the_database_codes(self):
        # 2026-11-04: 15 Rams and Washington games failed here, the table spelling LA/WAS and the engine LAR/WSH.
        import simulate_pregame_batch as batch
        path, sha = batch.SLC_V2_TABLES['playcall_fg_kicker']
        table = kfg.KickerTable.load(HERE.parents[1] / path, sha)
        for team in ('LAR', 'WSH', 'LA', 'WAS'):
            with self.subTest(team=team):
                self.assertTrue(table.kicker(2026, 1, team))

    def test_a_wrong_schema_or_hash_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'schema'):
            kfg.KickerTable(dict(TABLE, schema='old'), 'test')
        path = HERE.parents[1] / 'docs/research/fg-kicker-2026-11-04/kicker_table_through_2025_assign_2026.json'
        with self.assertRaisesRegex(ValueError, 'sha256'):
            kfg.KickerTable.load(path, '0' * 64)


if __name__ == '__main__':
    unittest.main()
