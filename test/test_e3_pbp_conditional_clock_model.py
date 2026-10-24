import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.bdb.e3_pbp_conditional_clock_model import (
    INPUT_FIELDS,
    actual_clock_delta,
    build_artifact,
    load_pbp,
    stoppage_context,
    validate_weeks,
)


def pbp_row(week, play_id, seconds, *, game_id=None, quarter=1, play_type="run", **extra):
    row = {
        "game_id": game_id or f"2022_{week:02d}_AAA_BBB",
        "play_id": play_id,
        "season": 2022,
        "week": week,
        "qtr": quarter,
        "down": 1,
        "ydstogo": 10,
        "game_seconds_remaining": seconds,
        "play_type": play_type,
        "complete_pass": None,
        "touchdown": 0,
        "interception": 0,
        "fumble_lost": 0,
        "sack": 0,
        "penalty": 0,
        "two_point_attempt": 0,
        "series_result": "First down",
    }
    row.update(extra)
    return row


class PbpConditionalClockModelTests(unittest.TestCase):
    def test_scope_rejects_weeks_6_through_9_before_opening_database(self):
        for week in (6, 7, 8, 9):
            with self.subTest(week=week), self.assertRaisesRegex(ValueError, "weeks 6-9 are reserved"):
                load_pbp(Path("/definitely/not/a/database"), (week,))
        self.assertEqual(validate_weeks((5, 1, 3)), (1, 3, 5))

    def test_read_only_loader_queries_the_selected_development_week_subset(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "pbp.sqlite3"
            connection = sqlite3.connect(db)
            columns = ",".join(f'"{name}"' for name in INPUT_FIELDS)
            connection.execute(f"CREATE TABLE nfl_pbp ({columns})")
            placeholders = ",".join("?" for _ in INPUT_FIELDS)
            for week in range(1, 6):
                row = pbp_row(week, week * 100, 500)
                connection.execute(f"INSERT INTO nfl_pbp VALUES ({placeholders})", [row[name] for name in INPUT_FIELDS])
            connection.commit()
            connection.close()
            records, digest = load_pbp(db, (1, 2, 3, 4, 5))
            self.assertEqual({row["week"] for row in records}, {1, 2, 3, 4, 5})
            self.assertEqual(len(records), 5)
            self.assertEqual(len(digest), 64)

    def test_clock_delta_labels_follow_observed_inferred_unresolvable_policy(self):
        current = pbp_row(1, 1, 100)
        following = pbp_row(1, 2, 90)
        self.assertEqual(actual_clock_delta(current, following), {
            "value": 10.0,
            "label": "inferred",
            "rule": "R4 inferred: current PBP game_seconds_remaining minus next same-quarter PBP play stamp",
        })
        self.assertEqual(actual_clock_delta(current, None)["label"], "unresolvable")
        self.assertIn("R4u2", actual_clock_delta(current, pbp_row(1, 2, 900, quarter=2))["rule"])
        self.assertIn("R4u3", actual_clock_delta(current, pbp_row(1, 2, 110))["rule"])
        self.assertEqual(actual_clock_delta(pbp_row(1, 1, None), following)["value"], None)

    def test_stoppage_context_does_not_invent_timeout_oob_or_penalty_clock_effect(self):
        incomplete = pbp_row(1, 1, 100, play_type="pass", complete_pass=0)
        self.assertEqual(stoppage_context(incomplete, "pass_incomplete")["label"], "inferred")
        penalty = pbp_row(1, 1, 100, penalty=1)
        self.assertIsNone(stoppage_context(penalty, "run")["value"])
        self.assertEqual(stoppage_context(penalty, "run")["label"], "unresolvable")
        self.assertEqual(stoppage_context(pbp_row(1, 1, 100), "run")["label"], "unresolvable")

    def test_cross_fitted_predictions_cover_each_play_and_label_all_margins(self):
        records = []
        for week in range(1, 6):
            gid = f"g{week}"
            records.extend([
                pbp_row(week, 1, 120, game_id=gid),
                pbp_row(week, 2, 100, game_id=gid),
            ])
        artifact = build_artifact(records, "a" * 64, (1, 2, 3, 4, 5))
        self.assertEqual(artifact["scope"]["all_rows"], 10)
        self.assertEqual(artifact["scope"]["weeks"], [1, 2, 3, 4, 5])
        self.assertEqual(len(artifact["plays"]), 10)
        self.assertEqual(artifact["evaluation"]["forward_week_5_holdout"]["n"], 1)
        self.assertTrue(all(row["prediction"]["game_clock_delta_s"]["label"] == "inferred" for row in artifact["plays"]))
        self.assertTrue(all(row["actual_game_clock_delta_s"]["label"] in {"inferred", "unresolvable"} for row in artifact["plays"]))
        self.assertTrue(all("model_inputs" in row and "features" not in row for row in artifact["plays"]))
        self.assertTrue(all(row["in_play_duration_s"]["value"] is None for row in artifact["plays"]))
        self.assertTrue(all(row["in_play_duration_s"]["label"] == "unresolvable" for row in artifact["plays"]))
        for row in artifact["plays"]:
            for field in ("terminal_event_family", "actual_game_clock_delta_s", "actual_clock_runoff_s",
                          "actual_runoff_behavior", "in_play_duration_s", "between_play_dead_time_s",
                          "stoppage_context", "observed_game_clock_seconds_remaining"):
                value = row[field]
                if value["label"] == "unresolvable":
                    self.assertIsNone(value["value"], f"{field} must not supply a value when unresolvable")
            for value in row["source_context"].values():
                if value["label"] == "unresolvable":
                    self.assertIsNone(value["value"])
        week5_train_weeks = {
            tuple(row["prediction"]["game_clock_delta_s"]["training_weeks"])
            for row in artifact["plays"] if row["week"] == 5
        }
        self.assertEqual(week5_train_weeks, {(1, 2, 3, 4)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
