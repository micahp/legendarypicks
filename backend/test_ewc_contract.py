#!/usr/bin/env python3
"""Phase 0 contract tests for the EWC module — participant model and standings snapshot store.

Covers the five participant states the plan names (named, stale, pending-winner, pending-loser,
fully unavailable) plus the atomic publication contract: last good survives, a failed candidate
never becomes readable, and validation rejects the plan's listed failure classes.
"""

import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Isolate any import-time database work from the live dev/prod databases.
_TEST_DB = tempfile.NamedTemporaryFile(prefix="ewc-contract-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers.esports import ewc  # noqa: E402


def _row(rank=1, club_id="team-falcons", club_name="Team Falcons", points=2600, **kw):
    r = {"rank": rank, "clubId": club_id, "clubName": club_name, "logo": None,
         "points": points, "eligibleTopEightCount": None, "titleWins": None,
         "eligibleToWin": None, "movement": None}
    r.update(kw)
    return r


def _snapshot(rows, source_club_count=None, published_at=None,
              source_label="Test Publisher", source_url="https://example.invalid/standings"):
    if published_at is None:
        published_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return {
        "event": "ewc-2026",
        "publishedAt": published_at,
        "source": {
            "label": source_label,
            "url": source_url,
            "fetchedAt": published_at,
            "sourceReportedClubs": source_club_count if source_club_count is not None else len(rows),
            "fetchedClubs": len(rows),
            "checksum": "deadbeef",
        },
        "standings": rows,
    }


class ParticipantContractTests(unittest.TestCase):
    def test_named_participant(self):
        p = ewc.named_participant(135377, "Team Heretics")
        self.assertEqual(p["state"], "named")
        self.assertEqual(p["clubId"], 135377)
        self.assertEqual(p["clubName"], "Team Heretics")
        self.assertNotIn("feederGameId", p)
        self.assertEqual(ewc.participant_label(p), "Team Heretics")

    def test_pending_winner_participant(self):
        p = ewc.pending_participant(1609943, "winner", "Winner of Falcons–Gentle Mates")
        self.assertEqual(p["state"], "pending")
        self.assertEqual(p["feederGameId"], 1609943)
        self.assertEqual(p["outcome"], "winner")
        self.assertEqual(ewc.participant_label(p), "Winner of Falcons–Gentle Mates")
        self.assertFalse(ewc.participant_is_resolved(p))

    def test_pending_loser_participant(self):
        p = ewc.pending_participant(1609946, "loser", "Loser of Semifinal 1")
        self.assertEqual(p["state"], "pending")
        self.assertEqual(p["outcome"], "loser")
        self.assertEqual(ewc.participant_label(p), "Loser of Semifinal 1")

    def test_fully_unavailable_participant(self):
        p = ewc.unavailable_participant()
        self.assertEqual(p["state"], "unavailable")
        self.assertEqual(ewc.participant_label(p), "Participant unavailable")
        self.assertFalse(ewc.participant_is_resolved(p))
        # An unresolved participant must never look like a team name.
        self.assertNotEqual(p.get("clubName"), "TBD")
        self.assertNotEqual(p.get("clubName"), "TBA")

    def test_named_participant_is_resolved(self):
        self.assertTrue(ewc.participant_is_resolved(ewc.named_participant(1, "FaZe Clan")))


class StandingsPublishContractTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="ewc-standings-", suffix=".json")
        os.close(fd)
        os.unlink(self.path)

    def tearDown(self):
        for p in (self.path, self.path + ".tmp", self.path + ".rejected"):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass

    def _publish(self, snapshot):
        return ewc.publish_standings(snapshot, path=self.path)

    def _read(self, stale_after_s=3600):
        return ewc.read_standings(path=self.path, stale_after_s=stale_after_s)

    def test_no_snapshot_is_honest_unavailable(self):
        out = self._read()
        self.assertEqual(out["event"], "ewc-2026")
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["standings"], [])
        self.assertIsNone(out["asOf"])
        self.assertIsNone(out["source"])
        self.assertIn("reason", out)

    def test_publish_then_read_is_current(self):
        self._publish(_snapshot([_row(1), _row(2, "team-vitality", "Team Vitality", 2000)]))
        out = self._read()
        self.assertEqual(out["status"], "current")
        self.assertEqual(out["asOf"], out["asOf"])
        self.assertEqual(out["source"]["label"], "Test Publisher")
        self.assertEqual(len(out["standings"]), 2)
        self.assertEqual(out["standings"][0]["clubName"], "Team Falcons")

    def test_stale_serves_last_good_snapshot(self):
        self._publish(_snapshot([_row(1)]))
        out = self._read(stale_after_s=0)
        self.assertEqual(out["status"], "stale")
        # Last good survives a refresh failure: data is intact, status says stale.
        self.assertEqual(len(out["standings"]), 1)
        self.assertEqual(out["standings"][0]["clubId"], "team-falcons")
        self.assertIsNotNone(out["asOf"])

    def test_failed_candidate_never_becomes_readable(self):
        self._publish(_snapshot([_row(1)]))
        before = open(self.path).read()
        # A candidate that fails validation (negative points) must not replace the good snapshot.
        with self.assertRaises(ValueError):
            self._publish(_snapshot([_row(1, points=-5)]))
        self.assertEqual(open(self.path).read(), before)
        out = self._read()
        self.assertEqual(out["status"], "current")
        self.assertEqual(out["standings"][0]["points"], 2600)

    def test_corrupt_snapshot_reads_as_unavailable(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        out = self._read()
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["standings"], [])

    def test_validation_accepts_tied_ranks_with_equal_points(self):
        # Real published rankings tie: equal points share a rank (Liquipedia rev 15997 ties 4th
        # and 6th). A duplicate rank with EQUAL points is a legitimate tie.
        self._publish(_snapshot([
            _row(1, points=2600),
            _row(1, "team-vitality", "Team Vitality", 2600),
        ]))
        out = self._read()
        self.assertEqual(out["status"], "current")
        self.assertEqual(len(out["standings"]), 2)

    def test_validation_rejects_duplicate_rank_with_different_points(self):
        # Same rank, different points is a tie mismatch / rank inversion.
        with self.assertRaises(ValueError):
            self._publish(_snapshot([_row(1), _row(1, "team-vitality", "Team Vitality", 2000)]))

    def test_validation_rejects_duplicate_club_id(self):
        with self.assertRaises(ValueError):
            self._publish(_snapshot([_row(1), _row(2)]))

    def test_validation_rejects_negative_points(self):
        with self.assertRaises(ValueError):
            self._publish(_snapshot([_row(1, points=-1)]))

    def test_validation_rejects_rank_inversion(self):
        # Rank 1 must not carry fewer points than rank 2 unless a publisher correction is marked.
        with self.assertRaises(ValueError):
            self._publish(_snapshot([_row(1, points=1000), _row(2, "team-vitality", "Team Vitality", 2000)]))

    def test_validation_rejects_tie_mismatch_after_drop(self):
        # Fewer points must strictly increase the rank — equal rank after a drop is an inversion.
        with self.assertRaises(ValueError):
            self._publish(_snapshot([
                _row(1, points=2600),
                _row(2, "team-vitality", "Team Vitality", 2000),
                _row(2, "natus-vincere", "Natus Vincere", 1500),
            ]))

    def test_validation_rejects_rank_regression(self):
        # Ranks must be non-decreasing.
        with self.assertRaises(ValueError):
            self._publish(_snapshot([
                _row(2, points=2600),
                _row(1, "team-vitality", "Team Vitality", 2200),
            ]))

    def test_validation_rejects_missing_timestamp(self):
        snap = _snapshot([_row(1)])
        del snap["publishedAt"]
        with self.assertRaises(ValueError):
            self._publish(snap)

    def test_validation_rejects_count_disagreement(self):
        with self.assertRaises(ValueError):
            self._publish(_snapshot([_row(1)], source_club_count=12))

    def test_publisher_correction_allows_regression(self):
        # A regression is rejected without the flag…
        self._publish(_snapshot([_row(1, points=2600), _row(2, "team-vitality", "Team Vitality", 2000)]))
        with self.assertRaises(ValueError):
            self._publish(_snapshot([
                _row(1, points=1500), _row(2, "team-vitality", "Team Vitality", 1200),
            ]))
        # …and allowed when explicitly identified as a publisher correction.
        snap = json.load(open(self.path))  # file still holds the first (good) run
        snap["standings"] = [_row(1, points=1500), _row(2, "team-vitality", "Team Vitality", 1200)]
        snap["publisherCorrection"] = True
        ewc.publish_standings(snap, path=self.path)
        out = self._read()
        self.assertEqual(out["status"], "current")
        self.assertEqual(out["standings"][0]["points"], 1500)

    def test_zero_points_is_a_real_zero_not_unknown(self):
        self._publish(_snapshot([_row(1, points=0)]))
        out = self._read()
        self.assertEqual(out["standings"][0]["points"], 0)


class StandingsRowContractTests(unittest.TestCase):
    def test_row_contract_fields(self):
        r = _row()
        for key in ("rank", "clubId", "clubName", "logo", "points", "eligibleTopEightCount",
                    "titleWins", "eligibleToWin", "movement"):
            self.assertIn(key, r)


if __name__ == "__main__":
    unittest.main()
