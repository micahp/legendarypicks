import unittest

from build_verified_penalty_opportunities import gamebook_blocks, norm


class OfficialGamebookExtractionTests(unittest.TestCase):
    def test_play_boundaries_and_multiple_penalty_lines(self):
        text = '''Play By Play  First Quarter
  3-6-TB 35     (12:54) J.Goff pass incomplete.
                 PENALTY on TB-J.Player, Illegal Contact, enforced - No Play.
                 Penalty on TB-A.Other, Defensive Holding, declined.
  1-10-TB 30    (12:47) J.Gibbs left tackle for 3 yards.
Timeout at 12:40.
'''
        rows = gamebook_blocks(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]['qtr'], rows[0]['down'], rows[0]['to_go'], rows[0]['field_team'], rows[0]['field_number']),
                         (1, 3, '6', 'TB', 35))
        self.assertIn('declined', rows[0]['text'])
        self.assertNotIn('Timeout', rows[1]['text'])

    def test_nflverse_jersey_numbers_do_not_prevent_matching(self):
        self.assertEqual(norm('(12:54) 16-J.Goff pass to 11-K.Raymond.'),
                         norm('(12:54) J.Goff pass to K.Raymond.'))

    def test_gamebook_first_down_marker_does_not_hide_declined_foul(self):
        source = 'J.Goff pass complete. Penalty on TB-J.Player, Defensive Holding, declined.'
        official = 'J.Goff pass complete. P1 Penalty on TB-J.Player, Defensive Holding, declined.'
        self.assertEqual(norm(source), norm(official))


if __name__ == '__main__':
    unittest.main()
