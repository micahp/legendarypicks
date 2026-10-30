"""Validate and summarize two matched-seed SLC ablation ledgers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


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


def compare_ledgers(control_path, ablation_path, *, disabled_layer, expected_games=None):
    """Require identical frozen inputs and seeds, then retain every result, including blocked/error seeds."""
    control_header, control_rows, control_duplicates = _read_ledger(control_path)
    ablation_header, ablation_rows, ablation_duplicates = _read_ledger(ablation_path)
    mismatched = [field for field in MATCHED_HEADER_FIELDS
                  if control_header.get(field) != ablation_header.get(field)]
    if mismatched:
        raise PairingError(f'paired ledgers differ in frozen run inputs: {mismatched}')
    if control_header.get('paired_randomness') is not True:
        raise PairingError('both runs must use --paired-randomness')
    control_layers = control_header.get('playcall_enabled_layers')
    ablation_layers = ablation_header.get('playcall_enabled_layers')
    if not isinstance(control_layers, dict) or not isinstance(ablation_layers, dict):
        raise PairingError('both ledgers must record their effective play-call layer maps')
    control_enabled = {key for key, enabled in control_layers.items() if enabled}
    ablation_enabled = {key for key, enabled in ablation_layers.items() if enabled}
    if control_enabled - ablation_enabled != {disabled_layer} or ablation_enabled - control_enabled:
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
        else:
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
        pairs.append({
            'seed': seed,
            'control_status': control.get('status'), 'ablation_status': ablation.get('status'),
            'control_valid_full_game': bool(control.get('valid_full_game')),
            'ablation_valid_full_game': bool(ablation.get('valid_full_game')),
            'control_score': list(control_score), 'ablation_score': list(ablation_score),
            'score_delta_home': (ablation_score[0] - control_score[0]
                                 if all(type(value) is int for value in (*control_score, *ablation_score)) else None),
            'score_delta_away': (ablation_score[1] - control_score[1]
                                 if all(type(value) is int for value in (*control_score, *ablation_score)) else None),
            'random_streams_match': (control_streams or {}).get('root_sha256') ==
                                    (ablation_streams or {}).get('root_sha256'),
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
