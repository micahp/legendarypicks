"""Tests for nfl_bracket_check.py: the check must fail when a seed is wrong."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_bracket_check as bc  # noqa: E402

NFC = ["A", "B", "C", "D", "E", "F", "G"]
SEEDS = [(i + 1, c) for i, c in enumerate(NFC)]
CONF = {c: "NFC" for c in NFC}
CONF.update({"X": "AFC", "Y": "AFC"})


def wc_rows():
    # 2 v 7 (B v G), 3 v 6 (C v F), 4 v 5 (D v E); higher seed (home) wins 24-17
    return [("B", "G", 24, 17), ("C", "F", 24, 17), ("D", "E", 24, 17)]


def div_rows(winners):
    # winners: the three WC winners. 1 seed (A) plays the lowest-seeded; the other two meet.
    by = {c: s for s, c in SEEDS}
    ranked = sorted(winners, key=lambda c: by[c])
    lowest = ranked[-1]
    middle = ranked[:-1]
    return [("A", lowest, 30, 10), (middle[0], middle[1], 30, 10)]


class Check(unittest.TestCase):
    def test_correct_seeds_pass(self):
        wc = wc_rows()
        winners = [h if hs > as_ else a for h, a, hs, as_ in wc]
        r = bc.check({"NFC": SEEDS, "AFC": SEEDS}, wc, div_rows(winners), CONF)
        self.assertTrue(r["conferences"]["NFC"]["ok"])

    def test_swapped_seeds_fail_the_wild_card_pairs(self):
        wrong = [(1, "A"), (2, "C"), (3, "B")] + SEEDS[3:]    # 2 and 3 swapped
        wc = wc_rows()
        winners = [h if hs > as_ else a for h, a, hs, as_ in wc]
        r = bc.check({"NFC": wrong, "AFC": SEEDS}, wc, div_rows(winners), CONF)
        self.assertFalse(r["conferences"]["NFC"]["wild_card_pairs_match"])
        self.assertFalse(r["ok"])

    def test_wrong_one_seed_fails_the_divisional_round(self):
        wc = wc_rows()
        winners = [h if hs > as_ else a for h, a, hs, as_ in wc]
        # The divisional games used the real lowest seed; a seeding that puts a different team
        # last among the winners must not match.
        bad_div = [("A", winners[0], 30, 10), (winners[1], winners[2], 30, 10)]
        r = bc.check({"NFC": SEEDS, "AFC": SEEDS}, wc, bad_div, CONF)
        self.assertFalse(r["conferences"]["NFC"]["divisional_pairs_match"])

    def test_missing_wild_card_field_fails(self):
        wrong = [(1, "A")] + [(i + 2, c) for i, c in enumerate(["B", "C", "D", "E", "F", "Z"])]
        wc = wc_rows()
        winners = [h if hs > as_ else a for h, a, hs, as_ in wc]
        r = bc.check({"NFC": wrong, "AFC": SEEDS}, wc, div_rows(winners), CONF)
        self.assertFalse(r["conferences"]["NFC"]["wild_card_field_match"])


if __name__ == "__main__":
    unittest.main()
