import unittest

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


if __name__ == "__main__":
    unittest.main()
