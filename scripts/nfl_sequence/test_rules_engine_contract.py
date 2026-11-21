"""Shared rules-engine contract: frozen V1.6 rules against the corrected rules, and the policy each run records.

The corrected rules and the frozen rules must agree everywhere except a loss past the own goal line. Off that line the
two modes are the same function, so a score change between them can only come from the own-end-zone rule.

Run: PYTHONPATH=scripts/nfl_sequence python3 -m unittest scripts/nfl_sequence/test_rules_engine_contract.py
"""
import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reducer  # noqa: E402
import simulate_pregame_batch as batch  # noqa: E402


def cli(profile='custom', own_end_zone=None, geometry_filter=None, recovery_model=None):
    return batch.apply_rules_defaults(argparse.Namespace(slc_profile=profile, own_end_zone=own_end_zone,
                                                         geometry_filter=geometry_filter,
                                                         recovery_model=recovery_model))


def state(yl):
    return {'quarter': 2, 'clock': 74, 'offense': 'A', 'defense': 'B', 'down': 1, 'togo': 10, 'yl': yl, 'dir': 1}


def outcome(st, event, yards, own_end_zone):
    try:
        return reducer.apply_play(st, event, yards, 25, own_end_zone=own_end_zone)
    except (ValueError, reducer.UnmodelledOutcome) as refused:
        return type(refused), str(refused)


class RulesEnginePolicy(unittest.TestCase):
    def test_refuse_is_the_frozen_v16_rule(self):
        manifest = reducer.rules_engine_manifest('refuse', False, False)
        self.assertEqual(manifest['policy'], 'frozen_refuse')
        self.assertEqual(manifest['schema'], reducer.RULES_ENGINE_SCHEMA)

    def test_refuse_with_the_geometry_filter_is_a_different_policy(self):
        manifest = reducer.rules_engine_manifest('refuse', False, True)
        self.assertEqual(manifest['policy'], 'frozen_refuse_geometry_filtered')
        self.assertNotEqual(manifest['policy'], reducer.rules_engine_manifest('refuse', False, False)['policy'])

    def test_resolve_without_a_recovery_model_halts_the_unmodelled_fumbles(self):
        manifest = reducer.rules_engine_manifest('resolve', False, True)
        self.assertEqual(manifest['policy'], 'resolve_unmodelled_fumbles_halt')
        self.assertTrue(manifest['geometry_filter'])
        self.assertFalse(manifest['recovery_model'])

    def test_resolve_with_the_recovery_model_is_named_separately(self):
        self.assertEqual(reducer.rules_engine_manifest('resolve', True, True)['policy'],
                         'resolve_with_recovery_model')

    def test_resolve_needs_the_geometry_filter(self):
        with self.assertRaises(ValueError):
            reducer.rules_engine_manifest('resolve', False, False)

    def test_the_recovery_model_needs_resolve(self):
        with self.assertRaises(ValueError):
            reducer.rules_engine_manifest('refuse', True, True)

    def test_an_unknown_own_end_zone_rule_is_refused(self):
        with self.assertRaises(ValueError):
            reducer.rules_engine_manifest('guess', False, True)


class FrozenAndCorrectedAgreeOffTheOwnGoalLine(unittest.TestCase):
    def test_every_play_that_does_not_cross_the_own_goal_line_is_the_same_under_both_rules(self):
        checked = 0
        for yl in range(1, 100):
            for event, yards in (('run', 3), ('run', -4), ('pass_complete', 6), ('pass_incomplete', 0),
                                 ('sack', -3), ('fumble_lost', -2), ('sack_fumble_lost', -2), ('interception', 0)):
                if yards > yl or yl - yards > 100:
                    continue
                frozen = outcome(state(yl), event, yards, 'refuse')
                corrected = outcome(state(yl), event, yards, 'resolve')
                self.assertEqual(frozen, corrected, f'{event} {yards} from yl {yl}')
                checked += 1
        self.assertGreater(checked, 300)


