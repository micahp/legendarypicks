#!/usr/bin/env python3

import datetime as dt
import os
import sys
import unittest
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ingest_ufc_fight_stats as ingest
import run_ufc_current_card_ingest as runner


class UfcTimerRunnerTests(unittest.TestCase):
    def test_current_plan_does_not_create_backup_or_open_writer(self):
        plan = ingest.IngestPlan(target_count=1, existing_count=5)
        with mock.patch.object(
            runner.ingest,
            "load_targets",
            return_value=([mock.sentinel.target], set(), {}),
        ), mock.patch.object(
            runner.ingest, "build_current_card_plan", return_value=plan
        ), mock.patch.object(
            runner.common, "backup_database"
        ) as backup, mock.patch.object(
            runner.ingest, "apply_plan"
        ) as apply:
            result = runner.run(
                "/tmp/not-opened.db",
                now=dt.datetime(2026, 7, 26, 12, 0, 0),
                emit=lambda _: None,
            )

        self.assertEqual("current", result["status"])
        backup.assert_not_called()
        apply.assert_not_called()

    def test_mutating_plan_backs_up_before_apply(self):
        plan = ingest.IngestPlan(
            target_count=1,
            identity_updates={1: "111"},
        )
        order = []
        with mock.patch.object(
            runner.ingest,
            "load_targets",
            return_value=([mock.sentinel.target], set(), {}),
        ), mock.patch.object(
            runner.ingest, "build_current_card_plan", return_value=plan
        ), mock.patch.object(
            runner.common,
            "backup_database",
            side_effect=lambda *_, **__: order.append("backup")
            or "/tmp/backup.db",
        ) as backup, mock.patch.object(
            runner.ingest,
            "apply_plan",
            side_effect=lambda *_: order.append("apply")
            or {
                "inserted_logs": 0,
                "identity_updates": 1,
                "game_links": 0,
            },
        ):
            result = runner.run(
                "/tmp/not-opened.db",
                now=dt.datetime(2026, 7, 26, 12, 0, 0),
                emit=lambda _: None,
            )

        self.assertEqual(["backup", "apply"], order)
        self.assertEqual("applied", result["status"])
        backup.assert_called_once_with(
            "/tmp/not-opened.db",
            "ufc-timer",
            now=dt.datetime(2026, 7, 26, 12, 0, 0),
        )

    def test_dry_run_reports_mutations_without_backup_or_writer(self):
        plan = ingest.IngestPlan(
            target_count=2,
            logs=[mock.sentinel.log],
            identity_updates={1: "111"},
            game_links={9: "999"},
        )
        with mock.patch.object(
            runner.ingest,
            "load_targets",
            return_value=([mock.sentinel.target], set(), {}),
        ), mock.patch.object(
            runner.ingest, "build_current_card_plan", return_value=plan
        ), mock.patch.object(
            runner.common, "backup_database"
        ) as backup, mock.patch.object(
            runner.ingest, "apply_plan"
        ) as writer:
            result = runner.run(
                "/tmp/not-opened.db",
                now=dt.datetime(2026, 7, 26, 12, 0, 0),
                emit=lambda _: None,
                apply=False,
            )

        self.assertEqual(
            {
                "status": "dry_run",
                "logs": 1,
                "identity_updates": 1,
                "game_links": 1,
                "unresolved": 0,
            },
            result,
        )
        backup.assert_not_called()
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
