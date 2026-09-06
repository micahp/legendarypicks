import unittest
from unittest import mock

import ingest_soccer_logs as subject


class SoccerPhaseTests(unittest.TestCase):
    def test_core_and_summary_regular_season_ids_share_semantic_phase(self):
        core = {"id": "1", "name": "Regular Season"}
        summary = {"type": 13846, "name": "2026 MLS, Regular Season"}

        self.assertEqual(subject._game_type_for_type(core), subject.REG)
        self.assertEqual(subject._game_type_for_name(summary["name"]), subject.REG)

    def test_soccer_phase_names_cover_all_shared_game_types(self):
        self.assertEqual(
            subject._game_type_for_name("MLS All-Star Game"), subject.ALLSTAR
        )
        self.assertEqual(
            subject._game_type_for_name("Eastern Conference Playoffs"), subject.POST
        )

    def test_summary_budget_counts_every_retry_attempt(self):
        spent = []
        with mock.patch.object(subject.time, "sleep"), \
                mock.patch.object(subject.espn, "summary", side_effect=RuntimeError("403")):
            with self.assertRaises(RuntimeError):
                subject._summary_retry(
                    "mls", "1", attempts=4,
                    before_request=lambda: spent.append(1),
                )
        self.assertEqual(len(spent), 4)

    def test_summary_budget_exhaustion_is_not_retried_or_hidden(self):
        def exhausted():
            raise subject._SummaryBudgetExhausted

        with mock.patch.object(subject.espn, "summary") as summary:
            with self.assertRaises(subject._SummaryBudgetExhausted):
                subject._summary_retry(
                    "mls", "1", before_request=exhausted,
                )
        summary.assert_not_called()

    def test_leagues_cup_current_season_comes_from_its_published_collection(self):
        with mock.patch.object(subject, "_get_core", return_value={
            "items": [{"$ref": "https://sports.core.api.espn.com/v2/sports/"
                       "soccer/leagues/concacaf.leagues.cup/seasons/2027"}],
        }):
            self.assertEqual(subject._published_current_season("lcup"), 2027)

    def test_cli_uses_published_current_season_and_exits_zero(self):
        with mock.patch.object(subject, "ingest", return_value=37) as ingest:
            result = subject.main(["--league", "mls", "--request-budget", "12"])
        self.assertEqual(result, 0)
        ingest.assert_called_once_with("mls", None, False, 12, False, False)


if __name__ == "__main__":
    unittest.main()
