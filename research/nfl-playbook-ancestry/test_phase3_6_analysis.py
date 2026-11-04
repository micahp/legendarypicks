import sqlite3
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase3_6_analysis as analysis


def play(season, week, game_id, play_id, play_type="run", **overrides):
    row = {
        "season": season, "week": week, "game_id": game_id, "play_id": play_id,
        "posteam": "SEA", "defteam": "SF", "play_type": play_type,
        "run_gap": "middle", "run_location": "left", "pass_location": None,
        "down": 1, "ydstogo": 2.0, "score_differential": 0,
        "participation_joined": True, "offense_formation": "SHOTGUN",
        "offense_personnel": "1 RB, 1 TE, 3 WR, 5 OL", "ftn_joined": True,
        "is_motion": False, "is_play_action": False, "shotgun": True,
    }
    row.update(overrides)
    return row


class Phase36RegressionTests(unittest.TestCase):
    def make_source_db(self, duplicate_participation=False):
        handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        handle.close()
        path = Path(handle.name)
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE nfl_hist_participation (
                nflverse_game_id TEXT, play_id INTEGER, offense_formation TEXT, offense_personnel TEXT
            );
            CREATE TABLE nfl_hist_ftn_charting (
                nflverse_game_id TEXT, nflverse_play_id INTEGER, is_motion INTEGER, is_play_action INTEGER
            );
        """)
        participation = ("G1", 1, "SHOTGUN", "1 RB, 1 TE, 3 WR, 5 OL")
        con.execute("INSERT INTO nfl_hist_participation VALUES (?,?,?,?)", participation)
        if duplicate_participation:
            con.execute("INSERT INTO nfl_hist_participation VALUES (?,?,?,?)", participation)
        con.execute("INSERT INTO nfl_hist_ftn_charting VALUES (?,?,?,?)", ("G1", 1, 1, 0))
        con.commit()
        con.close()
        return path

    def raw_post_row(self, game_id, play_id):
        return (2025, 19, game_id, play_id, "SEA", "SF", "run", None,
                "middle", "left", None, 1, 2.0, 0, 900, 1, 0,
                "SEA", "SF", "Coach A", "Coach B")

    def test_postseason_join_uses_exact_keys_and_preserves_unmatched_rows(self):
        path = self.make_source_db()
        try:
            names = ["season", "week", "game_id", "play_id", "posteam", "defteam", "play_type",
                     "receiver_player_id", "run_gap", "run_location", "pass_location", "down", "ydstogo",
                     "score_differential", "game_seconds_remaining", "shotgun", "no_huddle", "home_team",
                     "away_team", "home_coach", "away_coach"]
            rows = analysis.join_postseason_rows(
                [self.raw_post_row("G1", 1), self.raw_post_row("G1", 2)], names, path)
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[0]["participation_joined"])
            self.assertTrue(rows[0]["ftn_joined"])
            self.assertFalse(rows[1]["participation_joined"])
            self.assertFalse(rows[1]["ftn_joined"])
        finally:
            path.unlink()

    def test_postseason_join_rejects_source_fanout(self):
        path = self.make_source_db(duplicate_participation=True)
        try:
            names = ["season", "week", "game_id", "play_id", "posteam", "defteam", "play_type",
                     "receiver_player_id", "run_gap", "run_location", "pass_location", "down", "ydstogo",
                     "score_differential", "game_seconds_remaining", "shotgun", "no_huddle", "home_team",
                     "away_team", "home_coach", "away_coach"]
            with self.assertRaisesRegex(RuntimeError, "cardinality changed"):
                analysis.join_postseason_rows([self.raw_post_row("G1", 1)], names, path)
        finally:
            path.unlink()

    def test_postseason_context_report_separates_matched_unsupported_and_incomplete(self):
        regular = [play(2024, 8, "R1", 1, "run"), play(2024, 8, "R1", 2, "pass")]
        postseason = [play(2024, 19, "P1", 1, "run"),
                      play(2024, 19, "P1", 2, "run", score_differential=None),
                      play(2024, 19, "P1", 3, "run", defteam="LAR")]
        with tempfile.TemporaryDirectory() as directory:
            result = analysis.context_adjusted_postseason(regular, postseason, Path(directory))
        row = next(row for row in result["pooled_summary"] if row["feature"] == "run_pass")
        self.assertEqual(row["eligible_postseason_rows"], 3)
        self.assertEqual(row["matched_postseason_rows"], 1)
        self.assertEqual(row["unsupported_context_rows"], 1)
        self.assertEqual(row["incomplete_control_rows"], 1)
        self.assertEqual(row["postseason_positive_rate"], 1.0)
        self.assertEqual(row["regular_rate_standardized_to_matched_postseason_contexts"], 0.5)

    def test_chronological_prediction_is_unchanged_by_future_week(self):
        prior = [play(2022, 18, "OLD", 1, "pass")]
        current = [play(2023, 1, "W1", 1), play(2023, 2, "W2", 1, "pass")]
        before = analysis.build_phase6_records(prior + current)
        after = analysis.build_phase6_records(prior + current + [play(2023, 3, "W3", 1, "pass")])
        def target(records):
            return next(row for row in records if row["team"] == "SEA" and row["season"] == 2023
                        and row["week"] == 2 and row["family"] == "run_pass"
                        and row["model"] == "current_season_expanding")
        self.assertEqual(target(before), target(after))

    def test_personnel_parser_handles_supported_counts_and_unknowns(self):
        value = "1 RB, 2 TE, 2 WR, 6 OL"
        self.assertEqual(analysis.parse_personnel(value, "RB"), 1)
        self.assertEqual(analysis.parse_personnel(value, "TE"), 2)
        self.assertEqual(analysis.parse_personnel(value, "WR"), 2)
        self.assertIsNone(analysis.parse_personnel(None, "WR"))
        self.assertIsNone(analysis.parse_personnel("unparsed", "RB"))

    def test_snap_denominator_reconciles_rounded_percentages(self):
        rows = [{"offense_snaps": 126, "offense_pct": 0.97},
                {"offense_snaps": 125, "offense_pct": 0.96}]
        result = analysis.infer_team_offense_snaps(rows)
        self.assertEqual(result["status"], "resolved_from_rounded_offense_pct")
        self.assertEqual(result["total"], 130)
        self.assertGreater(result["total"], result["max_player_snaps"])
        tie = analysis.infer_team_offense_snaps([{"offense_snaps": 30, "offense_pct": 0.62}])
        self.assertEqual(tie["total"], 48)
        float_tie = analysis.infer_team_offense_snaps([
            {"offense_snaps": 42, "offense_pct": 0.53},
            {"offense_snaps": 80, "offense_pct": 1.0},
        ])
        self.assertEqual(float_tie["total"], 80)

    def test_snap_denominator_flags_ambiguous_and_inconsistent_inputs(self):
        ambiguous = analysis.infer_team_offense_snaps([{"offense_snaps": 1, "offense_pct": 0.01}])
        self.assertEqual(ambiguous["status"], "ambiguous_integer_denominator")
        inconsistent = analysis.infer_team_offense_snaps([
            {"offense_snaps": 100, "offense_pct": 1.0},
            {"offense_snaps": 99, "offense_pct": 1.0},
        ])
        self.assertEqual(inconsistent["status"], "inconsistent_percentage_constraints")

    def test_predictive_probabilities_normalize_including_empty_history(self):
        for family, train in (("run_pass", Counter()), ("run_pass", Counter({"run": 6, "pass": 4})),
                              ("personnel", Counter({"11": 3, "12": 1})),
                              ("formation", Counter())):
            dist = analysis.predictive_distribution(train, family)
            self.assertAlmostEqual(sum(dist["known"].values()) + dist["unseen"], 1.0)

    def test_walkforward_source_coverage_counts_supported_fields(self):
        rows = [play(2023, 2, "A", 1, "pass"),
                play(2026, 2, "B", 1, "pass", participation_joined=False,
                     offense_formation=None, offense_personnel=None, ftn_joined=False,
                     is_motion=None, is_play_action=None),
                play(2022, 2, "C", 1, "pass")]
        coverage = analysis.phase6_source_coverage(rows)
        self.assertEqual(coverage["walkforward_run_pass_target_rows"], 2)
        self.assertEqual(coverage["participation_joined"]["rows"], 1)
        self.assertEqual(coverage["formation_nonnull"]["rows"], 1)
        self.assertEqual(coverage["personnel_parseable_rb_te_wr"]["rows"], 1)
        self.assertEqual(coverage["motion_tag_nonnull"]["rows"], 1)
        self.assertEqual(coverage["play_action_pass_tag_nonnull"]["rows"], 1)

    def test_phase6_model_comparison_uses_common_team_week_population(self):
        target = Counter({"run": 3, "pass": 2})
        rows = []
        for model, train in (("current_season_expanding", Counter({"run": 8, "pass": 4})),
                             ("previous_season_static", Counter({"run": 5, "pass": 7}))):
            score = analysis.score_distribution(train, target, "run_pass")
            rows.append({"team": "SEA", "season": 2025, "week": 2, "family": "run_pass",
                         "model": model, **score})
        extra = analysis.score_distribution(Counter({"run": 1, "pass": 1}), target, "run_pass")
        rows.append({"team": "SEA", "season": 2025, "week": 3, "family": "run_pass",
                     "model": "current_season_expanding", **extra})
        with tempfile.TemporaryDirectory() as directory:
            summary, ci = analysis.aggregate_phase6(rows, Path(directory))
            self.assertTrue(summary)
            self.assertTrue(ci)
            self.assertTrue(all(row["matched_population_test_rows"] == 5 for row in summary))
            self.assertTrue(all(row["matched_population_test_groups"] == 1 for row in summary))
            self.assertTrue(all(row["matched_test_rows"] == 5 for row in ci))


if __name__ == "__main__":
    unittest.main()
