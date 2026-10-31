import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slc_engine as se  # noqa: E402
import e1_drive as e1  # noqa: E402

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

    def test_playcall_team_keys_are_normalized_to_the_pbp_codes(self):
        snapshot = {
            'schedule': {**SNAPSHOT['schedule'], 'home_team': 'LA', 'away_team': 'WAS'},
            'rosters': SNAPSHOT['rosters'],
        }
        self.assertEqual(se.side_teams(snapshot), {'A': 'LAR', 'B': 'WSH'})

    def test_the_artifact_path_is_checked_before_the_reference_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'artifact.json'
            path.write_text(json.dumps(artifact(list(range(2010, 2026)), 2025)))
            with self.assertRaises(ValueError):
                se.load_reference('/nonexistent/picks.db', SNAPSHOT, path)


class Summary(unittest.TestCase):
    def test_the_counts_separate_scrimmage_kicks_and_dropbacks(self):
        decisions = [{'intent': 'dropback'}, {'intent': 'run'}, {'intent': 'run'}, {'intent': 'kick'}]
        result = se.summary(decisions)
        self.assertEqual((result['decisions'], result['scrimmage'], result['dropback'], result['run']), (4, 3, 1, 2))
        self.assertEqual(result['kick_fallback'], 1)
        self.assertEqual(result['fallback_events'], {})
        self.assertEqual(result['layer_execution']['score_clock_playcalling'], 4)

    def test_score_clock_execution_count_excludes_historical_cell_baseline_draws(self):
        decisions = [
            {'intent': 'run', 'score_clock_playcalling_applied': True},
            {'intent': 'dropback', 'score_clock_playcalling_applied': False},
            {'intent': 'kick', 'score_clock_playcalling_applied': False},
        ]
        execution = se.summary(decisions)['layer_execution']
        self.assertEqual(execution['score_clock_playcalling'], 1)
        self.assertEqual(execution['score_clock_cell_baseline_draws'], 2)


class ScoreClockAblation(unittest.TestCase):
    def setUp(self):
        self.layer = SimpleNamespace(artifact={'sha256': 'artifact-hash'},
                                     p_dropback=Mock(return_value=0.27))
        self.sampler = se.slc.PlayCallSampler(self.layer)
        self.entry = {'base': {('run', 'run'): 6, ('dropback', 'pass'): 4,
                               ('kick', 'field_goal_attempt'): 3}}
        self.state = {'down': 2, 'togo': 7, 'yl': 64, 'score_diff': -3,
                      'quarter': 4, 'clock': 240}

    def test_disabled_score_clock_uses_only_the_historical_cell_run_pass_rate(self):
        self.sampler.score_clock_playcalling_enabled = False
        probability, source = self.sampler._dropback_probability(self.entry, self.state, 'AAA')
        self.assertEqual(probability, 0.4)
        self.assertEqual(source, 'historical_down_distance_field_cell_rate')
        self.layer.p_dropback.assert_not_called()

    def test_enabled_score_clock_uses_the_frozen_model(self):
        probability, source = self.sampler._dropback_probability(self.entry, self.state, 'AAA')
        self.assertEqual(probability, 0.27)
        self.assertEqual(source, 'score_clock_logistic_artifact')
        self.layer.p_dropback.assert_called_once_with(2, 7, 64, -3, 4, 240, 'AAA')

    def test_disabled_score_clock_fails_closed_when_cell_has_no_scrimmage_rows(self):
        self.sampler.score_clock_playcalling_enabled = False
        with self.assertRaisesRegex(e1.SamplingUnavailable, 'no_supported_scrimmage_intent_in_cell'):
            self.sampler._dropback_probability({'base': {('kick', 'punt'): 3}}, self.state, 'AAA')

    def test_fixed_and_dirichlet_share_applications_have_separate_runtime_counts(self):
        decisions = [
            {'intent': 'dropback', 'participants': {'participant_share_model': 'fixed_player_share'}},
            {'intent': 'run', 'participants': {'participant_share_model': 'dirichlet_multinomial'}},
        ]

        execution = se.summary(decisions)['layer_execution']

        self.assertEqual(execution['fixed_player_target_carry_shares'], 1)
        self.assertEqual(execution['dirichlet_player_target_carry_shares'], 1)