class OwnEndZoneTransitions(unittest.TestCase):
    def test_a_tackle_past_the_own_goal_line_is_a_safety_only_under_the_corrected_rules(self):
        self.assertIs(outcome(state(99), 'run', -5, 'refuse')[0], ValueError)
        after, terminal, flags = reducer.apply_play(state(99), 'run', -5, own_end_zone='resolve')
        self.assertIsNone(after)
        self.assertEqual(terminal, 'safety')
        self.assertEqual(flags['scoring_team'], 'B')

    def test_a_run_fumble_past_the_own_goal_line_halts_under_the_corrected_rules(self):
        with self.assertRaises(reducer.UnmodelledOutcome) as halted:
            reducer.apply_play(state(99), 'fumble_lost', -5, 20, own_end_zone='resolve')
        self.assertEqual(halted.exception.reason, 'own_end_zone_fumble_recovery_unresolved')

    def test_a_sack_fumble_past_the_own_goal_line_halts_under_the_corrected_rules(self):
        with self.assertRaises(reducer.UnmodelledOutcome):
            reducer.apply_play(state(99), 'sack_fumble_lost', -5, 20, own_end_zone='resolve')

    def test_frozen_v16_still_credits_a_run_fumble_past_the_own_goal_line_as_a_turnover(self):
        # Known frozen V1.6 defect, pinned so it cannot change silently. The fix is only in the corrected rules.
        after, terminal, flags = reducer.apply_play(state(99), 'fumble_lost', -5, 20, own_end_zone='refuse')
        self.assertEqual(terminal, 'turnover')
        self.assertTrue(flags['turnover'])

    def test_frozen_v16_still_refuses_a_sack_fumble_past_the_own_goal_line(self):
        with self.assertRaises(ValueError):
            reducer.apply_play(state(99), 'sack_fumble_lost', -5, 20, own_end_zone='refuse')


class RulesDefaultsByProfile(unittest.TestCase):
    def test_frozen_v16_defaults_to_the_refusal_with_every_rules_flag_off(self):
        args = cli('v1_6_candidate')
        self.assertEqual((args.own_end_zone, args.geometry_filter, args.recovery_model), ('refuse', False, False))

    def test_v17_defaults_to_the_corrected_rules_with_the_recovery_model_on(self):
        args = cli('v1_7_candidate')
        self.assertEqual((args.own_end_zone, args.geometry_filter, args.recovery_model), ('resolve', True, True))

    def test_v17_can_turn_the_recovery_model_off_explicitly(self):
        args = cli('v1_7_candidate', recovery_model=False)
        self.assertEqual((args.own_end_zone, args.geometry_filter, args.recovery_model), ('resolve', True, False))

    def test_v17_refusing_its_own_end_zone_conflicts_with_its_recovery_model(self):
        with self.assertRaises(ValueError):
            cli('v1_7_candidate', own_end_zone='refuse')

    def test_the_recovery_flag_implies_resolve_and_the_geometry_filter_on_v16(self):
        args = cli('v1_6_candidate', recovery_model=True)
        self.assertEqual((args.own_end_zone, args.geometry_filter, args.recovery_model), ('resolve', True, True))

    def test_rules_fix_is_v16_with_resolve_and_the_geometry_filter_and_no_recovery_model(self):
        args = cli('v1_6_rules_fix')
        self.assertEqual(args.slc_profile, 'v1_6_candidate')
        self.assertEqual((args.own_end_zone, args.geometry_filter, args.recovery_model), ('resolve', True, False))
        self.assertEqual(reducer.rules_engine_manifest(args.own_end_zone, args.recovery_model,
                                                       args.geometry_filter)['policy'],
                         'resolve_unmodelled_fumbles_halt')

    def test_rules_fix_conflicts_are_refused(self):
        for kwargs in ({'own_end_zone': 'refuse'}, {'geometry_filter': False}, {'recovery_model': True}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                cli('v1_6_rules_fix', **kwargs)


if __name__ == '__main__':
    unittest.main()
