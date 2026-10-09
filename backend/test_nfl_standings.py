"""Tests for nfl_standings.py with hand-worked values.

Five teams, six games. Every expected number below is worked out on paper from those games.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_standings as st  # noqa: E402

MAP = {"AAA": ("NFC", "NFC East"), "BBB": ("NFC", "NFC East"), "CCC": ("NFC", "NFC West"),
       "DDD": ("NFC", "NFC West"), "EEE": ("AFC", "AFC North")}
GAMES = [
    (1, "AAA", "BBB", 20, 10),   # A beats B
    (2, "CCC", "AAA", 14, 17),   # A beats C (away)
    (3, "BBB", "CCC", 21, 7),    # B beats C
    (4, "DDD", "AAA", 3, 10),    # A beats D (away)
    (5, "EEE", "AAA", 20, 14),   # A loses to E
    (6, "BBB", "EEE", 10, 7),    # B beats E
]


def teams(games=GAMES, through=None):
    return st.build(MAP, games, through_week=through)


class Records(unittest.TestCase):
    def test_overall_and_division_and_conference(self):
        t = teams()
        self.assertEqual(t["AAA"].record(), (3, 1, 0))
        self.assertEqual(st.division_record(t["AAA"], t), (1, 0, 0))   # beat B
        self.assertEqual(st.conference_record(t["AAA"], t), (3, 0, 0))  # lost only to AFC E
        self.assertEqual(t["BBB"].record(), (2, 1, 0))
        self.assertEqual(st.division_record(t["BBB"], t), (0, 1, 0))    # lost to A

    def test_through_week_cuts_later_games(self):
        t = teams(through=3)
        self.assertEqual(t["AAA"].record(), (2, 0, 0))  # wins in weeks 1 and 2; the loss is week 5

    def test_tie_counts_half_in_pct(self):
        games = [(1, "AAA", "BBB", 10, 10)]
        t = teams(games)
        self.assertEqual(t["AAA"].record(), (0, 0, 1))
        self.assertAlmostEqual(t["AAA"].pct, 0.5)

    def test_unknown_team_is_refused(self):
        with self.assertRaises(KeyError):
            teams([(1, "AAA", "ZZZ", 1, 2)])


class HeadToHead(unittest.TestCase):
    def test_head_to_head_is_from_a_side(self):
        t = teams()
        self.assertEqual(st.head_to_head(t["AAA"], t["BBB"]), (1, 0, 0))
        self.assertEqual(st.head_to_head(t["BBB"], t["AAA"]), (0, 1, 0))

    def test_never_played_is_none(self):
        t = teams()
        self.assertIsNone(st.head_to_head(t["DDD"], t["EEE"]))


class CommonGames(unittest.TestCase):
    def test_fewer_than_four_common_opponents_is_none(self):
        t = teams()
        # A and B share only C and E.
        self.assertIsNone(st.common_games_record(t["AAA"], t["BBB"], t))

    def test_three_common_opponents_is_still_refused(self):
        # Give B games against A's other opponents so they share four.
        games = GAMES + [(7, "BBB", "DDD", 9, 3), (8, "DDD", "CCC", 10, 2),
                         (9, "BBB", "AAA", 1, 2)]
        t = teams(games)
        common = st.common_opponents(t["AAA"], t["BBB"])
        # A played B, C, D, E; B played A, C, E, D. Common: C, D, E. Three is below the minimum.
        self.assertEqual(common, {"CCC", "DDD", "EEE"})
        self.assertIsNone(st.common_games_record(t["AAA"], t["BBB"], t))


class Strength(unittest.TestCase):
    def test_strength_of_victory_excludes_games_against_the_team(self):
        # A beat B, C, D. Excluding games against A:
        #   B: beat C and E, so 2-0 -> 1.0 ; C: beat only nobody, lost to B -> 0-1 -> 0.0
        #   D: no games left -> 0.0. SOV = (1 + 0 + 0) / 3 = 1/3.
        t = teams()
        self.assertAlmostEqual(st.strength_of_victory(t["AAA"], t), 1.0 / 3.0, places=12)

    def test_strength_of_schedule_excludes_games_against_the_team(self):
        # A's opponents: B (1.0 excluding A), C (0.0), D (0.0), E (0-1 excluding A -> 0.0).
        # SOS = 1 / 4.
        t = teams()
        self.assertAlmostEqual(st.strength_of_schedule(t["AAA"], t), 0.25, places=12)


if __name__ == "__main__":
    unittest.main()
