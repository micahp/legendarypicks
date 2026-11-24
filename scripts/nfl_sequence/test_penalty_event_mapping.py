import unittest

from penalty_event_mapping import (PenaltyTypeMappingError, classify_penalty_type,
                                   nominal_yards_for)


class PenaltyEventMappingTests(unittest.TestCase):
    def test_maps_only_exact_known_source_labels(self):
        cases = (
            ('False Start', 'offense', 'false_start', 5),
            ('Delay of Game', 'offense', 'delay_of_game', 5),
            ('Defensive Offside', 'defense', 'offside', 5),
            ('Roughing the Passer', 'defense', 'roughing_passer', 15),
            ('Offensive Holding', 'offense', 'offensive_holding', 10),
        )
        for label, team, expected, yards in cases:
            with self.subTest(label=label):
                classified = classify_penalty_type(label, team)
                self.assertEqual(classified.penalty_type, expected)
                self.assertEqual(nominal_yards_for(classified), yards)

    def test_resolves_only_side_specific_generic_labels(self):
        self.assertEqual(classify_penalty_type('Holding', 'offense').penalty_type,
                         'offensive_holding')
        self.assertEqual(classify_penalty_type('Holding', 'defense').penalty_type,
                         'defensive_holding')
        self.assertEqual(classify_penalty_type('Pass Interference', 'defense').penalty_type,
                         'defensive_pass_interference')

    def test_spot_foul_uses_nominal_zero_yards_and_requires_the_separate_spot(self):
        classified = classify_penalty_type('Defensive Pass Interference', 'defense')
        self.assertEqual(nominal_yards_for(classified), 0)

    def test_block_foul_requires_subtype_and_maps_source_subtypes(self):
        above = classify_penalty_type('Illegal Block Above the Waist', 'offense')
        self.assertEqual((above.penalty_type, above.block_subtype),
                         ('illegal_block', 'above_waist'))
        self.assertEqual(nominal_yards_for(above), 10)
        back = classify_penalty_type('Illegal Block in the Back', 'offense')
        self.assertEqual(back.block_subtype, 'in_back')
        with self.assertRaisesRegex(PenaltyTypeMappingError,
                                    'illegal_block_requires_verified_subtype'):
            classify_penalty_type('Illegal Block', 'offense')

    def test_unmodeled_or_wrong_side_penalties_fail_by_name(self):
        with self.assertRaisesRegex(PenaltyTypeMappingError,
                                    'penalty_type_not_supported_by_v17_rules'):
            classify_penalty_type('Unnecessary Roughness', 'defense')
        with self.assertRaisesRegex(PenaltyTypeMappingError,
                                    'penalty_type_not_supported_by_v17_rules'):
            classify_penalty_type('Offside', 'offense')


if __name__ == '__main__':
    unittest.main()
