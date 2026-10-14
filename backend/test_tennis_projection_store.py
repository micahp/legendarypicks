"""Stored tennis projections: a computed day round-trips, a day never computed is distinguishable, and forgetting recomputes."""
import sqlite3
import unittest

from tennis_daily_projections import forget_days, store_candidates, stored_candidates

NOW = "2026-10-14T12:00:00+00:00"


class TennisProjectionStoreTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")

    def test_a_day_never_computed_is_none_and_a_stored_day_round_trips(self):
        self.assertIsNone(stored_candidates(self.con, "atp", "2026-10-15"))
        store_candidates(self.con, "atp", "2026-10-15",
                         {"184950": {"projectedWinner": "Alex de Minaur", "totalGames": 22.5}}, NOW)
        self.assertEqual(stored_candidates(self.con, "atp", "2026-10-15"),
                         {"184950": {"projectedWinner": "Alex de Minaur", "totalGames": 22.5}})

    def test_a_computed_day_with_no_projections_is_stored_as_empty_not_missing(self):
        store_candidates(self.con, "wta", "2026-10-15", {}, NOW)
        self.assertEqual(stored_candidates(self.con, "wta", "2026-10-15"), {})

    def test_storing_a_day_replaces_its_previous_projections(self):
        store_candidates(self.con, "atp", "2026-10-15", {"1": {"totalGames": 20.5}}, NOW)
        store_candidates(self.con, "atp", "2026-10-15", {"2": {"totalGames": 21.5}}, NOW)
        self.assertEqual(set(stored_candidates(self.con, "atp", "2026-10-15")), {"2"})

    def test_forgetting_a_day_makes_the_next_read_recompute_it(self):
        store_candidates(self.con, "atp", "2026-10-15", {"1": {"totalGames": 20.5}}, NOW)
        forget_days(self.con, "atp", ["2026-10-15"])
        self.assertIsNone(stored_candidates(self.con, "atp", "2026-10-15"))

    def test_tours_and_days_are_kept_apart(self):
        store_candidates(self.con, "atp", "2026-10-15", {"1": {"totalGames": 20.5}}, NOW)
        self.assertIsNone(stored_candidates(self.con, "wta", "2026-10-15"))
        self.assertIsNone(stored_candidates(self.con, "atp", "2026-10-16"))


if __name__ == "__main__":
    unittest.main()
