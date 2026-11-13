"""Tests for the deterministic storyline candidate detector."""
import json
import unittest

import sports_relationships as sr
import storyline_candidates as sc
from test_sports_relationships import (BROOKS, CAPELA, DURANT, GREEN, extra, raw, rows_from,
                                       sample_payload)

PHX_GAME = {"game_id": "g1", "date": "2025-11-24", "home": "PHX", "away": "HOU"}   # at Phoenix
HOU_GAME = {"game_id": "g2", "date": "2026-01-20", "home": "HOU", "away": "PHX"}   # at Houston
ROSTER = {"HOU": [DURANT, CAPELA], "PHX": [GREEN, BROOKS]}
AS_OF = "2025-11-23"


def graph(*new_rows, as_of=None):
    return sr.build_graph(rows_from(extra(sample_payload(), *new_rows)), as_of=as_of)


def run(game=PHX_GAME, roster=ROSTER, availability=None, g=None, **kw):
    kw.setdefault("as_of", AS_OF)
    return sc.detect(game, g or graph(), roster, availability or {}, **kw)


def kinds(result):
    return sorted(c["kind"] for c in result["candidates"])


def one(result, kind, player=None):
    found = [c for c in result["candidates"] if c["kind"] == kind
             and (player is None or player in c["entities"]["players"])]
    assert len(found) == 1, (kind, player, [c["candidate_id"] for c in result["candidates"]])
    return found[0]


def reasons(result, kind):
    return [r["reason"] for r in result["rejected"] if r["kind"] == kind]


class FormerTeam(unittest.TestCase):
    def test_durant_against_the_suns_who_traded_him(self):
        c = one(run(availability={DURANT: "expected_to_play"}), "former_team_matchup", DURANT)
        self.assertEqual(c["entities"]["teams"], ["HOU", "PHX"])
        self.assertEqual(c["claim_scope"], "player_vs_former_team")
        self.assertTrue(c["evidence_ids"])
        self.assertTrue(c["headline_eligible"])

    def test_unconfirmed_availability_is_not_headline_eligible(self):
        c = one(run(availability={DURANT: "unknown"}), "former_team_matchup", DURANT)
        self.assertFalse(c["headline_eligible"])
        self.assertIn("availability_unconfirmed", c["reasons"])

    def test_an_inactive_player_is_rejected_with_a_reason(self):
        result = run(availability={DURANT: "inactive"})
        self.assertNotIn(DURANT, [p for c in result["candidates"]
                                  if c["kind"] == "former_team_matchup" for p in c["entities"]["players"]])
        self.assertIn("player_inactive", reasons(result, "former_team_matchup"))

    def test_the_other_side_gets_its_own_candidate(self):
        result = run(availability={GREEN: "expected_to_play"})
        self.assertEqual(one(result, "former_team_matchup", GREEN)["entities"]["teams"], ["HOU", "PHX"])

    def test_a_player_only_ever_on_the_current_team_has_no_former_team_tie(self):
        result = run(roster={"HOU": ["999"], "PHX": ["998"]})
        self.assertEqual([c for c in result["candidates"] if c["entities"]["players"] and c["kind"] != "reciprocal_trade_reunion"], [])
        self.assertNotIn("former_team_matchup", kinds(result))


class Reciprocal(unittest.TestCase):
    def test_two_way_trade_between_the_teams(self):
        c = one(run(), "reciprocal_trade_reunion")
        self.assertEqual(c["entities"]["teams"], ["HOU", "PHX"])
        self.assertEqual(sorted(c["entities"]["players"]), sorted([DURANT, GREEN, BROOKS]))
        self.assertEqual(c["claim_scope"], "scheduled_team_matchup")
        self.assertTrue(c["event_id"].startswith("nba:trade:Trade-2025005"))

    def test_a_one_way_deal_is_not_reciprocal(self):
        game = {"game_id": "g3", "date": "2025-12-01", "home": "ATL", "away": "HOU"}
        result = run(game=game, roster={"HOU": [CAPELA], "ATL": []})
        self.assertNotIn("reciprocal_trade_reunion", kinds(result))
        self.assertIn("former_team_matchup", kinds(result))        # Capela vs the Hawks

    def test_the_trade_stays_a_team_angle_when_a_player_is_scratched(self):
        result = run(availability={DURANT: "inactive", GREEN: "inactive", BROOKS: "inactive"})
        self.assertIn("reciprocal_trade_reunion", kinds(result))

    def test_a_trade_after_the_cutoff_is_not_used(self):
        result = run(as_of="2025-07-05")
        self.assertEqual(result["candidates"], [])


