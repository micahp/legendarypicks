"""Random-stream protocols for SLC runs.

Two protocols run side by side:

* v1 (explicit legacy replay; default without SLC). Every pre-event draw is keyed on the resealed snapshot hash. That hash carries the reference
  fingerprint, and the fingerprint carries SHA-256 hashes of the integration code. An edit to those files, or a new
  commit, therefore changes every seed's draws even with every research flag off. Archived runs keep this key.
* v2 (the SLC default, `--rng-protocol v2`). The stream root is keyed on stable inputs only: the pregame state (rosters,
  availability, schedule, captured before the reference attaches) and the model-input identity (the loaded reference
  tables and the layer tables, without code hashes). Code and artifact hashes stay in the provenance manifest and key
  no draw.

Named draw sites keep their semantic labels (playcall, participation, outcome, pbv1, and the p1 and p2 families when they
exist), so one arm that changes one decision leaves every other stream as it was.
"""
import hashlib
import json
from pathlib import Path

V1 = 'v1'
V2 = 'v2'
SCHEMA_V2 = 'lp.nfl.slc-rng.v2'
MODEL_IDENTITY_SCHEMA = 'lp.nfl.slc-model-input-identity.v1'
# Its hash wraps reference_sha256 and a fixed rule. Its candidate rows are the pool rows, which reference_data_sha256 covers.
EXACT_YARDLINE_LAYER = 'exact_yardline_outcomes'
THIS_FILE = Path(__file__).resolve()


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
                          .encode('utf-8')).hexdigest()


def pregame_state_sha256(snapshot):
    """Hash simulation inputs separately from the snapshot's provenance/content seal.

    The content seal still verifies every byte, including build time. Model-reference
    tables are covered separately by plan(), after they are loaded.
    """
    return canonical_sha256({key: value for key, value in snapshot.items()
                             if key not in {'snapshot_sha256', 'built_at_utc', 'model_reference'}})


def _is_sha256(text):
    return isinstance(text, str) and len(text) == 64 and all(char in '0123456789abcdef' for char in text)


def reference_data_sha256(ref):
    """Digest of the loaded reference tables. It carries no code hashes, file hashes or git commit."""
    blocked = ref.blocked_kicks or {}
    return canonical_sha256({
        'schema': MODEL_IDENTITY_SCHEMA,
        'play_cells': [[key, ref.pool[key]] for key in sorted(ref.pool)],
        'kickoff_pool': ref.kickoff_pool,
        'kick_table': ref.kicks,
        'participants': sorted(ref.participants.items()),
        'position_usage': ref.position_usage,
        'missed_field_goal_pool': sorted(ref.missed_field_goal_pool.items()),
        'blocked_kick_records': sorted((blocked.get('records') or {}).items()),
        'blocked_kick_rates': blocked.get('rates'),
        'blocked_kick_source_sha256': blocked.get('sha256'),
        'safety_kick_pool': getattr(ref, 'safety_kick_pool', None),
        'overtime_pool': getattr(ref, 'overtime_pool', None),
        'overtime_try_p_two': getattr(ref, 'overtime_try_p_two', None),
        'overtime_p_kick': getattr(ref, 'overtime_p_kick', None),
        'overtime_choice': getattr(ref, 'overtime_choice', None),
        'overtime_toss': getattr(ref, 'overtime_toss', None),
        'pool_scope': getattr(ref, 'pool_scope', None),
    })


def layer_table_sha256(playcall_description):
    """Per-layer table hashes and the enabled set, without the exact-yardline wrapper and without code hashes."""
    layers = dict(playcall_description['layer_artifact_sha256'])
    layers.pop(EXACT_YARDLINE_LAYER, None)
    return canonical_sha256({
        'artifact_sha256': playcall_description['artifact_sha256'],
        'enabled_layers': playcall_description.get('enabled_layers'),
        'layers': layers,
    })


def layer_pairing_identity(pregame_sha256, ref, description, execution_settings):
    """Capture the loaded inputs needed to prove a one-layer intervention is isolated."""
    return {'pregame_state_sha256': pregame_sha256, 'reference_data_sha256': reference_data_sha256(ref),
            'artifact_sha256': description['artifact_sha256'],
            'enabled_layers': description['enabled_layers'],
            'layer_artifact_sha256': description['layer_artifact_sha256'],
            'execution_settings': execution_settings}


