import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import s1_s2_models as m  # noqa: E402


class Crps(unittest.TestCase):
    def test_normal_crps_at_the_mean(self):
        # For a standard normal observed at its mean, CRPS = 2 phi(0) - 1 / sqrt(pi).
        expected = 2 * (1 / math.sqrt(2 * math.pi)) - 1 / math.sqrt(math.pi)
        self.assertAlmostEqual(m.crps_normal(0.0, 0.0, 1.0), expected, places=10)

    def test_crps_scales_with_sigma(self):
        # The same standardized point: (3 - 1) / 2 = 1 = (1 - 0) / 1. CRPS scales with sigma.
        self.assertAlmostEqual(m.crps_normal(3.0, 1.0, 2.0), 2.0 * m.crps_normal(1.0, 0.0, 1.0), places=10)


class Travel(unittest.TestCase):
    def test_west_coast_team_travelling_east_to_buffalo(self):
        self.assertEqual(m.tz_crossing('LAR', 'BUF'), (3, 0))

    def test_eastern_team_travelling_west_to_seattle(self):
        self.assertEqual(m.tz_crossing('NYJ', 'SEA'), (0, 3))

    def test_same_zone_has_no_crossing(self):
        self.assertEqual(m.tz_crossing('KC', 'DAL'), (0, 0))


class Features(unittest.TestCase):
    def game(self, **kw):
        base = dict(weekday='Sunday', gametime='13:00', home_rest=7, away_rest=7, neutral=False,
                    home='BUF', away='LAR', div_game=0)
        base.update(kw)
        return base

    def test_kickoff_windows(self):
        self.assertEqual(m.group_features(self.game(gametime='13:00'), ('kickoff',)), [0.0, 0.0])
        self.assertEqual(m.group_features(self.game(gametime='16:25'), ('kickoff',)), [1.0, 0.0])
        self.assertEqual(m.group_features(self.game(gametime='20:20'), ('kickoff',)), [0.0, 1.0])

    def test_rest_difference_is_clipped_and_short_rest_flagged(self):
        f = m.group_features(self.game(home_rest=16, away_rest=4), ('rest',))
        self.assertAlmostEqual(f[0], 7 / 7.0)   # home rest capped at 14, difference 10, clipped to 7
        self.assertEqual(f[1:], [0.0, 1.0])     # away team on 4 days' rest

    def test_neutral_sites_have_no_travel_feature(self):
        self.assertEqual(m.group_features(self.game(neutral=True, away='LAR'), ('travel',)), [0.0, 0.0])


if __name__ == '__main__':
    unittest.main()
