import math
import random
import sys
import unittest
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2_weekly_evolution as evolution


class StationaryNullTests(unittest.TestCase):
    def test_holm_adjustment_preserves_order_and_monotonicity(self):
        values = evolution.holm_adjust([0.01, 0.04, None, 0.03])
        self.assertEqual(values, [0.03, 0.06, None, 0.06])

    def test_sparse_js_divergence_matches_union_reference(self):
        pairs = [
            (Counter({"a": 4, "b": 2}), Counter({"b": 1, "c": 5})),
            (Counter({"only-left": 7}), Counter({"only-right": 3})),
            (Counter({"a": 3, "b": 1, "c": 9}), Counter({"a": 2, "c": 8, "d": 4})),
        ]
        for left, right in pairs:
            expected = 0.0
            nl, nr = sum(left.values()), sum(right.values())
            for key in left.keys() | right.keys():
                p, q = left.get(key, 0) / nl, right.get(key, 0) / nr
                m = (p + q) / 2
                if p:
                    expected += 0.5 * p * math.log2(p / m)
                if q:
                    expected += 0.5 * q * math.log2(q / m)
            self.assertAlmostEqual(evolution.js_divergence(left, right), expected, places=12)
            self.assertAlmostEqual(evolution.js_divergence(left, right),
                                   evolution.js_divergence(right, left), places=12)

    def test_cached_adjacent_week_divergences_match_direct_curve(self):
        weekly = {
            1: Counter({"a": 4, "b": 2}),
            3: Counter({"b": 1, "c": 5}),
            4: Counter({"a": 3, "c": 2}),
        }
        pairwise = {(left, right): evolution.js_divergence(weekly[left], weekly[right])
                    for left in weekly for right in weekly if left != right}
        direct = evolution.signature_change_curve(weekly)
        cached = evolution.signature_change_curve(weekly, pairwise)
        for week in weekly:
            for metric in direct[week]:
                if direct[week][metric] is None:
                    self.assertIsNone(cached[week][metric])
                else:
                    self.assertAlmostEqual(direct[week][metric], cached[week][metric], places=14)

        shuffled = {1: weekly[4], 3: weekly[1], 4: weekly[3]}
        origins = {1: 4, 3: 1, 4: 3}
        shuffled_curve = evolution.signature_change_curve(shuffled, pairwise, origins)
        self.assertAlmostEqual(shuffled_curve[3]["jsd_vs_previous_played_week"],
                               evolution.js_divergence(weekly[1], weekly[4]), places=14)
        self.assertAlmostEqual(shuffled_curve[4]["jsd_vs_previous_played_week"],
                               evolution.js_divergence(weekly[3], weekly[1]), places=14)

    def test_week_shuffle_preserves_signature_counts_and_individual_game_sizes(self):
        weeks = [1, 2, 3]
        packages = [
            [Counter({"A": 2}), Counter({"B": 1})],
            [Counter({"A": 1, "B": 2})],
            [Counter({"C": 4})],
        ]
        shuffled = evolution.shuffle_week_packages(weeks, packages, random.Random(17))
        pooled_before = Counter()
        pooled_after = Counter()
        sizes_before = sorted(sum(game.values()) for week in packages for game in week)
        sizes_after = sorted(sum(game.values()) for week in shuffled.values() for game in week)
        for week in packages:
            for game in week:
                pooled_before.update(game)
        for week in shuffled.values():
            for game in week:
                pooled_after.update(game)
        self.assertEqual(pooled_after, pooled_before)
        self.assertEqual(sizes_after, sizes_before)
        self.assertEqual(sorted(len(games) for games in shuffled.values()), [1, 1, 2])

    def test_stationary_null_is_reproducible_and_reports_uncertainty(self):
        game_counters = {}
        for week in range(1, 16):
            families = {
                family: Counter({f"{family}-{week % 4}": 18 + (week % 3),
                                 f"{family}-{(week + 1) % 4}": 7})
                for family in evolution.FAMILIES
            }
            game_counters[(2024, week, "SEA", f"G{week}")] = families
        first = evolution.stationary_week_order_null(game_counters, reps=30, seed=91)
        second = evolution.stationary_week_order_null(game_counters, reps=30, seed=91)
        self.assertEqual(first, second)
        contrast = next(row for row in first["contrasts"]
                        if row["family"] == "action" and row["metric"] == "novel_row_share")
        self.assertEqual(contrast["paired_team_seasons"], 1)
        self.assertEqual(contrast["permutations"], 30)
        self.assertIsNotNone(contrast["stationary_null_2_5pct"])
        self.assertIsNotNone(contrast["stationary_null_97_5pct"])
        week = next(row for row in first["weekly"]
                    if row["family"] == "action" and row["week"] == 8
                    and row["metric"] == "jsd_vs_prior_catalog")
        self.assertIsNotNone(week["stationary_null_mean"])
        self.assertIn("cross-family co-occurrence preserved", week["null"])
        self.assertEqual({row["family"] for row in first["weekly"]}, set(evolution.FAMILIES))
        self.assertEqual({row["family"] for row in first["contrasts"]}, set(evolution.FAMILIES))
        previous_contrast = next(row for row in first["contrasts"]
                                 if row["family"] == "action"
                                 and row["metric"] == "jsd_vs_previous_played_week")
        self.assertNotEqual(previous_contrast["stationary_null_2_5pct"],
                            previous_contrast["stationary_null_97_5pct"])
        for row in first["contrasts"]:
            self.assertGreaterEqual(row["holm_adjusted_permutation_p"], row["permutation_two_sided_p"])

    def test_joint_packages_keep_per_game_family_composition(self):
        packages = [
            [
                {"action": Counter({"A": 2}), "presentation": Counter({"P1": 2})},
                {"action": Counter({"B": 1}), "presentation": Counter({"P2": 1})},
            ],
            [{"action": Counter({"A": 1, "B": 2}),
              "presentation": Counter({"P1": 1, "P2": 2})}],
            [{"action": Counter({"C": 4}), "presentation": Counter({"P3": 4})}],
        ]
        shuffled = evolution.shuffle_week_packages([1, 2, 3], packages, random.Random(17))

        def package_multiset(weeks):
            return sorted(
                tuple(sorted((family, tuple(sorted(counter.items())))
                             for family, counter in game.items()))
                for week in weeks
                for game in week
            )

        self.assertEqual(package_multiset(packages), package_multiset(shuffled.values()))


if __name__ == "__main__":
    unittest.main()
