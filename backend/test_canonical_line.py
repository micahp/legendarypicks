"""Tests for the canonical prop line: the offer whose vig-free over probability is closest to even."""
import unittest

import canonical_line as cl


def offer(line, source, over, under):
    return {"line": line, "source": source, "over_odds": over, "under_odds": under, "captured_at": "t"}


class Prices(unittest.TestCase):
    def test_implied_probability_for_favourite_and_underdog_prices(self):
        self.assertAlmostEqual(110 / 210, cl.implied(-110))
        self.assertAlmostEqual(0.4, cl.implied(150))

    def test_fair_over_removes_the_vig(self):
        self.assertAlmostEqual(0.5, cl.fair_over(-110, -110))
        self.assertIsNone(cl.fair_over(None, -110))

    def test_pickem_placeholder_on_both_sides_is_not_a_price(self):
        self.assertIsNone(cl.fair_over(-137, -137))
        self.assertIsNotNone(cl.fair_over(-137, -110))                 # a pair with a real price on one side still prices


class Select(unittest.TestCase):
    def test_picks_the_offer_closest_to_even_odds(self):
        offers = [offer(64.5, "A", -145, 115), offer(69.5, "B", -112, -108), offer(74.5, "C", 125, -155)]
        chosen = cl.select(offers)
        self.assertEqual(69.5, chosen["line"])
        self.assertEqual("B", chosen["source"])
        self.assertEqual(1, chosen["books_at_line"])

    def test_books_at_line_counts_distinct_sources_at_the_chosen_line(self):
        offers = [offer(69.5, "A", -110, -110), offer(69.5, "B", -120, 100), offer(71.5, "C", -105, -115)]
        chosen = cl.select(offers)
        self.assertEqual(69.5, chosen["line"])
        self.assertEqual(2, chosen["books_at_line"])

    def test_a_tie_goes_to_the_lower_line(self):
        offers = [offer(70.5, "A", -110, -110), offer(68.5, "B", -110, -110)]
        self.assertEqual(68.5, cl.select(offers)["line"])

    def test_no_priced_offer_gives_none(self):
        self.assertIsNone(cl.select([offer(69.5, "A", None, -110)]))
        self.assertIsNone(cl.select([]))


if __name__ == "__main__":
    unittest.main()
