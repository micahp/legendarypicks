#!/usr/bin/env python3
"""Fixture-driven tests for the EWC per-title schedule fetcher (Liquipedia MediaWiki API).

No network: parse/publish logic runs against the committed rev fixtures
(docs/ewc2026/fixtures/liquipedia-schedule-{chess,rocketleague,counterstrike}-20260809.json)
plus synthetic wikitext for edge cases. Covers date/opponent normalization, qualifier
exclusion, pending participants (never fabricated), no-template pages, snapshot build
(weeks/datedCount/checksum), and publish/read roundtrip.
"""

import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fetch_ewc_title_schedules as fetcher  # noqa: E402

FIX = os.path.join(HERE, "..", "docs", "ewc2026", "fixtures")


def _fixture(name):
    with open(os.path.join(FIX, "liquipedia-schedule-%s-20260809.json" % name)) as f:
        return json.load(f)["parse"]["wikitext"]["*"]


class DateParsingTests(unittest.TestCase):
    def test_iso_date(self):
        iso, ms = fetcher.parse_date("2026-08-11")
        self.assertEqual(iso, "2026-08-11")
        self.assertIsNotNone(ms)

    def test_natural_date_with_timezone(self):
        iso, ms = fetcher.parse_date("August 12, 2026 - 17:10 {{Abbr/CEST}}")
        self.assertEqual(iso, "2026-08-12")
        self.assertIsNotNone(ms)

    def test_natural_date_no_time(self):
        iso, ms = fetcher.parse_date("August 12, 2026")
        self.assertEqual(iso, "2026-08-12")
        self.assertIsNotNone(ms)

    def test_empty_is_none(self):
        self.assertEqual(fetcher.parse_date(""), (None, None))
        self.assertEqual(fetcher.parse_date(" "), (None, None))
        self.assertEqual(fetcher.parse_date(None), (None, None))

    def test_malformed_published_date_is_rejected(self):
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.parse_date("August 41, 2026")
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.parse_date("TBD")


class OpponentParsingTests(unittest.TestCase):
    def test_named_team_opponent(self):
        kind, name, slug, score = fetcher.parse_opponent("{{TeamOpponent|Twisted Minds|score=}}")
        self.assertEqual((kind, name, slug), ("named", "Twisted Minds", "Twisted_Minds"))
        self.assertIsNone(score)

    def test_named_team_with_score(self):
        kind, name, slug, score = fetcher.parse_opponent("{{TeamOpponent|Team Falcons|score=2}}")
        self.assertEqual((kind, name, score), ("named", "Team Falcons", 2))

    def test_literal_opponent_is_pending_not_fabricated(self):
        kind, name, slug, score = fetcher.parse_opponent("{{LiteralOpponent|LCQ #1|score=}}")
        self.assertEqual((kind, name, slug), ("pending", "LCQ #1", None))

    def test_empty_team_opponent_is_pending(self):
        kind, name, _, _ = fetcher.parse_opponent("{{TeamOpponent|}}")
        self.assertEqual((kind, name), ("pending", None))

    def test_numeric_opponent_slot_is_pending(self):
        kind, name, _, _ = fetcher.parse_opponent("{{1Opponent|}}")
        self.assertEqual((kind, name), ("pending", None))

    def test_plain_name_is_named(self):
        kind, name, slug, _ = fetcher.parse_opponent("[[Team Secret|Team Secret]]")
        self.assertEqual((kind, name, slug), ("named", "Team Secret", "Team_Secret"))

    def test_empty_value_is_pending(self):
        kind, name, _, _ = fetcher.parse_opponent("")
        self.assertEqual((kind, name), ("pending", None))

    def test_unknown_opponent_template_is_rejected(self):
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.parse_opponent("{{MysteryOpponent|Team X}}")

    def test_malformed_score_is_rejected(self):
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.parse_opponent("{{TeamOpponent|Team X|score=won}}")


