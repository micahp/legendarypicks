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
from ingest_ufc_fight_stats import roster
from ingest_ufc_fight_stats.ufcstats_pipeline import UfcStatsPlan


class UfcTimerRunnerTests(unittest.TestCase):


    def setUp(self):
        """Neutralise the card-harvest phase for this class.

        These tests assert the PLAN and APPLY contract against the sentinel path
        `/tmp/not-opened.db`, which must never be opened. The harvest reads `players`
        before planning, so it is stubbed here rather than the sentinel being weakened:
        what each test guards is unchanged. The harvest has its own coverage in
        test_ingest_ufc_fight_stats.py::CardHarvestTest, including that it opens no
        writer and takes no backup when it has nothing to insert.
        """
        for target, attr, value in (
            (runner, "_connect_readonly", None),
            (runner.roster, "build_harvest_plan", roster.HarvestPlan()),
            (runner, "inspect_ufcstats_migration", {
                "state": "applied", "detail": "test",
            }),
        ):
            patcher = mock.patch.object(target, attr, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
    def test_current_plan_does_not_create_backup_or_open_writer(self):
        plan = UfcStatsPlan(target_count=1, existing_count=5)
        with mock.patch.object(
            runner, "load_ufcstats_state",
            return_value=([mock.sentinel.target], {}, {}, {}, {}),
        ), mock.patch.object(
            runner, "build_ufcstats_plan", return_value=plan
        ), mock.patch.object(
            runner.common, "backup_database"
        ) as backup, mock.patch.object(
            runner, "apply_ufcstats_plan"
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
        plan = UfcStatsPlan(
            target_count=1,
            mappings={1: "ufcstats-111"},
        )
        order = []
        with mock.patch.object(
            runner, "load_ufcstats_state",
            return_value=([mock.sentinel.target], {}, {}, {}, {}),
        ), mock.patch.object(
            runner, "build_ufcstats_plan", return_value=plan
        ), mock.patch.object(
            runner.common,
            "backup_database",
            side_effect=lambda *_, **__: order.append("backup")
            or "/tmp/backup.db",
        ) as backup, mock.patch.object(
            runner,
            "apply_ufcstats_plan",
            side_effect=lambda *_: order.append("apply")
            or {
                "inserted_logs": 0,
                "updated_logs": 0,
                "mappings_inserted": 1,
                "mappings_refreshed": 0,
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
        plan = UfcStatsPlan(
            target_count=2,
            inserts=[mock.sentinel.log],
            updates=[mock.sentinel.update],
            mappings={1: "ufcstats-111"},
        )
        with mock.patch.object(
            runner, "load_ufcstats_state",
            return_value=([mock.sentinel.target], {}, {}, {}, {}),
        ), mock.patch.object(
            runner, "build_ufcstats_plan", return_value=plan
        ), mock.patch.object(
            runner.common, "backup_database"
        ) as backup, mock.patch.object(
            runner, "apply_ufcstats_plan"
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
                "updates": 1,
                "source_mappings": 1,
                "no_history": 0,
            },
            result,
        )
        backup.assert_not_called()
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
