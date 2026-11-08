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

    def test_v1_keeps_the_legacy_snapshot_key(self):
        plan = rng_protocol.plan(rng_protocol.V1, None, None, None)
        self.assertIsNone(plan.seed_root({'snapshot_sha256': PREGAME}))
        self.assertFalse(plan.paired)
        self.assertEqual(plan.manifest()['scheme'], 'v1')

    def test_v2_root_ignores_code_provenance_and_the_reference_wrapper(self):
        base = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), _description())
        moved = rng_protocol.plan(rng_protocol.V2, PREGAME, _ref(), _description(
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
