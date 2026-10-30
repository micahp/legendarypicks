"""Named SLC execution profiles and fail-closed model identity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


V1_OPTIONS = {
    'playcall_team_outcomes': True,
    'playcall_formation': True,
    'playcall_coverage': True,
    'playcall_player_shares': False,
    'playcall_dirichlet_shares': True,
    'playcall_qb_decisions': True,
    'playcall_player_outcomes': True,
    'playcall_target_roles': True,
    'playcall_decision': True,
    'playcall_playbook': True,
    'playcall_point_splits': True,
    'playcall_streak_splits': True,
    'playcall_streak_league': True,
    'playcall_exact_yardline': True,
}

OPTION_TO_LAYER = {
    'playcall_team_outcomes': 'team_offense_defense_outcomes',
    'playcall_formation': 'formation_personnel_outcomes',
    'playcall_coverage': 'defensive_coverage_outcomes',
    'playcall_player_shares': 'fixed_player_target_carry_shares',
    'playcall_dirichlet_shares': 'dirichlet_player_target_carry_shares',
    'playcall_qb_decisions': 'qb_decisions',
    'playcall_player_outcomes': 'player_conditioned_outcomes',
    'playcall_target_roles': 'target_role_priors',
    'playcall_decision': 'decision_labels',
    'playcall_playbook': 'playbook_priors',
    'playcall_point_splits': 'point_splits',
    'playcall_streak_splits': 'team_streak_splits',
    'playcall_streak_league': 'league_streak_splits',
    'playcall_exact_yardline': 'exact_yardline_outcomes',
}

LAYER_CODE_FILES = {
    'score_clock_playcalling': ('slc_playcall.py', 'playcall_model.py'),
    'team_offense_defense_outcomes': ('team_tendency.py',),
    'formation_personnel_outcomes': ('formation_layer.py',),
    'defensive_coverage_outcomes': ('defense_layer.py',),
    'fixed_player_target_carry_shares': ('player_shares.py',),
    'dirichlet_player_target_carry_shares': ('share_distributions.py', 'pre_event.py'),
    'qb_decisions': ('qb_decisions.py', 'pre_event.py'),
    'player_conditioned_outcomes': ('player_outcomes.py', 'pre_event.py'),
    'target_role_priors': ('target_roles.py', 'pre_event.py'),
    'decision_labels': ('decision_layer.py',),
    'decision_row_filter': ('decision_layer.py', 'slc_playcall.py'),
    'playbook_priors': ('playbook_prior.py', 'pre_event.py'),
    'point_splits': ('point_splits.py', 'slc_playcall.py'),
    'team_streak_splits': ('streak_splits.py', 'slc_playcall.py'),
    'league_streak_splits': ('streak_splits.py', 'slc_playcall.py'),
    'exact_yardline_outcomes': ('slc_playcall.py',),
    'current_streak_context': ('streak_splits.py', 'slc_playcall.py'),
}

ENGINE_LAYER_KEYS = (
    'score_clock_playcalling',
    'team_offense_defense_outcomes',
    'formation_personnel_outcomes',
    'defensive_coverage_outcomes',
    'fixed_player_target_carry_shares',
    'dirichlet_player_target_carry_shares',
    'qb_decisions',
    'player_conditioned_outcomes',
    'target_role_priors',
    'decision_labels',
    'decision_row_filter',
    'playbook_priors',
    'point_splits',
    'team_streak_splits',
    'league_streak_splits',
    'exact_yardline_outcomes',
    'current_streak_context',
)

ABLATION_LAYERS = frozenset(ENGINE_LAYER_KEYS) - {
    'score_clock_playcalling', 'fixed_player_target_carry_shares',
}


def _expected_layers(options, *, profile, streak_file, decision_filter, artifact_enabled=False):
    layers = {key: False for key in ENGINE_LAYER_KEYS}
    if profile == 's0':
        return layers
    layers.update({
        'score_clock_playcalling': bool(artifact_enabled),
        'decision_row_filter': bool(options.get('playcall_decision') and decision_filter),
        'current_streak_context': bool(streak_file),
    })
    for option, layer in OPTION_TO_LAYER.items():
        layers[layer] = bool(options.get(option, False))
    return layers


def options_from_args(args):
    """Return the explicit feature flags supplied to the legacy/manual runner."""
    return {
        'playcall_team_outcomes': bool(args.playcall_team_outcomes),
        'playcall_formation': bool(args.playcall_formation),
        'playcall_coverage': bool(args.playcall_coverage),
        'playcall_player_shares': bool(args.playcall_player_shares),
        'playcall_dirichlet_shares': bool(args.playcall_dirichlet_shares),
        'playcall_qb_decisions': bool(args.playcall_qb_decisions),
        'playcall_player_outcomes': bool(args.playcall_player_outcomes),
        'playcall_target_roles': bool(args.playcall_target_roles),
        'playcall_decision': bool(args.playcall_decision),
        'playcall_playbook': bool(args.playcall_playbook),
        'playcall_point_splits': bool(args.playcall_point_splits or args.playcall_point_splits_cache),
        'playcall_streak_splits': bool(args.playcall_streak_splits or args.playcall_streak_cache),
        'playcall_streak_league': bool(args.playcall_streak_league),
        'playcall_exact_yardline': bool(args.playcall_exact_yardline),
    }


def apply_profile_to_args(args):
    """Resolve a named profile and install its effective switches on a batch-runner namespace."""
    supplied = options_from_args(args)
    if args.playcall_decision_unfiltered:
        supplied['playcall_decision_unfiltered'] = True
    resolved = resolve_profile(
        args.slc_profile,
        options=supplied,
        artifact_path=args.playcall_artifact,
        streak_file=args.playcall_streak_file,
        disable_layers=args.slc_disable_layer,
        decision_filter=not args.playcall_decision_unfiltered,
    )
    if args.slc_profile == 'custom' and not args.playcall_artifact and any(supplied.values()):
        raise ValueError('SLC feature flags require --playcall-artifact; refusing to silently run a partial S0 control')
    if args.slc_profile == 'v1_full_stack' and args.playcall_player_outcomes_receiver_only:
        raise ValueError('v1_full_stack requires all configured player-outcome roles; receiver-only is an ablation')
    if args.slc_profile in ('s0', 'v1_full_stack'):
        for option in V1_OPTIONS:
            setattr(args, option, resolved['options'].get(option, False))
        args.playcall_player_shares = resolved['options'].get('playcall_player_shares', False)
        args.playcall_decision_unfiltered = not resolved['decision_filter']
        args.playcall_streak_splits = resolved['options'].get('playcall_streak_splits', False)
        args.playcall_point_splits = resolved['options'].get('playcall_point_splits', False)
    args.resolved_slc_profile = resolved
    return resolved


def resolve_profile(profile='custom', *, options=None, artifact_path=None, streak_file=None,
                    disable_layers=(), decision_filter=True):
    """Resolve a preset. v1_full_stack owns its flags; manual overrides cannot make a partial stack wear its label."""
    if profile not in ('custom', 's0', 'v1_full_stack'):
        raise ValueError(f'unknown SLC profile {profile!r}')
    supplied = {key: bool(value) for key, value in (options or {}).items()}
    disabled = set(disable_layers)
    unknown = disabled - ABLATION_LAYERS
    if unknown:
        raise ValueError(f'unknown SLC ablation layer(s): {sorted(unknown)}')

    if profile == 's0':
        if artifact_path or streak_file or any(supplied.values()) or disabled:
            raise ValueError('S0 cannot load or enable SLC layers')
        layers = _expected_layers({}, profile='s0', streak_file=None, decision_filter=False)
        return {'profile': profile, 'model_id': 'S0', 'options': {}, 'enabled_layers': layers,
                'decision_filter': False, 'disabled_layers': []}

    if profile == 'v1_full_stack':
        if not artifact_path:
            raise ValueError('v1_full_stack requires --playcall-artifact')
        if supplied.get('playcall_player_shares'):
            raise ValueError('fixed and Dirichlet player share models are incompatible')
        if supplied.get('playcall_decision_unfiltered'):
            raise ValueError('v1_full_stack requires the decision row filter; disable it with --slc-disable-layer')
        resolved_options = dict(V1_OPTIONS)
        resolved_filter = True
        resolved_streak_file = streak_file
        for layer in disabled:
            if layer == 'decision_row_filter':
                resolved_filter = False
            elif layer == 'current_streak_context':
                resolved_streak_file = None
            elif layer == 'decision_labels':
                resolved_options['playcall_decision'] = False
                resolved_filter = False
            elif layer == 'score_clock_playcalling':
                raise ValueError('score-clock play calling is the SLC policy core; use the separate S0 profile for that control')
            else:
                option = next((name for name, key in OPTION_TO_LAYER.items() if key == layer), None)
                if option:
                    resolved_options[option] = False
        if resolved_options['playcall_player_shares'] and resolved_options['playcall_dirichlet_shares']:
            raise ValueError('fixed and Dirichlet player share models are incompatible')
        if resolved_options['playcall_playbook'] and not resolved_options['playcall_decision']:
            raise ValueError('playbook priors depend on decision labels; disable both layers for that ablation')
        needs_streak = (resolved_options['playcall_streak_splits'] or
                        resolved_options['playcall_streak_league'] or 'current_streak_context' not in disabled)
        if needs_streak and not resolved_streak_file:
            raise ValueError('v1_full_stack requires a frozen pregame streak file')
        layers = _expected_layers(resolved_options, profile=profile, streak_file=resolved_streak_file,
                                  decision_filter=resolved_filter, artifact_enabled=True)
        disabled_names = sorted(disabled)
        return {
            'profile': profile,
            'model_id': 'SLC_v1_full_stack' if not disabled_names else 'SLC_v1_ablation_' + '_'.join(disabled_names),
            'options': resolved_options,
            'enabled_layers': layers,
            'decision_filter': resolved_filter,
            'disabled_layers': disabled_names,
        }

    # The legacy default remains a manual/custom configuration.
    layers = _expected_layers(supplied, profile='custom', streak_file=streak_file,
                              decision_filter=decision_filter, artifact_enabled=bool(artifact_path))
    if layers['fixed_player_target_carry_shares'] and layers['dirichlet_player_target_carry_shares']:
        raise ValueError('fixed and Dirichlet player share models are incompatible')
    return {'profile': profile, 'model_id': 'SLC_custom' if any(layers.values()) else 'S0',
            'options': supplied, 'enabled_layers': layers, 'decision_filter': bool(decision_filter),
            'disabled_layers': []}


def validate_engine_layers(resolved, description):
    """Fail before a game is simulated if the sampler did not load every resolved layer."""
    actual = (description or {}).get('enabled_layers', {})
    if description is None and not any(resolved['enabled_layers'].values()):
        actual = {key: False for key in ENGINE_LAYER_KEYS}
    mismatches = {
        key: {'expected': expected, 'actual': actual.get(key)}
        for key, expected in resolved['enabled_layers'].items()
        if actual.get(key) is not expected
    }
    if mismatches:
        raise RuntimeError(f"resolved SLC profile does not match loaded engine layers: {mismatches}")
    return True


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(resolved, description, snapshot, input_provenance):
    """List every engine layer, with its setting, actual model hash, and source provenance."""
    validate_engine_layers(resolved, description)
    desc = description or {}
    artifact_sha = desc.get('artifact_sha256')
    reference_sha = desc.get('reference_sha256')
    layer_hashes = desc.get('layer_artifact_sha256', {})
    optional_hashes = desc.get('optional_input_sha256', {})
    retrospective = bool(snapshot.get('archive_reconstruction') or
                         (input_provenance or {}).get('mode') == 'retrospective_archive_reconstruction')
    model_hashes = {
        'score_clock_playcalling': layer_hashes.get('score_clock_playcalling', artifact_sha),
        'team_offense_defense_outcomes': layer_hashes.get('team_offense_defense_outcomes'),
        'formation_personnel_outcomes': layer_hashes.get('formation_personnel_outcomes'),
        'defensive_coverage_outcomes': layer_hashes.get('defensive_coverage_outcomes'),
        'fixed_player_target_carry_shares': None,
        'dirichlet_player_target_carry_shares': layer_hashes.get('dirichlet_player_target_carry_shares'),
        'qb_decisions': layer_hashes.get('qb_decisions'),
        'player_conditioned_outcomes': layer_hashes.get('player_conditioned_outcomes'),
        'target_role_priors': layer_hashes.get('target_role_priors'),
        'decision_labels': layer_hashes.get('decision_labels'),
        'decision_row_filter': layer_hashes.get('decision_row_filter'),
        'playbook_priors': layer_hashes.get('playbook_priors'),
        'point_splits': layer_hashes.get('point_splits'),
        'team_streak_splits': layer_hashes.get('team_streak_splits'),
        'league_streak_splits': layer_hashes.get('league_streak_splits'),
        'exact_yardline_outcomes': layer_hashes.get('exact_yardline_outcomes'),
        'current_streak_context': optional_hashes.get('current_streak_file'),
    }
    settings = {
        'score_clock_playcalling': {'artifact_id': desc.get('artifact_id'), 'source_cutoff': desc.get('source_cutoff')},
        'team_offense_defense_outcomes': {'fit_seasons': desc.get('fit_seasons')},
        'formation_personnel_outcomes': {'fit_seasons': desc.get('fit_seasons')},
        'defensive_coverage_outcomes': {'fit_seasons': desc.get('fit_seasons')},
        'fixed_player_target_carry_shares': {'adapter': 'fixed share adapter'},
        'dirichlet_player_target_carry_shares': desc.get('player_share_distribution'),
        'qb_decisions': desc.get('qb_decision_model'),
        'player_conditioned_outcomes': desc.get('player_outcome_model'),
        'target_role_priors': {'source': 'team-by-situation target_roles table',
                               'overlap_rule': 'category A is sampled from the normalized geometric mean of team target-role and decision priors, renormalized to frozen eligible roles',
                               'fit_seasons': desc.get('fit_seasons')},
        'decision_labels': {'categories': 'A-N', 'filter': resolved['decision_filter'],
                            'overlap_rule': 'category A controls target-role label when available; playbook replaces C/D/E where supported'},
        'decision_row_filter': {'enabled': resolved['decision_filter']},
        'playbook_priors': {'precedence': 'replaces decision labels for C/D/E when the source cell has a playbook prior',
                            'artifact_files': sorted(k for k in optional_hashes if k.startswith('playbook:'))},
        'point_splits': {'input_sha256': reference_sha},
        'team_streak_splits': {'input_sha256': reference_sha},
        'league_streak_splits': {'input_sha256': reference_sha},
        'exact_yardline_outcomes': {'yardline_rule': 'exact yardline inside the 20 when source rows exist'},
        'current_streak_context': {'input_sha256': optional_hashes.get('current_streak_file')},
    }
    resolved_input_provenance = {
        **(input_provenance or {}),
        'reference_sha256': reference_sha,
        'reference_source_cutoff': desc.get('source_cutoff'),
        'optional_input_sha256': optional_hashes,
        'playcall_artifact_sha256': artifact_sha,
    }
    layers = {
        key: {
            'enabled': bool(resolved['enabled_layers'][key]),
            'configuration': settings[key],
            'model_artifact_sha256': model_hashes[key],
            'implementation_sha256': {name: desc.get('integration_code_sha256', {}).get(name)
                                      for name in LAYER_CODE_FILES[key]},
            'input_provenance': resolved_input_provenance,
        }
        for key in ENGINE_LAYER_KEYS
    }
    missing_hashes = [key for key, item in layers.items()
                      if item['enabled'] and (not item['model_artifact_sha256']
                                               or len(item['model_artifact_sha256']) != 64)]
    if missing_hashes:
        raise RuntimeError(f'enabled SLC layer(s) have no 64-character model hash: {missing_hashes}')
    missing_implementation = [key for key, item in layers.items() if item['enabled'] and
                              any(not value or len(value) != 64
                                  for value in item['implementation_sha256'].values())]
    if missing_implementation:
        raise RuntimeError(f'enabled SLC layer(s) have missing implementation hashes: {missing_implementation}')
    snapshot_sha = snapshot.get('snapshot_sha256')
    if any(resolved['enabled_layers'].values()) and (not snapshot_sha or len(snapshot_sha) != 64):
        raise RuntimeError('enabled SLC layers require a hash-pinned input snapshot')
    core = {
        'schema': 'lp-nfl-slc-profile-manifest-1',
        'profile': resolved['profile'],
        'model_id': resolved['model_id'],
        'enabled_layers': dict(resolved['enabled_layers']),
        'disabled_layers': list(resolved['disabled_layers']),
        'layers': layers,
        'playcall_artifact_sha256': artifact_sha,
        'reference_sha256': reference_sha,
        'source_cutoff': desc.get('source_cutoff'),
        'integration_code_sha256': desc.get('integration_code_sha256', {}),
        'evaluation_class': (snapshot.get('archive_reconstruction', {}).get('mode')
                             if snapshot.get('archive_reconstruction') else
                             'retrospective_archive_reconstruction' if retrospective else
                             snapshot.get('evaluation', {}).get('class', 'prospective')),
        'prospective': not retrospective,
        'input_provenance': resolved_input_provenance,
        'snapshot_sha256': snapshot.get('snapshot_sha256'),
    }
    if desc.get('blocker_resolution'):
        core['blocker_resolution'] = desc['blocker_resolution']
    core['configuration_hash'] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(',', ':'), default=str).encode()
    ).hexdigest()
    return core


def _manifest_hash(value):
    if not value:
        return None
    return hashlib.sha256(json.dumps(_stable(value), sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _stable(value):
    """Convert nested mappings, tuple keys, counters, sets, and numpy scalars to canonical JSON values."""
    if isinstance(value, dict):
        entries = [(_stable(key), _stable(item)) for key, item in value.items()]
        entries.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True, default=str))
        return {'__mapping__': entries}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_stable(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if hasattr(value, 'item'):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, 'tolist'):
        try:
            return _stable(value.tolist())
        except (TypeError, ValueError):
            pass
    if hasattr(value, '__dict__'):
        return _stable(vars(value))
    return value
