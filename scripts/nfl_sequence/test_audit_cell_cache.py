"""Exact-equivalence tests for single-pass cell statistics (stdlib-only)."""
import unittest

from audit_cell_cache import CellFeatures, index_pool


def fixture(event, yards, team="AAA", defense="BBB", *, touchdown=0):
    return event, {"posteam": team, "defteam": defense, "yards_gained": yards,
                   "touchdown": touchdown, "play_type": "run" if event == "run" else "pass"}, 12, None


def intent(event, row):
    if event in ("punt", "field_goal_attempt"):
        return "kick"
    return "run" if event == "run" else "dropback"


class CellCacheTests(unittest.TestCase):
    def setUp(self):
        self.samples = [
            fixture("pass_complete", 5),
            fixture("pass_complete", 9, touchdown=1),
            fixture("pass_complete", 0, team="CCC"),
            fixture("pass_complete", -2),
            fixture("run", 2),
            fixture("run", 8, team="CCC"),
            fixture("pass_incomplete", None),
            fixture("sack", -7),
            fixture("punt", None),
            fixture("field_goal_attempt", None),
        ]
        self.cache = CellFeatures(self.samples, intent)

    def test_conditional_event_counts_match_naive(self):
        for play_intent in ("run", "dropback", "kick"):
            for event in {s[0] for s in self.samples}:
                expected = sum(intent(ev, row) == play_intent and ev == event
                               for ev, row, _, _ in self.samples)
                self.assertEqual(self.cache.intent_events[play_intent][event], expected)

    def test_gain_tails_match_naive_for_all_togo(self):
        for event in ("run", "pass_complete"):
            rows = [row for ev, row, _, _ in self.samples if ev == event
                    and row["yards_gained"] is not None]
            for togo in range(1, 16):
                expected = sum(row["yards_gained"] >= togo or row["touchdown"] == 1
                               for row in rows) / len(rows)
                self.assertAlmostEqual(self.cache.gain_probability(event, togo), expected)
        self.assertIsNone(self.cache.gain_probability("punt", 3))

    def test_yard_and_action_counts_equal_naive(self):
        for event in ("run", "pass_complete", "sack"):
            expected = [row["yards_gained"] for ev, row, _, _ in self.samples
                        if ev == event and row["yards_gained"] is not None]
            self.assertEqual(self.cache.yards(event), expected)
            for side, column in (("offense", "posteam"), ("defense", "defteam")):
                for team in ("AAA", "CCC", "BBB"):
                    observed = self.cache.yards(event, side=side, team=team)
                    expected = [row["yards_gained"] for ev, row, _, _ in self.samples
                                if ev == event and row[column] == team
                                and row["yards_gained"] is not None]
                    self.assertEqual(observed, expected)
        for side, team in ((None, None), ("offense", "AAA"), ("offense", "CCC"),
                           ("defense", "BBB")):
            for fg_allowed in (True, False):
                observed = self.cache.action_counts(side=side, team=team,
                                                    fg_allowed=fg_allowed)
                expected = {}
                for ev, row, _, _ in self.samples:
                    if side is not None and row["posteam" if side == "offense" else "defteam"] != team:
                        continue
                    if ev == "field_goal_attempt" and not fg_allowed:
                        continue
                    key = "punt" if ev == "punt" else "field_goal" if ev == "field_goal_attempt" else "go"
                    expected[key] = expected.get(key, 0) + 1
                self.assertEqual(dict(observed), expected)
                observed.clear()

    def test_indexes_are_independent(self):
        pool = {(1, "10+", "middle"): self.samples,
                (4, "1-2", "goal"): [fixture("punt", None)]}
        cache = index_pool(pool, intent)
        cache[(1, "10+", "middle")].action_counts().clear()
        self.assertEqual(cache[(1, "10+", "middle")].action_counts()["go"], 8)
        self.assertEqual(cache[(4, "1-2", "goal")].action_counts()["punt"], 1)


if __name__ == "__main__":
    unittest.main()
