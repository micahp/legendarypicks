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


class StrictTranslation(unittest.TestCase):
    def test_the_two_vocabularies_differ_only_by_the_rams_and_washington(self):
        self.assertEqual(len(teams.DB_CODES), 32)
        self.assertEqual(len(teams.NFLVERSE_CODES), 32)
        self.assertEqual(teams.DB_CODES - teams.NFLVERSE_CODES, {'LAR', 'WSH'})
        self.assertEqual(teams.NFLVERSE_CODES - teams.DB_CODES, {'LA', 'WAS'})

    def test_every_known_spelling_round_trips_through_both_vocabularies(self):
        for code in teams.TO_DB:
            with self.subTest(code=code):
                self.assertIn(teams.to_db(code), teams.DB_CODES)
                self.assertIn(teams.to_nflverse(code), teams.NFLVERSE_CODES)
                self.assertEqual(teams.to_db(teams.to_nflverse(code)), teams.to_db(code))

    def test_relocated_clubs_map_to_the_current_club(self):
        self.assertEqual([teams.to_db(c) for c in ('STL', 'OAK', 'SD', 'la', ' was ')], ['LAR', 'LV', 'LAC', 'LAR', 'WSH'])

    def test_an_unknown_code_or_a_null_raises_instead_of_passing_through(self):
        for bad in ('XYZ', None, '', 'LOS'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                teams.to_db(bad)

    def test_a_column_fails_whole_and_names_every_unknown_code(self):
        with self.assertRaises(ValueError) as caught:
            teams.convert(['LA', 'XYZ', 'XYZ', None], to='db')
        self.assertIn("'XYZ': 2", str(caught.exception))
        self.assertIn('None: 1', str(caught.exception))

    def test_game_ids_carry_nflverse_codes_and_convert_to_either_side(self):
        self.assertEqual(teams.teams_from_game_id('2026_08_LAC_LA'), ('LAC', 'LAR'))
        self.assertEqual(teams.teams_from_game_id('2026_04_IND_WAS', to='nflverse'), ('IND', 'WAS'))
        with self.assertRaises(ValueError):
            teams.teams_from_game_id('2026_08_LAC')

    def test_a_frame_is_converted_in_a_copy(self):
        import pandas as pd
        frame = pd.DataFrame({'team': ['LA', 'WAS', 'KC'], 'opponent': ['WSH', 'LAR', 'LV']})
        out = teams.normalize_frame(frame, ['team', 'opponent'], to='nflverse')
        self.assertEqual(out['team'].tolist(), ['LA', 'WAS', 'KC'])
        self.assertEqual(out['opponent'].tolist(), ['WAS', 'LA', 'LV'])
        self.assertEqual(frame['opponent'].tolist(), ['WSH', 'LAR', 'LV'])


if __name__ == '__main__':
    unittest.main()
