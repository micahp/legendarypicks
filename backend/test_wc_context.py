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

    def test_full_signal_population_is_available_before_episode_collapse(self):
        rows = [
            _signal(
                "Spain",
                f"Spain observation number {index} carries enough distinct match context",
                f"2026-07-19T19:{index:02d}:00Z",
            )
            for index in range(55)
        ]
        names = {"full": [], "last": {}}
        all_rows = wc_context._broadcast_insights(
            "unused", names, {"spain"}, rows=rows, limit=None
        )
        capped_rows = wc_context._broadcast_insights(
            "unused", names, {"spain"}, rows=rows, limit=40
        )
        self.assertEqual(len(all_rows), 55)
        self.assertEqual(len(capped_rows), 40)


class IdentityAndEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.summary = {
            "rosters": [{
                "team": {"abbreviation": "ARG", "displayName": "Argentina"},
                "roster": [
                    {"athlete": {"id": "1", "displayName": "Emiliano Martínez"}},
                    {"athlete": {"id": "2", "displayName": "Lisandro Martínez"}},
                    {"athlete": {"id": "3", "displayName": "Lautaro Martínez"}},
                ],
            }]
        }
        self.names = wc_context._roster_names(self.summary, {"ARG": "Argentina"})

    def test_same_surname_fails_closed_but_exact_full_name_resolves(self):
        ambiguous = wc_context._resolve_subject("Andrew Martinez", self.names)
        lisandro = wc_context._resolve_subject("Lisandro Martinez", self.names)

        self.assertEqual(ambiguous["name"], "Argentina")
        self.assertEqual(ambiguous["subject_kind"], "team")
        self.assertEqual(ambiguous["subject_resolution"], "ambiguous_team_fallback")
        self.assertCountEqual(
            ambiguous["ambiguous_players"],
            ["Emiliano Martínez", "Lisandro Martínez", "Lautaro Martínez"],
        )
        self.assertEqual(lisandro["name"], "Lisandro Martínez")
        self.assertEqual(lisandro["subject_id"], "player:2")

    def test_exact_player_mention_in_quote_upgrades_team_subject(self):
        rows = [_signal(
            "Argentina",
            "What a big loss for Lisandro Martinez in the middle of the defense",
            "2026-07-19T19:50:49Z",
            3,
            "injury",
        )]
        insights = wc_context._broadcast_insights(
            "unused",
            self.names,
            {"argentina", "arg"},
            rows=rows,
            team_subjects={
                "argentina": {
                    "name": "Argentina", "subject_id": "team:ARG",
                    "subject_kind": "team", "team_abbr": "ARG",
                }
            },
        )
        self.assertEqual(insights[0]["subject"], "Lisandro Martínez")
        self.assertEqual(insights[0]["subject_id"], "player:2")
        self.assertEqual(insights[0]["subject_resolution"], "exact_quote_mention")

    def test_nearby_rows_collapse_into_one_evolving_episode(self):
        base = {
            "subject": "Lionel Messi", "subject_id": "player:10", "subject_kind": "player",
            "subject_resolution": "exact_player", "espn_id": "10", "team_abbr": "ARG",
            "phase": "second_half", "time_scope": "historical_reference", "strength": 2,
        }
        rows = [
            {**base, "id": "a", "tag": "Key man", "ts": "2026-07-19T20:23:18Z",
             "quote": "Messi turns it on late in games and then finds pockets of space"},
            {**base, "id": "b", "tag": "Momentum", "ts": "2026-07-19T20:24:18Z",
             "quote": "When Messi gets involved he changes the game quickly"},
        ]
        episodes = wc_context._collapse_episodes(rows)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["receipt_count"], 2)
        self.assertCountEqual(episodes[0]["tags"], ["Key man", "Momentum"])

    def test_match_phase_uses_full_timeline_and_halftime_gap(self):
        rows = [
            {"ts": "2026-07-19T18:55:00Z"},
            {"ts": "2026-07-19T19:15:00Z"},
            {"ts": "2026-07-19T19:58:00Z"},
            {"ts": "2026-07-19T20:20:00Z"},
        ]
        current = wc_context._annotate_match_phases(
            rows, "2026-07-19T19:00:00Z", "46'"
        )
        self.assertEqual(
            [row["phase"] for row in rows],
            ["pregame", "first_half", "first_half", "second_half"],
        )
        self.assertEqual(current, "second_half")
        self.assertEqual(wc_context._current_phase("HT", "first_half"), "halftime")
        self.assertEqual(wc_context._current_phase("Final", "second_half"), "final")

    def test_player_action_requires_current_scope_fresh_quote_and_exact_id(self):
        episode = {
            "subject": "Lisandro Martínez", "subject_kind": "player",
            "subject_resolution": "exact_player", "espn_id": "2",
            "time_scope": "current_match",
        }
        market = {
            "Lisandro Martinez": {
                "player": "Lisandro Martinez", "espn_id": "2", "quote_status": "current",
                "line": "+2000", "price_as_of": "2026-07-19T19:50:00Z",
            }
        }
        self.assertIsNotNone(wc_context._actionable_market(episode, market))
        self.assertIsNone(wc_context._actionable_market(
            {**episode, "time_scope": "historical_reference"}, market
        ))
        self.assertIsNone(wc_context._actionable_market(
            {**episode, "subject_resolution": "ambiguous_team_fallback"}, market
        ))
        self.assertIsNone(wc_context._actionable_market(
            episode, {"Lisandro Martinez": {**market["Lisandro Martinez"], "quote_status": "stale"}}
        ))

    def test_quote_state_uses_shared_ninety_second_freshness_semantics(self):
        now = wc_context.dt.datetime(2026, 7, 19, 20, 0, tzinfo=wc_context.dt.timezone.utc)
        self.assertEqual(
            wc_context._quote_state("2026-07-19T19:59:00Z", now), ("current", 60)
        )
        self.assertEqual(
            wc_context._quote_state("2026-07-19T19:58:29Z", now), ("stale", 91)
        )

    def test_historical_comparison_is_retained_and_labeled(self):
        self.assertEqual(
            wc_context._time_scope(
                "When Messi gets involved, as England found out, things change quickly"
            ),
            "historical_reference",
        )

    def test_injury_episode_links_only_to_exact_espn_event_and_ranks_first(self):
        injury = {
            "id": "injury", "topic": "injury", "subject": "Argentina",
            "subject_kind": "team", "priority": "storyline", "strength": 2,
            "receipt_count": 2, "updated_at": "2026-07-19T19:52:47Z",
            "receipts": [{"quote": "What a big loss for Lisandro Martinez"}],
        }
        ordinary = {
            "id": "pressure", "topic": "chance_creation", "subject": "Spain",
            "subject_kind": "team", "priority": "storyline", "strength": 3,
            "receipt_count": 5, "updated_at": "2026-07-19T19:55:47Z",
            "receipts": [{"quote": "Spain are creating chances"}],
        }
        events = [{
            "clock": "44'", "kind": "Substitution", "team": "ARG",
            "players": ["Lisandro Martínez", "Nicolás Otamendi"],
            "text": "Nicolás Otamendi replaces Lisandro Martínez",
        }]
        attached = wc_context._attach_match_events([ordinary, injury], events)
        ranked = wc_context._rank_episodes(attached)
        self.assertEqual(injury["event_clock"], "44'")
        self.assertEqual(injury["match_event"]["matched_players"], ["Lisandro Martínez"])
        self.assertEqual(ranked[0]["id"], "injury")

    def test_featured_mix_keeps_availability_and_player_specific_story(self):
        common = {
            "priority": "storyline", "strength": 3, "receipt_count": 5,
            "updated_at": "2026-07-19T20:30:00Z", "time_scope": "current_match",
        }
        episodes = [
            {**common, "id": "injury", "topic": "injury", "priority": "availability",
             "subject": "Argentina", "subject_kind": "team", "team_abbr": "ARG"},
            {**common, "id": "arg1", "topic": "tactical", "subject": "Argentina",
             "subject_kind": "team", "team_abbr": "ARG"},
            {**common, "id": "arg2", "topic": "possession_control", "subject": "Argentina",
             "subject_kind": "team", "team_abbr": "ARG"},
            {**common, "id": "arg3", "topic": "mentality", "subject": "Argentina",
             "subject_kind": "team", "team_abbr": "ARG"},
            {**common, "id": "esp1", "topic": "chance_creation", "subject": "Spain",
             "subject_kind": "team", "team_abbr": "ESP"},
            {**common, "id": "messi", "topic": "player_influence", "subject": "Lionel Messi",
             "subject_kind": "player", "team_abbr": "ARG"},
        ]
        featured = wc_context._select_featured(episodes, limit=5)
        self.assertEqual(featured[0]["id"], "injury")
        self.assertIn("messi", [row["id"] for row in featured])
        self.assertLessEqual(
            sum(row.get("subject_kind") == "team" and row.get("team_abbr") == "ARG"
                for row in featured),
            3,  # availability plus at most two ordinary Argentina team stories
        )


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
        wc_context._episode_detail_cache.clear()

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

    def test_episode_enrichment_retries_indices_missing_from_first_batch(self):
        episodes = [
            {
                "tag": "Tactical", "subject": "Argentina", "subject_kind": "team",
                "subject_resolution": "exact_team", "phase": "first_half",
                "time_scope": "current_match", "quote": "Argentina cannot get out",
                "receipts": [{"quote": "Argentina cannot get out"}],
            },
            {
                "tag": "Momentum", "subject": "Spain", "subject_kind": "team",
                "subject_resolution": "exact_team", "phase": "first_half",
                "time_scope": "current_match", "quote": "Spain are creating the better chances",
                "receipts": [{"quote": "Spain are creating the better chances"}],
            },
        ]
        first = json.dumps([{"i": 0, "headline": "Argentina trapped", "analysis": "No outlet", "lean": ""}])
        retry = json.dumps([{"i": 1, "headline": "Spain creating more", "analysis": "Better chances", "lean": ""}])
        with mock.patch.object(wc_context, "_deepseek", side_effect=[first, retry]) as deepseek:
            enriched = wc_context._enrich_insights(episodes, {}, ("retry",))
        self.assertEqual(deepseek.call_count, 2)
        self.assertEqual(enriched[0]["headline"], "Argentina trapped")
        self.assertEqual(enriched[1]["headline"], "Spain creating more")


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

        self.assertEqual(context["episodes"][0]["subject"], "Spain")
        self.assertEqual(context["match_stats"][0], {
            "key": "possessionPct", "label": "Possession", "unit": "%", "away": "42", "home": "58"
        })
        self.assertEqual(context["history"]["teams"]["ARG"]["rest_days"], 4)
        self.assertEqual(context["social_sentiment"]["status"], "unavailable")
        self.assertEqual(context["sources"]["match_and_stats"], "ESPN summary")
        self.assertEqual(context["latest_booth_at"], "2026-07-19T19:18:46Z")
        self.assertEqual(context["schema_version"], "wc-context-v2")
        self.assertEqual(context["coverage"]["source_observation_count"], 1)
        self.assertEqual(context["coverage"]["episode_count"], 1)
        self.assertNotIn("insights", context)
        self.assertNotIn("_all_receipts", context["episodes"][0])
        detail = wc_context.get_episode_detail("760517", context["episodes"][0]["id"])
        self.assertEqual(detail["schema_version"], "wc-context-episode-v1")
        self.assertEqual(detail["receipt_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
