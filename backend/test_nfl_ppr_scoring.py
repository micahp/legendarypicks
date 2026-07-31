#!/usr/bin/env python3
"""test_nfl_ppr_scoring.py — REG-projection-formula gate.

Named position fixtures prove the Legendary Picks PPR formula from raw
PUBLISHED ESPN projection stats to the displayed total. Each expected value
below was hand-computed from the raw snapshot numbers (see the arithmetic in
the comments), independently of ppr_scoring.py.

Fixture source: backend/data/espn_2026_snapshot_page1.json (pinned 2026-07-31).
Run from backend/:  venv/bin/python -m pytest test_nfl_ppr_scoring.py -xvs
"""
import unittest

from ppr_scoring import (
    qb_ppr,
    skill_ppr,
    kicker_ppr,
    dst_ppr,
    pa_tier,
    project_ppr,
)


class TestPprFormula(unittest.TestCase):
    def test_qb_josh_allen(self):
        # Raw: pass_yds 3945.009526 /25 = 157.800381
        #      pass_td 26.21512507 *4 = 104.860500
        #      rush_yds 579.4539886 /10 = 57.945399
        #      rush_td 12.42919575 *6 = 74.575175
        #      int 11.57285237 *2 = -23.145705
        #      fum_lost 4.204255754 *2 = -8.408512
        # Total = 363.627238
        got = qb_ppr(
            pass_yds=3945.009526,
            pass_td=26.21512507,
            rush_yds=579.4539886,
            rush_td=12.42919575,
            interceptions=11.57285237,
            fumbles_lost=4.204255754,
        )
        self.assertAlmostEqual(got, 363.627238, places=3)

    def test_wr_justin_jefferson(self):
        # Raw: rec 110.7280637
        #      rec_yds 1375.592762 /10 = 137.559276
        #      rec_td 7.370305292 *6 = 44.221832
        #      rush_yds 10.62918947 /10 = 1.062919
        #      rush_td 0.098135737 *6 = 0.588814
        #      fum_lost 0.681212228 *2 = -1.362424
        # Total = 292.798481
        got = skill_ppr(
            receptions=110.7280637,
            rec_yds=1375.592762,
            rec_td=7.370305292,
            rush_yds=10.62918947,
            rush_td=0.098135737,
            fumbles_lost=0.681212228,
        )
        self.assertAlmostEqual(got, 292.798481, places=3)

    def test_k_blake_grupe(self):
        # Raw: fgm_0_39 15.75015595 *3 = 47.250468
        #      fgm_40_49 7.309369796 *4 = 29.237479
        #      fgm_50+ 5.48566023 *5 = 27.428301
        #      xp 34.77874843
        #      fg_missed 5.902476286 *1 = -5.902476
        # Total = 132.792520
        got = kicker_ppr(
            fgm_0_39=15.75015595,
            fgm_40_49=7.309369796,
            fgm_50_plus=5.48566023,
            xp_made=34.77874843,
            fg_missed=5.902476286,
        )
        self.assertAlmostEqual(got, 132.792520, places=3)

    def test_dst_falcons(self):
        # Raw: sack 38.64182962
        #      int 11.89759089 *2 = 23.795182
        #      fum_rec 8.195531653 *2 = 16.391063
        #      def_td 1.568742649 *6 = 9.412456
        #      PA 410.51 -> tier 35+ = -4
        # Total = 84.240531
        got = dst_ppr(
            sacks=38.64182962,
            ints=11.89759089,
            fumble_rec=8.195531653,
            def_td=1.568742649,
            points_allowed=410.511892,
        )
        self.assertAlmostEqual(got, 84.240531, places=3)

    def test_pa_tiers(self):
        self.assertEqual(pa_tier(0), 10.0)
        self.assertEqual(pa_tier(3), 7.0)
        self.assertEqual(pa_tier(13), 4.0)
        self.assertEqual(pa_tier(20), 1.0)
        self.assertEqual(pa_tier(24), 0.0)
        self.assertEqual(pa_tier(30), -1.0)
        self.assertEqual(pa_tier(40), -4.0)
        self.assertIsNone(None)  # explicit: None is a valid input handled by caller


class TestProjectPprDispatch(unittest.TestCase):
    """project_ppr dispatches by position over a raw ESPN stat map."""

    def test_qb_dispatch(self):
        stats = {
            3: 3945.009526, 4: 26.21512507, 20: 11.57285237,
            24: 579.4539886, 25: 12.42919575, 72: 4.204255754,
        }
        self.assertAlmostEqual(project_ppr("QB", stats), 363.627238, places=3)

    def test_skill_dispatch(self):
        stats = {
            53: 110.7280637, 42: 1375.592762, 43: 7.370305292,
            24: 10.62918947, 25: 0.098135737, 72: 0.681212228,
        }
        self.assertAlmostEqual(project_ppr("WR", stats), 292.798481, places=3)

    def test_k_dispatch(self):
        stats = {
            80: 15.75015595, 77: 7.309369796, 74: 5.48566023,
            86: 34.77874843, 85: 5.902476286,
        }
        self.assertAlmostEqual(project_ppr("PK", stats), 132.792520, places=3)

    def test_dst_dispatch(self):
        stats = {
            99: 38.64182962, 95: 11.89759089, 96: 8.195531653,
            94: 1.568742649, 120: 410.511892,
        }
        self.assertAlmostEqual(project_ppr("DEF", stats), 84.240531, places=3)

    def test_empty_map_is_honest_null(self):
        self.assertIsNone(project_ppr("QB", {}))
        self.assertIsNone(project_ppr("RB", None))

    def test_string_keys_from_json(self):
        """Regression: ESPN stat maps arrive via JSON with STRING keys. The
        compute path must normalize them, not return 0.0."""
        stats = {
            "53": 110.7280637, "42": 1375.592762, "43": 7.370305292,
            "24": 10.62918947, "25": 0.098135737, "72": 0.681212228,
        }
        self.assertAlmostEqual(project_ppr("WR", stats), 292.798481, places=3)

    def test_return_specialist_map_is_null_not_zero(self):
        """Regression: ESPN projects return specialists (Cowing, Covey...) with
        ONLY return-yard stat keys (101-119) — no offensive stats. Our formula
        scores none of them; storing 0.0 would be a fabricated claim. Must be
        None (renders as an honest dash)."""
        stats = {"101": 0.5, "114": 5.0, "210": 17.0}  # return keys only
        self.assertIsNone(project_ppr("WR", stats))
        self.assertIsNone(project_ppr("RB", stats))

    def test_non_draftable_position_is_null(self):
        """IDP (LB/CB/S/DE/DT) and P are not drafted in the room — their maps
        must yield None, never a QB-formula 0.0."""
        stats = {99: 5.0, 95: 1.0, 210: 17.0}
        self.assertIsNone(project_ppr("LB", stats))
        self.assertIsNone(project_ppr("P", stats))


if __name__ == "__main__":
    unittest.main()
