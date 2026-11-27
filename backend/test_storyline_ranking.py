"""Tests for the editorial ranking of storyline candidates."""
import copy
import json
import unittest

import storyline_candidates as sc
import storyline_ranking as rk
from test_storyline_candidates import AS_OF, HOU_GAME, PHX_GAME, ROSTER, run
from test_sports_relationships import CAPELA, DURANT, GREEN, BROOKS

STREAK = {"kind": "winning_streak", "lead_team": "HOU", "teams": ["PHX", "HOU"]}
UNDEFEATED = {"kind": "undefeated", "lead_team": "HOU", "teams": ["PHX", "HOU"]}
RECORDS = {"kind": "records", "lead_team": "PHX", "teams": ["PHX", "HOU"]}


def cand(cid, kind="former_team_matchup", eligible=True, event="e1", players=("1",), recency=100,
         teams=3, first=False, claims=None, reasons=(), shared=None):
    return {"candidate_id": cid, "kind": kind, "entities": {"teams": ["A", "B"], "players": list(players)},
            "event_id": event, "claim_scope": "x", "headline_eligible": eligible,
            "claims": claims if claims is not None else [{"type": "former_team", "tenure_start_documented": True,
                                                          "tenure_start": "2020-01-01", "left_on": "2023-01-01"}],
            "evidence_ids": ["ev"], "reasons": list(reasons),
            "rank_features": {"recency_days": recency, "multi_party_teams": teams, "first_event": first,
                              "shared_days": shared}}


def rank(cands, existing=STREAK, **kw):
    return rk.rank(cands, existing_angle=existing, **kw)


def roles(result):
    return {e["candidate_id"]: e["role"] for e in result["log"]}


class HoustonPhoenix(unittest.TestCase):
    def detect(self, game=PHX_GAME, **kw):
        kw.setdefault("availability", {DURANT: "expected_to_play", GREEN: "expected_to_play", BROOKS: "expected_to_play"})
        kw.setdefault("prior_meetings", [])
        kw.setdefault("meetings_coverage_start", "2025-01-01")
        avail = kw.pop("availability")
        return run(game=game, availability=avail, **kw)

    def test_the_first_meeting_after_a_major_trade_beats_a_generic_streak(self):
        result = rank(self.detect()["candidates"])
        self.assertEqual(result["lead"]["kind"], "first_team_meeting_after_trade")

    def test_the_reciprocal_trade_is_more_specific_than_a_generic_former_team_mention(self):
        cands = [c for c in self.detect()["candidates"] if c["kind"] != "first_team_meeting_after_trade"]
        result = rank(cands)
        self.assertEqual(result["lead"]["kind"], "reciprocal_trade_reunion")

    def test_the_same_trade_does_not_lead_forever(self):
        fresh = rank(self.detect()["candidates"])["lead"]["score"]
        late = self.detect(game=dict(PHX_GAME, date="2027-03-01"), as_of="2027-02-28",
                           prior_meetings=["2025-11-24"])
        old = rank(late["candidates"])
        self.assertLess(old["lead"]["score"], fresh)
        self.assertEqual(old["lead"]["kind"], "existing:winning_streak")      # decayed trade, generic streak wins

    def test_a_bigger_supported_angle_can_still_win(self):
        result = rank(self.detect()["candidates"], existing=UNDEFEATED)
        self.assertEqual(result["lead"]["kind"], "existing:undefeated")

    def test_complementary_angles_become_context_not_a_second_headline(self):
        result = rank(self.detect()["candidates"])
        self.assertEqual(result["lead"]["kind"], "first_team_meeting_after_trade")
        by_kind = {e["kind"]: e for e in result["log"]}
        self.assertEqual(by_kind["reciprocal_trade_reunion"]["role"], "context")
        self.assertEqual(by_kind["reciprocal_trade_reunion"]["reason"], "same_event_as_lead")
        self.assertEqual(sum(1 for e in result["log"] if e["role"] == "lead"), 1)

    def test_a_scratched_star_leaves_the_team_angle_in_front(self):
        result = rank(self.detect(availability={DURANT: "inactive", GREEN: "inactive", BROOKS: "inactive"})["candidates"])
        self.assertEqual(result["lead"]["kind"], "first_team_meeting_after_trade")
        self.assertNotIn("former_arena_return", [e["kind"] for e in result["log"]])


