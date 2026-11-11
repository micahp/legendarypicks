"""Regression tests for the enhanced preview slice.

Every fixture here is SYNTHETIC. Teams are AAA and BBB. Players are "Player
One" and so on. None of the numbers is a real game result. The verified
Golden State at Houston fixture is still pending and is not in this file.

Run from backend/:  python3 -m unittest test_preview_editorial -v
"""
import copy
import unittest
from datetime import datetime, timedelta

from preview_angle_candidates import candidates_for_game
from preview_article_audit import audit
from preview_article_renderer import render_article, render_compact
from preview_story_plan import build_plan


def _results(pattern, start):
    """pattern like 'LLLWWWWWWWW' -> chronological result rows from a start date."""
    rows = []
    first = datetime.strptime(start, "%Y-%m-%d")
    for i, letter in enumerate(pattern):
        day = (first + timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append({"date": day, "result": letter,
                     "ts": day + "T23:59:00Z"})
    return rows


def synthetic_bundle():
    return {
        "game": {"id": "SYN-0001", "league": "nba",
                 "home": "BBB", "away": "AAA"},
        "as_of": "2026-11-11T20:00:00Z",
        "season": {"games_completed": 11, "games_scheduled": 82},
        "results": {
            # Three straight losses, then eight straight wins.
            "AAA": _results("LLLWWWWWWWW", "2026-10-29"),
            "BBB": _results("LWWLWWWLWWW", "2026-10-29"),
        },
        "broadcast": {"network": "NETWORK-A", "national": True,
                      "ts": "2026-11-01T00:00:00Z"},
        "players": {
            "P1": {
                "name": "Player One",
                "draft": {"year": 2026, "overall": 11,
                          "ts": "2026-06-23T00:00:00Z"},
                "game_logs": [
                    {"date": "2026-10-30", "points": 12,
                     "ts": "2026-10-30T23:59:00Z"},
                    {"date": "2026-11-01", "points": 37,
                     "ts": "2026-11-01T23:59:00Z"},
                    {"date": "2026-11-07", "points": 23,
                     "ts": "2026-11-07T23:59:00Z"},
                    {"date": "2026-11-09", "points": 23,
                     "ts": "2026-11-09T23:59:00Z"},
                    # After the cutoff. Must never appear.
                    {"date": "2026-11-12", "points": 40,
                     "ts": "2026-11-12T23:59:00Z"},
                ],
            },
            "P2": {"name": "Player Two", "draft": None, "game_logs": []},
        },
        "availability": [
            {"player_id": "P2", "status": "out",
             "ts": "2026-11-11T18:00:00Z"},
            # Published after the cutoff. Must never appear.
            {"player_id": "P1", "status": "probable",
             "ts": "2026-11-12T10:00:00Z"},
        ],
    }


def build(bundle):
    candidates = candidates_for_game(bundle)
    plan = build_plan(bundle, candidates)
    article = render_article(plan, candidates)
    return candidates, plan, article


class CandidateTests(unittest.TestCase):
    def test_streak_claim_has_the_opening_stretch(self):
        candidates, _plan, _article = build(synthetic_bundle())
        momentum = next(c for c in candidates if c["id"] == "momentum:AAA")
        self.assertEqual(momentum["claim"],
                         "AAA lost their opening three games and have won "
                         "eight straight")
        self.assertEqual(momentum["streak_length"], 8)
        self.assertEqual(momentum["opening_losses"], 3)

    def test_emerging_player_uses_only_visible_logs(self):
        candidates, _plan, _article = build(synthetic_bundle())
        player = next(c for c in candidates if c["id"] == "player:P1")
        self.assertEqual(player["points"], [37, 23, 23])
        self.assertIn("37, 23 and 23 points", player["claim"])
        self.assertNotIn("40", player["claim"])

    def test_no_recent_logs_means_no_player_claim(self):
        bundle = synthetic_bundle()
        bundle["players"]["P1"]["game_logs"] = []
        candidates, _plan, _article = build(bundle)
        self.assertFalse(any(c["id"] == "player:P1" for c in candidates))

    def test_post_cutoff_availability_is_ignored(self):
        candidates, _plan, _article = build(synthetic_bundle())
        ids = [c["id"] for c in candidates]
        self.assertIn("availability:P2", ids)
        self.assertNotIn("availability:P1", ids)


class DraftGuardTests(unittest.TestCase):
    def test_drafted_player_is_never_called_undrafted(self):
        _c, _p, article = build(synthetic_bundle())
        text = " ".join([article["headline"], article["deck"]] +
                        [s["paragraph"] for s in article["sections"]])
        self.assertIn("11th overall", text)
        self.assertNotIn("undrafted", text.lower())

    def test_mutated_draft_record_fails_the_audit(self):
        bundle = synthetic_bundle()
        candidates, plan, article = build(bundle)
        article = copy.deepcopy(article)
        article["headline"] = article["headline"] + " undrafted rookie"
        self.assertTrue(any("undrafted" in p for p in
                            audit(bundle, candidates, article)))

    def test_missing_draft_record_cannot_be_cited(self):
        bundle = synthetic_bundle()
        bundle["players"]["P1"]["draft"] = None
        candidates, _plan, article = build(bundle)
        self.assertNotIn("overall", article["sections"][0]["paragraph"]
                         if article["sections"] else "")
        self.assertEqual(audit(bundle, candidates, article), [])


class BroadcastTests(unittest.TestCase):
    def test_national_telecast_is_mentioned(self):
        _c, _p, article = build(synthetic_bundle())
        self.assertIn("nationally televised on NETWORK-A", str(article))

    def test_regional_telecast_removes_the_claim(self):
        bundle = synthetic_bundle()
        bundle["broadcast"]["national"] = False
        candidates, _plan, article = build(bundle)
        self.assertFalse(any(c["kind"] == "national_broadcast"
                             for c in candidates))
        self.assertNotIn("nationally", str(article).lower())


class AvailabilityTests(unittest.TestCase):
    def test_out_player_is_stated_as_listed_not_as_playing(self):
        _c, _p, article = build(synthetic_bundle())
        text = str(article)
        self.assertIn("Player Two is listed as out", text)
        self.assertNotIn("will play", text.lower())


class EarlySeasonTests(unittest.TestCase):
    def test_early_stage_adds_the_small_sample_caveat(self):
        _c, plan, article = build(synthetic_bundle())
        self.assertEqual(plan["season_stage"]["phase"], "early_regular_season")
        self.assertIn("Only 11 games have been played", str(article))

    def test_no_stakes_language_early_in_the_season(self):
        bundle = synthetic_bundle()
        candidates, _plan, article = build(bundle)
        text = str(article).lower()
        for phrase in ("season-defining", "contender", "must-win",
                       "playoff implications", "clinch"):
            self.assertNotIn(phrase, text)
        self.assertEqual(audit(bundle, candidates, article), [])

    def test_unknown_league_makes_no_stage_claim(self):
        bundle = synthetic_bundle()
        bundle["game"]["league"] = "nfl"
        _c, plan, article = build(bundle)
        self.assertEqual(plan["season_stage"]["phase"], "unknown")
        self.assertNotIn("small", str(article).lower())


class RenderingTests(unittest.TestCase):
    def test_same_inputs_give_identical_output(self):
        first = build(synthetic_bundle())[2]
        second = build(synthetic_bundle())[2]
        self.assertEqual(first, second)
        self.assertEqual(first["preview_id"], second["preview_id"])

    def test_compact_preview_is_one_to_three_sentences(self):
        bundle = synthetic_bundle()
        candidates = candidates_for_game(bundle)
        plan = build_plan(bundle, candidates)
        compact = render_compact(plan, candidates)
        self.assertTrue(compact)
        self.assertLessEqual(compact.count("."), 3)

    def test_no_lead_renders_nothing(self):
        bundle = synthetic_bundle()
        bundle["results"] = {}
        bundle["players"] = {}
        bundle["availability"] = []
        bundle["broadcast"] = None
        candidates, plan, article = build(bundle)
        self.assertEqual(candidates, [])
        self.assertIsNone(article)
        self.assertIsNone(render_compact(plan, candidates))

    def test_no_probability_or_projection_is_invented(self):
        _c, _p, article = build(synthetic_bundle())
        text = str(article).lower()
        self.assertNotIn("%", text)
        self.assertNotIn("probability", text)
        self.assertNotIn("projected", text)

    def test_clean_render_passes_the_audit(self):
        bundle = synthetic_bundle()
        candidates, _plan, article = build(bundle)
        self.assertEqual(audit(bundle, candidates, article), [])


if __name__ == "__main__":
    unittest.main()