class PlayerShareManifest(unittest.TestCase):
    def test_loading_dirichlet_shares_attaches_the_model_version_cutoff_and_fit(self):
        import share_distributions as sd
        layer_artifact = {**artifact(list(range(2010, 2026)), 2026), 'artifact_id': 'a', 'sha256': 'b',
                          'frame_sha256': 'frame-hash'}
        sampler = se.slc.PlayCallSampler(SimpleNamespace(artifact=layer_artifact),
                                         side_teams={'A': 'AAA', 'B': 'BBB'})
        ref = SimpleNamespace(contextual_sampler=sampler, pool={}, participants={}, pool_scope={})
        table = {'phi': {'receive': 24.4, 'carry': 7.5}, 'base': {'receive': {}, 'carry': {}},
                 'fit': {'receive': {'phi': 24.4, 'team_games': 544},
                         'carry': {'phi': 7.5, 'team_games': 544}}, 'season': 2025,
                 'model': 'dirichlet-multinomial-mle-v2'}
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / 'artifact.json'
            artifact_path.write_text(json.dumps(artifact(list(range(2010, 2026)), 2026)))
            with patch.object(se.er, 'load', return_value=(ref, 0)) as load_ref, \
                 patch.object(sd, 'load', return_value=table), \
                 patch.object(se.er, '_reference_fingerprint', return_value={'sha256': 'reference-hash'}):
                loaded, _excluded = se.load_reference('/read-only.db', SNAPSHOT, artifact_path, dirichlet_shares=True,
                                                       source_commit='abc123', score_clock_playcalling=False)
        self.assertFalse(load_ref.call_args.kwargs['playcall_player_shares'])
        self.assertIsNone(loaded.contextual_sampler.player_shares)
        self.assertEqual(loaded.contextual_sampler.share_table, table)
        self.assertFalse(loaded.contextual_sampler.score_clock_playcalling_enabled)
        manifest = loaded.contextual_sampler.share_model_manifest
        self.assertEqual(manifest['model_version'], 'dirichlet-multinomial-mle-v2')
        self.assertEqual(manifest['source_season'], 2025)
        self.assertEqual(manifest['cutoff_season'], 2026)
        self.assertEqual(manifest['git_commit'], 'abc123')
        self.assertEqual(manifest['concentration']['receive']['team_games'], 544)
        with patch.object(se, 'is_slc', return_value=True):
            description = se.describe(loaded)
        self.assertEqual(description['player_share_distribution'], manifest)
        self.assertFalse(description['enabled_layers']['score_clock_playcalling'])


class PlayerOutcomeRoleManifest(unittest.TestCase):
    def test_receiver_only_role_scope_is_recorded_in_the_model_manifest(self):
        import player_outcomes as po
        layer_artifact = {**artifact(list(range(2010, 2026)), 2026), 'artifact_id': 'a', 'sha256': 'b'}
        sampler = SimpleNamespace(layer=SimpleNamespace(artifact=layer_artifact),
                                  share_model_manifest=None, qb_decision_table=None,
                                  player_outcome_table=None,
                                  describe=lambda: {'side_teams': {'A': 'AAA', 'B': 'BBB'}})
        ref = SimpleNamespace(contextual_sampler=sampler, pool={}, participants={}, pool_scope={})
        table = {'model_version': po.MODEL_VERSION, 'source_seasons': [2022, 2023, 2024, 2025],
                 'cutoff_season': 2026, 'sha256': 'outcome-hash', 'player_units': {},
                 'transferred_player_units': {}, 'source_counts': {}}
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / 'artifact.json'
            artifact_path.write_text(json.dumps(artifact(list(range(2010, 2026)), 2026)))
            with patch.object(se.er, 'load', return_value=(ref, 0)), \
                 patch.object(se.er, '_reference_fingerprint', return_value={'sha256': 'reference-hash'}), \
                 patch.object(po, 'load', return_value=table):
                loaded, _excluded = se.load_reference(
                    '/read-only.db', SNAPSHOT, artifact_path, player_outcomes=True,
                    player_outcomes_receiver_only=True, source_commit='abc123')
        self.assertEqual(loaded.contextual_sampler.player_outcome_roles, ('receiver',))
        self.assertEqual(loaded.contextual_sampler.player_outcome_manifest['enabled_roles'], ['receiver'])


if __name__ == '__main__':
    unittest.main()
