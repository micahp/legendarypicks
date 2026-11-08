"""The v2 stream root depends on stable inputs only; v1 keeps the legacy snapshot key."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paired_random_streams  # noqa: E402
import rng_protocol  # noqa: E402

PREGAME = 'a' * 64
OTHER_PREGAME = 'b' * 64


def _ref(sample=1.0):
    return SimpleNamespace(
        pool={('dropback', 'shotgun'): [('pass_complete', {'yardline_100': 20}, False, 'mid')],
               ('run', 'inside'): [('rush', {'yardline_100': 7}, False, 'mid', sample)]},
        kickoff_pool=[{'yards': 60}], kicks={'fg': [40, 41]}, participants={('KC', 'QB'): ['mahomes']},
        position_usage={'QB': 1}, missed_field_goal_pool={'short': [{'yards': 12}]},
        blocked_kicks={'records': {}, 'rates': {'fg': 0.01}, 'sha256': 'c' * 64}, pool_scope={'cutoff': '2026-10-29'},
    )


def _description(**overrides):
    description = {
        'artifact_sha256': 'd' * 64, 'enabled_layers': {'team_offense_defense_outcomes': True},
        'reference_sha256': 'e' * 64, 'integration_code_sha256': {'pre_event.py': 'f' * 64},
        'layer_artifact_sha256': {'team_offense_defense_outcomes': '1' * 64,
                                  'exact_yardline_outcomes': '2' * 64},
    }
    description.update(overrides)
    return description


class RngProtocol(unittest.TestCase):
    def test_stable_pregame_identity_ignores_build_time_but_not_roster(self):
        import copy
        original = {'built_at_utc': '2026-11-05T12:00:00Z', 'snapshot_sha256': 'a' * 64,
                    'rosters': {'home': ['QB1']}, 'as_of': '2026-11-05T11:00:00Z'}
        moved = copy.deepcopy(original)
        moved.update(built_at_utc='2026-11-05T12:00:01Z', snapshot_sha256='b' * 64,
                     model_reference={'observed_reference': {'sha256': 'c' * 64}})
        self.assertEqual(rng_protocol.pregame_state_sha256(original), rng_protocol.pregame_state_sha256(moved))
        moved['rosters']['home'] = ['QB2']
        self.assertNotEqual(rng_protocol.pregame_state_sha256(original), rng_protocol.pregame_state_sha256(moved))

    def test_pair_gate_refuses_mismatched_or_legacy_roots(self):
        control = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), _description())
        control.require_root(control.root)
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            control.require_root('f' * 64)
        with self.assertRaisesRegex(ValueError, 'requires v2'):
            rng_protocol.plan(rng_protocol.V1, None, None, None).require_root(control.root)

    def test_one_layer_ablation_uses_verified_control_stream(self):
        control_desc = _description()
        ablated_desc = _description(enabled_layers={'team_offense_defense_outcomes': False},
                                    layer_artifact_sha256={'team_offense_defense_outcomes': None,
                                                           'exact_yardline_outcomes': '9' * 64})
        control = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), control_desc)
        natural = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), ablated_desc)
        control_identity = rng_protocol.layer_pairing_identity(PREGAME, _ref(), control_desc, {'fixes': ['a']})
        ablated_identity = rng_protocol.layer_pairing_identity(PREGAME, _ref(), ablated_desc, {'fixes': ['a']})
        header = {'rng_protocol': control.manifest(), 'pairing_identity': control_identity}
        paired, evidence = rng_protocol.pair_layer_plan(natural, ablated_identity, header,
                                                        'team_offense_defense_outcomes')
        self.assertNotEqual(natural.root, control.root)
        self.assertEqual(paired.root, control.root)
        self.assertEqual(evidence['natural_ablation_stream_root_sha256'], natural.root)
        self.assertEqual(evidence['baseline_header_sha256'], rng_protocol.canonical_sha256(header))
        self.assertEqual(paired_random_streams.PairedRandomStreams(7, control.root).key('playcall', 1),
                         paired_random_streams.PairedRandomStreams(7, paired.root).key('playcall', 1))
        with self.assertRaisesRegex(ValueError, 'execution_settings'):
            bad = {**ablated_identity, 'execution_settings': {'fixes': ['other']}}
            rng_protocol.pair_layer_plan(natural, bad, header, 'team_offense_defense_outcomes')
        with self.assertRaisesRegex(ValueError, 'reference_data_sha256'):
            bad = {**ablated_identity, 'reference_data_sha256': 'b' * 64}
            rng_protocol.pair_layer_plan(natural, bad, header, 'team_offense_defense_outcomes')
        with self.assertRaisesRegex(ValueError, 'exactly the selected layer'):
            rng_protocol.pair_layer_plan(natural, control_identity, header, 'team_offense_defense_outcomes')
        with self.assertRaisesRegex(ValueError, 'root does not match'):
            bad_header = {**header, 'rng_protocol': {**header['rng_protocol'], 'stream_root_sha256': 'f' * 64}}
            rng_protocol.pair_layer_plan(natural, ablated_identity, bad_header, 'team_offense_defense_outcomes')

    def test_workload_pairing_requires_only_workload_table_to_change(self):
        layers = {'dirichlet_player_target_carry_shares': True, 'point_splits': True}
        before = _description(enabled_layers=layers, layer_artifact_sha256={
            'dirichlet_player_target_carry_shares': '1' * 64, 'point_splits': '2' * 64})
        after = _description(enabled_layers=layers, layer_artifact_sha256={
            'dirichlet_player_target_carry_shares': '3' * 64, 'point_splits': '2' * 64})
        control = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), before)
        natural = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), after)
        header = {'rng_protocol': control.manifest(),
                  'pairing_identity': rng_protocol.layer_pairing_identity(PREGAME, _ref(), before, {})}
        identity = rng_protocol.layer_pairing_identity(PREGAME, _ref(), after, {})
        paired, evidence = rng_protocol.pair_workload_plan(natural, identity, header)
        self.assertEqual(paired.root, control.root)
        self.assertNotEqual(evidence['natural_treatment_root_sha256'], paired.root)
        identity['layer_artifact_sha256']['point_splits'] = '4' * 64
        with self.assertRaisesRegex(ValueError, 'another layer'):
            rng_protocol.pair_workload_plan(natural, identity, header)

    def test_pairing_refuses_changed_other_active_layer(self):
        layers = {'team_offense_defense_outcomes': True, 'point_splits': True}
        hashes = {'team_offense_defense_outcomes': '1' * 64, 'point_splits': '2' * 64}
        before = _description(enabled_layers=layers, layer_artifact_sha256=hashes)
        after = _description(enabled_layers={**layers, 'team_offense_defense_outcomes': False},
                             layer_artifact_sha256={**hashes, 'team_offense_defense_outcomes': None,
                                                    'point_splits': '3' * 64})
        control = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), before)
        natural = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), after)
        header = {'rng_protocol': control.manifest(),
                  'pairing_identity': rng_protocol.layer_pairing_identity(PREGAME, _ref(), before, {})}
        identity = rng_protocol.layer_pairing_identity(PREGAME, _ref(), after, {})
        with self.assertRaisesRegex(ValueError, 'another active layer input: point_splits'):
            rng_protocol.pair_layer_plan(natural, identity, header, 'team_offense_defense_outcomes')

    def test_dirichlet_ablation_may_also_unload_its_fixed_share_adapter(self):
        before = _description(enabled_layers={'dirichlet_player_target_carry_shares': True,
                                               'fixed_player_target_carry_shares': True},
                              layer_artifact_sha256={'dirichlet_player_target_carry_shares': '1' * 64,
                                                     'fixed_player_target_carry_shares': '2' * 64})
        after = _description(enabled_layers={key: False for key in before['enabled_layers']},
                             layer_artifact_sha256={key: None for key in before['layer_artifact_sha256']})
        control = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), before)
        natural = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), after)
        header = {'rng_protocol': control.manifest(),
                  'pairing_identity': rng_protocol.layer_pairing_identity(PREGAME, _ref(), before, {})}
        identity = rng_protocol.layer_pairing_identity(PREGAME, _ref(), after, {})
        paired, _ = rng_protocol.pair_layer_plan(natural, identity, header, 'dirichlet_player_target_carry_shares')
        self.assertEqual(paired.root, control.root)

    def test_v1_keeps_the_legacy_snapshot_key(self):
        plan = rng_protocol.plan(rng_protocol.V1, None, None, None)
        self.assertIsNone(plan.seed_root({'snapshot_sha256': PREGAME}))
        self.assertFalse(plan.paired)
        self.assertEqual(plan.manifest()['scheme'], 'v1')

    def test_v2_root_ignores_code_provenance_and_the_reference_wrapper(self):
        base = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), _description())
        intervention = _ref()
        intervention.blocker_fixes = frozenset({'restore_sack_mass'})
        moved = rng_protocol.plan(rng_protocol.V2, PREGAME, intervention, _description(
            integration_code_sha256={'pre_event.py': '0' * 64}, reference_sha256='9' * 64,
            layer_artifact_sha256={'team_offense_defense_outcomes': '1' * 64,
                                   'exact_yardline_outcomes': '8' * 64}))
        self.assertEqual(base.root, moved.root)
        self.assertTrue(base.paired)
        self.assertEqual(base.seed_root({'snapshot_sha256': 'x' * 64}), base.root)

    def test_v2_root_moves_with_pregame_state_and_model_tables(self):
        base = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), _description())
        self.assertNotEqual(base.root, rng_protocol.plan(rng_protocol.V2, OTHER_PREGAME, _ref(), _description()).root)
        self.assertNotEqual(base.root, rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(sample=2.0), _description()).root)
        changed_layer = _description(layer_artifact_sha256={'team_offense_defense_outcomes': '3' * 64,
                                                            'exact_yardline_outcomes': '2' * 64})
        self.assertNotEqual(base.root, rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), changed_layer).root)

    def test_v2_manifest_separates_stream_key_from_provenance(self):
        manifest = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), _description()).manifest()
        self.assertEqual(manifest['schema'], rng_protocol.SCHEMA_V2)
        self.assertEqual(len(manifest['rng_protocol_file_sha256']), 64)
        self.assertNotIn('integration_code_sha256', manifest)

    def test_v2_refuses_without_the_slc_layer_or_a_bad_pregame_hash(self):
        with self.assertRaises(ValueError):
            rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), None)
        with self.assertRaises(ValueError):
            rng_protocol.plan(rng_protocol.V2, 'not-a-hash', _ref(), _description())
        with self.assertRaises(ValueError):
            rng_protocol.plan('v3', PREGAME, _ref(), _description())

    def test_named_streams_are_stable_and_independent(self):
        root = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), _description()).root
        streams = paired_random_streams.PairedRandomStreams(7, root)
        again = paired_random_streams.PairedRandomStreams(7, root)
        self.assertEqual(streams.rng('playcall', 3).random(), again.rng('playcall', 3).random())
        self.assertNotEqual(streams.key('playcall', 3), streams.key('participation', 3))


if __name__ == '__main__':
    unittest.main()
