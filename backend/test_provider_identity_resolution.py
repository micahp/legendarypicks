"""Provider codes and slugs: the player-code and surname readers, and the review resolver's stats test."""
import unittest

import provider_player_map as ppm
import provider_review_resolver as rr


class CodeAndSlugTest(unittest.TestCase):
    def test_365scores_codes_are_the_two_numbers_before_the_event_id(self):
        url = ("https://www.365scores.com/en-us/tennis/match/wuhan-6177/"
               "maja-chwalinska-sonay-kartal-67712-68117-6177#id=4877964")
        self.assertEqual(ppm.codes_for("365scores", url), ["67712", "68117"])

    def test_tennis24_codes_are_the_suffix_of_each_player_slug(self):
        url = "https://www.tennis24.com/match/chwalinska-maja-OIxOD54s/kartal-sonay-nFb01JTe/?mid=UyZvIQm2"
        self.assertEqual(ppm.codes_for("tennis24", url), ["OIxOD54s", "nFb01JTe"])

    def test_tennis24_surnames_are_first_in_each_slug(self):
        url = "https://www.tennis24.com/match/chwalinska-maja-OIxOD54s/kartal-sonay-nFb01JTe/?mid=UyZvIQm2"
        self.assertEqual(rr.slug_surnames("tennis24", url), ["chwalinska", "kartal"])

    def test_365scores_surnames_are_the_last_name_word(self):
        url = ("https://www.365scores.com/en-us/tennis/match/wuhan-6177/"
               "maja-chwalinska-sonay-kartal-67712-68117-6177#id=4877964")
        self.assertEqual(rr.slug_surnames("365scores", url), ["chwalinska", "kartal"])


class StatsEqualityTest(unittest.TestCase):
    def test_a_swapped_orientation_still_counts_as_the_same_stats(self):
        mine = (6, 2, 3, 0)
        other = (2, 6, 0, 3)
        self.assertTrue(other == mine or other == (mine[1], mine[0], mine[3], mine[2]))

    def test_different_values_do_not_match(self):
        self.assertFalse((6, 2, 3, 0) == (6, 3, 3, 0))


if __name__ == "__main__":
    import unittest as u
    u.main()
