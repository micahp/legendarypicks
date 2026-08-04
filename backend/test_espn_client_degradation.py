#!/usr/bin/env python3
"""An upstream refusal is not the same as having no data.

On 2026-08-04 ESPN 403'd this box and every scores and standings surface
returned 500 the moment the 30s cache expired. The page then rendered "No data
available for NBA", which reads as *we have no standings* rather than *we could
not reach the publisher just now* -- our data taking the blame for their outage.
"""

import unittest
import urllib.error
import urllib.request
from unittest import mock

import espn_client


class HostTest(unittest.TestCase):
    def test_scores_and_standings_do_not_point_at_the_host_that_refused(self):
        # site.api.espn.com 403s this box; site.web.api.espn.com serves the
        # identical paths. Verified 8 of 8 across four leagues, both shapes.
        self.assertNotIn("//site.api.espn.com", espn_client._SITE)
        self.assertNotIn("//site.api.espn.com", espn_client._CORE)


class DegradationTest(unittest.TestCase):
    def setUp(self):
        self.url = "https://site.web.api.espn.com/apis/v2/sports/test/standings"
        espn_client._CACHE.pop(self.url, None)
        self.addCleanup(espn_client._CACHE.pop, self.url, None)

    def refuse(self, *_args, **_kwargs):
        raise urllib.error.HTTPError(self.url, 403, "Forbidden", None, None)

    def test_a_403_serves_the_last_good_payload_instead_of_raising(self):
        espn_client._CACHE[self.url] = (0, {"standings": "last good"})
        with mock.patch.object(urllib.request, "urlopen", self.refuse):
            self.assertEqual(
                espn_client._get(self.url), {"standings": "last good"}
            )

    def test_it_retries_rather_than_serving_stale_forever(self):
        espn_client._CACHE[self.url] = (0, {"standings": "last good"})
        with mock.patch.object(urllib.request, "urlopen", self.refuse):
            espn_client._get(self.url)
        expires, _payload = espn_client._CACHE[self.url]
        import time
        self.assertLessEqual(expires - time.time(), 60.5)

    def test_with_nothing_cached_it_still_fails(self):
        # Serving invented emptiness would be worse than failing: an empty
        # standings table is indistinguishable from a real one with no rows.
        with mock.patch.object(urllib.request, "urlopen", self.refuse):
            with self.assertRaises(urllib.error.HTTPError):
                espn_client._get(self.url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
