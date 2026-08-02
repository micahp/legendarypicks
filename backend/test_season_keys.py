"""Gates for the season-key boundary.

The defect these exist to prevent is not a crash. It is a query that returns
zero rows and is read as "no data" — NHL 2026 sat at coverage `partial` with all
1,312 of its games present, because `player_game_logs` keyed them `20252026`.
"""
import unittest

from season_keys import normalize_season


class TestNhleSpanKeys(unittest.TestCase):
    def test_nhle_span_becomes_espn_end_year(self):
        # The measured correspondence: nhle 20252026 IS ESPN 2026.
        self.assertEqual(normalize_season("nhle.com", "nhl", "20252026"), 2026)
        self.assertEqual(normalize_season("nhle.com", "nhl", "20242025"), 2025)
        self.assertEqual(normalize_season("nhle.com", "nhl", "20212022"), 2022)

    def test_int_and_str_are_the_same_answer(self):
        self.assertEqual(normalize_season("nhle.com", "nhl", 20252026), 2026)

    def test_already_normalised_passes_through(self):
        # Re-running an ingest over migrated rows must be a no-op, not a second
        # translation.
        self.assertEqual(normalize_season("nhle.com", "nhl", 2026), 2026)
        self.assertEqual(normalize_season("nhle.com", "nhl", "2026"), 2026)

    def test_non_consecutive_halves_raise(self):
        # 20252027 is not a season nhle publishes; accepting it would invent one.
        with self.assertRaises(ValueError):
            normalize_season("nhle.com", "nhl", "20252027")


class TestUnmeasuredCasesRefuse(unittest.TestCase):
    def test_unknown_shape_raises_rather_than_passing_through(self):
        with self.assertRaises(ValueError):
            normalize_season("nhle.com", "nhl", "2025-26")
        with self.assertRaises(ValueError):
            normalize_season("espn", "nfl", "20252026")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            normalize_season("nhle.com", "nhl", "")
        with self.assertRaises(ValueError):
            normalize_season("nhle.com", "nhl", None)

    def test_espn_leagues_are_untouched(self):
        # No publisher-specific case: a plain year is already ours, whatever the
        # league's own start/end convention happens to be.
        for league in ("nfl", "nba", "mlb", "nhl"):
            self.assertEqual(normalize_season("espn", league, "2026"), 2026)


if __name__ == "__main__":
    unittest.main()
