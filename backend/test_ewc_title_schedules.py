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

    def test_empty_or_unparseable_is_none(self):
        self.assertEqual(fetcher.parse_date(""), (None, None))
        self.assertEqual(fetcher.parse_date(" "), (None, None))
        self.assertEqual(fetcher.parse_date("TBD"), (None, None))
        self.assertEqual(fetcher.parse_date(None), (None, None))


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

    def test_snapshot_build_weeks_and_counts(self):
        rows = fetcher.build_rows(_fixture("chess"))
        snap = fetcher.build_snapshot("chess", rows, [34705], "2026-08-09T00:00:00+00:00")
        self.assertEqual(snap["event"], "ewc-2026")
        self.assertEqual(snap["slug"], "chess")
        self.assertEqual(snap["schedule"]["status"], "published")
        self.assertEqual(snap["schedule"]["count"], 13)
        self.assertEqual(snap["schedule"]["datedCount"], 13)
        self.assertTrue(snap["schedule"]["weeks"])
        self.assertEqual(snap["source"]["revisions"], [34705])
        self.assertTrue(snap["source"]["checksum"])

    def test_empty_snapshot_is_unavailable(self):
        snap = fetcher.build_snapshot("apex-legends", [], [123], "2026-08-09T00:00:00+00:00")
        self.assertEqual(snap["schedule"]["status"], "unavailable")
        self.assertEqual(snap["schedule"]["count"], 0)

    def test_publish_read_roundtrip_and_last_good(self):
        rows = fetcher.build_rows(_fixture("chess"))
        snap = fetcher.build_snapshot("chess", rows, [34705], "2026-08-09T00:00:00+00:00")
        path = fetcher.publish("chess", snap)
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(path + ".tmp"))
        got = fetcher.read_snapshot("chess")
        self.assertEqual(got["schedule"]["count"], 13)
        self.assertEqual(got["source"]["checksum"], snap["source"]["checksum"])

    def test_read_missing_snapshot_is_none(self):
        self.assertIsNone(fetcher.read_snapshot("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
