"""Validate and summarize two matched-seed SLC ablation ledgers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import rng_protocol
from paired_random_streams import PairedRandomStreams


SCHEMA = 'lp.nfl.paired-seed-ablation-report.v1'
ERROR_STATUSES = frozenset({'simulation_error', 'validation_error'})
MATCHED_HEADER_FIELDS = (
    'schema', 'game_id', 'as_of', 'source_snapshot_sha256', 'observed_reference_sha256',
    'source_commit', 'producer_file_sha256', 'seed_start', 'paired_randomness',
)


class PairingError(ValueError):
    """The input ledgers do not satisfy the paired-seed evaluation contract."""


def _read_ledger(path):
    path = Path(path)
    lines = path.read_text(encoding='utf-8').splitlines()
    if not lines:
        raise PairingError(f'{path} is empty')
    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise PairingError(f'{path} has invalid ledger header JSON: {exc}') from exc
    header = first.get('header')
    if not isinstance(header, dict):
        raise PairingError(f'{path} does not start with a seed-ledger header')
    rows = {}
    duplicates = 0
    for line_number, line in enumerate(lines[1:], start=2):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PairingError(f'{path} has invalid JSON at line {line_number}: {exc}') from exc
        seed, outcome = row.get('seed'), row.get('outcome')
        if type(seed) is not int or not isinstance(outcome, dict) or outcome.get('seed') != seed:
            raise PairingError(f'{path} has an invalid seed/outcome row at line {line_number}')
        if seed in rows:
            duplicates += 1
        rows[seed] = outcome  # matches the simulator's append-only resume ledger: the latest retry is authoritative
    return header, rows, duplicates


IDENTITY_FIELDS = ('pregame_state_sha256', 'reference_data_sha256', 'artifact_sha256',
                   'enabled_layers', 'layer_artifact_sha256', 'execution_settings')


def header_sha256(header):
    return hashlib.sha256(json.dumps(header, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def validate_v2_header(header):
    protocol = header.get('rng_protocol')
    identity = header.get('pairing_identity')
    if not isinstance(protocol, dict) or protocol.get('scheme') != 'v2':
        raise PairingError('ledger must use RNG protocol v2')
    root = protocol.get('stream_root_sha256')
    if not isinstance(root, str) or len(root) != 64 or any(c not in '0123456789abcdef' for c in root):
        raise PairingError('invalid v2 stream root')
    if not isinstance(identity, dict) or any(key not in identity or identity[key] is None for key in IDENTITY_FIELDS):
        raise PairingError('missing v2 pairing identity')
    for key in IDENTITY_FIELDS[:3]:
        value = identity[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise PairingError(f'invalid pairing identity {key}')
    if not isinstance(identity['enabled_layers'], dict) or not all(
            isinstance(key, str) and type(value) is bool for key, value in identity['enabled_layers'].items()):
        raise PairingError('invalid pairing identity enabled_layers')
    if not isinstance(identity['layer_artifact_sha256'], dict) or not isinstance(identity['execution_settings'], dict):
        raise PairingError('invalid pairing identity layer artifacts or execution settings')
    if (identity['enabled_layers'] != header.get('playcall_enabled_layers')
            or identity['pregame_state_sha256'] != protocol.get('pregame_state_sha256')):
        raise PairingError('v2 pairing identity disagrees with ledger metadata')
    return root, identity


def validate_v2_streams(outcome, root, seed, label):
    manifest = outcome.get('paired_random_streams')
    model_seed = int.from_bytes(hashlib.sha256(f'{seed}:{root}'.encode()).digest()[:8], 'big')
    expected = PairedRandomStreams(model_seed, root).manifest()
    if (not isinstance(manifest, dict) or manifest.get('schema') != 'lp.nfl.paired-random-streams.v1'
            or manifest.get('snapshot_sha256') != root
            or manifest.get('root_sha256') != expected['root_sha256']):
        raise PairingError(f'seed {seed} has invalid {label} paired-random-stream evidence')
    return manifest


def compare_ledgers(control_path, ablation_path, *, disabled_layer, expected_games=None):
    """Require identical frozen inputs and seeds, then retain every result, including blocked/error seeds."""
    control_header, control_rows, control_duplicates = _read_ledger(control_path)
    ablation_header, ablation_rows, ablation_duplicates = _read_ledger(ablation_path)
    is_v2 = any(isinstance(h.get('rng_protocol'), dict) and h['rng_protocol'].get('scheme') == 'v2'
                for h in (control_header, ablation_header))
    mismatched = [field for field in MATCHED_HEADER_FIELDS if not (is_v2 and field == 'observed_reference_sha256')
                  if control_header.get(field) != ablation_header.get(field)]
    if mismatched:
        raise PairingError(f'paired ledgers differ in frozen run inputs: {mismatched}')
    if control_header.get('paired_randomness') is not True:
        raise PairingError('both runs must use --paired-randomness')
    if is_v2:
        root, control_identity = validate_v2_header(control_header)
        ablation_root, ablation_identity = validate_v2_header(ablation_header)
        if root != ablation_root:
            raise PairingError('v2 header stream roots differ')
        if control_header.get('paired_layer_baseline'):
            raise PairingError('control must not have a paired layer baseline')
        natural_model = rng_protocol.canonical_sha256({
            'reference_data_sha256': ablation_identity['reference_data_sha256'],
            'layer_tables_sha256': rng_protocol.layer_table_sha256(ablation_identity)})
        natural_root = rng_protocol.canonical_sha256({
            'schema': rng_protocol.SCHEMA_V2, 'pregame_state_sha256': ablation_identity['pregame_state_sha256'],
            'model_input_sha256': natural_model})
        natural = rng_protocol.RngPlan(rng_protocol.V2, root=natural_root,
                                       pregame_state_sha256=ablation_identity['pregame_state_sha256'],
                                       model_input_sha256=natural_model)
        try:
            verified, expected_binding = rng_protocol.pair_layer_plan(
                natural, ablation_identity, control_header, disabled_layer)
        except (ValueError, KeyError) as exc:
            raise PairingError(f'invalid v2 pairing identity: {exc}') from exc
        if (verified.root != root or ablation_header.get('paired_layer_baseline') != expected_binding
                or ablation_header['rng_protocol'].get('model_input_sha256') != verified.model_input_sha256):
            raise PairingError('invalid paired layer baseline binding')
        control_layers = control_identity['enabled_layers']
        ablation_layers = ablation_identity['enabled_layers']
        if set(control_layers) != set(ablation_layers):
            raise PairingError('pairing identity layer keys differ')
    else:
        control_layers = control_header.get('playcall_enabled_layers')
        ablation_layers = ablation_header.get('playcall_enabled_layers')
    if not isinstance(control_layers, dict) or not isinstance(ablation_layers, dict):
        raise PairingError('both ledgers must record their effective play-call layer maps')
    control_enabled = {key for key, enabled in control_layers.items() if enabled}
    ablation_enabled = {key for key, enabled in ablation_layers.items() if enabled}
    expected_disabled = {disabled_layer}
    if (is_v2 and disabled_layer == 'dirichlet_player_target_carry_shares'
            and control_layers.get('fixed_player_target_carry_shares') is True
            and ablation_layers.get('fixed_player_target_carry_shares') is False):
        expected_disabled.add('fixed_player_target_carry_shares')
    if control_enabled - ablation_enabled != expected_disabled or ablation_enabled - control_enabled:
        raise PairingError(
            f'expected exactly {disabled_layer!r} to be disabled; '
            f'control_only={sorted(control_enabled - ablation_enabled)}, '
            f'ablation_only={sorted(ablation_enabled - control_enabled)}')

    control_seeds, ablation_seeds = set(control_rows), set(ablation_rows)
    if control_seeds != ablation_seeds:
        raise PairingError(f'seed coverage differs; control_only={sorted(control_seeds - ablation_seeds)}, '
                           f'ablation_only={sorted(ablation_seeds - control_seeds)}')
    seeds = sorted(control_seeds)
    if expected_games is not None and len(seeds) != expected_games:
        raise PairingError(f'expected {expected_games} paired seeds, found {len(seeds)}')

    pairs = []
    error_seeds = []
    stream_mismatches = []
    for seed in seeds:
        control, ablation = control_rows[seed], ablation_rows[seed]
        control_streams = control.get('paired_random_streams')
        ablation_streams = ablation.get('paired_random_streams')
        control_error = control.get('status') in ERROR_STATUSES
        ablation_error = ablation.get('status') in ERROR_STATUSES
        if control_error or ablation_error:
            error_seeds.append(seed)
        if is_v2:
            if not control_error or control_streams:
                control_streams = validate_v2_streams(control, root, seed, 'control')
            if not ablation_error or ablation_streams:
                ablation_streams = validate_v2_streams(ablation, root, seed, 'ablation')
        elif not (control_error or ablation_error):
            for label, manifest in (('control', control_streams), ('ablation', ablation_streams)):
                if (not isinstance(manifest, dict)
                        or manifest.get('schema') != 'lp.nfl.paired-random-streams.v1'
                        or manifest.get('snapshot_sha256') != control_header['source_snapshot_sha256']):
                    raise PairingError(f'seed {seed} has invalid {label} paired-random-stream evidence')
        if (isinstance(control_streams, dict) and isinstance(ablation_streams, dict)
                and control_streams.get('root_sha256') != ablation_streams.get('root_sha256')):
            stream_mismatches.append(seed)
        control_score = (control.get('home_points'), control.get('away_points'))
        ablation_score = (ablation.get('home_points'), ablation.get('away_points'))
        comparable_scores = (not control_error and not ablation_error
                             and bool(control.get('valid_full_game')) and bool(ablation.get('valid_full_game'))
                             and all(type(value) is int for value in (*control_score, *ablation_score)))
        pairs.append({
            'seed': seed,
            'control_status': control.get('status'), 'ablation_status': ablation.get('status'),
            'control_valid_full_game': bool(control.get('valid_full_game')),
            'ablation_valid_full_game': bool(ablation.get('valid_full_game')),
            'control_score': list(control_score), 'ablation_score': list(ablation_score),
            'score_delta_home': (ablation_score[0] - control_score[0]
                                 if comparable_scores else None),
            'score_delta_away': (ablation_score[1] - control_score[1]
                                 if comparable_scores else None),
            'random_streams_match': (isinstance(control_streams, dict) and isinstance(ablation_streams, dict)
                                     and bool(control_streams.get('root_sha256')) and
                                     control_streams.get('root_sha256') == ablation_streams.get('root_sha256')),
        })
    if stream_mismatches:
        raise PairingError(f'paired random stream roots differ for seeds {stream_mismatches[:20]}')
    return {
        'schema': SCHEMA,
        'status': 'paired_with_seed_errors' if error_seeds else 'paired',
        'valid_for_complete_game_comparison': bool(pairs) and not error_seeds and all(
            pair['control_valid_full_game'] and pair['ablation_valid_full_game'] for pair in pairs),
        'game_id': control_header.get('game_id'),
        'source_snapshot_sha256': control_header.get('source_snapshot_sha256'),
        'disabled_layer': disabled_layer,
        'disabled_layers': sorted(expected_disabled),
        'intervention_kind': 'combined_with_dependent_adapter' if len(expected_disabled) > 1 else 'single_layer',
        'seed_count': len(seeds), 'error_seeds': error_seeds,
        'duplicate_ledger_rows': {'control': control_duplicates, 'ablation': ablation_duplicates},
        'control_enabled_layers': sorted(control_enabled),
        'ablation_enabled_layers': sorted(ablation_enabled),
        'pairs': pairs,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', required=True, type=Path, help='control .seeds.jsonl ledger')
    parser.add_argument('--ablation', required=True, type=Path, help='one-layer-disabled .seeds.jsonl ledger')
    parser.add_argument('--disabled-layer', required=True, help='effective layer key disabled in the ablation')
    parser.add_argument('--expected-games', type=int, help='require this many matched seeds')
    parser.add_argument('--out', type=Path, help='write the JSON report here; stdout is used when omitted')
    args = parser.parse_args(argv)
    if args.expected_games is not None and args.expected_games < 1:
        parser.error('--expected-games must be positive')
    report = compare_ledgers(args.control, args.ablation, disabled_layer=args.disabled_layer,
                             expected_games=args.expected_games)
    rendered = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.out:
        args.out.write_text(rendered, encoding='utf-8')
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
