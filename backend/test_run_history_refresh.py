import os
import sqlite3
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_history_refresh as runner


class HistoryRefreshTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="history-refresh-", suffix=".db", delete=False
        )
        handle.close()
        self.db_path = handle.name
        connection = sqlite3.connect(self.db_path)
        connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.close()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_jobs_are_run_sequentially_in_declared_order(self):
        order = []

        def first(db_path, apply, emit):
            order.append(("first", db_path, apply))
            return {"status": "dry_run"}

        def second(db_path, apply, emit):
            order.append(("second", db_path, apply))
            return {"status": "current"}

        result = runner.run(
            self.db_path,
            apply=False,
            emit=lambda _: None,
            jobs=[
                runner.RefreshJob("first", first),
                runner.RefreshJob("second", second),
            ],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["first", "second"], [item[0] for item in order])
        self.assertTrue(all(item[1] == self.db_path for item in order))
        self.assertTrue(all(item[2] is False for item in order))

    def test_one_failure_is_reported_and_next_job_still_runs(self):
        order = []

        def broken(db_path, apply, emit):
            order.append("broken")
            raise ValueError("source unavailable")

        def healthy(db_path, apply, emit):
            order.append("healthy")
            return {"status": "applied"}

        result = runner.run(
            self.db_path,
            apply=True,
            emit=lambda _: None,
            jobs=[
                runner.RefreshJob("broken", broken),
                runner.RefreshJob("healthy", healthy),
            ],
        )

        self.assertFalse(result["ok"])
        self.assertEqual(["broken", "healthy"], order)
        self.assertEqual("ValueError", result["failures"]["broken"]["error_type"])
        self.assertEqual("applied", result["results"]["healthy"]["status"])

    def test_invalid_database_stops_before_any_job(self):
        called = []
        with open(self.db_path, "wb") as handle:
            handle.write(b"not sqlite")

        with self.assertRaises(sqlite3.DatabaseError):
            runner.run(
                self.db_path,
                apply=False,
                emit=lambda _: None,
                jobs=[
                    runner.RefreshJob(
                        "never",
                        lambda *_: called.append(True),
                    )
                ],
            )

        self.assertEqual([], called)


if __name__ == "__main__":
    unittest.main(verbosity=2)
