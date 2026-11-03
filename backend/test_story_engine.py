import json
import re
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from story_engine import (
    LEAGUE_TEAM_NAMES,
    _h2h,
    _lead,
    _nba_player_clause,
    _nfl_player_clause,
    _streak_phrase,
    _team_name,
    collect_story_facts,
    generate_story,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/research/narrative-event-knowledge-2026-11-03/relevance-ranking/examples.jsonl"
MATCHUPS = {
    "2026_08_CHI_SEA", "0022600164", "0022600165", "0022600167", "0022600168", "0022600169",
}
TEAM_NAMES = {
    "CHI": "Chicago Bears", "SEA": "Seattle Seahawks", "SAC": "Sacramento Kings",
    "DAL": "Dallas Mavericks", "NO": "New Orleans Pelicans", "MEM": "Memphis Grizzlies",
    "BOS": "Boston Celtics", "HOU": "Houston Rockets", "UTAH": "Utah Jazz",
    "SA": "San Antonio Spurs", "POR": "Portland Trail Blazers", "DEN": "Denver Nuggets",
}


def recent_player_evidence(**stats_by_key):
    count = max((len(values) for values in stats_by_key.values()), default=0)
    return [{"id": f"log-{index}", "date": f"2026-10-{10-index:02d}",
             "available_at": f"2026-10-{10-index:02d}T12:00:00Z",
             "stats": {key: values[index] for key, values in stats_by_key.items()
                       if index < len(values)}} for index in range(count)]
NBA_STANDINGS = ROOT / "docs/research/narrative-event-knowledge-2026-11-03/deterministic-engine/nba_standings_2026-11-02.json"
SWIFT_LOGS = ROOT / "docs/research/narrative-event-knowledge-2026-11-03/deterministic-engine/swift_2026_logs.json"


def saved_facts():
    """Adapt the frozen, source-audited comparison rows to the renderer's public fact contract."""
    bundles = {}
    for line in EXAMPLES.read_text(encoding="utf-8").splitlines():
        example = json.loads(line)
        game_id = example["target_game_id"]
        if game_id not in MATCHUPS:
            continue
        fields = example["baseline_fields"]
        record_facts = fields["record_facts"]
        teams = {}
        for record in record_facts:
            teams[record["team"]] = {
                "name": TEAM_NAMES[record["team"]],
                "wins": record["wins"], "losses": record["losses"],
                "ties": record.get("ties", 0), "games": record["games"],
                "streak_result": record["streak_result"],
                "streak_length": record["streak_length"],
                "rank": record.get("rank"),
                "league_size": 30 if example["league"] == "nba" else 32,
                "evidence": [
                    {"id": row["game_id"], "available_at": row["available_at"],
                     "date": row["date"], "opponent": row["opponent"],
                     "result": row["result"], "for": row["for"], "against": row["against"]}
                    for row in record["source_game_rows"]
                ],
            }

        players = []
        for player in fields["player_form"]:
            stats = player["statistics"]
            logs = player["source_logs"]
            players.append({
                "name": player["name"], "team": player["team"],
                "league": example["league"],
                "recent": stats,
                "season_logs": [
                    {"id": str(log["player_game_log_id"]), "available_at": log["available_at"],
                     "date": log["game_date"], "game_id": log["game_id"], "stats": log["stats"]}
                    for log in logs
                ],
                "season_totals_complete": False,
                "evidence": [
                    {"id": str(log["player_game_log_id"]),
                     "available_at": log["available_at"],
                     "date": log["game_date"], "game_id": log["game_id"],
                     "stats": log["stats"]}
                    for log in logs
                ],
            })

        # Swift's season total is recomputed from every cutoff-safe local player game log.
        if game_id == "2026_08_CHI_SEA":
            swift = next(p for p in players if p["name"] == "D'Andre Swift")
            swift_snapshot = json.loads(SWIFT_LOGS.read_text(encoding="utf-8"))
            swift["season_logs"] = swift_snapshot["logs"]
            swift["season_totals_complete"] = len(swift_snapshot["logs"]) == 7

        bundles[game_id] = {
            "league": example["league"], "game_id": game_id,
            "away": example["matchup"]["away"], "home": example["matchup"]["home"],
            "start_utc": example["kickoff_utc"], "as_of": example["as_of"],
            "season": 2027 if example["league"] == "nba" else 2026,
            "teams": teams, "players": players,
            "league_standings": json.loads(NBA_STANDINGS.read_text(encoding="utf-8"))["teams"]
            if example["league"] == "nba" else [],
            "baseline": example["baseline_preview"],
        }
    return bundles


def story_sentence_count(text):
    without_abbreviations = re.sub(r"\b(?:Jr|Sr|Oct|Nov|Dec)\.", "", text)
    return len(re.split(r"(?<=[.!?])\s+", without_abbreviations.strip()))


def make_team(code, name, outcomes, opponent):
    evidence = []
    for index, result in enumerate(outcomes, start=1):
        day = index + 1
        game_date = f"2026-10-{day:02d}"
        own_score, other_score = (24, 17) if result == "W" else (17, 24) if result == "L" else (20, 20)
        evidence.append({
            "id": f"{code}-game-{index}",
            "available_at": f"{game_date}T18:00:00Z",
            "date": game_date,
            "opponent": opponent,
            "result": result,
            "for": own_score,
            "against": other_score,
        })
    streak_length = 0
    if outcomes:
        for result in reversed(outcomes):
            if result != outcomes[-1]:
                break
            streak_length += 1
    return {
        "code": code,
        "name": name,
        "wins": outcomes.count("W"),
        "losses": outcomes.count("L"),
        "ties": outcomes.count("T"),
        "games": len(outcomes),
        "streak_result": outcomes[-1] if outcomes else None,
        "streak_length": streak_length,
        "evidence": evidence,
    }


def matchup_facts(away, home, away_results, home_results, league="nba", players=None):
    return {
        "league": league,
        "game_id": "regression-game",
        "season": 2027 if league == "nba" else 2026,
        "away": away,
        "home": home,
        "start_utc": "2026-11-02T23:00:00Z",
        "as_of": "2026-11-02T22:00:00Z",
        "teams": {
            away: make_team(away, _test_name(away, league), away_results, home),
            home: make_team(home, _test_name(home, league), home_results, away),
        },
        "league_standings": [],
        "players": players or [],
    }


def _test_name(code, league):
    names = {
        "nba": {"BOS": "Boston Celtics", "NY": "New York Knicks", "PHI": "Philadelphia 76ers"},
        "nfl": {"CHI": "Chicago Bears", "SEA": "Seattle Seahawks"},
    }
    return names[league].get(code, code)


class StoryEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = saved_facts()
        cls.outputs = {game_id: generate_story(bundle) for game_id, bundle in cls.facts.items()}

    def test_jsn_remains_the_chicago_seattle_player_story(self):
        story = self.outputs["2026_08_CHI_SEA"]["story"]
        self.assertIn("Jaxon Smith-Njigba", story)
        self.assertRegex(story, r"four of his last five")
        self.assertIn("100 receiving yards", story)
        self.assertIn("rushed for 476 yards and seven touchdowns", story)

    def test_memphis_undefeated_record_leads_new_orleans_preview(self):
        story = self.outputs["0022600165"]["story"]
        self.assertTrue(story.startswith("Memphis"), story)
        self.assertRegex(story.lower(), r"undefeated|perfect start")
        self.assertIn("Ty Jerome", story)
        self.assertNotRegex(story.lower(), r"epa|points allowed|run differential")

    def test_dallas_sacramento_uses_winless_last_place_and_both_stars(self):
        story = self.outputs["0022600164"]["story"]
        self.assertIn("winless", story.lower())
        self.assertIn("dead last", story.lower())
        self.assertIn("Cooper Flagg", story)
        self.assertIn("Darius Acuff Jr.", story)

    def test_portland_denver_has_a_substantive_preview(self):
        story = self.outputs["0022600169"]["story"]
        self.assertGreaterEqual(len(story.split()), 30)
        self.assertIn("Deni Avdija", story)
        self.assertIn("Jamal Murray", story)

    def test_all_six_saved_matchups_have_one_to_three_sentences(self):
        self.assertEqual(len(self.outputs), 6)
        for result in self.outputs.values():
            sentences = story_sentence_count(result["story"])
            self.assertGreaterEqual(sentences, 1)
            self.assertLessEqual(sentences, 3)
            self.assertGreaterEqual(len(result["story"].split()), 40)
            self.assertLessEqual(len(result["story"].split()), 85)
            self.assertNotIn("No preview", result["story"])

    def test_rank_language_requires_verified_full_league_coverage(self):
        story = self.outputs["0022600164"]["story"].lower()
        self.assertIn("dead last", story)
        facts = deepcopy(self.facts["0022600164"])
        kings = next(row for row in facts["league_standings"] if row["code"] == "SAC")
        kings["evidence"][0]["available_at"] = "2026-11-04T00:00:00Z"
        unverified = generate_story(facts)["story"].lower()
        self.assertNotIn("dead last", unverified)

    def test_team_record_is_recomputed_from_scored_game_evidence(self):
        facts = deepcopy(self.facts["2026_08_CHI_SEA"])
        facts["teams"]["CHI"].update({"wins": 0, "losses": 7, "streak_length": 7})
        story = generate_story(facts)["story"]
        self.assertIn("5-2 Bears", story)
        self.assertNotIn("0-7", story)

    def test_all_published_claims_have_cutoff_safe_evidence(self):
        for game_id, result in self.outputs.items():
            as_of = self.facts[game_id]["as_of"]
            selected = result["manifest"]["selected_facts"]
            self.assertTrue(selected)
            for fact in selected:
                self.assertTrue(fact["evidence_ids"], fact)
                self.assertEqual(set(fact["evidence_ids"]), {str(e["id"]) for e in fact["evidence"]})
                self.assertTrue(all(e["available_at"] <= as_of for e in fact["evidence"]), fact)

    def test_swift_season_total_recomputes_from_all_seven_local_logs(self):
        swift = next(fact for fact in self.outputs["2026_08_CHI_SEA"]["manifest"]["selected_facts"]
                     if fact.get("player") == "D'Andre Swift")
        self.assertEqual(len(swift["evidence"]), 7)
        self.assertEqual(sum(row["stats"].get("rush_yds", 0) for row in swift["evidence"]), 476)
        self.assertEqual(sum(row["stats"].get("rush_td", 0) for row in swift["evidence"]), 7)

    def test_nba_rebound_star_has_a_preview_when_records_are_unavailable(self):
        facts = {
            "league": "nba", "game_id": "rebounds-1", "away": "UTAH", "home": "SA",
            "start_utc": "2026-11-02T02:00:00Z", "as_of": "2026-11-02T00:00:00Z",
            "teams": {}, "league_standings": [],
            "players": [{
                "player_id": 1, "name": "Test Center", "team": "UTAH", "league": "nba",
                "evidence": [
                    {"id": str(i), "available_at": f"2026-11-01T0{i}:00:00Z", "date": f"2026-10-{31-i:02d}",
                     "game_id": f"g{i}", "stats": {"PTS": 12, "AST": 2, "REB": value}}
                    for i, value in enumerate([14, 13, 12, 15, 10], start=1)
                ],
            }],
        }
        story = generate_story(facts)["story"]
        self.assertIn("Test Center", story)
        self.assertIn("12.8 rebounds over his last five", story)

    def test_nfl_passing_trend_has_a_preview_when_records_are_unavailable(self):
        facts = {
            "league": "nfl", "game_id": "passing-1", "away": "NYJ", "home": "NE",
            "start_utc": "2026-11-02T02:00:00Z", "as_of": "2026-11-02T00:00:00Z",
            "teams": {}, "league_standings": [],
            "players": [{
                "player_id": 2, "name": "Test Quarterback", "team": "NYJ", "league": "nfl",
                "evidence": [
                    {"id": str(i), "available_at": f"2026-11-01T0{i}:00:00Z", "date": f"2026-10-{31-i:02d}",
                     "game_id": f"q{i}", "stats": {"pass_yds": value, "pass_td": 2,
                                                            "rush_yds": 0, "rush_td": 0,
                                                            "rec_yds": 0, "rec_td": 0}}
                    for i, value in enumerate([320, 315, 280, 270, 240], start=1)
                ],
            }],
        }
        story = generate_story(facts)["story"]
        self.assertIn("Test Quarterback", story)
        self.assertIn("thrown for 300 yards in two of his last five", story)

    def test_nfl_usage_trend_uses_recent_carries(self):
        facts = {
            "league": "nfl", "game_id": "usage-1", "away": "CHI", "home": "SEA",
            "start_utc": "2026-11-02T02:00:00Z", "as_of": "2026-11-02T00:00:00Z",
            "teams": {}, "league_standings": [],
            "players": [{
                "player_id": 3, "name": "Test Running Back", "team": "CHI", "league": "nfl",
                "evidence": [
                    {"id": str(i), "available_at": f"2026-11-01T0{i}:00:00Z", "date": f"2026-10-{31-i:02d}",
                     "game_id": f"r{i}", "stats": {"rush_yds": 80, "rush_td": 0,
                                                            "carries": carries, "rec_yds": 0, "rec_td": 0}}
                    for i, carries in enumerate([22, 20, 21, 15, 22], start=1)
                ],
            }],
        }
        story = generate_story(facts)["story"]
        self.assertIn("carried the ball 20 or more times in four of his last five", story)

    def test_player_team_attribution_is_preserved(self):
        story = self.outputs["0022600165"]["story"]
        self.assertRegex(story, r"(Grizzlies|Memphis).{0,80}Ty Jerome")
        story = self.outputs["2026_08_CHI_SEA"]["story"]
        self.assertRegex(story, r"Jaxon Smith-Njigba.{0,80}(Seattle|Seahawks)")

    def test_team_story_angle_is_fixed_before_player_statistics_are_considered(self):
        facts = deepcopy(self.facts["2026_08_CHI_SEA"])
        angle = generate_story(facts)["angle"]
        facts["players"] = []
        self.assertEqual(angle["kind"], "records")
        self.assertEqual(generate_story(facts)["angle"], angle)

    def test_no_internal_research_language_reaches_published_text(self):
        banned = re.compile(
            r"verified evidence|supplied deltas|relationship gate|metric alignment|"
            r"no eligible preview|source rows|no relationship cleared|evidence gate",
            re.IGNORECASE,
        )
        for result in self.outputs.values():
            self.assertNotRegex(result["story"], banned)

    def test_renderer_makes_no_network_or_model_calls(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network call")), \
             patch("socket.create_connection", side_effect=AssertionError("network call")):
            for facts in self.facts.values():
                generate_story(facts)

    def test_fallback_uses_records_and_recent_results_when_players_are_missing(self):
        facts = self.facts["0022600169"]
        facts["players"] = []
        result = generate_story(facts)
        self.assertTrue(result["story"])
        self.assertIn("4-1", result["story"])
        self.assertNotIn("No preview", result["story"])

    def test_two_losing_streaks_are_never_called_winning_streaks(self):
        facts = matchup_facts("BOS", "NY", ["W", "W", "L", "L", "L", "L"],
                              ["W", "W", "L", "L", "L", "L"])
        result = generate_story(facts)
        self.assertEqual(result["angle"]["kind"], "losing_streak")
        self.assertRegex(result["story"].lower(), r"dropped four straight|lost four in a row")
        self.assertNotRegex(result["story"].lower(), r"winning streak|won four straight")

    def test_single_losing_streak_is_rendered_in_the_correct_direction(self):
        facts = matchup_facts("BOS", "NY", ["W", "W", "L", "L", "L", "L"],
                              ["W", "L", "W", "L", "W", "L"])
        story = generate_story(facts)["story"].lower()
        self.assertIn("dropped four straight", story)
        self.assertNotIn("winning streak", story)

    def test_two_game_loss_streak_uses_loss_language(self):
        facts = matchup_facts("BOS", "NY", ["W", "W", "L", "L"], ["W", "L", "W", "W"])
        story = generate_story(facts)["story"].lower()
        self.assertIn("dropped two straight", story)
        self.assertNotIn("winning streak", story)

    def test_city_named_opponent_uses_singular_grammar(self):
        facts = matchup_facts("PIT", "CIN", ["L", "W", "W", "W", "W"],
                              ["W", "W", "W", "L", "W", "W", "L"], league="nfl")
        story = generate_story(facts)["story"]
        self.assertIn("its matchup with Cincinnati, which is 5-2", story)
        self.assertNotIn("Cincinnati, who sit", story)

    def test_streak_clash_handles_the_winning_streak_on_the_road(self):
        facts = matchup_facts("BOS", "NY", ["L", "W", "W", "W", "W"],
                              ["W", "W", "L", "L", "L", "L"])
        result = generate_story(facts)
        self.assertEqual(result["angle"]["kind"], "streak_clash")
        self.assertIn("Boston has won four straight", result["story"])
        self.assertIn("New York has dropped four in a row", result["story"])

    def test_team_name_maps_cover_both_complete_league_directories(self):
        self.assertEqual(len(LEAGUE_TEAM_NAMES["nba"]), 30)
        self.assertEqual(len(LEAGUE_TEAM_NAMES["nfl"]), 32)

    def test_generic_nfl_lead_does_not_use_basketball_home_court_language(self):
        facts = matchup_facts("CHI", "SEA", ["W", "L", "W"], ["L", "W", "L"], league="nfl")
        story = generate_story(facts)["story"].lower()
        self.assertIn("protect home turf", story)
        self.assertNotIn("home court", story)

    def test_generic_nba_lead_keeps_basketball_home_court_language(self):
        facts = matchup_facts("BOS", "NY", ["W", "L", "W"], ["L", "W", "L"])
        story = generate_story(facts)["story"].lower()
        self.assertIn("protect home court", story)
        self.assertNotIn("home turf", story)

    def test_head_to_head_does_not_call_a_tie_a_win(self):
        row_away = {"id": "prior", "opponent": "DET", "for": 110, "against": 110}
        row_home = {"id": "prior", "opponent": "CHI", "for": 110, "against": 110}
        facts = {"away": "CHI", "home": "DET", "teams": {
            "CHI": {"code": "CHI", "evidence": [row_away]},
            "DET": {"code": "DET", "evidence": [row_home]},
        }}
        self.assertIsNone(_h2h(facts))

    def test_winless_last_place_fallback_names_the_opponent_naturally(self):
        bundle = {
            "league": "nba", "away": "SAC", "home": "PHX", "league_standings": [],
            "teams": {
                "SAC": {"code": "SAC", "name": "Sacramento Kings", "wins": 0, "losses": 6,
                         "ties": 0, "streak_result": "L", "streak_length": 6, "evidence": []},
                "PHX": {"code": "PHX", "name": "Phoenix Suns", "wins": 1, "losses": 3,
                         "ties": 0, "streak_result": "L", "streak_length": 1, "evidence": []},
            },
        }
        lead, _ = _lead(bundle, {"kind": "winless_last", "lead_team": "SAC"})
        self.assertIn("visit Phoenix, where the Suns are 1-3", lead)
        self.assertNotIn("Phoenix's 1-3 team", lead)

    def test_one_game_losing_result_does_not_default_to_winning(self):
        facts = matchup_facts("BOS", "NY", ["W", "W", "W", "W"],
                              ["W", "W", "W", "L"])
        story = generate_story(facts)["story"].lower()
        self.assertIn("lost its last game", story)
        self.assertNotIn("won its last game", story)
        self.assertEqual(_streak_phrase({"streak_result": None, "streak_length": 0}), None)

    def test_receiver_is_only_described_as_coming_off_the_latest_game(self):
        def logs(values):
            return [{"id": f"g{index}", "date": f"2026-10-{10-index:02d}",
                     "available_at": f"2026-10-{10-index:02d}T12:00:00Z",
                     "stats": {"rec_yds": value}}
                    for index, value in enumerate(values)]

        fact = {
            "player": "Test Receiver",
            "team": "SEA",
            "stats": {"receiving_yards": [42, 121, 75, 68, 55]},
            "season_totals": {},
            "evidence": logs([42, 121, 75, 68, 55]),
        }
        clause = _nfl_player_clause(fact)
        self.assertIn("one of his last five", clause)
        self.assertNotIn("coming off", clause)

        fact["stats"]["receiving_yards"] = [121, 42, 75, 68, 55]
        fact["evidence"] = logs([121, 42, 75, 68, 55])
        clause = _nfl_player_clause(fact)
        self.assertIn("coming off a 121-yard receiving game", clause)

    def test_quarterback_passing_touchdowns_are_not_called_player_scores(self):
        fact = {
            "player": "Test Quarterback",
            "team": "NYJ",
            "stats": {
                "passing_touchdowns": [2, 2, 1, 3, 2],
                "receiving_touchdowns": [0, 0, 0, 0, 0],
                "rushing_touchdowns": [0, 0, 0, 0, 0],
            },
        }
        self.assertIsNone(_nfl_player_clause(fact))

    def test_nba_player_template_uses_league_specific_philadelphia_identity(self):
        self.assertEqual(_team_name("PHI", "nba"), "Philadelphia 76ers")
        self.assertEqual(_team_name("PHI", "nfl"), "Philadelphia Eagles")
        fact = {
            "player": "Test Star",
            "team": "PHI",
            "stats": {"points": [45, 22, 21, 24, 25], "assists": [6, 6, 6, 6, 6]},
            "evidence": recent_player_evidence(PTS=[45, 22, 21, 24, 25], AST=[6, 6, 6, 6, 6]),
        }
        clause = _nba_player_clause(fact)
        self.assertIn("76ers star Test Star", clause)
        self.assertNotIn("Eagles", clause)

    def test_nba_player_numbers_do_not_claim_to_cause_a_team_hot_start(self):
        fact = {
            "player": "Test Star",
            "team": "PHI",
            "stats": {"points": [45, 22, 21, 24, 25], "assists": [6, 6, 6, 6, 6]},
            "evidence": recent_player_evidence(PTS=[45, 22, 21, 24, 25], AST=[6, 6, 6, 6, 6]),
        }
        clause = _nba_player_clause(fact).lower()
        self.assertIn("is averaging", clause)
        self.assertNotRegex(clause, r"powered|hot start")

    def test_nba_scoring_clause_lists_exactly_the_games_it_counts(self):
        fact = {"player": "Test Guard", "team": "BOS",
                "stats": {"points": [34, 26, 21, 20, 15]},
                "evidence": recent_player_evidence(PTS=[34, 26, 21, 20, 15])}
        clause = _nba_player_clause(fact)
        self.assertIn("in each of his last four", clause)
        self.assertIn("including 34, 26, 21, 20", clause)

        fact["stats"]["points"] = [40, 20, 35, 36, 10]
        fact["evidence"] = recent_player_evidence(PTS=[40, 20, 35, 36, 10])
        clause = _nba_player_clause(fact)
        self.assertIn("40, 35 and 36 in three of his last five", clause)

    def test_nba_four_or_five_game_scoring_run_uses_the_actual_count(self):
        fact = {"player": "Test Forward", "team": "BOS",
                "stats": {"points": [24, 25, 23, 24, 26]},
                "evidence": recent_player_evidence(PTS=[24, 25, 23, 24, 26])}
        clause = _nba_player_clause(fact)
        self.assertIn("at least 23 in each of his last five", clause)
        fact["stats"]["points"] = [24, 25, 23, 24, 10]
        fact["evidence"] = recent_player_evidence(PTS=[24, 25, 23, 24, 10])
        clause = _nba_player_clause(fact)
        self.assertIn("at least 23 in four of his last five", clause)

    def test_nba_star_on_struggling_team_does_not_get_credit_for_a_hot_start(self):
        facts = matchup_facts("PHI", "BOS", ["W", "L", "L", "L", "L", "L"],
                              ["W", "W", "W", "L", "W", "W"])
        facts["teams"]["PHI"]["name"] = "Philadelphia 76ers"
        facts["players"] = [{
            "player_id": 12,
            "name": "Test Star",
            "team": "PHI",
            "league": "nba",
            "evidence": [
                {"id": f"star-{day}", "available_at": f"2026-10-{day:02d}T18:00:00Z",
                 "date": f"2026-10-{day:02d}", "game_id": f"player-game-{day}",
                 "stats": {"PTS": points, "AST": 6, "REB": 4}}
                for day, points in enumerate([25, 24, 21, 22, 45], start=2)
            ],
        }]
        result = generate_story(facts)
        self.assertIn("1-5", result["story"])
        self.assertIn("76ers star Test Star", result["story"])
        self.assertNotRegex(result["story"].lower(), r"powered|hot start")


class FactCollectionTests(unittest.TestCase):
    def test_collector_filters_after_cutoff_logs_and_returns_read_only_facts(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as db:
            connection = sqlite3.connect(db.name)
            connection.executescript("""
                CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, league TEXT);
                CREATE TABLE player_game_logs(
                    id INTEGER PRIMARY KEY, player_id INTEGER, league TEXT, season INTEGER,
                    game_id TEXT, game_date TEXT, team TEXT, opponent TEXT, stats TEXT,
                    ingested_at TEXT, game_type TEXT
                );
            """)
            connection.execute("INSERT INTO players VALUES (1,'Test Star','nba')")
            connection.executemany("INSERT INTO player_game_logs VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                (10, 1, "nba", 2027, "g1", "2026-10-30", "AAA", "BBB",
                 '{"PTS": 35, "AST": 6, "REB": 7, "MIN": 30}', "2026-10-31T00:00:00Z", "REG"),
                (12, 1, "nba", 2027, "g3", "2026-10-31", "AAA", "CCC",
                 '{"PTS": 42, "AST": 6, "REB": 7, "MIN": 30}', "2026-11-01T00:00:00Z", "REG"),
                (11, 1, "nba", 2027, "g2", "2026-10-31", "AAA", "CCC",
                 '{"PTS": 50, "AST": 9, "REB": 8, "MIN": 30}', "2026-11-02T00:00:01Z", "REG"),
            ])
            connection.commit()
            connection.close()

            facts = collect_story_facts(
                db.name,
                {"league": "nba", "season": 2027, "away": "AAA", "home": "BBB",
                 "start_utc": "2026-11-01T01:00:00Z"},
                as_of="2026-11-01T00:00:00Z",
            )
        player = next(p for p in facts["players"] if p["name"] == "Test Star")
        self.assertEqual([row["id"] for row in player["evidence"]], ["12", "10"])
        self.assertEqual([row["stats"]["PTS"] for row in player["evidence"]], [42, 35])
        self.assertEqual(facts["source"]["mode"], "read_only")
        story = generate_story(facts)["story"]
        self.assertIn("Test Star", story)
        self.assertIn("42 and 35 in his last two", story)
        self.assertNotIn("50", story)

    def test_collector_rejects_a_post_cutoff_matchup(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as db:
            with self.assertRaises(ValueError):
                collect_story_facts(
                    db.name,
                    {"league": "nba", "season": 2027, "away": "AAA", "home": "BBB",
                     "start_utc": "2026-10-31T23:59:59Z"},
                    as_of="2026-11-01T00:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
