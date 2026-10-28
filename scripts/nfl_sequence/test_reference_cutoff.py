import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402

KNOWN_UNSAFE = {'blocked_kicks', 'safety_kicks', 'overtime_drives', 'try_fallback', 'overtime_choice_model', 'kick_table',
                'missed_field_goal_pool', 'play_extras', 'position_usage'}


class HistoricalCutoffRefusesUnsafeSources(unittest.TestCase):
    def test_a_historical_cutoff_is_refused_and_names_every_unsafe_source(self):
        with self.assertRaises(ValueError) as caught:
            er.load(eligible_before=(2024, 8))
        message = str(caught.exception)
        self.assertIn('historical cutoff refused', message)
        for name in KNOWN_UNSAFE:
            self.assertIn(name, message)

    def test_the_unsafe_list_covers_every_known_special_teams_and_participant_source(self):
        self.assertEqual(set(er.COHORT_UNSAFE_SOURCES), KNOWN_UNSAFE)

    def test_every_listed_source_states_why_it_is_unsafe(self):
        for name, reason in er.COHORT_UNSAFE_SOURCES.items():
            self.assertTrue(reason.strip(), name)


if __name__ == '__main__':
    unittest.main()
