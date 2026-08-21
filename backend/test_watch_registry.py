#!/usr/bin/env python3
"""Contract tests for the Watch source registry; no network or managed DB required."""

import os
import sys
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from routers.watch_registry import WATCH_SOURCES, public_sources, validate_registry  # noqa: E402
from routers.watch import router as watch_router  # noqa: E402


class WatchRegistryTests(unittest.TestCase):
    def test_public_contract_exposes_only_enabled_sources(self):
        payload = public_sources()

        self.assertEqual("watch-source-v1", payload["schemaVersion"])
        self.assertEqual({"pwhl-youtube", "fiba-youtube", "fifa-plus"},
                         {row["id"] for row in payload["sources"]})
        self.assertIn("discovery metadata only", payload["publicationRule"])

    def test_event_specific_sources_are_not_claimed_as_generally_free(self):
        payload = {row["id"]: row for row in public_sources()["sources"]}

        self.assertEqual("event_specific", payload["fiba-youtube"]["availability"])
        self.assertEqual("event_specific", payload["fifa-plus"]["availability"])
        self.assertIn("Do not auto-publish", payload["fiba-youtube"]["titlePolicy"])

    def test_invalid_embed_source_fails_before_publication(self):
        bad = ({
            "id": "bad", "delivery": "youtube_embed", "availability": "always_free",
            "official_url": "https://example.test", "evidence_url": "https://example.test/evidence",
            "title_policy": "must verify", "channel": None,
        },)
        with self.assertRaisesRegex(ValueError, "official channel handle"):
            validate_registry(bad)

    def test_registry_is_exposed_by_a_read_only_route(self):
        routes = {route.path: route.methods for route in watch_router.routes}
        self.assertEqual({"GET"}, routes["/api/watch/sources"])


if __name__ == "__main__":
    unittest.main()
