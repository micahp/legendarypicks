"""The disk cache must answer to the caller's freshness requirement.

`Fetcher.cache_ttl` is the instance default — 12 hours, which is what the bulk
ingest scripts want so a re-run costs nothing. The serving paths ask for much
less: espn_client requests the scoreboard at ttl=20 and standings at ttl=900.

Before this, `_read_disk` compared against `cache_ttl` no matter what the caller
asked for, so configuring a disk cache would have served a 12-hour-old score to
a page that asked for a 20-second one. Enabling the cache in prod is the whole
point of the change these tests guard, so the trap has to stay shut.
"""
import os
import tempfile
import time
import unittest

import paced_http


class DiskCacheHonoursCallerTtl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fetcher = paced_http.Fetcher(
            min_interval=0.0, retry_waits=(), cache_dir=self.tmp.name, cache_ttl=43200,
        )
        self.addCleanup(self.tmp.cleanup)

    def seed(self, url, payload, age_seconds):
        self.fetcher._write_disk(url, payload)
        path = self.fetcher._path(url)
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))

    def test_an_entry_older_than_the_requested_ttl_is_a_miss(self):
        self.seed("http://x/scoreboard", {"score": "stale"}, age_seconds=60)
        self.assertIsNone(self.fetcher._read_disk("http://x/scoreboard", ttl=20))

    def test_an_entry_inside_the_requested_ttl_is_a_hit(self):
        self.seed("http://x/scoreboard", {"score": "fresh"}, age_seconds=5)
        self.assertEqual(
            self.fetcher._read_disk("http://x/scoreboard", ttl=20), {"score": "fresh"}
        )

    def test_a_caller_naming_no_ttl_still_gets_the_instance_default(self):
        """What the bulk scripts depend on: a re-run inside 12h costs nothing."""
        self.seed("http://x/bulk", {"rows": 578}, age_seconds=3600)
        self.assertEqual(self.fetcher._read_disk("http://x/bulk"), {"rows": 578})

    def test_the_caller_cannot_ask_for_longer_than_the_instance_allows(self):
        self.seed("http://x/bulk", {"rows": 578}, age_seconds=50000)
        self.assertIsNone(self.fetcher._read_disk("http://x/bulk", ttl=99999))

    def test_no_cache_dir_is_always_a_miss(self):
        bare = paced_http.Fetcher(min_interval=0.0, retry_waits=(), cache_dir="")
        self.assertIsNone(bare._read_disk("http://x/anything", ttl=20))


class DiskCacheIsBounded(unittest.TestCase):
    """Re-enabling a cache with no eviction is how the last one reached 134MB."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fetcher = paced_http.Fetcher(
            min_interval=0.0, retry_waits=(), cache_dir=self.tmp.name, cache_ttl=3600,
        )

    def age(self, url, seconds):
        path = self.fetcher._path(url)
        stamp = time.time() - seconds
        os.utime(path, (stamp, stamp))

    def test_sweep_drops_expired_entries_and_keeps_live_ones(self):
        self.fetcher._write_disk("http://x/old", {"a": 1})
        self.fetcher._write_disk("http://x/new", {"a": 2})
        self.age("http://x/old", 7200)
        self.fetcher._sweep()
        self.assertFalse(os.path.exists(self.fetcher._path("http://x/old")))
        self.assertTrue(os.path.exists(self.fetcher._path("http://x/new")))

    def test_sweep_leaves_files_it_did_not_write(self):
        stranger = os.path.join(self.tmp.name, "picks.db")
        with open(stranger, "w") as handle:
            handle.write("not mine")
        os.utime(stranger, (0, 0))
        self.fetcher._sweep()
        self.assertTrue(os.path.exists(stranger))

    def test_writes_trigger_a_sweep_without_being_asked(self):
        self.fetcher._sweep_every = 3
        self.fetcher._write_disk("http://x/stale", {"a": 1})
        self.age("http://x/stale", 7200)
        for i in range(3):
            self.fetcher._write_disk(f"http://x/{i}", {"a": i})
        self.assertFalse(os.path.exists(self.fetcher._path("http://x/stale")))


if __name__ == "__main__":
    unittest.main()
