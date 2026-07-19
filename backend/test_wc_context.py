import json
import os
import sys
import tempfile
import unittest
from collections import OrderedDict
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wc_context


def _signal(subject, quote, ts, strength=2, kind="momentum"):
    return {
        "type": kind,
        "subject": subject,
        "quote": quote,
        "direction": "bullish",
        "strength": strength,
        "ts": ts,
    }


def _bracket_fixture():
    return {
        "rounds": [
            {
                "round": "Quarterfinals",
                "matches": [
                    {
                        "game_id": "760511",
                        "date": "2026-07-10T19:00Z",
                        "home": {"abbrev": "ESP", "name": "Spain"},
                        "away": {"abbrev": "BEL", "name": "Belgium"},
                        "homeScore": 2,
                        "awayScore": 1,
                        "winner": "ESP",
                        "status": "STATUS_FULL_TIME",
                    },
                    {
                        "game_id": "760513",
                        "date": "2026-07-12T01:00Z",
                        "home": {"abbrev": "ARG", "name": "Argentina"},
                        "away": {"abbrev": "SUI", "name": "Switzerland"},
                        "homeScore": 3,
                        "awayScore": 1,
                        "winner": "ARG",
                        "status": "STATUS_FINAL_AET",
                    },
                ],
            },
            {
                "round": "Semifinals",
                "matches": [
                    {
                        "game_id": "760514",
                        "date": "2026-07-14T19:00Z",
                        "home": {"abbrev": "FRA", "name": "France"},
                        "away": {"abbrev": "ESP", "name": "Spain"},
                        "homeScore": 0,
                        "awayScore": 2,
                        "winner": "ESP",
                        "status": "STATUS_FULL_TIME",
                    },
                    {
                        "game_id": "760515",
                        "date": "2026-07-15T19:00Z",
                        "home": {"abbrev": "ENG", "name": "England"},
                        "away": {"abbrev": "ARG", "name": "Argentina"},
                        "homeScore": 1,
                        "awayScore": 2,
                        "winner": "ARG",
                        "status": "STATUS_FULL_TIME",
                    },
                ],
            },
            {
                "round": "Final",
                "matches": [
                    {
                        "game_id": "760517",
                        "date": "2026-07-19T19:00Z",
                        "home": {"abbrev": "ESP", "name": "Spain"},
                        "away": {"abbrev": "ARG", "name": "Argentina"},
                        "homeScore": 0,
                        "awayScore": 0,
                        "winner": None,
                        "status": "STATUS_FIRST_HALF",
                    }
                ],
            },
        ]
    }


def _summary_fixture():
    return {
        "header": {
            "competitions": [
                {
                    "date": "2026-07-19T19:00Z",
                    "status": {"type": {"detail": "12'"}},
                    "competitors": [
                        {
                            "homeAway": "home",
                            "score": "0",
                            "team": {"displayName": "Spain", "abbreviation": "ESP"},
                        },
                        {
                            "homeAway": "away",
                            "score": "0",
                            "team": {"displayName": "Argentina", "abbreviation": "ARG"},
                        },
                    ],
                }
            ]
        },
        "rosters": [
            {
                "team": {"abbreviation": "ARG"},
                "roster": [{"athlete": {"displayName": "Lionel Messi"}}],
            },
            {
                "team": {"abbreviation": "ESP"},
                "roster": [{"athlete": {"displayName": "Lamine Yamal"}}],
            },
        ],
        "boxscore": {
            "teams": [
                {
                    "team": {"abbreviation": "ARG"},
                    "statistics": [
                        {"name": "possessionPct", "displayValue": "42"},
                        {"name": "totalShots", "displayValue": "2"},
                        {"name": "shotsOnTarget", "displayValue": "1"},
                    ],
                },
                {
                    "team": {"abbreviation": "ESP"},
                    "statistics": [
                        {"name": "possessionPct", "displayValue": "58"},
                        {"name": "totalShots", "displayValue": "4"},
                        {"name": "shotsOnTarget", "displayValue": "2"},
                    ],
                },
            ]
        },
        "keyEvents": [],
        "pickcenter": [],
    }