class FixtureParseTests(unittest.TestCase):
    def test_chess_fixture_all_dated_pending(self):
        rows = fetcher.build_rows(_fixture("chess"))
        self.assertEqual(len(rows), 13)
        self.assertTrue(all(r["startTime"] for r in rows))
        self.assertTrue(all(r["teamAPending"] and r["teamBPending"] for r in rows))

    def test_rocketleague_fixture_named_and_pending(self):
        rows = fetcher.build_rows(_fixture("rocketleague"))
        self.assertEqual(len(rows), 28)
        named = [r for r in rows if not r["teamAPending"]]
        self.assertGreaterEqual(len(named), 5)
        self.assertTrue(any(r["teamBPending"] for r in rows))  # LCQ slots stay pending
        self.assertTrue(all(r["startTime"] for r in rows))
        for r in rows:
            self.assertIsNone(r["scoreA"])  # no fabricated scores
            self.assertFalse(r["finished"])

    def test_counterstrike_fixture_dates_not_published(self):
        rows = fetcher.build_rows(_fixture("counterstrike"))
        self.assertGreaterEqual(len(rows), 20)
        self.assertTrue(all(r["startTime"] is None for r in rows))  # dates not published yet
        self.assertTrue(all(r["teamAPending"] and r["teamBPending"] for r in rows))

    def test_qualifier_rows_excluded(self):
        w = ("{{Stage|Main Event}}\n{{Match\n|date=2026-08-12\n|opponent1={{TeamOpponent|A}}\n"
             "|opponent2={{TeamOpponent|B}}\n}}\n"
             "{{Stage|Last Chance Qualifier}}\n{{Match\n|date=2026-08-10\n"
             "|opponent1={{TeamOpponent|Q1}}\n|opponent2={{TeamOpponent|Q2}}\n}}\n")
        rows = fetcher.build_rows(w)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["teamA"], "A")
        self.assertIn("Main Event", rows[0]["stage"])

    def test_lcq_stage_excluded(self):
        w = ("{{Stage|LCQ}}\n{{Match\n|date=2026-08-10\n"
             "|opponent1={{TeamOpponent|Q1}}\n|opponent2={{TeamOpponent|Q2}}\n}}\n")
        self.assertEqual(fetcher.build_rows(w), [])

    def test_no_match_templates_yields_empty(self):
        self.assertEqual(fetcher.build_rows("{{Infobox league|name=X}}"), [])
        self.assertEqual(fetcher.build_rows(""), [])

    def test_unknown_numbered_match_template_rejects_mixed_page(self):
        w = ("{{Match\n|date=2026-08-12\n|opponent1={{TeamOpponent|A}}\n"
             "|opponent2={{TeamOpponent|B}}\n}}\n"
             "{{Match3\n|date=2026-08-13\n|opponent1={{TeamOpponent|C}}\n"
             "|opponent2={{TeamOpponent|D}}\n}}")
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.build_rows(w)

    def test_scores_only_marked_finished_when_dated(self):
        w = ("{{Match\n|date=2026-08-12\n|opponent1={{TeamOpponent|A|score=3}}\n"
             "|opponent2={{TeamOpponent|B|score=1}}\n|finished=true\n}}\n"
             "{{Match\n|date=2026-08-13\n|opponent1={{TeamOpponent|C}}\n"
             "|opponent2={{TeamOpponent|D}}\n}}\n"
             "{{Match\n|opponent1={{TeamOpponent|E|score=2}}\n"
             "|opponent2={{TeamOpponent|F|score=1}}\n}}\n")
        rows = fetcher.build_rows(w)
        self.assertTrue(rows[0]["finished"])   # finished flag
        self.assertFalse(rows[1]["finished"])  # dated but no scores yet
        self.assertFalse(rows[2]["finished"])  # scores but no date -> not a verifiable result


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ewc-sched-")
        self.old_dir = fetcher.SCHEDULES_DIR
        fetcher.SCHEDULES_DIR = self.dir

    def tearDown(self):
        fetcher.SCHEDULES_DIR = self.old_dir

    def test_snapshot_build_dates_lifecycle_and_checksum(self):
        rows = fetcher.build_rows(_fixture("chess"), source_key="chess:Esports World Cup/2026")
        snap = fetcher.build_snapshot("chess", rows, [34705], "2026-08-09T00:00:00+00:00",
                                      lifecycle="upcoming")
        fetcher.validate_snapshot(snap, expected_slug="chess")
        self.assertEqual(snap["schemaVersion"], 1)
        self.assertEqual(snap["event"], "ewc-2026")
        self.assertEqual(snap["slug"], "chess")
        self.assertEqual(snap["lifecycle"], "upcoming")
        self.assertEqual(snap["schedule"]["status"], "published")
        self.assertEqual(snap["schedule"]["count"], 13)
        self.assertEqual(snap["schedule"]["datedCount"], 13)
        self.assertEqual(snap["schedule"]["firstDate"], "2026-08-11")
        self.assertEqual(snap["schedule"]["lastDate"], "2026-08-11")
        self.assertEqual(snap["source"]["revisions"], [34705])
        self.assertTrue(snap["source"]["checksum"])
        self.assertEqual(len({row["sourceMatchId"] for row in snap["matches"]}), 13)

    def test_empty_snapshot_is_rejected(self):
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.build_snapshot("apex-legends", [], [123], "2026-08-09T00:00:00+00:00")

    def test_final_snapshot_requires_completion_evidence(self):
        rows = fetcher.build_rows(
            "{{Match\n|date=2026-08-11\n|opponent1={{1Opponent|Magnus Carlsen}}\n"
            "|opponent2={{1Opponent|Hikaru Nakamura}}\n|finished=true\n}}",
            source_key="chess:Esports World Cup/2026",
        )
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.build_snapshot("chess", rows, [34705], "2026-08-09T00:00:00+00:00",
                                   lifecycle="final")
        snap = fetcher.build_snapshot(
            "chess", rows, [34705], "2026-08-09T00:00:00+00:00", lifecycle="final",
            finality={"allMatchesResolved": True, "participantsComplete": True,
                      "sourceRevisionRecorded": True},
        )
        fetcher.validate_snapshot(snap, expected_slug="chess")

    def test_publish_read_roundtrip_and_last_good(self):
        rows = fetcher.build_rows(_fixture("chess"), source_key="chess:Esports World Cup/2026")
        snap = fetcher.build_snapshot("chess", rows, [34705], "2026-08-09T00:00:00+00:00")
        path = fetcher.publish("chess", snap)
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path + ".tmp"))
        got = fetcher.read_snapshot("chess")
        self.assertEqual(got["schedule"]["count"], 13)
        self.assertEqual(got["source"]["checksum"], snap["source"]["checksum"])
        manifest = fetcher.read_manifest()
        self.assertEqual(set(manifest["titles"]), set(fetcher.TITLE_PAGES))
        self.assertEqual(manifest["titles"]["chess"]["checksum"], snap["source"]["checksum"])

        bad = json.loads(json.dumps(snap))
        bad["matches"].append(dict(bad["matches"][0]))
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.publish("chess", bad)
        self.assertEqual(fetcher.read_snapshot("chess")["source"]["checksum"],
                         snap["source"]["checksum"])

    def test_manifest_rejects_wrong_catalog_and_checksum(self):
        manifest = fetcher.build_manifest()
        fetcher.validate_manifest(manifest)
        del manifest["titles"]["valorant"]
        with self.assertRaises(fetcher.ScheduleSourceError):
            fetcher.validate_manifest(manifest)

    def test_tampered_snapshot_fails_closed(self):
        rows = fetcher.build_rows(_fixture("chess"), source_key="chess:Esports World Cup/2026")
        snap = fetcher.build_snapshot("chess", rows, [34705], "2026-08-09T00:00:00+00:00")
        path = fetcher.publish("chess", snap)
        with open(path) as f:
            tampered = json.load(f)
        tampered["matches"][0]["teamA"] = "Changed after publication"
        with open(path, "w") as f:
            json.dump(tampered, f)
        self.assertIsNone(fetcher.read_snapshot("chess"))

    def test_stale_upcoming_snapshot_fails_closed_but_final_does_not_expire(self):
        rows = fetcher.build_rows(_fixture("chess"), source_key="chess:Esports World Cup/2026")
        upcoming = fetcher.build_snapshot("chess", rows, [34705], "2020-01-01T00:00:00+00:00")
        upcoming["publishedAt"] = "2020-01-01T00:00:00+00:00"
        upcoming["source"]["publishedAt"] = upcoming["publishedAt"]
        upcoming["source"]["checksum"] = fetcher._snapshot_checksum(upcoming)
        fetcher.publish("chess", upcoming)
        self.assertIsNone(fetcher.read_snapshot("chess"))

        final_rows = fetcher.build_rows(
            "{{Match\n|date=2026-08-11\n|opponent1={{1Opponent|Magnus Carlsen}}\n"
            "|opponent2={{1Opponent|Hikaru Nakamura}}\n|finished=true\n}}",
            source_key="chess:Esports World Cup/2026",
        )
        final = fetcher.build_snapshot(
            "chess", final_rows, [34705], "2020-01-01T00:00:00+00:00", lifecycle="final",
            finality={"allMatchesResolved": True, "participantsComplete": True,
                      "sourceRevisionRecorded": True},
        )
        final["publishedAt"] = "2020-01-01T00:00:00+00:00"
        final["source"]["publishedAt"] = final["publishedAt"]
        final["source"]["checksum"] = fetcher._snapshot_checksum(final)
        fetcher.publish("chess", final)
        self.assertEqual(fetcher.read_snapshot("chess")["lifecycle"], "final")

    def test_read_missing_snapshot_is_none(self):
        self.assertIsNone(fetcher.read_snapshot("does-not-exist"))


class OperatorCommandTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ewc-operator-")
        self.old_dir = fetcher.SCHEDULES_DIR
        fetcher.SCHEDULES_DIR = self.dir

    def tearDown(self):
        fetcher.SCHEDULES_DIR = self.old_dir

    def test_requested_failure_returns_nonzero(self):
        with mock.patch.object(fetcher, "_api_get", side_effect=RuntimeError("source down")):
            self.assertEqual(fetcher.main(["--slug", "chess", "--dry-run"]), 1)

    def test_parse_requests_wait_for_the_publisher_slot(self):
        old_last = fetcher._LAST_PARSE_REQUEST
        fetcher._LAST_PARSE_REQUEST = 100.0
        try:
            with mock.patch.object(fetcher.time, "monotonic", side_effect=[110.0, 130.0]), \
                    mock.patch.object(fetcher.time, "sleep") as sleep:
                fetcher._wait_for_parse_slot()
            sleep.assert_called_once_with(20.0)
            self.assertEqual(fetcher._LAST_PARSE_REQUEST, 130.0)
        finally:
            fetcher._LAST_PARSE_REQUEST = old_last

    def test_final_rate_limit_attempt_fails_without_an_extra_sleep(self):
        error = urllib.error.HTTPError(
            "https://liquipedia.invalid", 429, "Too Many Requests",
            {"Retry-After": "60"}, None,
        )
        with mock.patch.object(fetcher, "_wait_for_parse_slot"), \
                mock.patch.object(fetcher._API_OPENER, "open", side_effect=error), \
                mock.patch.object(fetcher.time, "sleep") as sleep:
            with self.assertRaisesRegex(fetcher.ScheduleSourceError, "Retry-After=60"):
                fetcher._api_get("chess", "Esports World Cup/2026", retries=1)
        sleep.assert_not_called()

    def test_final_snapshot_is_skipped_without_override(self):
        rows = fetcher.build_rows(
            "{{Match\n|date=2026-08-11\n|opponent1={{1Opponent|Magnus Carlsen}}\n"
            "|opponent2={{1Opponent|Hikaru Nakamura}}\n|finished=true\n}}",
            source_key="chess:Esports World Cup/2026",
        )
        snap = fetcher.build_snapshot(
            "chess", rows, [34705], "2026-08-09T00:00:00+00:00", lifecycle="final",
            finality={"allMatchesResolved": True, "participantsComplete": True,
                      "sourceRevisionRecorded": True},
        )
        fetcher.publish("chess", snap)
        with mock.patch.object(fetcher, "_api_get") as api_get:
            self.assertEqual(fetcher.main(["--slug", "chess", "--dry-run"]), 0)
        api_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
