"""Directional NFL team-code normalization tests."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import nfl_team_codes as teams  # noqa: E402


class TeamCodeDirections(unittest.TestCase):
    def test_pbp_codes_are_canonicalized_from_known_source_aliases(self):
        for source, expected in (
            ('LA', 'LAR'), ('LAR', 'LAR'), ('WAS', 'WSH'), ('WSH', 'WSH'),
            ('JAC', 'JAX'), ('JAX', 'JAX'), ('LV', 'LV'), (None, None),
        ):
            with self.subTest(source=source):
                self.assertEqual(teams.to_pbp_team_code(source), expected)

    def test_nflverse_codes_use_the_source_specific_reverse_alias(self):
        for source, expected in (
            ('LAR', 'LA'), ('LA', 'LA'), ('WSH', 'WAS'), ('WAS', 'WAS'),
            ('JAC', 'JAX'), ('JAX', 'JAX'), ('LV', 'LV'), (None, None),
        ):
            with self.subTest(source=source):
                self.assertEqual(teams.to_nflverse_team_code(source), expected)

    def test_legacy_franchise_codes_collapse_only_in_identity_comparisons(self):
        for source, expected in (
            ('OAK', 'LV'), ('LV', 'LV'), ('LA', 'LAR'), ('LAR', 'LAR'),
            ('WAS', 'WSH'), ('WSH', 'WSH'), ('JAC', 'JAX'), ('JAX', 'JAX'),
        ):
            with self.subTest(source=source):
                self.assertEqual(teams.canonical_franchise_team_code(source), expected)

    def test_coverage_checks_normalize_required_and_available_codes(self):
        self.assertEqual(teams.missing_pbp_team_codes(('LA', 'WAS'), ('LAR', 'WSH')), [])
        self.assertEqual(teams.missing_pbp_team_codes(('LA', 'XYZ'), ('LAR',)), ['XYZ'])


if __name__ == '__main__':
    unittest.main()