class BroadcastFilteringTests(unittest.TestCase):
    def test_current_teams_survive_and_nonparticipants_fail_closed(self):
        rows = [
            _signal("Spain", "Spain are moving Argentina around with patient possession", "2026-07-19T19:10:00Z"),
            _signal("Messi", "Messi is finding the right pocket between Spain's lines", "2026-07-19T19:12:00Z"),
            _signal("England", "England used a deep shell in the previous semifinal", "2026-07-19T19:13:00Z"),
            _signal("Mbappe", "Mbappe carried France through a different match yesterday", "2026-07-19T19:14:00Z"),
            _signal("Spain", "Listen to the iHeart podcast after this match ends", "2026-07-19T19:15:00Z"),
        ]
        names = {
            "full": ["Lionel Messi", "Lamine Yamal"],
            "last": {"messi": "Lionel Messi", "yamal": "Lamine Yamal"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "20260719_WC_ARGESP_signals.jsonl")
            with open(path, "w") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            with mock.patch.object(wc_context, "BROADCAST_DIR", tmp):
                insights = wc_context._broadcast_insights(
                    "20260719_WC_ARGESP", names, {"argentina", "arg", "spain", "esp"}, limit=40
                )

        self.assertEqual([row["subject"] for row in insights], ["Lionel Messi", "Spain"])
        self.assertEqual([row["ts"] for row in insights], sorted(
            [row["ts"] for row in insights], reverse=True
        ))
        self.assertTrue(all(row.get("id") for row in insights))


class HistoryTests(unittest.TestCase):
    def test_route_rest_and_extra_time_come_from_bracket_contract(self):
        history = wc_context._tournament_history(
            _bracket_fixture(), "760517", "2026-07-19T19:00Z", "ESP", "ARG"
        )
        argentina = history["teams"]["ARG"]
        spain = history["teams"]["ESP"]
        self.assertEqual(argentina["rest_days"], 4)
        self.assertEqual(spain["rest_days"], 5)
        self.assertEqual(argentina["extra_time_matches"], 1)
        self.assertEqual(argentina["extra_time_minutes"], 30)
        self.assertEqual(spain["extra_time_minutes"], 0)
        self.assertEqual(argentina["matches"][-1]["opponent"]["abbr"], "ENG")


class CacheAndClaimsTests(unittest.TestCase):
    def setUp(self):
        wc_context._read_cache.clear()
        wc_context._insight_cache.clear()

    def test_cache_is_bounded_and_content_hash_changes_with_quote(self):
        cache = OrderedDict()
        for index in range(wc_context._CACHE_MAX + 2):
            wc_context._cache_put(cache, index, {"value": index})
        self.assertEqual(len(cache), wc_context._CACHE_MAX)
        self.assertNotIn(0, cache)
        self.assertNotEqual(
            wc_context._content_hash([{"quote": "old"}]),
            wc_context._content_hash([{"quote": "new"}]),
        )

    def test_read_uses_exact_receipts_and_rejects_uncited_numbers(self):
        generated = json.dumps([
            {
                "headline": "DATA shows Messi walks 65% of the tournament",
                "evidence_refs": ["B0"],
            },
            {
                "headline": "Spain has 70% possession",
                "evidence_refs": ["F0"],
            },
        ])
        insights = [{
            "tag": "Fatigue",
            "subject": "Lionel Messi",
            "quote": "The booth said Messi walks for 65% of this tournament",
        }]
        with mock.patch.object(wc_context, "_deepseek", return_value=generated):
            read = wc_context._synthesize_read(
                ["Spain has 55% possession"], insights, ("claims-test",), market_lines={}
            )
        self.assertEqual(len(read), 1)
        self.assertEqual(read[0]["source"], "booth")
        self.assertEqual(read[0]["headline"], "Messi walks 65% of the tournament")
        self.assertIn("Booth:", read[0]["evidence"])
        self.assertNotIn("DATA shows", read[0]["headline"])


class ContextContractTests(unittest.TestCase):
    def test_context_exposes_stats_history_provenance_and_social_gap(self):
        row = _signal(
            "Spain", "Spain are stretching Argentina across the middle", "2026-07-19T19:18:46Z", 3, "tactical"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "20260719_WC_ARGESP_signals.jsonl")
            with open(path, "w") as handle:
                handle.write(json.dumps(row) + "\n")
            patches = [
                mock.patch.object(wc_context, "BROADCAST_DIR", tmp),
                mock.patch.object(wc_context.espn, "summary", return_value=_summary_fixture()),
                mock.patch.object(wc_context, "_forms", return_value={"ARG": "WWWWW", "ESP": "WWWWW"}),
                mock.patch.object(wc_context, "_world_cup_bracket", return_value=_bracket_fixture()),
                mock.patch.object(wc_context, "_top_scorers", return_value=[]),
                mock.patch.object(wc_context, "_goals_market", return_value={}),
                mock.patch.object(wc_context, "_team_odds", return_value={}),
                mock.patch.object(wc_context, "_enrich_insights", side_effect=lambda rows, *_: rows),
                mock.patch.object(wc_context, "_synthesize_read", return_value=[]),
            ]
            for patcher in patches:
                patcher.start()
            try:
                context = wc_context.build_context("760517", limit=40)
            finally:
                for patcher in reversed(patches):
                    patcher.stop()

        self.assertEqual(context["insights"][0]["subject"], "Spain")
        self.assertEqual(context["match_stats"][0], {
            "key": "possessionPct", "label": "Possession", "unit": "%", "away": "42", "home": "58"
        })
        self.assertEqual(context["history"]["teams"]["ARG"]["rest_days"], 4)
        self.assertEqual(context["social_sentiment"]["status"], "unavailable")
        self.assertEqual(context["sources"]["match_and_stats"], "ESPN summary")
        self.assertEqual(context["latest_booth_at"], "2026-07-19T19:18:46Z")


if __name__ == "__main__":
    unittest.main(verbosity=2)
