#!/usr/bin/env python3

import email.message
import json
import os
import sqlite3
import tempfile
import unittest
import urllib.error
from unittest import mock

import paced_http
import ingest_nba_stats
from ingest_nba_stats import (
    NBAStatsIngestError,
    fetch_athlete_stats,
    parse_athlete_stats,
    refresh_nba_stats,
)
from league_stats import PLAYER_STATS_TABLE_SQL


def stats_payload(*, games=64, points=33.484375):
    values = {
        "gamesPlayed": games,
        "avgPoints": points,
        "avgRebounds": 7.734375,
        "avgAssists": 8.28125,
        "avgSteals": 1.640625,
        "avgBlocks": 0.53125,
        "avgTurnovers": 3.984375,
        "fieldGoalsMade": 693,
        "fieldGoalsAttempted": 1457,
        "threePointFieldGoalsMade": 254,
        "threePointFieldGoalsAttempted": 694,
        "freeThrowsMade": 503,
        "freeThrowsAttempted": 645,
        "avgMinutes": 35.765625,
        "trueShootingPct": 61.552,
    }
    return {
        "splits": {
            "categories": [
                {
                    "name": "all",
                    "stats": [
                        {"name": name, "value": value}
                        for name, value in values.items()
                    ],
                }
            ]
        }
    }


class NBAStatsIngestTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="nba-stats-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(
            lambda: os.path.exists(self.path) and os.unlink(self.path)
        )
        connection = sqlite3.connect(self.path)
        connection.executescript(
            """
            CREATE TABLE players(
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              league TEXT NOT NULL,
              team TEXT,
              espn_id TEXT,
              active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        connection.execute(PLAYER_STATS_TABLE_SQL)
        connection.executemany(
            """INSERT INTO players(
                 id,name,league,team,espn_id,active
               ) VALUES(?,?,?,?,?,1)""",
            [
                (1, "Canonical One", "nba", "BOS", "101"),
                (2, "Canonical Two", "nba", "DAL", "202"),
            ],
        )
        connection.execute(
            """INSERT INTO player_stats(
                 player_id,player_name,league,team,stat_type,season,
                 games,pts,source
               ) VALUES(1,'Last Good','nba','OLD','season',2026,
                        10,10.0,'espn_core')"""
        )
        connection.commit()
        connection.close()

    def rows(self):
        connection = sqlite3.connect(self.path)
        try:
            return connection.execute(
                """SELECT player_id,player_name,team,games,pts,source
                   FROM player_stats WHERE league='nba' AND season=2026
                   ORDER BY player_id"""
            ).fetchall()
        finally:
            connection.close()

    def test_parser_maps_published_totals_and_per_game_values(self):
        parsed = parse_athlete_stats(stats_payload())
        self.assertEqual(parsed["games"], 64)
        self.assertEqual(parsed["values"]["pts"], 33.5)
        self.assertEqual(parsed["values"]["fgm"], 693)
        self.assertEqual(parsed["values"]["minutes"], 35.8)
        self.assertEqual(parsed["values"]["ts_pct"], 61.6)

    def test_fetch_failure_preserves_the_last_good_snapshot(self):
        before = self.rows()

        def fetcher(espn_id, _season):
            if espn_id == "202":
                raise NBAStatsIngestError("upstream unavailable")
            return stats_payload()

        with self.assertRaisesRegex(
            NBAStatsIngestError, "upstream unavailable"
        ):
            refresh_nba_stats(
                self.path, season=2026, fetcher=fetcher,
                min_coverage=1.0,
            )
        self.assertEqual(self.rows(), before)

    def test_low_coverage_preserves_the_last_good_snapshot(self):
        before = self.rows()
        with self.assertRaisesRegex(
            NBAStatsIngestError, "below required"
        ):
            refresh_nba_stats(
                self.path,
                season=2026,
                fetcher=lambda espn_id, season: (
                    stats_payload() if espn_id == "101" else None
                ),
                min_coverage=0.75,
            )
        self.assertEqual(self.rows(), before)

    def test_complete_fetch_atomically_replaces_the_population(self):
        result = refresh_nba_stats(
            self.path,
            season=2026,
            fetcher=lambda espn_id, season: stats_payload(
                points=20.0 if espn_id == "101" else 25.0
            ),
            min_coverage=1.0,
        )
        self.assertEqual(result["published"], 2)
        self.assertEqual(
            self.rows(),
            [
                (1, "Canonical One", "BOS", 64, 20.0, "espn_core"),
                (2, "Canonical Two", "DAL", 64, 25.0, "espn_core"),
            ],
        )

    def test_duplicate_active_espn_id_fails_closed(self):
        connection = sqlite3.connect(self.path)
        connection.execute(
            """INSERT INTO players(
                 id,name,league,team,espn_id,active
               ) VALUES(3,'Duplicate','nba','NYK','101',1)"""
        )
        connection.commit()
        connection.close()
        before = self.rows()
        with self.assertRaisesRegex(
            NBAStatsIngestError, "duplicate active ESPN IDs"
        ):
            refresh_nba_stats(
                self.path,
                season=2026,
                fetcher=lambda espn_id, season: stats_payload(),
            )
        self.assertEqual(self.rows(), before)

    def test_active_player_without_espn_id_fails_closed(self):
        connection = sqlite3.connect(self.path)
        connection.execute(
            """INSERT INTO players(
                 id,name,league,team,espn_id,active
               ) VALUES(3,'Missing ID','nba','NYK',NULL,1)"""
        )
        connection.commit()
        connection.close()
        before = self.rows()
        with self.assertRaisesRegex(
            NBAStatsIngestError, "lack canonical ESPN IDs"
        ):
            refresh_nba_stats(
                self.path,
                season=2026,
                fetcher=lambda espn_id, season: stats_payload(),
            )
        self.assertEqual(self.rows(), before)

    def test_historical_season_is_rejected_before_fetch(self):
        calls = []
        with self.assertRaisesRegex(
            NBAStatsIngestError, "only after season 2023"
        ):
            refresh_nba_stats(
                self.path,
                season=2023,
                fetcher=lambda espn_id, season: calls.append(espn_id),
            )
        self.assertEqual(calls, [])


def http_error(code, retry_after=None):
    headers = None
    if retry_after is not None:
        headers = email.message.Message()
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        "https://sports.core.api.espn.com/", code, "refused", headers, None
    )


class FetchPacingTest(unittest.TestCase):
    """An ESPN 403 here means we asked too fast, not that we are banned.

    On 2026-08-04 an unpaced run of this ingest 403'd on its first athlete and
    took `sports.core.api.espn.com` down for this box for hours, including the
    live Standings tab.  These tests pin the pacing that prevents a repeat.
    """

    def setUp(self):
        paced_http.reset_host_budget()
        ingest_nba_stats._FETCH._last_request_at = 0.0
        self.slept = []
        patch_sleep = mock.patch.object(
            ingest_nba_stats.time, "sleep", self.slept.append
        )
        patch_sleep.start()
        self.addCleanup(patch_sleep.stop)

    def responses(self, *outcomes):
        """Drive urlopen through a fixed sequence of raises/returns.

        Patching paced_http.urllib.request.urlopen: the request now goes
        through the shared Fetcher, which calls urlopen from its own module
        namespace. (ingest_nba_stats no longer imports urllib.request.)
        """
        remaining = list(outcomes)

        def urlopen(_request, timeout=None):
            outcome = remaining.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            body = mock.MagicMock()
            body.read.return_value = json.dumps(outcome).encode()
            body.__enter__.return_value = body
            return body

        return mock.patch.object(paced_http.urllib.request, "urlopen", urlopen)

    def test_requests_are_spaced_by_the_minimum_interval(self):
        with self.responses({"ok": 1}, {"ok": 2}):
            fetch_athlete_stats("1966", 2026)
            fetch_athlete_stats("1967", 2026)
        # Two reads after an idle period means exactly one wait: the first
        # request owes nothing, the second must not follow it immediately.
        # Count before inspecting -- `all()` over an empty list is True, so
        # asserting only the gap sizes would let "no pacing at all" pass.
        self.assertEqual(
            len(self.slept), 1,
            "the second read followed the first with no wait between them",
        )
        self.assertGreater(self.slept[0], 0)

    def test_a_403_is_waited_out_rather_than_aborting_the_snapshot(self):
        with self.responses(http_error(403), http_error(403), {"ok": 1}):
            self.assertEqual(fetch_athlete_stats("1966", 2026), {"ok": 1})
        for wait in ingest_nba_stats.RETRY_WAITS[:2]:
            self.assertIn(wait, self.slept)

    def test_a_retry_after_header_longer_than_our_backoff_wins(self):
        with self.responses(http_error(429, retry_after=120), {"ok": 1}):
            fetch_athlete_stats("1966", 2026)
        self.assertIn(120.0, self.slept)

    def test_a_404_is_not_retried(self):
        with self.responses(http_error(404)):
            self.assertIsNone(fetch_athlete_stats("1966", 2026))

    def test_a_403_that_never_clears_still_fails_closed(self):
        outcomes = [http_error(403)] * (len(ingest_nba_stats.RETRY_WAITS) + 1)
        with self.responses(*outcomes):
            with self.assertRaisesRegex(NBAStatsIngestError, "HTTP 403"):
                fetch_athlete_stats("1966", 2026)


if __name__ == "__main__":
    unittest.main(verbosity=2)