def pair_layer_plan(natural_plan, identity, baseline_header, disabled_layer):
    """Bind an isolated layer ablation to a verified v2 control, before drawing any seeds."""
    baseline = baseline_header.get('pairing_identity')
    protocol = baseline_header.get('rng_protocol') or {}
    if (natural_plan.scheme != V2 or protocol.get('scheme') != V2 or not isinstance(baseline, dict)
            or baseline_header.get('paired_layer_baseline')):
        raise ValueError('layer pairing requires an unpaired v2 control with a complete pairing identity')
    for key in ('pregame_state_sha256', 'reference_data_sha256', 'artifact_sha256', 'execution_settings'):
        if identity.get(key) != baseline.get(key):
            raise ValueError(f'layer pairing input differs from control: {key}')
    old, new = baseline.get('enabled_layers'), identity.get('enabled_layers')
    old_hashes, new_hashes = baseline.get('layer_artifact_sha256'), identity.get('layer_artifact_sha256')
    if not all(isinstance(x, dict) for x in (old, new, old_hashes, new_hashes)) or old.keys() != new.keys():
        raise ValueError('layer pairing requires matching complete layer maps')
    changed = {key for key in old if old[key] != new[key]}
    allowed = {disabled_layer}
    # The fixed-share adapter is loaded to supply players to the Dirichlet layer;
    # disabling Dirichlet also unloads that adapter when it was not independently requested.
    if (disabled_layer == 'dirichlet_player_target_carry_shares'
            and old.get('fixed_player_target_carry_shares') is True
            and new.get('fixed_player_target_carry_shares') is False):
        allowed.add('fixed_player_target_carry_shares')
    if changed != allowed or old.get(disabled_layer) is not True or new.get(disabled_layer) is not False:
        raise ValueError(f'layer pairing requires exactly the selected layer disabled: {sorted(changed)}')
    for key, enabled in old.items():
        if enabled and key not in allowed and key != EXACT_YARDLINE_LAYER:
            if not old_hashes.get(key) or old_hashes.get(key) != new_hashes.get(key):
                raise ValueError(f'layer pairing changes another active layer input: {key}')
    baseline_model = canonical_sha256({'reference_data_sha256': baseline['reference_data_sha256'],
                                       'layer_tables_sha256': layer_table_sha256(baseline)})
    expected = canonical_sha256({'schema': SCHEMA_V2, 'pregame_state_sha256': baseline['pregame_state_sha256'],
                                 'model_input_sha256': baseline_model})
    if protocol.get('stream_root_sha256') != expected or protocol.get('model_input_sha256') != baseline_model:
        raise ValueError('control v2 stream root does not match its recorded inputs')
    paired = RngPlan(V2, root=expected, pregame_state_sha256=baseline['pregame_state_sha256'],
                     model_input_sha256=baseline_model)
    evidence = {'disabled_layer': disabled_layer, 'baseline_stream_root_sha256': expected,
                'baseline_header_sha256': canonical_sha256(baseline_header),
                'natural_ablation_stream_root_sha256': natural_plan.root,
                'natural_ablation_model_input_sha256': natural_plan.model_input_sha256}
    return paired, evidence


class RngPlan:
    """Which stream protocol a batch uses, and the root every pre-event draw is keyed on."""

    def __init__(self, scheme, root=None, pregame_state_sha256=None, model_input_sha256=None):
        self.scheme = scheme
        self.root = root
        self.pregame_state_sha256 = pregame_state_sha256
        self.model_input_sha256 = model_input_sha256

    @property
    def paired(self):
        """v2 draws every game-level stream from the named streams, so the paired streams are always on."""
        return self.scheme == V2

    def seed_root(self, snapshot):
        """The key for the pre-event draws. None keeps the legacy snapshot key, so v1 runs are unchanged."""
        return None if self.scheme == V1 else self.root

    def require_root(self, expected):
        """Refuse an unpaired experiment before producing any seed outcomes."""
        if self.scheme != V2 or not _is_sha256(expected):
            raise ValueError('paired comparison requires v2 and a valid expected stream root SHA-256')
        if self.root != expected:
            raise ValueError(f'paired stream root mismatch: expected {expected}, loaded {self.root}')

    def manifest(self):
        provenance = {'rng_protocol_file_sha256': hashlib.sha256(THIS_FILE.read_bytes()).hexdigest()}
        if self.scheme == V1:
            return {'scheme': V1, 'stream_key': 'snapshot_sha256 (resealed; carries the reference fingerprint and code hashes)',
                    **provenance}
        return {'scheme': V2, 'schema': SCHEMA_V2, 'stream_root_sha256': self.root,
                'pregame_state_sha256': self.pregame_state_sha256, 'model_input_sha256': self.model_input_sha256,
                'stream_key': 'stream_root_sha256 (code and artifact hashes are provenance only)', **provenance}


def plan(scheme, pregame_state_sha256, ref, playcall_description):
    """The RNG plan for one batch. v2 needs the SLC layer description, so a run without the layer fails loudly."""
    if scheme == V1:
        return RngPlan(V1)
    if scheme != V2:
        raise ValueError(f'unknown rng protocol {scheme!r}')
    if not _is_sha256(pregame_state_sha256):
        raise ValueError('rng protocol v2 needs the pregame state SHA-256')
    if not playcall_description:
        raise ValueError('rng protocol v2 needs the SLC play-call layer description; this run has none')
    model_input = canonical_sha256({'reference_data_sha256': reference_data_sha256(ref),
                                    'layer_tables_sha256': layer_table_sha256(playcall_description)})
    root = canonical_sha256({'schema': SCHEMA_V2, 'pregame_state_sha256': pregame_state_sha256,
                             'model_input_sha256': model_input})
    return RngPlan(V2, root=root, pregame_state_sha256=pregame_state_sha256, model_input_sha256=model_input)
