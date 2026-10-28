import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e2_reference as er  # noqa: E402


class CutoffGuard(unittest.TestCase):
    def test_a_listed_source_refuses_a_historical_cutoff_and_is_named(self):
        with mock.patch.dict(er.COHORT_UNSAFE_SOURCES, {'safety_kicks': 'test-only entry'}, clear=True):
            with self.assertRaises(ValueError) as caught:
                er.refuse_unsafe_cutoff((2024, 8))
        self.assertIn('historical cutoff refused', str(caught.exception))
        self.assertIn('safety_kicks', str(caught.exception))

    def test_with_no_listed_source_a_historical_cutoff_is_not_refused(self):
        with mock.patch.dict(er.COHORT_UNSAFE_SOURCES, {}, clear=True):
            er.refuse_unsafe_cutoff((2024, 8))

    def test_no_cutoff_is_never_refused(self):
        with mock.patch.dict(er.COHORT_UNSAFE_SOURCES, {'safety_kicks': 'test-only entry'}, clear=True):
            er.refuse_unsafe_cutoff(None)

    def test_every_listed_source_states_why_it_is_unsafe(self):
        for name, reason in er.COHORT_UNSAFE_SOURCES.items():
            self.assertTrue(reason.strip(), name)


if __name__ == '__main__':
    unittest.main()
