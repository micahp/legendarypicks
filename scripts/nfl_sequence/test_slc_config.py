import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import slc_config as config  # noqa: E402
import pre_event  # noqa: E402


class FullStackProfile(unittest.TestCase):
    def setUp(self):
        self.resolved = config.resolve_profile('v1_full_stack', artifact_path='artifact.json',
                                               streak_file='streak.json')

    def test_profile_enumerates_every_intended_layer_and_excludes_fixed_share_adapter(self):
        self.assertEqual(set(self.resolved['enabled_layers']), set(config.ENGINE_LAYER_KEYS))
        for layer in config.ENGINE_LAYER_KEYS:
            expected = layer not in ('fixed_player_target_carry_shares', 'qb_run_role_style')
            self.assertEqual(self.resolved['enabled_layers'][layer], expected, layer)
        self.assertTrue(self.resolved['enabled_layers']['decision_row_filter'])
        self.assertTrue(self.resolved['enabled_layers']['current_streak_context'])

    def test_missing_artifact_and_streak_context_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'requires --playcall-artifact'):
            config.resolve_profile('v1_full_stack', streak_file='streak.json')
        with self.assertRaisesRegex(ValueError, 'frozen pregame streak'):
            config.resolve_profile('v1_full_stack', artifact_path='artifact.json')

    def test_fixed_shares_and_unfiltered_decisions_are_incompatible(self):
        with self.assertRaisesRegex(ValueError, 'fixed and Dirichlet'):
            config.resolve_profile('v1_full_stack', artifact_path='a', streak_file='s',
                                   options={'playcall_player_shares': True})
        with self.assertRaisesRegex(ValueError, 'requires the decision row filter'):
            config.resolve_profile('v1_full_stack', artifact_path='a', streak_file='s',
                                   options={'playcall_decision_unfiltered': True})

    def test_individual_optional_layer_ablations_get_a_distinct_identity(self):
        ablated = config.resolve_profile('v1_full_stack', artifact_path='a', streak_file='s',
                                         disable_layers=('decision_row_filter',))
        self.assertFalse(ablated['enabled_layers']['decision_row_filter'])
        self.assertTrue(ablated['enabled_layers']['decision_labels'])
        self.assertNotEqual(ablated['model_id'], self.resolved['model_id'])

    def test_qb_run_role_style_is_opt_in_and_can_be_ablated_independently(self):
        self.assertFalse(self.resolved['enabled_layers']['qb_run_role_style'])
        enabled = config.resolve_profile('v1_full_stack', artifact_path='a', streak_file='s',
                                         options={'playcall_qb_run_role_style': True})
        self.assertTrue(enabled['enabled_layers']['qb_run_role_style'])
        self.assertEqual(enabled['model_id'], 'SLC_v1_full_stack_qb_run_role_style')
        ablated = config.resolve_profile('v1_full_stack', artifact_path='a', streak_file='s',
                                         options={'playcall_qb_run_role_style': True},
                                         disable_layers=('qb_run_role_style',))
        self.assertFalse(ablated['enabled_layers']['qb_run_role_style'])
        self.assertTrue(ablated['enabled_layers']['qb_decisions'])
        self.assertTrue(ablated['enabled_layers']['decision_labels'])
        self.assertNotEqual(ablated['model_id'], self.resolved['model_id'])

    def test_qb_run_role_style_requires_qb_decisions(self):
        with self.assertRaisesRegex(ValueError, 'requires the QB decision model'):
            config.resolve_profile('custom', artifact_path='a',
                                   options={'playcall_qb_run_role_style': True})

    def test_qb_run_role_style_requires_decision_labels(self):
        with self.assertRaisesRegex(ValueError, 'requires decision labels'):
            config.resolve_profile('custom', artifact_path='a', options={
                'playcall_qb_decisions': True,
                'playcall_qb_run_role_style': True,
            })

    def test_custom_profile_can_disable_the_style_while_retaining_qb_decisions(self):
        ablated = config.resolve_profile('custom', artifact_path='a',
                                         options={'playcall_qb_decisions': True},
                                         disable_layers=('qb_run_role_style',))
        self.assertTrue(ablated['enabled_layers']['qb_decisions'])
        self.assertFalse(ablated['enabled_layers']['qb_run_role_style'])

    def test_disabling_decision_labels_requires_disabling_dependent_playbook_layer(self):
        with self.assertRaisesRegex(ValueError, 'playbook priors depend on decision labels'):
            config.resolve_profile('v1_full_stack', artifact_path='a', streak_file='s',
                                   disable_layers=('decision_labels',))

    def test_required_layer_mismatch_fails_before_execution(self):
        description = {'enabled_layers': dict(self.resolved['enabled_layers'])}
        description['enabled_layers']['qb_decisions'] = False
        with self.assertRaisesRegex(RuntimeError, 'qb_decisions'):
            config.validate_engine_layers(self.resolved, description)

    def test_batch_namespace_receives_the_complete_profile_without_manual_flag_omissions(self):
        values = {
            'slc_profile': 'v1_full_stack', 'slc_disable_layer': [], 'playcall_artifact': 'artifact.json',
            'playcall_streak_file': 'streak.json', 'playcall_decision_unfiltered': False,
            'playcall_player_outcomes_receiver_only': False, 'playcall_point_splits_cache': None,
            'playcall_streak_cache': None, 'playcall_qb_run_role_style': False,
        }
        values.update({option: False for option in config.V1_OPTIONS})
        args = SimpleNamespace(**values)
        resolved = config.apply_profile_to_args(args)
        self.assertEqual(resolved['model_id'], 'SLC_v1_full_stack')
        self.assertTrue(args.playcall_team_outcomes)
        self.assertTrue(args.playcall_dirichlet_shares)
        self.assertFalse(args.playcall_player_shares)
        self.assertTrue(args.playcall_decision)
        self.assertFalse(args.playcall_decision_unfiltered)

    def test_manifest_hashes_every_enabled_layer_and_pins_input_provenance(self):
        description = {
            'enabled_layers': dict(self.resolved['enabled_layers']),
            'artifact_sha256': 'a' * 64,
            'reference_sha256': 'b' * 64,
            'layer_artifact_sha256': {key: 'c' * 64 for key, enabled in self.resolved['enabled_layers'].items()
                                      if enabled},
            'optional_input_sha256': {'current_streak_file': 'd' * 64, 'playbook:one.json': 'e' * 64},
            'integration_code_sha256': {name: 'f' * 64 for files in config.LAYER_CODE_FILES.values()
                                        for name in files},
            'fit_seasons': [2022, 2023, 2024, 2025],
            'source_cutoff': {'eligible_before': [2026, 1]},
        }
        manifest = config.build_manifest(self.resolved, description,
                                         {'snapshot_sha256': '1' * 64, 'as_of': '2026-10-09T10:00:00Z',
                                          'evaluation': {}, 'schedule': {}},
                                         {'mode': 'retrospective_archive_reconstruction',
                                          'archive_validation': {'prospective': False}})
        self.assertEqual(len(manifest['configuration_hash']), 64)
        self.assertEqual(set(manifest['layers']), set(config.ENGINE_LAYER_KEYS))
        for layer in manifest['layers'].values():
            self.assertIn('enabled', layer)
            self.assertIn('configuration', layer)
            self.assertIn('model_artifact_sha256', layer)
            self.assertIn('implementation_sha256', layer)
            self.assertIn('input_provenance', layer)
        self.assertEqual(manifest['evaluation_class'], 'retrospective_archive_reconstruction')
        self.assertFalse(manifest['prospective'])

    def test_target_role_and_decision_category_a_priors_compose_over_available_roles(self):
        combined = pre_event.combine_role_priors(
            {'RB': .7, 'WR': .2, 'TE': .1, 'Other': 0.0},
            {'RB': .1, 'WR': .8, 'TE': .1, 'Other': 0.0},
            {'RB', 'WR'},
        )
        self.assertAlmostEqual(sum(combined.values()), 1.0)
        self.assertEqual(set(combined), {'RB', 'WR'})
        self.assertAlmostEqual(combined['RB'], (.7 * .1) ** .5 / ((.7 * .1) ** .5 + (.2 * .8) ** .5))

    def test_missing_hash_for_an_enabled_layer_fails_manifest_creation(self):
        description = {'enabled_layers': dict(self.resolved['enabled_layers']),
                       'layer_artifact_sha256': {}}
        with self.assertRaisesRegex(RuntimeError, 'no 64-character model hash'):
            config.build_manifest(self.resolved, description, {'snapshot_sha256': 'x'}, {})


if __name__ == '__main__':
    unittest.main()
