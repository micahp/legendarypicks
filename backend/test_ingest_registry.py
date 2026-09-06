#!/usr/bin/env python3
"""The registry exists to make an unschedulable or uncheckable job impossible to add.

These tests assert that refusal, not the happy path. A registry that accepts a job nobody
can verify is the defect it was built to remove: `ingest_soccer_logs.py` existed, worked,
was tested, and ran never, and nothing anywhere noticed for 28 days.
"""
import datetime as dt
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_registry
import monitor_ingest_freshness as monitor
import run_ingest_jobs
import run_props_ingest


def _job(**overrides):
    job = {
        "id": "example",
        "cadence_min": 60,
        "timeout_sec": 600,
        "host_lock": "espn",
        "steps": [["ingest_example.py"]],
        "needs_api_base": False,
        "freshness": [{
            "table": "player_game_logs",
            "date_column": "game_date",
            "stale_hours": 48,
            "label": "example rows",
        }],
    }
    job.update(overrides)
    return job


class TheShippedRegistryIsValid(unittest.TestCase):
    def test_the_real_registry_validates(self):
        ingest_registry.validate()

    def test_every_shipped_job_declares_a_freshness_target(self):
        for job in ingest_registry.JOBS:
            self.assertTrue(job["freshness"], job["id"])

    def test_every_shipped_step_names_a_script_that_exists(self):
        """A step naming a missing script would schedule a job that can only ever fail."""
        here = os.path.dirname(os.path.abspath(__file__))
        for job in ingest_registry.JOBS:
            for step in job["steps"]:
                script = step[0]
                if script.startswith("-"):
                    continue
                self.assertTrue(os.path.isfile(os.path.join(here, script)),
                                "{}: {} does not exist".format(job["id"], script))


class ARegistryRefusesWhatCannotBeChecked(unittest.TestCase):
    def test_a_job_with_no_freshness_target_is_refused(self):
        with self.assertRaises(ingest_registry.RegistryError):
            ingest_registry.validate([_job(freshness=[])])

    def test_a_freshness_target_missing_its_threshold_is_refused(self):
        broken = [{"table": "t", "date_column": "d", "label": "x"}]
        with self.assertRaises(ingest_registry.RegistryError):
            ingest_registry.validate([_job(freshness=broken)])

    def test_a_non_positive_stale_hours_is_refused(self):
        broken = [{"table": "t", "date_column": "d", "label": "x", "stale_hours": 0}]
        with self.assertRaises(ingest_registry.RegistryError):
            ingest_registry.validate([_job(freshness=broken)])

    def test_a_job_with_no_steps_is_refused(self):
        with self.assertRaises(ingest_registry.RegistryError):
            ingest_registry.validate([_job(steps=[])])

    def test_a_missing_required_key_is_refused(self):
        for key in ("cadence_min", "timeout_sec", "host_lock", "steps", "freshness"):
            job = _job()
            del job[key]
            with self.assertRaises(ingest_registry.RegistryError, msg=key):
                ingest_registry.validate([job])

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ingest_registry.RegistryError):
            ingest_registry.validate([_job(), _job()])

    def test_a_non_positive_cadence_is_refused(self):
        with self.assertRaises(ingest_registry.RegistryError):
            ingest_registry.validate([_job(cadence_min=0)])


class OneEngineNotTwo(unittest.TestCase):
    """The whole point of the thin runner: no second copy of the ledger or the locks."""

    def test_the_jobs_runner_drives_the_props_engine(self):
        self.assertIs(run_ingest_jobs.run_props_ingest, run_props_ingest)

    def test_listing_jobs_shows_the_jobs_not_the_props_providers(self):
        ids = run_props_ingest._provider_ids(ingest_registry.JOBS)
        self.assertEqual(ids, ingest_registry.job_ids())
        self.assertNotIn("bovada", ids)

    def test_the_props_registry_is_untouched_by_default(self):
        """The live props timer must behave exactly as before this change."""
        self.assertEqual(run_props_ingest._provider_ids(),
                         [p["id"] for p in run_props_ingest.PROVIDERS])
        self.assertIn("bovada", run_props_ingest._provider_ids())

    def test_freshness_targets_carry_the_job_that_feeds_them(self):
        for target in ingest_registry.freshness_targets():
            self.assertIn("job", target)
            self.assertIn(target["job"], ingest_registry.job_ids())


class TheMonitorFailsClosed(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "t.db")
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE player_game_logs(league TEXT, game_date TEXT)")
        con.commit()
        con.close()
        self.now = dt.datetime(2026, 9, 6, 12, 0, tzinfo=dt.timezone.utc)
        self.target = {"job": "j", "label": "rows", "table": "player_game_logs",
                       "date_column": "game_date", "stale_hours": 48}

    def _levels(self, targets=None):
        return [lvl for lvl, _ in monitor.check(
            "test", self.db, targets or [self.target], now=self.now)]

    def _insert(self, date):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO player_game_logs VALUES('mls', ?)", (date,))
        con.commit()
        con.close()

    def test_fresh_rows_pass(self):
        self._insert("2026-09-05")
        self.assertEqual(self._levels(), ["OK"])

    def test_stale_rows_alert(self):
        self._insert("2026-08-08")
        self.assertEqual(self._levels(), ["ALERT"])

    def test_an_empty_table_alerts_rather_than_passing(self):
        """No rows is the loudest stale, not a vacuous pass."""
        self.assertEqual(self._levels(), ["ALERT"])

    def test_a_missing_table_alerts(self):
        missing = dict(self.target, table="table_that_does_not_exist")
        self.assertEqual(self._levels([missing]), ["ALERT"])

    def test_a_missing_database_alerts(self):
        result = monitor.check("test", os.path.join(self.dir, "nope.db"), [self.target])
        self.assertEqual([lvl for lvl, _ in result], ["ALERT"])

    def test_an_unparseable_date_alerts_rather_than_reading_as_fresh(self):
        self._insert("not-a-date")
        self.assertEqual(self._levels(), ["ALERT"])

    def test_hour_precision_so_a_settlement_gap_is_visible(self):
        """A settlement stall is hours, not days. Day granularity could not see the real
        defect: prod settled nothing for 14.5h against a 6h threshold."""
        target = dict(self.target, date_column="game_date", stale_hours=6)
        self._insert("2026-09-06T03:00:00+00:00")
        self.assertEqual(self._levels([target]), ["ALERT"])

    def test_a_timestamp_inside_the_threshold_is_fresh(self):
        target = dict(self.target, stale_hours=6)
        self._insert("2026-09-06T09:00:00+00:00")
        self.assertEqual(self._levels([target]), ["OK"])

    def test_a_bare_date_is_read_as_the_START_of_that_day(self):
        """Never fresher than reality: a date-only value must not round in our favour."""
        self.assertEqual(monitor._parse_when("2026-09-06"),
                         dt.datetime(2026, 9, 6, 0, 0, tzinfo=dt.timezone.utc))


if __name__ == "__main__":
    unittest.main()
