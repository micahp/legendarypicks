"""Provider-to-ESPN proposals: one candidate proposes, zero or several go to review."""
import unittest

import provider_espn_crosswalk as cw

FINALS = [
    {"game_id": "185375", "home": "Maja Chwalinska", "away": "Sonay Kartal"},
    {"game_id": "185369", "home": "Ann Li", "away": "Iga Swiatek"},
    {"game_id": "184947", "home": "Alejandro Davidovich Fokina", "away": "Rafael Jodar"},
]


class CrosswalkTest(unittest.TestCase):
    def test_a_365scores_slug_proposes_its_one_espn_final(self):
        url = ("https://www.365scores.com/en-us/tennis/match/wuhan-6177/"
               "maja-chwalinska-sonay-kartal-67712-68117-6177#id=4877964")
        result = cw.link_provider_match(url, FINALS)
        self.assertEqual((result["status"], result["espn_game_id"]), ("proposed", "185375"))

    def test_a_tennis24_slug_proposes_its_one_espn_final(self):
        url = ("https://www.tennis24.com/match/chwalinska-maja-OIxOD54s/kartal-sonay-nFb01JTe/?mid=UyZvIQm2")
        result = cw.link_provider_match(url, FINALS)
        self.assertEqual((result["status"], result["espn_game_id"]), ("proposed", "185375"))

    def test_compound_surnames_match_on_the_last_word(self):
        url = "https://www.365scores.com/en-us/tennis/match/shanghai/alejandro-davidovich-fokina-rafael-jodar-1#id=9"
        result = cw.link_provider_match(url, FINALS)
        self.assertEqual(result["espn_game_id"], "184947")

    def test_no_espn_final_with_both_surnames_goes_to_review(self):
        url = "https://www.365scores.com/en-us/tennis/match/wuhan-6177/aryna-sabalenka-iga-swiatek-9#id=7"
        result = cw.link_provider_match(url, FINALS)
        self.assertEqual((result["status"], result["espn_game_id"], result["candidates"]), ("review", None, []))

    def test_two_espn_finals_with_the_same_pair_go_to_review(self):
        finals = FINALS + [{"game_id": "999", "home": "Sonay Kartal", "away": "Maja Chwalinska"}]
        url = "https://www.365scores.com/en-us/tennis/match/wuhan-6177/maja-chwalinska-sonay-kartal-1#id=2"
        result = cw.link_provider_match(url, finals)
        self.assertEqual(result["status"], "review")
        self.assertEqual(sorted(result["candidates"]), ["185375", "999"])


if __name__ == "__main__":
    import unittest as u
    u.main()
