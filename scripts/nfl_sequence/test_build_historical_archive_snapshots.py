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
        self.assertTrue(builder._identity_name_matches('00-0036159', 'Josh Uche', 'Joshua Uche'))
        self.assertTrue(builder._identity_name_matches('00-0039156', 'JuJu Brents', 'Julius Brents'))
        variants = (
            ('00-0034413', 'Foyesade Oluokun', 'Foye Oluokun'),
            ('00-0036348', 'Joshua Metellus', 'Josh Metellus'),
            ('00-0036535', 'William Sherman', 'Will Sherman'),
            ('00-0036629', 'Cam Bynum', 'Camryn Bynum'),
            ('00-0036919', 'Kenny Gainwell', 'Kenneth Gainwell'),
            ('00-0037292', 'Drew Ogletree', 'Andrew Ogletree'),
            ('00-0037758', "Cor'Dale Flott", 'Cordale Flott'),
            ('00-0039176', 'CJ Okoye', 'Basil Okoye'),
            ('00-0039324', 'Chris Roland-Wallace', 'Christian Roland-Wallace'),
            ('00-0039422', 'Nate Thomas', 'Nathan Thomas'),
            ('00-0039790', 'Olu Fashanu', 'Olumuyiwa Fashanu'),
            ('00-0039821', 'Dru Phillips', 'Andru Phillips'),
            ('00-0040186', 'Kiko Mauigoa', 'Francisco Mauigoa'),
            ('00-0040744', 'Jaylahn Tuimoloau', 'JT Tuimoloau'),
        )
        for gsis_id, source, canonical in variants:
            with self.subTest(gsis_id=gsis_id):
                self.assertTrue(builder._identity_name_matches(gsis_id, source, canonical))
        self.assertTrue(builder._identity_name_matches('00-0039373', 'Audric Estime', 'Audric Estimé'))
        self.assertFalse(builder._identity_name_matches('00-0000000', 'Matt Orzech', 'Matthew Orzech'))
        self.assertFalse(builder._identity_name_matches('00-0035118', 'Matt Jones', 'Matthew Orzech'))
        self.assertFalse(builder._identity_name_matches('00-0000000', 'Josh Uche', 'Joshua Uche'))

    def test_normalized_equal_names_still_require_a_stable_id_join(self):
        self.assertTrue(builder._identity_name_matches('00-0000000', 'K. Williams Jr.', 'K. Williams'))
        self.assertTrue(builder._identity_name_matches('00-0038642', 'DJ Ivey', 'D.J. Ivey'))
        self.assertTrue(builder._identity_name_matches('00-0038642', 'D.J. Ivey', 'DJ Ivey'))


class DefensiveFrontFallback(unittest.TestCase):
    def test_missing_interior_starter_uses_unreserved_eligible_front_backup(self):
        expected = {('Base 4-3 D', 'LDT', 1), ('Base 4-3 D', 'RDT', 1)}
        players = [
            {'gsis_id': 'sieler', 'group': 'Base 4-3 D', 'pos_abb': 'RDT', 'pos_rank': 1,
             'unit': 'defense', 'roster_eligible': True, 'starter': False},
            {'gsis_id': 'biggers', 'group': 'Base 4-3 D', 'pos_abb': 'RDT', 'pos_rank': 2,
             'unit': 'defense', 'roster_eligible': True, 'starter': False},
        ]
        chosen = builder._cross_role_front_backup(players, group='Base 4-3 D', pos='LDT',
                                                  expected_roles=expected, game_id='test', team='MIA')
        self.assertEqual(chosen['gsis_id'], 'biggers')

    def test_fallback_fails_when_no_eligible_compatible_front_backup_exists(self):
        players = [{'gsis_id': 'edge', 'group': 'Base 4-3 D', 'pos_abb': 'RDE', 'pos_rank': 2,
                    'unit': 'defense', 'roster_eligible': True, 'starter': False}]
        with self.assertRaisesRegex(ValueError, 'no eligible compatible defensive-front backup'):
            builder._cross_role_front_backup(players, group='Base 4-3 D', pos='LDT',
                                             expected_roles={('Base 4-3 D', 'LDT', 1)},
                                             game_id='test', team='MIA')


if __name__ == '__main__':
    unittest.main()
