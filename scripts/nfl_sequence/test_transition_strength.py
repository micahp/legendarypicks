"""Regression coverage for the opt-in transition-strength runtime paths."""
import random
import unittest

import transition_strength as ts
import slc_playcall as slc
from test_slc_playcall import STATE, blank_artifact, cell


class TransitionStrengthRegression(unittest.TestCase):
    def test_ratio_key_uses_the_supplied_transition_and_falls_back(self):
        key = "pass_complete:3_5:not_converted:no_touchdown"
        situation = (1, "d10_14", "own_side")
        table = ts.TransitionStrength(
            {"offense": {"AAA": {ts.cell_name(situation): {key: 1.5}}},
             "defense": {"BBB": {}}},
            {}, {"sha256": "test"},
        )
        self.assertEqual(table.ratio_key("offense", "AAA", situation, key), 1.5)
        row = {"yards_gained": 5, "ydstogo": 10, "touchdown": 0}
        self.assertEqual(table.ratio("offense", "AAA", situation, "pass_complete", row), 1.5)
        self.assertEqual(table.ratio_key("defense", "BBB", situation, key), 1.0)
        self.assertEqual(table.fallback_count, 1)

    def test_transition_strength_samples_the_outcome_backoff_path(self):
        sampler = slc.PlayCallSampler(
            slc.PlayCallLayer(blank_artifact(30.0)),
            side_teams={"A": "AAA", "B": "BBB"},
        )
        sampler.transition_strength = ts.TransitionStrength(
            {"offense": {"AAA": {}}, "defense": {"BBB": {}}},
            {}, {"sha256": "test"},
        )
        sampler.outcome_backoff_enabled = True
        candidates = cell([("pass_complete", "pass") for _ in range(12)])
        for candidate in candidates:
            candidate[1].update(yards_gained=5, touchdown=0)
        sampler.source_pool = {"fixture": candidates}
        event, _, _, _ = sampler.sample(
            random.Random(7), candidates[:1], "A", "B", state=STATE,
        )
        self.assertEqual(event, "pass_complete")
        self.assertGreater(sampler.transition_strength.fallback_count, 0)
        self.assertTrue(sampler.decisions[-1]["team_transition_split"])

    def test_adaptation_excludes_unknown_penalties_without_breaking_play_order(self):
        def row(play_id, *, play_type, posteam, defteam, penalty, seconds, yards=None):
            value = {column: None for column in ts.e1.COLUMNS}
            value.update({
                "game_id": "2026_01_AAA_BBB", "play_id": play_id, "season": 2026, "week": 1,
                "posteam": posteam, "defteam": defteam, "qtr": 1, "down": 1, "ydstogo": 10,
                "yardline_100": 50, "game_seconds_remaining": seconds, "play_type": play_type,
                "yards_gained": yards, "touchdown": 0, "penalty": penalty,
                "two_point_attempt": 0, "qb_scramble": 0, "sack": 0, "complete_pass": 0,
                "interception": 0, "fumble_lost": 0,
            })
            return value

        rows = [
            row(1, play_type="punt", posteam="AAA", defteam="BBB", penalty=0, seconds=900),
            row(2, play_type="no_play", posteam="BBB", defteam="AAA", penalty=None, seconds=895),
            row(3, play_type="run", posteam="BBB", defteam="AAA", penalty=0, seconds=890, yards=3),
            row(4, play_type="run", posteam="BBB", defteam="AAA", penalty=0, seconds=886, yards=2),
        ]
        cell_key = ts.e1.e0.pool_key(1, 10, 50)
        transition = ts.transition_key("run", rows[2])
        hist = ts.TransitionStrength(
            {"offense": {"BBB": {}}, "defense": {"AAA": {}}},
            {ts.cell_name(cell_key): {transition: 1.0}},
            {"sha256": "historical", "target_season": 2026, "fit_seasons": [2025]},
        )

        updated = ts.adapt(hist, rows, n0=4, team_games={"AAA": 1, "BBB": 1})

        self.assertEqual(updated.manifest["plays"], 1)
        self.assertEqual(updated.manifest["rows_excluded_unknown_penalty_status"], 1)
        self.assertEqual(updated.manifest["excluded"]["punt without a clean receiving-team snap"], 1)
        self.assertNotIn("AAA", updated.ratios["offense"])
        self.assertIn(transition, updated.ratios["offense"]["BBB"][ts.cell_name(cell_key)])

    def test_historical_fit_excludes_unknown_penalty_rows(self):
        def row(play_id, *, play_type, posteam, defteam, penalty, seconds, yards=None):
            value = {column: None for column in ts.e1.COLUMNS}
            value.update({
                "game_id": "2025_01_AAA_BBB", "play_id": play_id, "season": 2025, "week": 1,
                "posteam": posteam, "defteam": defteam, "qtr": 1, "down": 1, "ydstogo": 10,
                "yardline_100": 50, "game_seconds_remaining": seconds, "play_type": play_type,
                "yards_gained": yards, "touchdown": 0, "penalty": penalty,
                "two_point_attempt": 0, "qb_scramble": 0, "sack": 0, "complete_pass": 0,
                "interception": 0, "fumble_lost": 0,
            })
            return value

        rows = [
            row(1, play_type="punt", posteam="AAA", defteam="BBB", penalty=0, seconds=900),
            row(2, play_type="no_play", posteam="BBB", defteam="AAA", penalty=None, seconds=895),
            row(3, play_type="run", posteam="BBB", defteam="AAA", penalty=0, seconds=890, yards=3),
            row(4, play_type="run", posteam="BBB", defteam="AAA", penalty=0, seconds=886, yards=2),
        ]
        fitted = ts.build_from_rows(rows, 2026, cutoff=(2026, 1))

        self.assertEqual(fitted.manifest["plays"], 1)
        self.assertEqual(fitted.manifest["rows_excluded_unknown_penalty_status"], 1)
        self.assertEqual(fitted.manifest["excluded"]["punt without a clean receiving-team snap"], 1)


if __name__ == "__main__":
    unittest.main()
