import unittest

from event_expansion import EventExpansionSwitches, FROZEN_CONTROL


class EventExpansionSwitchesTest(unittest.TestCase):
    def test_frozen_control_has_every_expansion_disabled(self):
        self.assertEqual(FROZEN_CONTROL.enabled(), ())
        self.assertEqual(FROZEN_CONTROL.model_identity()['model_id'],
                         'slc-v2-week11-frozen+frozen-control')

    def test_mechanisms_are_independently_selectable(self):
        switches = EventExpansionSwitches.from_enabled(('interception_returns',))
        self.assertEqual(switches.enabled(), ('interception_returns',))
        self.assertFalse(switches.fumble_returns)
        self.assertFalse(switches.punt_return_events)

    def test_model_identity_is_stable_and_switch_sensitive(self):
        one = EventExpansionSwitches.from_enabled(('pre_snap_penalties',)).model_identity()
        same = EventExpansionSwitches.from_enabled(('pre_snap_penalties',)).model_identity()
        two = EventExpansionSwitches.from_enabled(('live_ball_penalties',)).model_identity()
        self.assertEqual(one, same)
        self.assertNotEqual(one['config_sha256'], two['config_sha256'])

    def test_unknown_and_duplicate_switch_names_fail(self):
        with self.assertRaisesRegex(ValueError, 'unknown event expansion switch'):
            EventExpansionSwitches.from_enabled(('not_a_switch',))
        with self.assertRaisesRegex(ValueError, 'must be unique'):
            EventExpansionSwitches.from_enabled(('fumble_returns', 'fumble_returns'))

    def test_switch_values_must_be_booleans(self):
        with self.assertRaisesRegex(ValueError, 'must be boolean'):
            EventExpansionSwitches(interception_returns=1)


if __name__ == '__main__':
    unittest.main()
