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

    def test_completed_aet_and_penalty_statuses_are_terminal(self):
        self.assertEqual(wc_context._current_phase("AET", "second_half"), "final")
        self.assertEqual(
            wc_context._current_phase(
                "AET", "second_half",
                {"name": "STATUS_FINAL_AET", "state": "post", "completed": True},
            ),
            "final",
        )
        self.assertEqual(
            wc_context._current_phase("Penalty Shootout", "extra_time"),
            "penalties",
        )
        self.assertEqual(wc_context._current_phase("98'", "second_half"), "extra_time")

    def test_espn_wallclock_timeline_places_periods_and_final_whistle(self):
        def event(kind, wallclock, clock):
            return {
                "type": {"text": kind}, "wallclock": wallclock,
                "clock": {"displayValue": clock},
            }

        sm = {"keyEvents": [
            event("Kickoff", "2026-07-19T19:00:00Z", ""),
            event("Halftime", "2026-07-19T19:49:00Z", "45'+4'"),
            event("Start 2nd Half", "2026-07-19T20:05:00Z", "45'"),
            event("End Regular Time", "2026-07-19T20:59:00Z", "90'+9'"),
            event("Start Extra Time", "2026-07-19T21:04:00Z", "90'"),
            event("Halftime Extra Time", "2026-07-19T21:22:00Z", "105'+3'"),
            event("Start 2nd Half Extra Time", "2026-07-19T21:25:00Z", "105'"),
            event("End Extra Time", "2026-07-19T21:45:00Z", "120'+5'"),
        ], "commentary": [{
            "time": {"displayValue": "83'"},
            "play": {
                "wallclock": "2026-07-19T20:43:00Z",
                "clock": {"displayValue": "83'"},
                "period": {"number": 2},
            },
        }]}
        timeline = wc_context._match_clock_timeline(sm)

        halftime = wc_context._timeline_position(
            "2026-07-19T19:55:00Z", timeline, completed=True
        )
        second_half = wc_context._timeline_position(
            "2026-07-19T20:43:10Z", timeline, completed=True
        )
        extra_time = wc_context._timeline_position(
            "2026-07-19T21:10:00Z", timeline, completed=True
        )
        final = wc_context._timeline_position(
            "2026-07-19T21:45:01Z", timeline, completed=True
        )

        self.assertEqual(halftime["phase"], "halftime")
        self.assertEqual(halftime["match_time"]["display"], "HT")
        self.assertEqual(second_half["match_time"]["display"], "~83'")
        self.assertEqual(extra_time["phase"], "extra_time")
        self.assertTrue(extra_time["match_time"]["display"].startswith("~"))
        self.assertEqual(final["phase"], "final")
        self.assertEqual(final["match_time"]["display"], "FT")

    def test_stated_current_minute_wins_but_historical_minute_does_not(self):
        stated = wc_context._stated_match_time(
            "Still no shots for Argentina in the 83rd minute",
            "second_half", "current_match",
        )
        historical = wc_context._stated_match_time(
            "Messi changed the semifinal in the 55th minute against England",
            "second_half", "historical_reference",
        )
        self.assertEqual(stated["display"], "83'")
        self.assertEqual(stated["precision"], "stated")
        self.assertIsNone(historical)

    def test_signal_quote_recovers_the_source_transcript_time(self):
        transcript = [
            {
                "ts": "2026-07-19T21:01:18Z",
                "_stamp": wc_context._parse_datetime("2026-07-19T21:01:18Z"),
                "_text": wc_context._plain(
                    "Still no shots for Argentina in the 83rd minute of the game"
                ),
            },
            {
                "ts": "2026-07-19T21:01:48Z",
                "_stamp": wc_context._parse_datetime("2026-07-19T21:01:48Z"),
                "_text": wc_context._plain("Spain recycle possession through midfield"),
            },
        ]
        source = wc_context._source_transcript_time(
            "still no shots for Argentina in the 83rd minute",
            "2026-07-19T21:02:46Z",
            transcript,
        )
        self.assertEqual(source, "2026-07-19T21:01:18Z")

    def test_future_player_event_does_not_retime_an_unrelated_episode(self):
        episode = {
            "id": "fatigue", "topic": "fatigue", "subject": "Julián Álvarez",
            "subject_kind": "player", "priority": "storyline", "strength": 2,
            "receipt_count": 1, "updated_at": "2026-07-19T21:06:49Z",
            "receipts": [{
                "quote": "Julian Alvarez is dead on his legs and cannot press",
                "source_ts": "2026-07-19T21:05:18Z",
            }],
        }
        event = {
            "clock": "102'", "wallclock": "2026-07-19T21:32:00Z",
            "kind": "Substitution", "team": "ARG",
            "players": ["Julián Álvarez", "Marcos Senesi"],
            "text": "Marcos Senesi replaces Julián Álvarez",
        }
        wc_context._attach_match_events([episode], [event])
        self.assertNotIn("match_event", episode)

    def test_final_catch_up_reports_outcome_and_winning_goal_in_past_tense(self):
        line = wc_context._final_catch_up(
            "Argentina", "Spain", "0", "1", "AET",
            [{
                "clock": "106'", "scoring": True,
                "players": ["Ferran Torres"],
            }],
        )
        self.assertEqual(
            line["headline"],
            "Spain beat Argentina 1–0 after extra time; Ferran Torres scored at 106'",
        )
        self.assertEqual(line["source"], "fact")
        self.assertNotIn("comeback", line["headline"].lower())

    def test_player_action_requires_current_scope_fresh_quote_and_exact_id(self):
        episode = {
            "subject": "Lisandro Martínez", "subject_kind": "player",
            "subject_resolution": "exact_player", "espn_id": "2",
            "time_scope": "current_match", "phase": "first_half",
        }
        market = {
            "Lisandro Martinez": {
                "player": "Lisandro Martinez", "espn_id": "2", "quote_status": "current",
                "line": "+2000", "price_as_of": "2026-07-19T19:50:00Z",
                "contract_ticker": "KXWCGOAL-TEST", "evidence_gate": "passed",
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
        self.assertIsNone(wc_context._actionable_market(
            episode, {"Lisandro Martinez": {
                **market["Lisandro Martinez"], "contract_ticker": None,
            }}
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

    def test_public_episode_does_not_present_capture_time_as_match_clock(self):
        episode = {
            "id": "injury", "topic": "injury", "subject": "Argentina",
            "phase": "first_half", "started_at": "2026-07-19T19:49:00Z",
            "updated_at": "2026-07-19T20:24:00Z", "receipt_count": 2,
            "receipts": [{
                "id": "receipt-1", "quote": "Lisandro Martinez is forced off",
                "ts": "2026-07-19T20:24:00Z", "time_scope": "current_match",
            }],
            "event_clock": "44'",
            "match_event": {"clock": "44'", "players": ["Lisandro Martínez"]},
            "match_time": {
                "display": "44'", "source": "espn_event",
                "relation": "contemporaneous_event", "precision": "exact_event",
            },
        }
        public = wc_context._public_episode(episode)

        self.assertEqual(public["match_time"], {
            "display": "44'", "source": "espn_event",
            "relation": "contemporaneous_event", "precision": "exact_event",
        })
        self.assertEqual(public["latest_capture_at"], "2026-07-19T20:24:00Z")
        self.assertEqual(public["receipts"][0]["captured_at"], "2026-07-19T20:24:00Z")
        self.assertEqual(public["receipts"][0]["time_basis"], "broadcast_capture")
        self.assertNotIn("ts", public["receipts"][0])
        self.assertNotIn("started_at", public)
        self.assertNotIn("updated_at", public)
        self.assertNotIn("event_clock", public)

    def test_public_episode_omits_match_time_without_espn_event_link(self):
        public = wc_context._public_episode({
            "id": "pressure", "phase": "second_half",
            "updated_at": "2026-07-19T20:24:00Z", "receipts": [],
        })
        self.assertNotIn("match_time", public)

    def test_episode_detail_receipts_read_oldest_to_newest(self):
        episode = {
            "id": "pressure", "phase": "second_half", "subject": "Spain",
            "receipt_count": 2,
            "_all_receipts": [
                {"quote": "later", "ts": "2026-07-19T20:24:00Z"},
                {"quote": "earlier", "ts": "2026-07-19T20:20:00Z"},
            ],
        }
        wc_context._cache_episode_details("760517", [episode])
        detail = wc_context.get_episode_detail("760517", "pressure")

        self.assertEqual(detail["receipt_order"], "oldest_to_newest")
        self.assertEqual([row["quote"] for row in detail["receipts"]], ["earlier", "later"])

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

    def test_catch_up_labels_booth_capture_time_without_calling_it_match_time(self):
        public = wc_context._public_catch_up({
            "headline": "Spain are controlling the ball",
            "evidence_items": [{
                "ref": "B0", "kind": "booth", "scope": "current_match",
                "text": "Spain continue to control possession",
                "ts": "2026-07-19T20:24:00Z",
            }],
        })
        receipt = public["evidence_items"][0]
        self.assertEqual(receipt["captured_at"], "2026-07-19T20:24:00Z")
        self.assertEqual(receipt["time_basis"], "broadcast_capture")
        self.assertNotIn("ts", receipt)
        self.assertNotIn("match_time", receipt)


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
        self.assertEqual(context["latest_booth_capture_at"], "2026-07-19T19:18:46Z")
        self.assertNotIn("latest_booth_at", context)
        self.assertEqual(context["schema_version"], "wc-context-v2")
        self.assertEqual(context["time_semantics"]["capture_time_basis"], "broadcast_capture")
        self.assertEqual(
            context["time_semantics"]["phase_basis"],
            "scheduled_kickoff_and_broadcast_gap",
        )
        self.assertEqual(context["coverage"]["capture_started_at"], "2026-07-19T19:18:46Z")
        self.assertEqual(context["coverage"]["capture_latest_at"], "2026-07-19T19:18:46Z")
        self.assertNotIn("source_started_at", context["coverage"])
        self.assertNotIn("source_latest_at", context["coverage"])
        self.assertEqual(context["coverage"]["source_observation_count"], 1)
        self.assertEqual(context["coverage"]["episode_count"], 1)
        self.assertNotIn("insights", context)
        self.assertNotIn("_all_receipts", context["episodes"][0])
        detail = wc_context.get_episode_detail("760517", context["episodes"][0]["id"])
        self.assertEqual(detail["schema_version"], "wc-context-episode-v2")
        self.assertEqual(detail["receipt_count"], 1)
        self.assertEqual(detail["receipt_order"], "oldest_to_newest")
        self.assertEqual(detail["receipts"][0]["captured_at"], "2026-07-19T19:18:46Z")
        self.assertEqual(detail["receipts"][0]["time_basis"], "broadcast_capture")
        self.assertNotIn("ts", detail["receipts"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
