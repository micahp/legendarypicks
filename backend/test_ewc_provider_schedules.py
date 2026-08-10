#!/usr/bin/env python3
"""Tests for the EWC per-title provider acquisition path (PandaScore + Lichess).

No network: the PandaScore match fetch and the Lichess round/game fetch are mocked.
Covers the provider row mapper (finished / not-started placeholder zero / canceled),
lifecycle derivation (final with canceled-as-terminal, active, upcoming), provider-aware
snapshot identity validation, and publish/read roundtrips through the shared store.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fetch_ewc_title_schedules as store  # noqa: E402
import fetch_ewc_provider_schedules as provider  # noqa: E402


def _ps_match(mid=1609949, status="finished", begin="2026-08-09T17:24:13Z",
              opponents=None, results=None, tournament="Playoffs"):
    return {
        "id": mid, "status": status, "begin_at": begin, "end_at": None,
        "opponents": opponents or [
            {"type": "Team", "opponent": {"id": 135379, "name": "Team Falcons", "slug": "team-falcons"}},
            {"type": "Team", "opponent": {"id": 135378, "name": "100 Thieves", "slug": "100-thieves"}},
        ],
        "results": results or [{"team_id": 135379, "score": 3}, {"team_id": 135378, "score": 4}],
        "tournament": {"name": tournament},
    }


class PandascoreRowMappingTests(unittest.TestCase):
    def test_finished_match_maps_teams_scores_and_finished(self):
        row = provider._ps_match_row(_ps_match())
        self.assertEqual(row["sourceMatchId"], "pandascore:1609949")
        self.assertEqual(row["teamA"], "Team Falcons")
        self.assertEqual(row["teamB"], "100 Thieves")
        self.assertEqual(row["scoreA"], 3)
        self.assertEqual(row["scoreB"], 4)
        self.assertTrue(row["finished"])
        self.assertFalse(row["canceled"])
        self.assertEqual(row["date"], "2026-08-09")
        self.assertEqual(row["stage"], "Playoffs")

    def test_not_started_placeholder_zero_is_never_published(self):
        # Verified live: a not_started match can carry a placeholder score 0 in `results`
        # with only one opponent known. The mapper must NOT publish that invented zero.
        match = _ps_match(status="not_started", results=[{"team_id": 131331, "score": 0}],
                          opponents=[{"type": "Team",
                                      "opponent": {"id": 131331, "name": "Twisted Minds",
                                                   "slug": "twisted-minds"}}])
        row = provider._ps_match_row(match)
        self.assertFalse(row["finished"])
        self.assertIsNone(row["scoreA"])
        self.assertIsNone(row["scoreB"])
        self.assertTrue(row["teamBPending"])

    def test_canceled_match_is_terminal_without_score(self):
        match = _ps_match(status="canceled", begin=None, results=[])
        row = provider._ps_match_row(match)
        self.assertFalse(row["finished"])
        self.assertTrue(row["canceled"])
        self.assertIsNone(row["scoreA"])
        self.assertIsNone(row["scoreB"])

    def test_unsupported_status_rejects(self):
        with self.assertRaises(store.ScheduleSourceError):
            provider._ps_match_row(_ps_match(status="void"))


class PandascoreLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ewc-provider-")
        self.old_dir = store.SCHEDULES_DIR
        store.SCHEDULES_DIR = self.dir
        store.publish  # ensure module loaded

    def tearDown(self):
        store.SCHEDULES_DIR = self.old_dir

    def _series(self, slug="counter-strike-2", end_at_ms=None):
        end_at_ms = end_at_ms or provider._iso_to_ms("2026-08-01T00:00:00Z")
        return [dict(s, endAtMs=end_at_ms) for s in store.PANDASCORE_SERIES[slug]]

    def test_all_finished_ended_series_is_final(self):
        rows = [provider._ps_match_row(_ps_match(i, "finished")) for i in (1, 2, 3)]
        snap = provider.build_pandascore_snapshot("counter-strike-2", rows, self._series(),
                                                 "2026-08-10T00:00:00+00:00")
        self.assertEqual(snap["lifecycle"], "final")
        self.assertTrue(snap["finality"]["allMatchesResolved"])
        self.assertTrue(snap["finality"]["participantsComplete"])
        store.validate_snapshot(snap, expected_slug="counter-strike-2")

    def test_canceled_plus_finished_is_final(self):
        rows = [provider._ps_match_row(_ps_match(1, "finished")),
                provider._ps_match_row(_ps_match(2, "canceled", begin=None, results=[]))]
        snap = provider.build_pandascore_snapshot("dota-2", rows, self._series(),
                                                 "2026-08-10T00:00:00+00:00")
        self.assertEqual(snap["lifecycle"], "final")
        store.validate_snapshot(snap, expected_slug="dota-2")

    def test_any_finished_is_active(self):
        rows = [provider._ps_match_row(_ps_match(1, "finished")),
                provider._ps_match_row(_ps_match(2, "not_started", begin="2026-08-20T10:00:00Z",
                                                 results=[]))]
        snap = provider.build_pandascore_snapshot("counter-strike-2", rows, self._series(),
                                                 "2026-08-10T00:00:00+00:00")
        self.assertEqual(snap["lifecycle"], "active")

    def test_none_finished_is_upcoming(self):
        rows = [provider._ps_match_row(_ps_match(1, "not_started", begin="2026-08-20T10:00:00Z",
                                                 results=[]))]
        snap = provider.build_pandascore_snapshot("counter-strike-2", rows, self._series(),
                                                 "2026-08-10T00:00:00+00:00")
        self.assertEqual(snap["lifecycle"], "upcoming")

    def test_unresolved_participant_blocks_final(self):
        # A finished match whose second participant id is published but never named is a
        # resolved result with an incomplete participant record — the snapshot must NOT
        # claim final (participantsComplete=False). Both scores exist (score mapping is
        # by team id), so the row is valid; only the participant record is incomplete.
        rows = [provider._ps_match_row(_ps_match(1, "finished")),
                provider._ps_match_row(_ps_match(
                    2, "finished", opponents=[
                        {"type": "Team",
                         "opponent": {"id": 5, "name": "Known", "slug": "known"}},
                        {"type": "Team",
                         "opponent": {"id": 6, "name": None, "slug": None}}],
                    results=[{"team_id": 5, "score": 1}, {"team_id": 6, "score": 0}]))]
        snap = provider.build_pandascore_snapshot("counter-strike-2", rows, self._series(),
                                                 "2026-08-10T00:00:00+00:00")
        self.assertEqual(snap["lifecycle"], "active")
        self.assertIsNone(snap["finality"])

    def test_publish_read_roundtrip_pandascore(self):
        rows = [provider._ps_match_row(_ps_match())]
        snap = provider.build_pandascore_snapshot(
            "rocket-league", rows, self._series("rocket-league"),
            "2026-08-10T00:00:00+00:00")
        path = store.publish("rocket-league", snap)
        self.assertTrue(os.path.exists(path))
        got = store.read_snapshot("rocket-league")
        self.assertEqual(got["source"]["provider"], "pandascore")
        self.assertEqual(got["source"]["urls"], ["https://api.pandascore.co/series/10850"])
        self.assertEqual(got["source"]["revisions"], [10850])
        self.assertEqual(got["matches"][0]["sourceMatchId"], "pandascore:1609949")

    def test_identity_rejects_wrong_provider_urls(self):
        snap = provider.build_pandascore_snapshot(
            "rocket-league", [provider._ps_match_row(_ps_match(1, "finished"))],
            self._series(), "2026-08-10T00:00:00+00:00")
        snap["source"]["urls"] = ["https://liquipedia.net/rocketleague/Esports_World_Cup/2026"]
        with self.assertRaises(store.ScheduleSourceError):
            store.validate_snapshot(snap, expected_slug="rocket-league")


class LichessChessTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ewc-lichess-")
        self.old_dir = store.SCHEDULES_DIR
        store.SCHEDULES_DIR = self.dir

    def tearDown(self):
        store.SCHEDULES_DIR = self.old_dir

    def _round_doc(self, games=None):
        return {
            "round": {"id": "5kphrGNd", "name": "Upper | Round 1"},
            "tour": {"id": "Ywo3zsIE", "name": "Esports World Cup 2026 | Play-in"},
            "games": games or [],
        }

    def _mock_lichess(self, tour_doc, round_doc):
        """Dispatcher: the tour endpoint returns tour_doc; every other path the round doc."""
        def _get(path):
            if path == "/api/broadcast/Ywo3zsIE":
                return tour_doc
            return round_doc
        return mock.patch.object(provider, "_lichess_get", side_effect=_get)

    def test_upcoming_rounds_map_to_pending_rows(self):
        tour_doc = {"rounds": [
            {"id": "5kphrGNd", "name": "Upper | Round 1", "slug": "upper-round-1",
             "startsAt": 1786442400000},
            {"id": "aYNYi8pz", "name": "Upper | Round 2", "slug": "upper-round-2",
             "startsAt": 1786451400000},
        ]}
        with self._mock_lichess(tour_doc, self._round_doc()):
            rows = provider.build_lichess_rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["teamAPending"] and r["teamBPending"] for r in rows))
        self.assertTrue(all(not r["finished"] for r in rows))
        self.assertEqual(rows[0]["stage"], "Play-in · Upper | Round 1")
        self.assertEqual(rows[0]["startTime"], 1786442400000)
        self.assertEqual(rows[0]["date"], "2026-08-11")

    def test_finished_games_map_players_and_result(self):
        tour_doc = {"rounds": [
            {"id": "KNiyCsi0", "name": "Round 1", "slug": "round-1", "startsAt": 1785837600000},
        ]}
        round_doc = {"games": [
            {"id": "g1", "players": [{"name": "Fressinet, Laurent"}, {"name": "Daurelle, Herve"}],
             "status": "1-0"},
            {"id": "g2", "players": [{"name": "A"}, {"name": "B"}], "status": "1/2-1/2"},
        ]}
        with self._mock_lichess(tour_doc, round_doc):
            rows = provider.build_lichess_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["teamA"], "Fressinet, Laurent")
        self.assertEqual(rows[0]["scoreA"], 1)
        self.assertTrue(rows[0]["finished"])
        # Draw is finished with no fabricated score
        self.assertTrue(rows[1]["finished"])
        self.assertIsNone(rows[1]["scoreA"])
        self.assertIsNone(rows[1]["scoreB"])

    def test_chess_snapshot_publishes_and_reads(self):
        tour_doc = {"rounds": [
            {"id": "5kphrGNd", "name": "Upper | Round 1", "slug": "upper-round-1",
             "startsAt": 1786442400000},
        ]}
        with self._mock_lichess(tour_doc, self._round_doc()):
            snap = provider.build_lichess_snapshot("2026-08-10T00:00:00+00:00")
        self.assertEqual(snap["lifecycle"], "upcoming")
        self.assertEqual(snap["source"]["provider"], "lichess")
        store.validate_snapshot(snap, expected_slug="chess")
        path = store.publish("chess", snap)
        got = store.read_snapshot("chess")
        self.assertEqual(got["source"]["revisions"], ["Ywo3zsIE"])
        self.assertEqual(got["source"]["urls"],
                         ["https://lichess.org/broadcast/esports-world-cup-2026-play-in/Ywo3zsIE"])


class ProviderIdentityTests(unittest.TestCase):
    def test_lichess_identity_is_chess_only(self):
        with self.assertRaises(store.ScheduleSourceError):
            store._source_identity("rocket-league", "lichess")

    def test_unsupported_provider_rejects(self):
        with self.assertRaises(store.ScheduleSourceError):
            store._source_identity("chess", "esportscharts")

    def test_known_pandascore_slugs_are_coverable(self):
        for slug in ("call-of-duty-black-ops-7", "counter-strike-2", "dota-2",
                     "ea-sports-fc-26", "honor-of-kings", "league-of-legends",
                     "mobile-legends-bang-bang", "overwatch-2", "rainbow-six-siege",
                     "rocket-league", "valorant"):
            self.assertIn(slug, store.PANDASCORE_SERIES)


if __name__ == "__main__":
    unittest.main()
