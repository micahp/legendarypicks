#!/usr/bin/env python3
"""UFC finish parsing: details[] -> outcome_method/outcome_round/outcome_clock.

The raw shapes are the measured 2026-08-19 ufc/scoreboard payloads (2026-08-15
and 2026-08-18): the method lives in `competitions[].details[].type`
("Unofficial Winner Submission" / "Kotko" / "Decision"), and the round/clock in
`status`. A fight that goes the distance publishes no finish detail; Decision is
derived only when period == regulation.periods and the clock is the full round.
"""
import unittest
import warnings

from espn_client.scoreboard import _games_from_payload


def _fight(fight_id="600059185", method_id=None, method_text="Unofficial Winner X",
           period=3, clock="1:24", regulation=3, state="post", completed=True):
    details = []
    if method_id is not None:
        details.append({"id": "18901", "type": {"id": method_id, "text": method_text}})
    # the event-detail noise a real payload also carries
    details.append({"id": "18900", "type": {"id": "19", "text": "Fight Over"}})
    return {
        "id": "401869336",
        "name": "Test Card",
        "date": "2026-08-16T01:00Z",
        "competitions": [{
            "id": fight_id,
            "date": "2026-08-16T01:00Z",
            # `completed` is what ESPN actually publishes and what decides
            # whether a fight is over. Measured on the real 2026-08-15 payload:
            #   {"id":"3","name":"STATUS_FINAL","state":"post","completed":true,...}
            # An earlier version of this fixture omitted it, so the tests were
            # asserting against a payload ESPN never sends.
            "status": {"type": {"state": state, "completed": completed,
                                "description": "Final", "shortDetail": "Final"},
                       "period": period, "displayClock": clock},
            "format": {"regulation": {"periods": regulation}},
            "details": details,
            "competitors": [
                {"id": "3332412", "order": 1, "winner": True,
                 "athlete": {"id": "3332412", "displayName": "Islam Makhachev",
                             "shortName": "I. Makhachev"},
                 "records": [{"type": "total", "summary": "29-1-0"}]},
                {"id": "4738092", "order": 2, "winner": False,
                 "athlete": {"id": "4738092", "displayName": "Ian Machado Garry",
                             "shortName": "I. Machado Garry"},
                 "records": [{"type": "total", "summary": "17-2-0"}]},
            ],
        }],
    }


def _one(payload):
    games = _games_from_payload("ufc", None, {"events": [payload]})
    assert len(games) == 1, games
    return games[0]


class UfcOutcomeTests(unittest.TestCase):
    def test_submission_detail_becomes_the_method(self):
        g = _one(_fight(method_id="20", method_text="Unofficial Winner Submission",
                        period=3, clock="1:24"))
        self.assertEqual(g["outcome_method"], "Submission")
        self.assertEqual(g["outcome_round"], 3)
        self.assertEqual(g["outcome_clock"], "1:24")

    def test_kotko_is_ko_tko(self):
        # ESPN's spelling of KO/TKO is literally "Kotko" (measured 2026-08-15).
        g = _one(_fight(method_id="21", method_text="Unofficial Winner Kotko",
                        period=1, clock="1:38"))
        self.assertEqual(g["outcome_method"], "KO/TKO")
        self.assertEqual(g["outcome_round"], 1)

    def test_decision_detail_is_decision(self):
        g = _one(_fight(method_id="22", method_text="Unofficial Winner Decision",
                        period=5, clock="5:00", regulation=5))
        self.assertEqual(g["outcome_method"], "Decision")

    def test_distance_with_no_detail_derives_decision(self):
        # No finish detail, but the published period IS the regulation length
        # and the clock is the full round: the fight went the distance.
        g = _one(_fight(method_id=None, period=3, clock="5:00", regulation=3))
        self.assertEqual(g["outcome_method"], "Decision")

    def test_mid_round_stop_with_no_detail_emits_nothing(self):
        # period == regulation but the clock is NOT the full round: this could
        # be a finish we cannot name — never guess.
        g = _one(_fight(method_id=None, period=3, clock="1:36", regulation=3))
        self.assertIsNone(g["outcome_method"])

    def test_early_stop_with_no_detail_emits_nothing(self):
        g = _one(_fight(method_id=None, period=1, clock="2:03", regulation=3))
        self.assertIsNone(g["outcome_method"])

    def test_unrecognised_winner_detail_is_warned_not_dropped(self):
        # A method id we have never seen (e.g. No Contest) must be named.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            g = _one(_fight(method_id="24", method_text="Unofficial Winner No Contest",
                            period=3, clock="1:24"))
        self.assertIsNone(g["outcome_method"])
        self.assertTrue(any("unrecognised finish detail type id '24'" in str(w.message)
                            for w in caught), [str(w.message) for w in caught])

    def test_event_details_do_not_warn(self):
        # Round Start / Fight Over / Takedown are event details, not methods.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _one(_fight(method_id=None, period=3, clock="5:00", regulation=3))
        self.assertEqual([str(w.message) for w in caught], [])


class UfcOutcomeUnfinishedTests(unittest.TestCase):
    """Nothing is emitted for a fight that is not over.

    These are the empty-window cases. The decision rule reads period and clock,
    and a LIVE fight at the start of its final round publishes exactly what a
    decision publishes: period == regulation, displayClock "5:00" (UFC rounds
    count down from 5:00). Without a completion guard the board labels a fight
    "Decision" while it is still being fought.
    """

    def test_live_fight_at_the_start_of_the_final_round_is_not_a_decision(self):
        g = _one(_fight(method_id=None, period=3, clock="5:00", regulation=3,
                        state="in", completed=False))
        self.assertIsNone(g["outcome_method"])
        self.assertIsNone(g["outcome_round"])
        self.assertIsNone(g["outcome_clock"])

    def test_live_five_round_fight_at_the_start_of_round_five(self):
        g = _one(_fight(method_id=None, period=5, clock="5:00", regulation=5,
                        state="in", completed=False))
        self.assertIsNone(g["outcome_method"])

    def test_scheduled_fight_emits_nothing(self):
        g = _one(_fight(method_id=None, period=0, clock="5:00",
                        state="pre", completed=False))
        self.assertIsNone(g["outcome_method"])

    def test_postponed_is_state_post_but_was_never_fought(self):
        # `state == "post"` is not "this fight happened": a postponed event is
        # also state=post. `completed` is the key, the same rule the rest of
        # espn_client.scoreboard already follows.
        g = _one(_fight(method_id="20", method_text="Unofficial Winner Submission",
                        period=3, clock="1:24", state="post", completed=False))
        self.assertIsNone(g["outcome_method"])


if __name__ == "__main__":
    unittest.main()