class FirstTeamMeeting(unittest.TestCase):
    def test_first_meeting_after_the_trade_ignores_who_plays(self):
        result = run(availability={DURANT: "inactive"}, prior_meetings=[], meetings_coverage_start="2025-01-01")
        c = one(result, "first_team_meeting_after_trade")
        self.assertEqual(c["claim_scope"], "scheduled_team_matchup")
        self.assertTrue(c["rank_features"]["first_event"])
        self.assertEqual(c["entities"]["players"], [])           # a team claim, not a player return

    def test_an_earlier_meeting_after_the_trade_means_not_first(self):
        result = run(game=HOU_GAME, prior_meetings=["2025-11-24"], meetings_coverage_start="2025-01-01",
                     as_of="2026-01-19")
        self.assertNotIn("first_team_meeting_after_trade", kinds(result))
        self.assertIn("prior_meeting_exists", reasons(result, "first_team_meeting_after_trade"))
        self.assertIn("reciprocal_trade_reunion", kinds(result))

    def test_meeting_history_that_starts_after_the_trade_proves_nothing(self):
        result = run(prior_meetings=[], meetings_coverage_start="2025-09-01")
        self.assertNotIn("first_team_meeting_after_trade", kinds(result))
        self.assertIn("meeting_history_incomplete", reasons(result, "first_team_meeting_after_trade"))

    def test_no_meeting_history_given_is_unknown_not_first(self):
        result = run()
        self.assertNotIn("first_team_meeting_after_trade", kinds(result))


class ArenaReturn(unittest.TestCase):
    def test_return_to_the_former_arena_without_history_is_not_a_first(self):
        result = run(availability={DURANT: "expected_to_play"})
        self.assertIn("former_arena_return", kinds(result))
        self.assertNotIn("first_return_to_former_arena", kinds(result))

    def test_first_return_needs_complete_appearance_history(self):
        history = {"coverage_start": "2025-07-01", "games": {DURANT: []}}
        result = run(availability={DURANT: "expected_to_play"}, appearance_history=history)
        self.assertIn("first_return_to_former_arena", kinds(result))

    def test_a_prior_appearance_at_that_arena_since_the_trade_is_not_a_first(self):
        history = {"coverage_start": "2025-07-01",
                   "games": {DURANT: [{"date": "2025-11-24", "home": "PHX"}]}}
        game = dict(PHX_GAME, game_id="g9", date="2026-04-07")
        result = run(game=game, as_of="2026-04-06", availability={DURANT: "expected_to_play"},
                     appearance_history=history)
        self.assertNotIn("first_return_to_former_arena", kinds(result))
        self.assertIn("former_arena_return", kinds(result))

    def test_a_scratched_player_has_no_arena_return(self):
        result = run(availability={DURANT: "inactive"},
                     appearance_history={"coverage_start": "2025-07-01", "games": {DURANT: []}})
        self.assertNotIn("former_arena_return", kinds(result))
        self.assertNotIn("first_return_to_former_arena", kinds(result))

    def test_history_that_starts_after_the_trade_is_not_enough(self):
        history = {"coverage_start": "2025-10-01", "games": {DURANT: []}}
        result = run(availability={DURANT: "expected_to_play"}, appearance_history=history)
        self.assertNotIn("first_return_to_former_arena", kinds(result))

    def test_only_the_former_teams_own_arena_counts(self):
        result = run(game=HOU_GAME, as_of="2026-01-19", availability={DURANT: "expected_to_play"})
        durant_returns = [c for c in result["candidates"] if c["kind"] == "former_arena_return"
                          and DURANT in c["entities"]["players"]]
        self.assertEqual(durant_returns, [])                    # Houston is not Durant's former arena


