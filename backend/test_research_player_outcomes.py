"""Verified outcomes: name rule for official pages, official tier matching, and the orientation rule."""
import unittest

import research_player_outcomes as rpo


class NameRuleTest(unittest.TestCase):
    def test_order_insensitive(self):
        self.assertTrue(rpo.same_person("Zhang Zhizhen", "Zhizhen Zhang"))

    def test_shorter_legal_name_inside_longer_with_same_surname(self):
        self.assertTrue(rpo.same_person("Coleman Wong", "Chak Lam Coleman Wong"))

    def test_same_surname_different_person_does_not_match(self):
        self.assertFalse(rpo.same_person("Gael Monfils", "Elina Monfils"))

    def test_different_surname_does_not_match(self):
        self.assertFalse(rpo.same_person("Ann Li", "Iga Swiatek"))


class OfficialMatchingTest(unittest.TestCase):
    GAMES = {
        "184947": {"league": "atp", "status": "Final",
                   "home": {"name": "Alejandro Davidovich Fokina"}, "away": {"name": "Rafael Jodar"}},
        "184848": {"league": "atp", "status": "Final",
                   "home": {"name": "Chak Lam Coleman Wong"}, "away": {"name": "Cruz Hewitt"}},
    }

    def test_an_official_page_maps_to_its_one_game_by_names(self):
        page = {"names": ["Alejandro Davidovich Fokina", "Rafael Jodar"], "parse_status": "ok", "url": "ms001"}
        self.assertEqual(list(rpo.official_by_game([page], self.GAMES)), ["184947"])

    def test_a_short_official_name_still_maps(self):
        page = {"names": ["Coleman Wong", "Cruz Hewitt"], "parse_status": "ok", "url": "ms066"}
        self.assertEqual(list(rpo.official_by_game([page], self.GAMES)), ["184848"])

    def test_a_page_that_does_not_parse_is_not_used(self):
        page = {"names": ["Alejandro Davidovich Fokina", "Rafael Jodar"], "parse_status": "no_stats"}
        self.assertEqual(rpo.official_by_game([page], self.GAMES), {})


if __name__ == "__main__":
    import unittest as u
    u.main()
