"""Tests for storyline templates and the independent wording audit."""
import copy
import unittest

import sports_relationships as sr
import storyline_audit as au
import storyline_templates as tp
from test_sports_relationships import BROOKS, CAPELA, DURANT, GREEN
from test_storyline_candidates import PHX_GAME, graph, raw, run, FormerTeammates

NAMES = {DURANT: "Kevin Durant", GREEN: "Jalen Green", BROOKS: "Dillon Brooks", CAPELA: "Clint Capela",
         "111": "Some Guy", "222": "Other Guy"}
EXPECT = {DURANT: "expected_to_play", GREEN: "expected_to_play", BROOKS: "expected_to_play"}


def result(**kw):
    kw.setdefault("availability", EXPECT)
    kw.setdefault("prior_meetings", [])
    kw.setdefault("meetings_coverage_start", "2025-01-01")
    return run(**kw)


def pick(res, kind, player=None):
    return next(c for c in res["candidates"]
                if c["kind"] == kind and (player is None or player in c["entities"]["players"]))


def render(c):
    return tp.render(c, NAMES)


def audit(c, text, g=None, as_of="2025-11-23"):
    return au.audit(c, text, g or graph(), as_of=as_of, names=NAMES)


def checks(report):
    return sorted({f["check"] for f in report["failures"]})


class Templates(unittest.TestCase):
    def test_reciprocal_states_each_direction_with_the_right_teams(self):
        out = render(pick(result(), "reciprocal_trade_reunion"))
        self.assertIn("Kevin Durant went from the Phoenix Suns to the Houston Rockets", out["text"])
        self.assertIn("Dillon Brooks and Jalen Green went from the Houston Rockets to the Phoenix Suns", out["text"])
        self.assertIn("July 6, 2025", out["text"])
        self.assertIn("Atlanta Hawks", out["text"])
        self.assertEqual(out["label"], "Trade reunion")

    def test_first_meeting_is_a_team_claim_and_names_no_return(self):
        out = render(pick(result(), "first_team_meeting_after_trade"))
        self.assertIn("first time since the July 6, 2025 trade", out["text"])
        self.assertNotIn("return", out["text"].lower())

    def test_expected_player_is_worded_as_expected(self):
        out = render(pick(result(), "former_team_matchup", DURANT))
        self.assertIn("Kevin Durant is expected to face the Phoenix Suns", out["headline"])
        self.assertIn("in a trade on July 6, 2025", out["body"])

    def test_unconfirmed_player_is_worded_with_if(self):
        out = render(pick(result(availability={DURANT: "unknown"}), "former_team_matchup", DURANT))
        self.assertTrue(out["headline"].startswith("If Kevin Durant plays"))
        self.assertNotIn("expected", out["text"])

    def test_arena_return_without_a_proven_first_never_says_first(self):
        out = render(pick(result(), "former_arena_return", DURANT))
        self.assertNotIn("first", out["text"].lower())

    def test_a_proven_first_return_says_first(self):
        res = result(appearance_history={"coverage_start": "2025-07-01", "games": {DURANT: []}})
        out = render(pick(res, "first_return_to_former_arena", DURANT))
        self.assertIn("first return to Phoenix", out["text"])

    def test_a_missing_name_fails_loudly(self):
        with self.assertRaises(ValueError):
            tp.render(pick(result(), "former_team_matchup", DURANT), {})

    def test_no_em_dash_and_no_banned_word_in_any_template(self):
        res = result(appearance_history={"coverage_start": "2025-07-01", "games": {DURANT: [], GREEN: [], BROOKS: []}})
        for c in res["candidates"]:
            text = render(c)["text"]
            self.assertNotIn("\u2014", text)
            self.assertEqual(au.banned_words(text), [], c["kind"])

    def test_teammates_complete_and_incomplete(self):
        g = graph(*FormerTeammates.ROWS)
        res = run(game=FormerTeammates.GAME, as_of="2024-02-29", roster={"BOS": ["222"], "PHI": ["111"]}, g=g,
                  availability={"222": "expected_to_play", "111": "expected_to_play"})
        out = render(pick(res, "former_teammates_now_opponents"))
        self.assertIn("February 2020 to January 2023", out["text"])
        part = copy.deepcopy(pick(res, "former_teammates_now_opponents"))
        part["claims"][0]["complete"] = False
        part["headline_eligible"] = False
        out = render(part)
        self.assertIn("not documented", out["text"])
        self.assertNotIn("face each other", out["text"])


