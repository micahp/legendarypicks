"""The Bovada scoreboard fallback.

Live games cannot be summoned to order, so the states that matter are covered
with the publisher's own payload shapes, captured 2026-08-18 from
/services/sports/results/api/v1/scores/{id}.

The case worth the most attention is PRE_GAME: it returns latestScore 0-0 with a
lastUpdated days old, and that 0-0 is indistinguishable from a real 0-0 in a game
under way. Publishing it would put a fabricated score on the board.
"""
import datetime as dt
import unittest
from unittest.mock import patch

import scoreboard_fallback as fallback


def scores_payload(status, home, visitor, ticking=False, period="", game_time=""):
    return {
        "eventId": 1, "sport": "BASEBALL",
        "latestScore": {"home": home, "visitor": visitor},
        "clock": {"period": period, "periodNumber": 5, "gameTime": game_time,
                  "isTicking": ticking, "numberOfPeriods": 9},
        "gameStatus": status,
    }


def coupon_event(event_id=1, live=False, start=None, home="Baltimore Orioles",
                 away="New York Yankees"):
    when = start or dt.datetime.now(dt.timezone.utc)
    return {
        "id": event_id, "type": "GAMEEVENT", "live": live,
        "startTime": int(when.timestamp() * 1000),
        "competitors": [
            {"name": home, "home": True, "shortName": "Orioles"},
            {"name": away, "home": False, "shortName": "Yankees"},
        ],
    }


class ScoreIsOnlyReadFromAGameUnderWay(unittest.TestCase):
    def read(self, payload):
        with patch.object(fallback, "urllib") as urllib_mock:
            handle = urllib_mock.request.urlopen.return_value.__enter__.return_value
            handle.read.return_value = __import__("json").dumps(payload).encode()
            return fallback.event_scoreboard(1)

    def test_a_pre_game_zero_zero_is_refused(self):
        self.assertIsNone(self.read(scores_payload("PRE_GAME", "0", "0")))

    def test_a_live_game_yields_its_score(self):
        out = self.read(scores_payload("IN_PROGRESS", "4", "2", ticking=True,
                                       period="Top 5th", game_time="5"))
        self.assertEqual((out["home"], out["away"]), (4, 2))
        self.assertEqual(out["state"], "in")
        self.assertFalse(out["completed"])

    def test_a_ticking_clock_counts_as_under_way_when_the_word_is_unknown(self):
        """Bovada's status vocabulary is not documented; a running clock is the
        fact, so an unrecognised status with isTicking still reports."""
        out = self.read(scores_payload("SOME_NEW_WORD", "1", "0", ticking=True))
        self.assertIsNotNone(out)
        self.assertEqual(out["state"], "in")

    def test_a_final_game_is_marked_post_and_completed(self):
        out = self.read(scores_payload("FINAL", "7", "3"))
        self.assertEqual(out["state"], "post")
        self.assertTrue(out["completed"])
        self.assertEqual(out["status"], "Final")

    def test_a_final_status_is_not_overridden_by_a_stuck_clock(self):
        out = self.read(scores_payload("FINAL", "7", "3", ticking=True))
        self.assertEqual(out["state"], "post")

    def test_an_unparseable_score_is_absent_rather_than_zero(self):
        self.assertIsNone(self.read(scores_payload("IN_PROGRESS", "", None, ticking=True)))


class SlateShape(unittest.TestCase):
    def test_only_the_requested_date_is_returned(self):
        today = dt.datetime.now(dt.timezone.utc)
        tomorrow = today + dt.timedelta(days=1)
        with patch.object(fallback.bovada_scraper, "fetch_events",
                          return_value=[coupon_event(1, start=today),
                                        coupon_event(2, start=tomorrow)]):
            games = fallback.bovada_games("mlb", today.date().isoformat(), with_scores=False)
        self.assertEqual([g["game_id"] for g in games], ["bovada-1"])

    def test_a_scheduled_game_carries_no_score(self):
        with patch.object(fallback.bovada_scraper, "fetch_events",
                          return_value=[coupon_event(1)]):
            games = fallback.bovada_games("mlb", with_scores=False)
        self.assertIsNone(games[0]["home"]["score"])
        self.assertIsNone(games[0]["away"]["score"])
        self.assertEqual(games[0]["state"], "pre")

    def test_ids_are_namespaced_so_they_cannot_pass_as_espn_ids(self):
        with patch.object(fallback.bovada_scraper, "fetch_events",
                          return_value=[coupon_event(29645385)]):
            games = fallback.bovada_games("mlb", with_scores=False)
        self.assertEqual(games[0]["game_id"], "bovada-29645385")
        self.assertEqual(games[0]["source"], "bovada")

    def test_a_league_bovada_does_not_carry_returns_nothing(self):
        self.assertEqual(fallback.bovada_games("ncaaf"), [])

    def test_a_listing_failure_is_an_empty_board_not_an_exception(self):
        """This is the fallback. It must never hand a second failure to a path
        that is already degraded."""
        with patch.object(fallback.bovada_scraper, "fetch_events",
                          side_effect=RuntimeError("bovada down")):
            self.assertEqual(fallback.bovada_games("mlb"), [])

    def test_a_live_listing_entry_gets_its_score_attached(self):
        with patch.object(fallback.bovada_scraper, "fetch_events",
                          return_value=[coupon_event(1, live=True)]), \
             patch.object(fallback, "event_scoreboard", return_value={
                 "home": 4, "away": 2, "state": "in", "completed": False,
                 "status": "Top 5th", "period": 5, "clock": "5",
                 "status_detail": "Top 5th"}):
            games = fallback.bovada_games("mlb")
        self.assertEqual(games[0]["home"]["score"], 4)
        self.assertEqual(games[0]["status_detail"], "Top 5th")

    def test_a_live_game_whose_score_is_refused_still_shows_as_live(self):
        """No score is not no game — the matchup and its state still belong on
        the board, with the score rendering as a dash."""
        with patch.object(fallback.bovada_scraper, "fetch_events",
                          return_value=[coupon_event(1, live=True)]), \
             patch.object(fallback, "event_scoreboard", return_value=None):
            games = fallback.bovada_games("mlb")
        self.assertEqual(games[0]["state"], "in")
        self.assertIsNone(games[0]["home"]["score"])

    def test_scores_are_not_requested_for_games_that_are_not_live(self):
        """One extra request per LIVE game, never per scheduled one."""
        with patch.object(fallback.bovada_scraper, "fetch_events",
                          return_value=[coupon_event(1, live=False)]), \
             patch.object(fallback, "event_scoreboard") as score_call:
            fallback.bovada_games("mlb")
        score_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
