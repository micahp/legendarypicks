import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slc_engine as se  # noqa: E402

SNAPSHOT = {'schedule': {'game_id': '2026_05_AAA_BBB', 'season': 2026, 'week': 5, 'home_team': 'AAA', 'away_team': 'BBB'},
            'rosters': {'home': {}, 'away': {}}}


def artifact(fit_seasons, reference_season):
    return {'fit_seasons': fit_seasons, 'reference_season': reference_season}


class Refusals(unittest.TestCase):
    def test_a_game_without_a_snapshot_is_refused(self):
        with self.assertRaises(ValueError):
            se.require_snapshot(None)
        with self.assertRaises(ValueError):
            se.require_snapshot({'schedule': {'season': 2024}})

    def test_load_reference_refuses_a_missing_snapshot_before_it_reads_the_artifact(self):
        with self.assertRaises(ValueError):
            se.load_reference('/nonexistent/picks.db', None, '/nonexistent/artifact.json')

    def test_play_refuses_a_reference_without_the_play_call_layer(self):
        class Ref:
            contextual_sampler = None
        self.assertFalse(se.is_slc(Ref()))
        with self.assertRaises(ValueError):
            se.play(1, Ref(), SNAPSHOT)


class CutoffByReferenceSeason(unittest.TestCase):
    def test_a_2026_game_may_use_a_fit_through_2025(self):
        se.check_artifact_cutoff(artifact(list(range(2010, 2026)), 2026), 2026)

    def test_a_2025_game_may_not_use_a_fit_that_includes_2025(self):
        with self.assertRaises(ValueError):
            se.check_artifact_cutoff(artifact(list(range(2010, 2026)), 2025), 2025)

    def test_a_2024_game_uses_a_2010_to_2023_fit(self):
        se.check_artifact_cutoff(artifact(list(range(2010, 2024)), 2024), 2024)
        with self.assertRaises(ValueError):
            se.check_artifact_cutoff(artifact(list(range(2010, 2025)), 2024), 2024)

    def test_the_reference_season_must_be_the_game_season(self):
        with self.assertRaises(ValueError):
            se.check_artifact_cutoff(artifact(list(range(2010, 2024)), 2026), 2024)

    def test_an_artifact_with_no_fit_seasons_is_refused(self):
        with self.assertRaises(ValueError):
            se.check_artifact_cutoff(artifact([], 2026), 2026)

    def test_the_committed_2026_artifact_passes_its_own_check(self):
        committed = Path(__file__).resolve().parents[2] / 'docs/research/SLC-PLAYCALL-ARTIFACT-v1.json'
        se.check_artifact_cutoff(json.loads(committed.read_text()), 2026)


class Mapping(unittest.TestCase):
    def test_offense_side_a_is_the_home_team_as_in_the_engine_record(self):
        self.assertEqual(se.side_teams(SNAPSHOT), {'A': 'AAA', 'B': 'BBB'})

    def test_the_artifact_path_is_checked_before_the_reference_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'artifact.json'
            path.write_text(json.dumps(artifact(list(range(2010, 2026)), 2025)))
            with self.assertRaises(ValueError):
                se.load_reference('/nonexistent/picks.db', SNAPSHOT, path)


class Summary(unittest.TestCase):
    def test_the_counts_separate_scrimmage_kicks_and_dropbacks(self):
        decisions = [{'intent': 'dropback'}, {'intent': 'run'}, {'intent': 'run'}, {'intent': 'kick'}]
        self.assertEqual(se.summary(decisions), {'decisions': 4, 'scrimmage': 3, 'dropback': 1, 'run': 2, 'kick_fallback': 1})


if __name__ == '__main__':
    unittest.main()
