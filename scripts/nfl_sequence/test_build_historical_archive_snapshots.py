import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_historical_archive_snapshots as builder  # noqa: E402


class VerifiedIdentityNameVariants(unittest.TestCase):
    def test_exact_reviewed_variant_is_allowed_only_for_its_stable_id(self):
        self.assertTrue(builder._identity_name_matches('00-0035118', 'Matt Orzech', 'Matthew Orzech'))
        self.assertTrue(builder._identity_name_matches('00-0035118', 'Matthew Orzech', 'Matt Orzech'))
        self.assertTrue(builder._identity_name_matches('00-0037743', 'Dax Hill', 'Daxton Hill'))
        self.assertTrue(builder._identity_name_matches('00-0036642', 'T.J. Slaton Jr.', 'Tedarrell Slaton'))
        self.assertFalse(builder._identity_name_matches('00-0000000', 'Matt Orzech', 'Matthew Orzech'))
        self.assertFalse(builder._identity_name_matches('00-0035118', 'Matt Jones', 'Matthew Orzech'))

    def test_normalized_equal_names_still_require_a_stable_id_join(self):
        self.assertTrue(builder._identity_name_matches('00-0000000', 'K. Williams Jr.', 'K. Williams'))


if __name__ == '__main__':
    unittest.main()
