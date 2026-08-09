#!/usr/bin/env python3
"""Fixture-driven tests for the Liquipedia Club Championship standings fetcher.

No network: parse/publish logic runs against the committed rev-15997 fixtures
(docs/ewc2026/fixtures/liquipedia-ewc-standings-20260809.json + -wikitext-). Covers
stage selection, the exact 90-row population, ties, duplicate club IDs, incomplete
population, malformed stage, point/rank inversion, and last-good survival.
"""

import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_TEST_DB = tempfile.NamedTemporaryFile(prefix="ewc-fetcher-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers.esports import ewc  # noqa: E402
import fetch_ewc_standings as fetcher  # noqa: E402

FIX = os.path.join(HERE, "..", "docs", "ewc2026", "fixtures")
TEXT_FIX = os.path.join(FIX, "liquipedia-ewc-standings-20260809.json")
WIKI_FIX = os.path.join(FIX, "liquipedia-ewc-wikitext-20260809.json")

REV = 15997


def _fixture_html():
    with open(TEXT_FIX) as f:
        return json.load(f)["parse"]["text"]["*"]


def _fixture_wikitext():
    with open(WIKI_FIX) as f:
        return json.load(f)["parse"]["wikitext"]["*"]


def _snapshot(rows, source_count=None, published_at=None):
    if published_at is None:
        published_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return {
        "event": "ewc-2026",
        "publishedAt": published_at,
        "source": {
            "label": "Test",
            "url": "https://example.invalid",
            "revision": REV,
            "fetchedAt": published_at,
            "sourceReportedClubs": source_count if source_count is not None else len(rows),
            "fetchedClubs": len(rows),
            "checksum": "c",
        },
        "standings": rows,
    }


class StageSelectionTests(unittest.TestCase):
    def test_fixture_stage_is_5_cutoff_19(self):
        self.assertEqual(fetcher.parse_stage(_fixture_wikitext()), (5, 19))

    def test_malformed_stage_missing_current(self):
        with self.assertRaises(fetcher.StandingsSourceError):
            fetcher.parse_stage("stage5cutoff=19\n")

    def test_malformed_stage_missing_cutoff(self):
        with self.assertRaises(fetcher.StandingsSourceError):
            fetcher.parse_stage("current-stage=5\nstage4cutoff=14\n")

    def test_malformed_stage_bad_values(self):
        with self.assertRaises(fetcher.StandingsSourceError):
            fetcher.parse_stage("current-stage=0\nstage0cutoff=19\n")


class PopulationParseTests(unittest.TestCase):
    def test_fixture_parses_exact_90_unique_rows(self):
        rows = fetcher.parse_rows(_fixture_html(), 19)
        self.assertEqual(len(rows), 90)
        slugs = [r["clubId"] for r in rows]
        self.assertEqual(len(slugs), len(set(slugs)), "clubIds must be unique")
        for r in rows:
            self.assertIsInstance(r["rank"], int)
            self.assertIsInstance(r["clubId"], str)
            self.assertIsInstance(r["clubName"], str)
            self.assertIsInstance(r["points"], int)
            self.assertGreaterEqual(r["points"], 0)

    def test_top_rows_match_research(self):
        rows = fetcher.parse_rows(_fixture_html(), 19)
        top = [(r["rank"], r["clubName"], r["points"]) for r in rows[:10]]
        self.assertEqual(top, [
            (1, "AG.AL International", 3350),
            (2, "Team Falcons", 2900),
            (3, "Natus Vincere", 2250),
            (4, "Team Vitality", 2200),
            (4, "Virtus.pro", 2200),
            (6, "T1", 1750),
            (6, "Team Vision", 1750),
            (8, "Twisted Minds", 1700),
            (9, "ZETA DIVISION", 1500),
            (10, "100 Thieves", 1300),
        ])

    def test_club_ids_are_stable_liquipedia_slugs(self):
        rows = fetcher.parse_rows(_fixture_html(), 19)
        by_name = {r["clubName"]: r["clubId"] for r in rows}
        self.assertEqual(by_name["AG.AL International"], "AG.AL_International")
        self.assertEqual(by_name["Team Falcons"], "Team_Falcons")
        self.assertEqual(by_name["Virtus.pro"], "Virtus.pro")

    def test_no_rows_for_unknown_cutoff_is_malformed(self):
        with self.assertRaises(fetcher.StandingsSourceError):
            fetcher.parse_rows(_fixture_html(), 999)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="ewc-fetcher-pub-", suffix=".json")
        os.close(fd)
        os.unlink(self.path)

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def _rows_from_fixture(self):
        return fetcher.parse_rows(_fixture_html(), 19)

    def test_fixture_snapshot_publishes_and_reads_current(self):
        rows = self._rows_from_fixture()
        snap = fetcher.build_snapshot(rows, REV, 5, 19, time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))
        ewc.publish_standings(snap, path=self.path)
        # The committed snapshot file carries full source attribution.
        with open(self.path) as f:
            stored = json.load(f)
        self.assertEqual(stored["source"]["revision"], REV)
        self.assertEqual(stored["source"]["stage"], 5)
        self.assertEqual(stored["source"]["stageCutoff"], 19)
        self.assertEqual(stored["source"]["label"], fetcher.SOURCE_LABEL)
        self.assertEqual(stored["source"]["url"], fetcher.SOURCE_URL)
        self.assertEqual(stored["source"]["sourceReportedClubs"], 90)
        self.assertEqual(stored["source"]["fetchedClubs"], 90)
        self.assertTrue(stored["source"]["fetchedAt"])
        self.assertTrue(stored["source"]["publishedAt"])
        self.assertTrue(stored["source"]["checksum"])
        # The API reader serves the rows with its existing source contract.
        out = ewc.read_standings(path=self.path)
        self.assertEqual(out["status"], "current")
        self.assertEqual(len(out["standings"]), 90)
        self.assertEqual(out["standings"][0]["clubName"], "AG.AL International")
        self.assertEqual(out["source"]["label"], fetcher.SOURCE_LABEL)
        self.assertEqual(out["source"]["url"], fetcher.SOURCE_URL)

    def test_incomplete_population_rejected(self):
        rows = self._rows_from_fixture()[:89]
        snap = _snapshot(rows, source_count=90)
        with self.assertRaises(ValueError):
            ewc.publish_standings(snap, path=self.path)

    def test_duplicate_club_id_rejected(self):
        rows = self._rows_from_fixture()
        rows[1]["clubId"] = rows[0]["clubId"]  # duplicate slug
        with self.assertRaises(ValueError):
            ewc.publish_standings(_snapshot(rows), path=self.path)

    def test_point_regression_rejected_without_correction_flag(self):
        rows = self._rows_from_fixture()
        good = fetcher.build_snapshot(rows, REV, 5, 19, "2026-08-09T00:00:00+00:00")
        ewc.publish_standings(good, path=self.path)
        bad = json.loads(json.dumps(good))
        bad["standings"][0]["points"] = 100  # AG.AL 3350 -> 100 (regression)
        with self.assertRaises(ValueError):
            ewc.publish_standings(bad, path=self.path)
        # Last good survives.
        out = ewc.read_standings(path=self.path)
        self.assertEqual(out["status"], "current")
        self.assertEqual(out["standings"][0]["points"], 3350)

    def test_last_good_survives_failed_candidate(self):
        rows = self._rows_from_fixture()
        good = fetcher.build_snapshot(rows, REV, 5, 19, "2026-08-09T00:00:00+00:00")
        ewc.publish_standings(good, path=self.path)
        # A candidate that fails validation (incomplete population) never replaces it.
        with self.assertRaises(ValueError):
            ewc.publish_standings(_snapshot(rows[:10], source_count=90), path=self.path)
        out = ewc.read_standings(path=self.path)
        self.assertEqual(out["status"], "current")
        self.assertEqual(len(out["standings"]), 90)

    def test_stale_retains_rows(self):
        rows = self._rows_from_fixture()
        good = fetcher.build_snapshot(rows, REV, 5, 19, "2026-08-09T00:00:00+00:00")
        ewc.publish_standings(good, path=self.path)
        out = ewc.read_standings(path=self.path, stale_after_s=0)
        self.assertEqual(out["status"], "stale")
        self.assertEqual(len(out["standings"]), 90)  # rows retained when stale

    def test_tie_mismatch_rejected(self):
        rows = self._rows_from_fixture()
        # Break the 4th-place tie: same points, different rank.
        rows[3]["rank"] = 5
        with self.assertRaises(ValueError):
            ewc.publish_standings(_snapshot(rows), path=self.path)

    def test_rank_regression_rejected(self):
        rows = self._rows_from_fixture()
        rows[1]["rank"] = 1  # two rows ranked 1 with different points
        with self.assertRaises(ValueError):
            ewc.publish_standings(_snapshot(rows), path=self.path)


if __name__ == "__main__":
    unittest.main()