class Guards(unittest.TestCase):
    def test_no_candidates_leaves_the_existing_angle_alone(self):
        result = rank([])
        self.assertEqual(result["lead"]["kind"], "existing:winning_streak")
        self.assertEqual(result["secondary"], [])

    def test_a_weak_connection_does_not_beat_the_floor(self):
        weak = cand("w", recency=1200, teams=2, claims=[{"type": "former_team", "tenure_start_documented": False,
                                                          "tenure_start": None, "left_on": "2023-01-01"}],
                    reasons=["availability_unconfirmed"], eligible=False)
        self.assertEqual(rank([weak], existing=RECORDS)["lead"]["kind"], "existing:records")

    def test_a_candidate_not_headline_eligible_never_leads(self):
        strong = cand("s", kind="reciprocal_trade_reunion", eligible=False, recency=1, first=True, teams=7)
        result = rank([strong], existing=RECORDS)
        self.assertEqual(result["lead"]["kind"], "existing:records")
        self.assertEqual(roles(result)["s"], "context")

    def test_unknown_existing_angle_kind_fails_loudly(self):
        with self.assertRaises(ValueError):
            rank([], existing={"kind": "mystery"})

    def test_no_existing_angle_and_nothing_eligible_means_no_lead(self):
        result = rk.rank([cand("x", eligible=False)], existing_angle=None)
        self.assertIsNone(result["lead"])

    def test_prior_use_lowers_the_score(self):
        base = rank([cand("a", kind="reciprocal_trade_reunion", first=True)])
        used = rank([cand("a", kind="reciprocal_trade_reunion", first=True)], prior_use={"e1": 2})
        a = next(e for e in base["log"] if e["candidate_id"] == "a")["score"]
        b = next(e for e in used["log"] if e["candidate_id"] == "a")["score"]
        self.assertLess(b, a)
        self.assertAlmostEqual(b, a * 0.5, places=6)

    def test_stakes_raise_the_score_only_when_supplied(self):
        c = cand("a", kind="reciprocal_trade_reunion", first=True)
        plain = next(e for e in rank([c])["log"] if e["candidate_id"] == "a")["score"]
        high = next(e for e in rank([c], stakes=1.0)["log"] if e["candidate_id"] == "a")["score"]
        self.assertGreater(high, plain)

    def test_incomplete_evidence_lowers_the_score_on_its_own(self):
        # reciprocal strength ignores claims, so only the evidence factor can differ
        full = cand("f", kind="reciprocal_trade_reunion", claims=[{"type": "moved"}])
        part = cand("p", kind="reciprocal_trade_reunion", claims=[{"type": "moved", "complete": False}])
        log = {e["candidate_id"]: e["score"] for e in rank([full, part])["log"]}
        self.assertAlmostEqual(log["p"], log["f"] * rk.RUBRIC["incomplete_evidence"], places=6)

    def test_ties_break_on_candidate_id(self):
        a = cand("nba:g:z", event="e1", players=("1",))
        b = cand("nba:g:a", event="e2", players=("2",))
        order = [e["candidate_id"] for e in rank([a, b], existing=RECORDS)["log"] if e["candidate_id"].startswith("nba")]
        self.assertEqual(order, ["nba:g:a", "nba:g:z"])

    def test_a_duplicate_event_and_players_is_omitted(self):
        a = cand("a", kind="former_team_matchup")
        b = cand("b", kind="former_arena_return", first=True)
        log = {e["candidate_id"]: e for e in rank([a, b])["log"]}
        self.assertEqual({log["a"]["role"], log["b"]["role"]} - {"lead", "secondary", "context"}, {"omitted"})

    def test_secondary_cap(self):
        cands = [cand("c%d" % i, event="e%d" % i, players=(str(i),), recency=30) for i in range(6)]
        result = rank(cands, existing=RECORDS, max_secondary=2)
        self.assertLessEqual(len(result["secondary"]), 2)
        self.assertIn("below_secondary_cap", [e.get("reason") for e in result["log"]])

    def test_detector_rejections_are_logged(self):
        det = run(availability={DURANT: "inactive"})
        result = rank(det["candidates"], rejected=det["rejected"])
        self.assertIn("player_inactive", [e["reason"] for e in result["log"] if e["role"] == "rejected_by_detector"])

    def test_every_log_row_carries_its_feature_breakdown(self):
        result = rank([cand("a")])
        row = next(e for e in result["log"] if e["candidate_id"] == "a")
        self.assertEqual(set(row["features"]), set(rk.RUBRIC["weights"]))

    def test_output_is_stable_and_versioned(self):
        det = run(availability={DURANT: "expected_to_play"})
        one = json.dumps(rank(det["candidates"]), sort_keys=True)
        two = json.dumps(rank(copy.deepcopy(det["candidates"])), sort_keys=True)
        self.assertEqual(one, two)
        self.assertEqual(json.loads(one)["rubric_version"], rk.RUBRIC["version"])

    def test_input_candidates_are_not_mutated(self):
        det = run(availability={DURANT: "expected_to_play"})
        before = json.dumps(det["candidates"], sort_keys=True)
        rank(det["candidates"])
        self.assertEqual(json.dumps(det["candidates"], sort_keys=True), before)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(rk.RUBRIC["weights"].values()), 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
