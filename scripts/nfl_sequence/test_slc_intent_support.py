"""Regression tests for V1.6's bounded fourth-down historical-support guard."""
import unittest

import slc_intent_support as guard


class FourthDownSupportGuard(unittest.TestCase):
    def test_repro_ari_dal_seed_one_unsupported_run_cell(self):
        # Exact blocker was playcall_no_run_outcomes_in_cell:(4,'4-6','80-99').
        # The historical cell supports kicks and dropbacks but has no run.
        intent, reason = guard.resolve_fourth_down_intent('run', 4, {'dropback'}, enabled=True)
        self.assertEqual(intent, 'dropback')
        self.assertEqual(reason, 'unsupported_fourth_down_run_intent_resolved_to_dropback')

    def test_supported_run_is_not_rewritten(self):
        self.assertEqual(guard.resolve_fourth_down_intent(
            'run', 4, {'run', 'dropback'}, enabled=True), ('run', None))

    def test_unsupported_dropback_uses_supported_run(self):
        self.assertEqual(guard.resolve_fourth_down_intent(
            'dropback', 4, {'run'}, enabled=True),
            ('run', 'unsupported_fourth_down_dropback_intent_resolved_to_run'))

    def test_kick_policy_and_other_downs_are_unchanged(self):
        self.assertEqual(guard.resolve_fourth_down_intent(
            'kick', 4, {'dropback'}, enabled=True), ('kick', None))
        self.assertEqual(guard.resolve_fourth_down_intent(
            'run', 3, {'dropback'}, enabled=True), ('run', None))

    def test_frozen_profiles_keep_original_behavior(self):
        self.assertEqual(guard.resolve_fourth_down_intent(
            'run', 4, {'dropback'}, enabled=False), ('run', None))

    def test_no_historical_scrimmage_support_is_still_an_error_in_sampler(self):
        self.assertEqual(guard.resolve_fourth_down_intent(
            'run', 4, set(), enabled=True), ('run', None))


if __name__ == '__main__':
    unittest.main()
