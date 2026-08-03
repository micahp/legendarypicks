"""The game-type boundary refuses to guess, and the NHL mapping is falsifiable.

These are the two properties worth testing. That `2` maps to `REG` is a lookup;
that an *unknown* type does not quietly become `REG` is the behaviour that keeps
preseason exhibitions out of the denominator of every per-game rate we serve.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_types import (
    PHASES,
    espn_event_phase,
    normalize_game_type,
    verify_nhl_phase,
)


class NormalizeGameType(unittest.TestCase):
    def test_measured_nhl_ids(self):
        for raw, want in ((1, "PRE"), (2, "REG"), (3, "POST"), ("2", "REG")):
            self.assertEqual(normalize_game_type("nhle.com", "nhl", raw), want)

    def test_our_own_vocabulary_passes_through(self):
        for phase in PHASES:
            self.assertEqual(normalize_game_type("nflverse", "nfl", phase), phase)
            self.assertEqual(normalize_game_type("nflverse", "nfl", phase.lower()), phase)

    def test_null_raises_rather_than_defaulting(self):
        # The whole defect in one assertion: a NULL game_type is not a game type.
        # If this ever returns 'REG', every league inherits NFL 2024's "missed 17".
        for empty in (None, "", "   "):
            with self.assertRaises(ValueError):
                normalize_game_type("nhle.com", "nhl", empty)

    def test_unmeasured_type_id_raises(self):
        # NHL publishes no enum for these ids. An id we have never seen may be a
        # phase we have never ingested; it is not REG by default.
        with self.assertRaises(ValueError):
            normalize_game_type("nhle.com", "nhl", 4)

    def test_unmeasured_publisher_raises(self):
        # No shared default across publishers: NHL's 1/2/3 and ESPN's 1/2/3/4
        # agree by coincidence, not by standard.
        with self.assertRaises(ValueError):
            normalize_game_type("mlb_statsapi", "mlb", "R")


class VerifyNhlPhase(unittest.TestCase):
    """`verify_nhl_phase` compares a stamp to the publisher's calendar.

    Offline: the published window is injected, so the assertion is about the
    comparison and not about the network.
    """

    WINDOW = {
        "preseasonStartdate": "2025-09-20T19:00:00",
        "startDate": "2025-10-07T17:00:00",
        "regularSeasonEndDate": "2026-04-17T00:00:00",
        "endDate": "2026-06-15T00:00:00",
    }

    def setUp(self):
        import game_types
        self._real = game_types.nhl_season_window
        game_types.nhl_season_window = lambda season, timeout=15: self.WINDOW
        self.addCleanup(setattr, game_types, "nhl_season_window", self._real)

    def test_regular_season_dates_inside_window(self):
        self.assertIsNone(
            verify_nhl_phase(20252026, "REG", ["2025-10-07", "2026-04-16"])
        )

    def test_a_playoff_date_stamped_REG_is_reported(self):
        # This is the failure the check exists for: an ingest that stamps from
        # its own request parameter rather than the publisher's answer would
        # file a June game as regular season and nothing else would notice.
        problem = verify_nhl_phase(20252026, "REG", ["2025-10-07", "2026-06-01"])
        self.assertIsNotNone(problem)
        self.assertIn("2026-06-01", problem)

    def test_playoff_window_starts_at_regular_season_end(self):
        self.assertIsNone(verify_nhl_phase(20252026, "POST", ["2026-04-20", "2026-06-15"]))

    def test_no_dates_is_not_a_failure(self):
        self.assertIsNone(verify_nhl_phase(20252026, "POST", []))


class EspnEventPhase(unittest.TestCase):
    """The NBA cases, measured 2026-08-02 against real scoreboard responses."""

    @staticmethod
    def _event(season_type, competition_type="STD"):
        return {"season_type": season_type, "competition_type": competition_type}

    def test_measured_nba_ids(self):
        self.assertEqual(espn_event_phase("nba", self._event(1)), "PRE")
        self.assertEqual(espn_event_phase("nba", self._event(2)), "REG")
        self.assertEqual(espn_event_phase("nba", self._event(3)), "POST")
        self.assertEqual(espn_event_phase("nba", self._event(5)), "PLAYIN")

    def test_all_star_is_published_as_regular_season_and_must_not_be(self):
        """ESPN files All-Star weekend *inside* type 2. `WORLD @ STARS` on
        2026-02-15 publishes season.type=2 exactly as opening night does; the
        only thing separating them is the competition type. Trusting the season
        field here puts three exhibitions into the denominator of every NBA
        per-game rate we serve."""
        allstar = self._event(2, competition_type="ALLSTAR")
        self.assertEqual(normalize_game_type("espn", "nba", allstar["season_type"]), "REG")
        self.assertEqual(espn_event_phase("nba", allstar), "ALLSTAR")

    def test_off_season_id_raises_rather_than_defaulting(self):
        """Type 4 publishes zero events. A row claiming it is not a phase we
        failed to map — it is a row that should not exist."""
        with self.assertRaises(ValueError):
            espn_event_phase("nba", self._event(4))

    def test_missing_season_type_raises(self):
        with self.assertRaises(ValueError):
            espn_event_phase("nba", self._event(None))

    def test_competition_override_is_league_scoped(self):
        """The override table is keyed by league on purpose: another league's
        ALLSTAR abbreviation is not automatically ours to reinterpret."""
        with self.assertRaises(ValueError):
            espn_event_phase("nhl", self._event(2, competition_type="ALLSTAR"))


if __name__ == "__main__":
    unittest.main()
