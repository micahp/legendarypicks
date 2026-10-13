#!/usr/bin/env python3
"""Contract tests for the Watch source registry; no network or managed DB required."""

import os
import sys
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from routers.watch_registry import (  # noqa: E402
    WATCH_SOURCES,
    public_broadcasts,
    public_sources,
    validate_broadcasts,
    validate_registry,
)
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
        self.assertEqual({"GET"}, routes["/api/watch/broadcasts"])

    def test_broadcast_contract_only_returns_concrete_verified_embeds(self):
        payload = public_broadcasts()

        self.assertEqual("watch-broadcast-v1", payload["schemaVersion"])
        self.assertEqual(1, len(payload["broadcasts"]))
        self.assertEqual("WhVHB8C9mPY", payload["broadcasts"][0]["videoId"])
        self.assertEqual("ended", payload["broadcasts"][0]["status"])

    def test_unverified_broadcast_cannot_be_published(self):
        bad = ({
            "id": "bad", "source_id": "fiba-youtube", "title": "Bad", "competition": "Test",
            "video_id": "abc123", "status": "live", "checked_at": "2026-08-21T00:00:00Z",
            "embed_verified": False, "free_verified": True, "official_verified": True,
        },)
        with self.assertRaisesRegex(ValueError, "publication checks"):
            validate_broadcasts(bad)


if __name__ == "__main__":
    unittest.main()
