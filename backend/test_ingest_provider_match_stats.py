"""Provider stats parsing: the rendered text of a 365scores and a tennis24 match page, and the stop rules."""
import unittest

import ingest_provider_match_stats as ing

SCORES_365 = "\n".join(["Stats", "1", "Aces", "0", "0/3 (0%)", "Break Points Won", "4/9 (44%)", "2",
                        "Double Faults", "1", "See All", "Game Info"])
TENNIS24_MATCH = "\n".join(["MATCH", "SET 1", "SET 2", "SET 3", "SERVICE", "0", "Aces", "0", "1",
                            "Double Faults", "1", "75%", "1st serve percentage", "76%"])


class ParseStatsTest(unittest.TestCase):
    def test_365scores_block_reads_left_then_right(self):
        parsed = ing.parse_stats_text(SCORES_365)
        self.assertEqual(parsed["parse_status"], "ok")
        self.assertEqual((parsed["home_aces"], parsed["away_aces"]), (1, 0))
        self.assertEqual((parsed["home_double_faults"], parsed["away_double_faults"]), (2, 1))

    def test_tennis24_block_reads_zero_aces_and_one_double_fault_each_side(self):
        parsed = ing.parse_stats_text(TENNIS24_MATCH)
        self.assertEqual(parsed["parse_status"], "ok")
        self.assertEqual((parsed["home_aces"], parsed["away_aces"]), (0, 0))
        self.assertEqual((parsed["home_double_faults"], parsed["away_double_faults"]), (1, 1))

    def test_a_page_without_stats_is_no_stats_not_zero(self):
        parsed = ing.parse_stats_text("Tennis Scores\nFinished\n6-4 6-3")
        self.assertEqual(parsed["parse_status"], "no_stats")
        self.assertIsNone(parsed["home_aces"])

    def test_a_label_without_numbers_is_partial_not_ok(self):
        parsed = ing.parse_stats_text("Aces\nn/a\nDouble Faults\n1\n2")
        self.assertNotEqual(parsed["parse_status"], "ok")


class StopRuleTest(unittest.TestCase):
    def test_bot_check_text_raises(self):
        with self.assertRaises(ing.StopRun):
            ing._check_block("Performing security verification. Just a moment...")

    def test_normal_page_passes(self):
        ing._check_block(SCORES_365)

    def test_the_picks_dev_database_is_refused(self):
        with self.assertRaises(SystemExit):
            ing.run("/root/legendarypicks/backend/data/picks.dev.db", "wuhan-wta-2026", "365scores", True)


if __name__ == "__main__":
    unittest.main()
