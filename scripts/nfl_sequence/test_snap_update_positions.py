"""Regression tests for nflverse running-back snap position labels and cutoff behavior."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snap_update  # noqa: E402


class SnapUpdatePositionLabels(unittest.TestCase):
    def setUp(self):
        self.snaps = snap_update.SnapCounts(
            {
                "schema": snap_update.SCHEMA,
                "season": 2026,
                "team_snaps": [["CIN", 1, 64], ["CIN", 2, 60]],
                "player_snaps": [
                    ["CIN", 1, "chase", "HB", 46],
                    ["CIN", 1, "perine", "HB", 18],
                    ["CIN", 1, "wideout", "WR", 64],
                    ["CIN", 1, "tightend", "TE", 64],
                    ["CIN", 2, "chase", "HB", 40],
                    ["CIN", 2, "perine", "HB", 24],
                ],
                "active": [
                    ["CIN", 1, ["chase", "perine", "wideout", "tightend"]],
                    ["CIN", 2, ["chase", "perine"]],
                ],
            },
            "synthetic-test-hash",
        )

    def test_hb_is_part_of_rb_grouping_target(self):
        games, shares = self.snaps.class_shares("CIN", 2)
        self.assertEqual(games, 1)
        self.assertEqual(shares, [1.0, 1.0, 1.0])

        games, shares = self.snaps.class_shares("CIN", 3)
        self.assertEqual(games, 2)
        self.assertAlmostEqual(shares[0], (46 + 18 + 40 + 24) / (64 + 60))

    def test_future_snap_rows_do_not_enter_week_two(self):
        games, share = self.snaps.player_share("CIN", 2, "chase")
        self.assertEqual(games, 1)
        self.assertAlmostEqual(share, 46 / 64)

        games, share = self.snaps.player_share("CIN", 3, "chase")
        self.assertEqual(games, 2)
        self.assertAlmostEqual(share, (46 + 40) / (64 + 60))


if __name__ == "__main__":
    unittest.main()
