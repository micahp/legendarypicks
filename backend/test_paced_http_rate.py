#!/usr/bin/env python3
"""The per-host short-window rate limit.

Why a RATE and not a count: measured 2026-08-19 over 27,801 ESPN requests, the
hour before a 403 is indistinguishable from the hour before a 200 (median 1238
vs 1266) while the MINUTE before is not (63 vs 36). See
docs/DESIGN-request-budget.md §1b.

The case these tests exist for is the serving path. A request handler must
REFUSE rather than wait: on 2026-08-18 prod slept 46 minutes because the count
budget slept in a handler. A second mechanism that can sleep is a second chance
to make that mistake, so it is pinned here.
"""
import time
import unittest

import paced_http


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self._rate, self._window = paced_http.HOST_RATE, paced_http.RATE_WINDOW
        paced_http.HOST_RATE, paced_http.RATE_WINDOW = 5, 2.0
        paced_http.reset_host_budget()
        self.addCleanup(paced_http.reset_host_budget)
        self.addCleanup(setattr, paced_http, "RATE_WINDOW", self._window)
        self.addCleanup(setattr, paced_http, "HOST_RATE", self._rate)

    def test_requests_under_the_cap_do_not_wait(self):
        t0 = time.time()
        for _ in range(5):
            paced_http._pace_rate("https://example.test/a", "sleep")
        self.assertLess(time.time() - t0, 0.5)

    def test_a_batch_job_waits_for_the_window(self):
        for _ in range(5):
            paced_http._pace_rate("https://example.test/a", "sleep")
        waited = paced_http._pace_rate("https://example.test/a", "sleep")
        self.assertGreater(waited, 1.0)

    def test_a_serving_path_refuses_instead_of_sleeping(self):
        # The 2026-08-18 prod incident, in one assertion.
        for _ in range(5):
            paced_http._pace_rate("https://example.test/a", "refuse")
        t0 = time.time()
        with self.assertRaises(paced_http.BudgetExhausted):
            paced_http._pace_rate("https://example.test/a", "refuse")
        self.assertLess(time.time() - t0, 0.5, "a handler must not pause")

    def test_the_limit_is_per_host(self):
        for _ in range(5):
            paced_http._pace_rate("https://a.test/x", "refuse")
        paced_http._pace_rate("https://b.test/x", "refuse")  # must not raise

    def test_the_window_slides_rather_than_resetting(self):
        for _ in range(5):
            paced_http._pace_rate("https://example.test/a", "sleep")
        time.sleep(2.05)
        t0 = time.time()
        paced_http._pace_rate("https://example.test/a", "refuse")
        self.assertLess(time.time() - t0, 0.5)

    def test_setting_the_rate_to_zero_disables_it(self):
        # The escape hatch. A publisher we have never seen refuse should not
        # inherit ESPN's ceiling.
        paced_http.HOST_RATE = 0
        for _ in range(50):
            paced_http._pace_rate("https://example.test/a", "refuse")

    def test_process_lifetime_does_not_exhaust_a_serving_path(self):
        """The API must still work after its hundredth lifetime request."""
        for _ in range(250):
            paced_http._charge(
                "https://example.test/a", budget=100, cooldown=60,
                on_exhausted="refuse",
            )
        self.assertEqual(paced_http._host_spend, {})


class ProcessLabelTests(unittest.TestCase):
    """`python -m pkg` must not log as `__main__.py`.

    3,043 requests, 11% of one day's ESPN traffic, were unattributable because
    every `-m` invocation collapsed to one label, `python -m pytest` included.
    """

    def _who(self, argv0):
        import sys
        old = sys.argv
        sys.argv = [argv0]
        try:
            return paced_http._who()
        finally:
            sys.argv = old

    def test_a_package_run_with_dash_m_reports_the_package(self):
        self.assertEqual(
            self._who("/root/legendarypicks/backend/bovada_scraper/__main__.py"),
            "bovada_scraper")

    def test_the_test_runner_is_named(self):
        self.assertEqual(
            self._who("/venv/lib/python3.8/site-packages/pytest/__main__.py"), "pytest")

    def test_a_plain_script_is_unchanged(self):
        self.assertEqual(self._who("/x/backend/ingest_scoreboards.py"),
                         "ingest_scoreboards.py")


if __name__ == "__main__":
    unittest.main()
