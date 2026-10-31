import unittest

from narrative_event_knowledge import (
    NarrativeDataError,
    derive_game_events,
    derive_player_outliers,
    normalize_espn_plays,
    retrieve_pregame_context,
)


def _play(event_id, at, clock, home, away, *, period=4, team="", drive="d1",
          scoring=False, down=None, turnover=False, text="never retained"):
    return {
        "event_id": str(event_id), "sequence": event_id, "period": period,
        "clock_seconds_remaining": clock, "occurred_at": f"2026-10-01T{at}Z",
        "available_at": "2026-11-01T00:00:00Z", "home_score": home,
        "away_score": away, "team": team, "scoring_play": scoring,
        "score_value": max(home, away), "play_type": "Field Goal",
        "drive_id": drive, "down": down, "turnover": turnover,
        "text": text,
    }


class NarrativeEventKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.plays = [
            _play(1, "20:00:00", 240, 0, 0),
            _play(2, "20:01:00", 180, 0, 3, team="GB", drive="d2", scoring=True),
            _play(3, "20:01:30", 150, 4, 3, team="DET", drive="d3", scoring=True),
            _play(4, "20:02:00", 120, 4, 6, team="GB", drive="d4", scoring=True),
            _play(5, "20:03:00", 0, 7, 6, team="DET", drive="d5", scoring=True, down=4),
        ]

    def test_extracts_comeback_lead_changes_decisive_score_and_clutch(self):
        facts = derive_game_events(
            league="nfl", game_id="g1", home_team="DET", away_team="GB",
            final_home_score=7, final_away_score=6, plays=self.plays)
        by_category = {fact["category"]: fact for fact in facts}
        self.assertEqual(3, by_category["comeback"]["calculation"]["largest_deficit_overcome"])
        self.assertEqual(3, by_category["lead_changes"]["calculation"]["count"])
        self.assertEqual("DET", by_category["decisive_score"]["team"])
        self.assertEqual(4, by_category["clutch_events"]["calculation"][
            "fourth_quarter_final_five_minutes_or_overtime"])
        for fact in facts:
            self.assertEqual(["g1"], fact["supporting_game_ids"])
            self.assertTrue(fact["supporting_event_ids"])

    def test_rejects_duplicate_ids_bad_order_and_score_mismatch(self):
        duplicate = [*self.plays, dict(self.plays[-1])]
        with self.assertRaisesRegex(NarrativeDataError, "duplicate play id"):
            derive_game_events(league="nfl", game_id="g1", home_team="DET", away_team="GB",
                               final_home_score=7, final_away_score=6, plays=duplicate)
        bad_order = [dict(p) for p in self.plays]
        bad_order[3]["occurred_at"] = "2026-10-01T20:01:10Z"
        with self.assertRaisesRegex(NarrativeDataError, "chronological order"):
            derive_game_events(league="nfl", game_id="g1", home_team="DET", away_team="GB",
                               final_home_score=7, final_away_score=6, plays=bad_order)
        with self.assertRaisesRegex(NarrativeDataError, "schedule says"):
            derive_game_events(league="nfl", game_id="g1", home_team="DET", away_team="GB",
                               final_home_score=8, final_away_score=6, plays=self.plays)

    def test_normalizer_drops_play_description_and_uses_game_clock(self):
        raw = [
            {"id": "2", "period": {"number": 4}, "clock": {"displayValue": "3:00"},
             "wallclock": "2026-10-01T20:01:00Z", "homeScore": "0", "awayScore": "3",
             "scoringPlay": True, "scoreValue": 3, "type": {"text": "Field Goal"},
             "text": "copyrighted description", "start": {"down": 4}},
            {"id": "1", "period": {"number": 4}, "clock": {"displayValue": "4:00"},
             "wallclock": "2026-10-01T20:00:00Z", "homeScore": "0", "awayScore": "0",
             "text": "another description"},
        ]
        normalized = normalize_espn_plays(raw, league="nfl", game_id="g1",
                                          captured_at="2026-11-01T00:00:00Z")
        self.assertEqual(["1", "2"], [p["event_id"] for p in normalized])
        self.assertTrue(all("text" not in p for p in normalized))
        self.assertTrue(all(p["available_at"] == "2026-11-01T00:00:00Z" for p in normalized))

    def test_player_outlier_uses_only_prior_available_games_and_stable_ids(self):
        logs = []
        for i, day in enumerate(range(1, 6)):
            logs.append({"log_id": f"l{i}", "game_id": f"p{i}", "player_id": 99,
                         "team": "GS", "game_type": "REG",
                         "game_start": f"2026-09-{day:02}T19:00:00Z",
                         "available_at": f"2026-09-{day:02}T23:00:00Z",
                         "stats": {"PTS": 10, "REB": 3, "AST": 2, "PRA": 15}})
        logs.append({"log_id": "l5", "game_id": "g1", "player_id": 99, "team": "GS",
                     "game_type": "REG", "game_start": "2026-10-01T19:00:00Z",
                     "available_at": "2026-10-01T23:00:00Z",
                     "stats": {"PTS": 40, "REB": 3, "AST": 2, "PRA": 45}})
        facts = derive_player_outliers(
            league="nba", target_game_id="g1", target_start="2026-10-01T19:00:00Z",
            target_end="2026-10-01T22:00:00Z", target_available_at="2026-10-01T23:00:00Z",
            logs=logs)
        points = next(f for f in facts if f["calculation"]["stat"] == "PTS")
        self.assertEqual(5, points["calculation"]["prior_games"])
        self.assertEqual({"g1", "p0", "p1", "p2", "p3", "p4"},
                         set(points["supporting_game_ids"]))
        self.assertEqual("player_game_logs", points["source"])

        late_prior = [dict(row, available_at="2026-10-01T19:01:00Z")
                      if row["game_id"] == "p4" else row for row in logs]
        filtered = derive_player_outliers(
            league="nba", target_game_id="g1", target_start="2026-10-01T19:00:00Z",
            target_end="2026-10-01T22:00:00Z", target_available_at="2026-10-01T23:00:00Z",
            logs=late_prior)
        self.assertFalse(any(f["calculation"]["stat"] == "PTS" for f in filtered))

    def test_retrieval_is_cutoff_safe_relevant_and_deterministic(self):
        facts = derive_game_events(
            league="nfl", game_id="g1", home_team="DET", away_team="GB",
            final_home_score=7, final_away_score=6, plays=self.plays)
        late = dict(facts[0], event_id="future", available_at="2026-11-02T00:00:00Z")
        same_game = dict(facts[0], event_id="same", game_id="upcoming",
                         supporting_game_ids=["upcoming"])
        irrelevant = dict(facts[0], event_id="other", team="NYG")
        context = retrieve_pregame_context(
            [*facts, late, same_game, irrelevant], league="nfl", target_game_id="upcoming",
            target_start="2026-11-03T18:00:00Z", as_of="2026-11-01T00:00:00Z",
            teams=["DET", "GB"], limit=10)
        self.assertEqual([f["event_id"] for f in context],
                         [f["event_id"] for f in retrieve_pregame_context(
                             [*facts, late, same_game, irrelevant], league="nfl",
                             target_game_id="upcoming", target_start="2026-11-03T18:00:00Z",
                             as_of="2026-11-01T00:00:00Z", teams=["DET", "GB"], limit=10)])
        self.assertNotIn("future", [f["event_id"] for f in context])
        self.assertNotIn("same", [f["event_id"] for f in context])
        self.assertNotIn("other", [f["event_id"] for f in context])
        self.assertEqual([], retrieve_pregame_context(
            facts, league="nfl", target_game_id="upcoming", target_start="2026-10-01T20:01:30Z",
            as_of="2026-11-01T00:00:00Z", teams=["DET", "GB"], limit=10))


if __name__ == "__main__":
    unittest.main()
