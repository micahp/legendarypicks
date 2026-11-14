"""Focused, database-free invariants for the research point calibration."""
import importlib.util
import pathlib
import unittest

FILE = pathlib.Path(__file__).with_name("calibrate_player_projection_points.py")
SPEC = importlib.util.spec_from_file_location("point_calibration", FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(week, actual, projection=2.0, game=None):
    return {"week": week, "market": "receptions", "game_id": game or f"2026_{week:02d}_A_B",
            "player_id": str(week), "projection": float(projection), "actual": float(actual)}


class ForwardCalibrationTests(unittest.TestCase):
    def test_shrink_prior_and_nonnegative(self):
        t = [row(2, 3.0, 2.0)] * 100
        p = MODULE.fit(t)
        self.assertAlmostEqual(p["mean_offset"], 0.5)
        self.assertAlmostEqual(p["median_offset"], 0.5)
        self.assertAlmostEqual(p["mean_scale"], 1.25)
        self.assertEqual(MODULE.predict(0.0, p, "add_mean"), 0.5)
        self.assertEqual(MODULE.predict(0.0, p, "add_median"), 0.5)
        self.assertEqual(MODULE.predict(-4.0, p, "raw"), 0.0)

    def test_week_three_does_not_learn_week_three_outcome(self):
        base = [row(2, 4.0), row(3, 0.0)]
        changed = [row(2, 4.0), row(3, 500.0)]
        a, forecast_a = MODULE.evaluate(base)
        b, forecast_b = MODULE.evaluate(changed)
        p_a = next(x for x in forecast_a if x["week"] == 3)
        p_b = next(x for x in forecast_b if x["week"] == 3)
        self.assertAlmostEqual(p_a["add_mean"], p_b["add_mean"])
        self.assertAlmostEqual(p_a["mult_mean"], p_b["mult_mean"])
        self.assertAlmostEqual(p_a["add_median"], p_b["add_median"])

    def test_deduplicated_sample_and_no_future_information(self):
        t = [row(2, 6.0), row(3, 2.0), row(4, 2.0)]
        _report, preds = MODULE.evaluate(t)
        self.assertEqual([p["fit_rows_before_week"] for p in preds], [0, 1, 2])

    def test_reject_unknown_strategy(self):
        with self.assertRaises(ValueError):
            MODULE.predict(2.0, MODULE.fit([]), "just_add_seven_yards")


if __name__ == "__main__":
    unittest.main()