class FormerTeammates(unittest.TestCase):
    ROWS = (
        raw("2020-01-01", "Signing", "Boston Celtics signed guard Some Guy to a Contract.", "celtics", 111, "some-guy"),
        raw("2020-02-01", "Signing", "Boston Celtics signed guard Other Guy to a Contract.", "celtics", 222, "other-guy"),
        raw("2023-01-01", "Trade", "Philadelphia 76ers received guard Some Guy from Boston Celtics.",
            "sixers", 111, "some-guy", "Trade 2023001"),
    )
    GAME = {"game_id": "g5", "date": "2024-03-01", "home": "BOS", "away": "PHI"}

    def test_documented_shared_tenure_makes_a_candidate(self):
        result = run(game=self.GAME, as_of="2024-02-29", roster={"BOS": ["222"], "PHI": ["111"]},
                     g=graph(*self.ROWS), availability={"222": "expected_to_play", "111": "expected_to_play"})
        c = one(result, "former_teammates_now_opponents")
        self.assertEqual(sorted(c["entities"]["players"]), ["111", "222"])
        self.assertTrue(c["headline_eligible"])
        self.assertEqual(c["claims"][0]["team"], "BOS")
        self.assertEqual(c["claims"][0]["start"], "2020-02-01")
        self.assertEqual(c["claims"][0]["end"], "2023-01-01")

    def test_a_re_signed_start_is_not_enough_for_a_headline(self):
        rows = (raw("2017-07-01", "Signing", "Boston Celtics re-signed forward Jayson Tatum to a Rookie Scale Contract.",
                    "celtics", 1628369, "jayson-tatum"),
                raw("2016-07-27", "Signing", "Boston Celtics re-signed guard Jaylen Brown to a Rookie Scale Contract.",
                    "celtics", 1627759, "jaylen-brown"),
                raw("2026-07-06", "Trade", "Philadelphia 76ers received guard Jaylen Brown from Boston Celtics.",
                    "sixers", 1627759, "jaylen-brown", "Trade 2026001"))
        game = {"game_id": "g6", "date": "2026-12-01", "home": "BOS", "away": "PHI"}
        result = run(game=game, as_of="2026-11-30", roster={"BOS": ["1628369"], "PHI": ["1627759"]},
                     g=graph(*rows), availability={"1628369": "expected_to_play", "1627759": "expected_to_play"})
        c = one(result, "former_teammates_now_opponents")
        self.assertFalse(c["headline_eligible"])
        self.assertIn("shared_tenure_incomplete", c["reasons"])

    def test_players_who_never_shared_a_team_make_no_candidate(self):
        result = run(game=self.GAME, as_of="2024-02-29", roster={"BOS": ["222"], "PHI": [DURANT]},
                     g=graph(*self.ROWS))
        self.assertNotIn("former_teammates_now_opponents", kinds(result))


class Guards(unittest.TestCase):
    def test_no_connection_leaves_nothing_to_say(self):
        game = {"game_id": "g7", "date": "2025-12-01", "home": "BOS", "away": "LAL"}
        self.assertEqual(run(game=game, roster={"BOS": ["1"], "LAL": ["2"]})["candidates"], [])

    def test_a_played_status_in_a_pregame_call_is_refused(self):
        with self.assertRaises(ValueError):
            run(availability={DURANT: "played"})

    def test_an_unknown_status_word_is_refused(self):
        with self.assertRaises(ValueError):
            run(availability={DURANT: "probably"})

    def test_a_cutoff_after_the_game_date_is_refused(self):
        with self.assertRaises(ValueError):
            run(as_of="2025-11-25")

    def test_same_inputs_give_identical_output(self):
        a = json.dumps(run(availability={DURANT: "expected_to_play"}), sort_keys=True)
        b = json.dumps(run(availability={DURANT: "expected_to_play"}), sort_keys=True)
        self.assertEqual(a, b)

    def test_candidates_are_ordered_by_id(self):
        ids = [c["candidate_id"] for c in run(availability={DURANT: "expected_to_play"})["candidates"]]
        self.assertEqual(ids, sorted(ids))

    def test_coverage_is_stated(self):
        cov = run()["coverage"]
        self.assertEqual(cov["transactions_from"], "2025-07-06")     # earliest row in this fixture
        self.assertEqual(cov["appearances"], "unknown")

    def test_a_graph_built_without_as_of_still_cannot_leak_a_later_trade(self):
        late = raw("2025-11-30", "Trade", "Phoenix Suns received guard Some Guy from Houston Rockets.",
                   "suns", 777, "some-guy", "Trade 2025099")
        result = run(g=graph(late), roster={"HOU": [], "PHX": ["777"]})
        self.assertNotIn("777", [p for c in result["candidates"] for p in c["entities"]["players"]])


if __name__ == "__main__":
    unittest.main()