class Audit(unittest.TestCase):
    def setUp(self):
        self.res = result()
        self.recip = pick(self.res, "reciprocal_trade_reunion")
        self.text = render(self.recip)["text"]

    def test_good_copy_passes(self):
        for c in self.res["candidates"]:
            report = audit(c, render(c)["text"])
            self.assertTrue(report["ok"], (c["kind"], report["failures"]))

    def test_a_reversed_trade_is_caught(self):
        bad = "Kevin Durant went from the Houston Rockets to the Phoenix Suns."
        self.assertIn("direction", checks(audit(self.recip, bad)))

    def test_one_reversed_sentence_is_caught_even_when_the_rest_is_right(self):
        bad = self.text + " Jalen Green went from the Phoenix Suns to the Houston Rockets."
        report = audit(self.recip, bad)
        self.assertIn("direction", checks(report))
        self.assertIn("not in the graph", report["failures"][0]["detail"])

    def test_a_missing_direction_statement_is_caught(self):
        self.assertIn("direction", checks(audit(self.recip, "Houston and Phoenix are linked by a trade.")))

    def test_a_claim_the_graph_does_not_hold_is_caught(self):
        forged = copy.deepcopy(self.recip)
        forged["claims"][0]["from"], forged["claims"][0]["to"] = forged["claims"][0]["to"], forged["claims"][0]["from"]
        self.assertIn("claim_not_in_graph", checks(audit(forged, self.text)))

    def test_emotion_words_are_caught(self):
        for word in ("revenge", "bad blood", "grudge match", "heated", "betrayed", "something to prove"):
            report = audit(self.recip, self.text + " A game of %s." % word)
            self.assertIn("banned_word", checks(report), word)

    def test_a_forged_former_team_claim_is_caught(self):
        c = copy.deepcopy(pick(self.res, "former_team_matchup", DURANT))
        c["claims"][0]["left_on"] = "2025-07-01"
        self.assertIn("claim_not_in_graph", checks(audit(c, render(c)["text"])))
        c = copy.deepcopy(pick(self.res, "former_team_matchup", DURANT))
        c["claims"][0]["former_team"] = "OKC"
        self.assertIn("claim_not_in_graph", checks(audit(c, "Kevin Durant faces the Oklahoma City Thunder.")))

    def test_a_forged_shared_tenure_claim_is_caught(self):
        g = graph(*FormerTeammates.ROWS)
        res = run(game=FormerTeammates.GAME, as_of="2024-02-29", roster={"BOS": ["222"], "PHI": ["111"]}, g=g,
                  availability={"222": "expected_to_play", "111": "expected_to_play"})
        c = copy.deepcopy(pick(res, "former_teammates_now_opponents"))
        self.assertTrue(au.audit(c, render(c)["text"], g, as_of="2024-02-29", names=NAMES)["ok"])
        c["claims"][0]["start"] = "2019-01-01"
        self.assertIn("claim_not_in_graph", checks(au.audit(c, render(c)["text"], g, as_of="2024-02-29", names=NAMES)))

    def test_an_unsupported_first_is_caught(self):
        c = pick(self.res, "former_arena_return", DURANT)
        report = audit(c, "Kevin Durant makes his first return to Phoenix.")
        self.assertIn("unsupported_first", checks(report))

    def test_first_team_meeting_wording_is_allowed_for_that_kind_only(self):
        first = pick(self.res, "first_team_meeting_after_trade")
        self.assertTrue(audit(first, render(first)["text"])["ok"])
        self.assertIn("unsupported_first", checks(audit(self.recip, "Houston and Phoenix meet for the first time since the trade.")))

    def test_expected_to_play_without_confirmation_is_caught(self):
        unconfirmed = pick(result(availability={DURANT: "unknown"}), "former_team_matchup", DURANT)
        report = audit(unconfirmed, "Kevin Durant is expected to face the Phoenix Suns, a former team.")
        self.assertIn("availability", checks(report))

    def test_a_team_that_is_not_in_the_matchup_is_caught(self):
        self.assertIn("unexpected_team", checks(audit(self.recip, self.text + " The Boston Celtics watch.")))

    def test_postgame_language_is_caught(self):
        for phrase in ("Houston won 110-100.", "Durant scored 31.", "The final score was close."):
            self.assertIn("postgame_language", checks(audit(self.recip, self.text + " " + phrase)), phrase)

    def test_a_fact_dated_after_the_cutoff_is_caught(self):
        self.assertIn("future_fact", checks(audit(self.recip, self.text, as_of="2025-07-05")))

    def test_an_em_dash_is_caught(self):
        self.assertIn("style", checks(audit(self.recip, self.text + " Big \u2014 game.")))

    def test_a_player_in_the_candidate_missing_from_a_player_claim_is_caught(self):
        c = pick(self.res, "former_team_matchup", DURANT)
        self.assertIn("missing_name", checks(audit(c, "A former team is on the schedule.", )))


if __name__ == "__main__":
    unittest.main()
