#!/usr/bin/env python3
"""Materialize SLC v2 player-line thresholds 8-11 from pinned 2022-2024 data.

This script reuses the hash-pinned ACT-roster and player-line loaders from
materialize_thresholds.py. It accepts no season selection and reads no simulation
output. DuckDB is required for the pinned parquet inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import fmean, pvariance
from typing import Any


ALLOWED_SEASONS = (2022, 2023, 2024)
CALIBRATION_SEASONS = (2023, 2024)
REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_SCRIPT = Path(__file__).resolve().with_name('materialize_thresholds.py')
BASE_SCRIPT_SHA256 = 'bfb5c1d9168f34f2f4d5f2ef51008afa1cd9792a67dd5b80076c0cb4f4619191'
OUTPUT_DEFAULT = Path(__file__).resolve().with_name('extended_observed_thresholds.json')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_base_module():
    if not BASE_SCRIPT.is_file():
        raise FileNotFoundError(f'missing pinned base script: {BASE_SCRIPT}')
    digest = sha256_file(BASE_SCRIPT)
    print(f'input_sha256  materialize_thresholds.py  {digest}')
    if digest != BASE_SCRIPT_SHA256:
        raise ValueError(f'base script hash mismatch: expected {BASE_SCRIPT_SHA256}, got {digest}')
    spec = importlib.util.spec_from_file_location('slc_v2_pinned_observed_thresholds', BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load pinned base script at {BASE_SCRIPT}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, digest


def finite_values(values: list[float], label: str) -> None:
    if not values:
        raise ValueError(f'{label}: no player-game observations')
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f'{label}: non-finite player-game value')


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError('quantile requires a non-empty sample')
    rank = (len(ordered) - 1) * probability
    lower, upper = math.floor(rank), math.ceil(rank)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def rows_by_line_role(roster_rows: dict[int, list[dict[str, Any]]],
                      role_specs: dict[str, tuple[str, ...]]) -> dict[int, dict[str, dict[str, list[dict[str, Any]]]]]:
    result: dict[int, dict[str, dict[str, list[dict[str, Any]]]]] = {
        year: {stat: {role: [] for role in roles} for stat, roles in role_specs.items()}
        for year in ALLOWED_SEASONS
    }
    for year in ALLOWED_SEASONS:
        for row in roster_rows[year]:
            role = row['role']
            for stat, roles in role_specs.items():
                if role in roles:
                    result[year][stat][role].append(row)
    return result


def population_details(rows: list[dict[str, Any]], stat: str) -> dict[str, Any]:
    values = [float(row[stat]) for row in rows]
    finite_values(values, f'{stat} population')
    return {
        'player_game_lines': len(values),
        'game_clusters': len({row['game'] for row in rows}),
        'mean': fmean(values),
        'population_variance_ddof_0': pvariance(values),
    }


def metric_8(by_year: dict[int, dict[str, dict[str, list[dict[str, Any]]]]],
             role_specs: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    fold_training = {2023: (2022,), 2024: (2022, 2023)}
    levels = {
        'central_50': (0.25, 0.75),
        'central_95': (0.025, 0.975),
    }
    fold_results: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for test_year, train_years in fold_training.items():
        fold_results[str(test_year)] = {}
        for stat, roles in role_specs.items():
            fold_results[str(test_year)][stat] = {}
            for role in roles:
                training = [float(row[stat]) for year in train_years
                            for row in by_year[year][stat][role]]
                held_out = by_year[test_year][stat][role]
                finite_values(training, f'metric 8 {test_year} {stat}/{role} training')
                if not held_out:
                    raise ValueError(f'metric 8 {test_year} {stat}/{role}: no held-out lines')
                held_values = [float(row[stat]) for row in held_out]
                detail = {
                    'training_player_game_lines': len(training),
                    'held_out_player_game_lines': len(held_values),
                    'held_out_game_clusters': len({row['game'] for row in held_out}),
                }
                for label, (low_p, high_p) in levels.items():
                    low, high = quantile(training, low_p), quantile(training, high_p)
                    covered = sum(low <= value <= high for value in held_values)
                    detail[label] = {
                        'lower_probability': low_p,
                        'upper_probability': high_p,
                        'lower_endpoint': low,
                        'upper_endpoint': high,
                        'covered_player_game_lines': covered,
                        'coverage': covered / len(held_values),
                    }
                fold_results[str(test_year)][stat][role] = detail

    envelopes: dict[str, dict[str, dict[str, Any]]] = {}
    for stat, roles in role_specs.items():
        envelopes[stat] = {}
        for role in roles:
            envelopes[stat][role] = {}
            for level in levels:
                first = fold_results['2023'][stat][role][level]['coverage']
                second = fold_results['2024'][stat][role][level]['coverage']
                envelopes[stat][role][level] = {
                    'lower': min(first, second),
                    'upper': max(first, second),
                    'coverage_2023': first,
                    'coverage_2024': second,
                }
    return {'coverage_envelopes': envelopes, 'fold_details': fold_results}


def metric_9(by_year: dict[int, dict[str, dict[str, list[dict[str, Any]]]]],
             role_specs: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for stat, roles in role_specs.items():
        result[stat] = {}
        for role in roles:
            first = population_details(by_year[2023][stat][role], stat)
            second = population_details(by_year[2024][stat][role], stat)
            result[stat][role] = {
                'n_2023': first['player_game_lines'],
                'n_2024': second['player_game_lines'],
                'game_clusters_2023': first['game_clusters'],
                'game_clusters_2024': second['game_clusters'],
                'mean_2023': first['mean'],
                'mean_2024': second['mean'],
                'T_mean_bias': abs(second['mean'] - first['mean']),
            }
    return result


def metric_10(by_year: dict[int, dict[str, dict[str, list[dict[str, Any]]]]],
              role_specs: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for stat, roles in role_specs.items():
        result[stat] = {}
        for role in roles:
            first = population_details(by_year[2023][stat][role], stat)
            second = population_details(by_year[2024][stat][role], stat)
            var_2023 = first['population_variance_ddof_0']
            var_2024 = second['population_variance_ddof_0']
            if var_2023 <= 0 or var_2024 <= 0:
                threshold = None
                status = 'NOT_EVALUABLE_ZERO_VARIANCE'
            else:
                threshold = abs(math.log(var_2024 / var_2023))
                status = 'EVALUABLE'
            result[stat][role] = {
                'n_2023': first['player_game_lines'],
                'n_2024': second['player_game_lines'],
                'game_clusters_2023': first['game_clusters'],
                'game_clusters_2024': second['game_clusters'],
                'population_variance_2023_ddof_0': var_2023,
                'population_variance_2024_ddof_0': var_2024,
                'T_log_variance_ratio': threshold,
                'status': status,
            }
    return result


def metric_11(by_year: dict[int, dict[str, dict[str, list[dict[str, Any]]]]],
              role_specs: dict[str, tuple[str, ...]],
              quantile_fn) -> dict[str, Any]:
    result: dict[str, dict[str, Any]] = {}
    for stat, roles in role_specs.items():
        result[stat] = {}
        for role in roles:
            baseline = [float(row[stat]) for row in by_year[2022][stat][role]]
            finite_values(baseline, f'metric 11 2022 {stat}/{role} cutoff')
            values_2023 = [float(row[stat]) for row in by_year[2023][stat][role]]
            values_2024 = [float(row[stat]) for row in by_year[2024][stat][role]]
            finite_values(values_2023, f'metric 11 2023 {stat}/{role}')
            finite_values(values_2024, f'metric 11 2024 {stat}/{role}')
            result[stat][role] = {}
            for label, probability in (('p95', 0.95), ('p99', 0.99)):
                cutoff = quantile_fn(baseline, probability)
                exceed_2023 = sum(value > cutoff for value in values_2023)
                exceed_2024 = sum(value > cutoff for value in values_2024)
                freq_2023 = exceed_2023 / len(values_2023)
                freq_2024 = exceed_2024 / len(values_2024)
                result[stat][role][label] = {
                    'cutoff_probability': probability,
                    'cutoff_2022': cutoff,
                    'n_cutoff_2022': len(baseline),
                    'n_2023': len(values_2023),
                    'exceedances_2023': exceed_2023,
                    'frequency_2023': freq_2023,
                    'n_2024': len(values_2024),
                    'exceedances_2024': exceed_2024,
                    'frequency_2024': freq_2024,
                    'T_tail_frequency': abs(freq_2024 - freq_2023),
                }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT_DEFAULT,
                        help='output JSON path; input files and seasons are fixed')
    args = parser.parse_args()

    base, base_hash = load_base_module()
    input_hashes = base.verify_inputs()
    gsis_to_pfr, pfr_to_gsis, gsis_position = base.load_player_crosswalk()
    (_pbp_by_play, week_team_game, _situation_counts, _pass_run_calls,
     _identified_targets, _targets_by_player, _opportunities, player_lines) = base.load_pbp()
    (_snaps, _team_games, _snap_week_team_game, _snap_values, _snap_by_position,
     _snap_share_by_gsis, roster_rows) = base.load_snap_and_rosters(
         pfr_to_gsis, gsis_to_pfr, gsis_position, week_team_game)

    # This call populates the exact stat lines, zero-fill policy, active rows, and roles
    # used by metric 7. Derive the role registry from its fold detail to avoid drift.
    base_metric_7 = base.metric_7(roster_rows, player_lines)
    role_specs = {
        stat: tuple(base_metric_7['fold_details']['2023'][stat]['position_role_detail'])
        for stat in base_metric_7['fold_details']['2023']
    }
    by_year = rows_by_line_role(roster_rows, role_specs)
    for year in ALLOWED_SEASONS:
        if len(roster_rows[year]) != base_metric_7['active_roster_player_games'][str(year)]:
            raise ValueError(f'{year}: ACT player-game population changed from metric 7')

    result = {
        'schema': 'lp.nfl.slc-v2-extended-observed-realism-thresholds.v1',
        'allowed_source_seasons': list(ALLOWED_SEASONS),
        'calibration_seasons': list(CALIBRATION_SEASONS),
        'season_policy': 'Fixed explicit hashed 2022-2024 files only; source row seasons are checked; no other season is accepted.',
        'population': {
            'roster': 'ACT weekly roster player-games, regular season weeks 1-18',
            'zero_fill': 'All metric-7 player lines are zero-filled for ACT player-games without an observed line.',
            'position_roles': role_specs,
            'active_roster_player_games': base_metric_7['active_roster_player_games'],
            'line_units': {
                'offensive_snap_share': 'share',
                'passing_attempts': 'attempts per player-game',
                'rushing_attempts': 'attempts per player-game',
                'rushing_yards': 'yards per player-game',
                'targets': 'targets per player-game',
                'receptions': 'receptions per player-game',
                'receiving_yards': 'yards per player-game',
                'offensive_touchdowns': 'touchdowns per player-game',
            },
        },
        'method': {
            'metric_8': '2023 uses 2022 role-specific linear-interpolated empirical intervals; 2024 uses 2022-2023 pooled intervals. Coverage includes both endpoints. Envelopes are min/max of the two held-out fold coverages.',
            'metric_9': 'League mean per active-roster player-game by line and role. T is the absolute 2024 minus 2023 mean difference.',
            'metric_10': 'Population variance (ddof=0) of single player-game lines by line and role. T is abs(ln(var_2024/var_2023)); zero-variance comparisons are not evaluable.',
            'metric_11': 'Role-specific 2022 empirical p95/p99 cutoffs by line, using linear interpolation at rank (n-1)*p. Tail frequency is the share strictly greater than the fixed cutoff. T is abs(freq_2024-freq_2023).',
        },
        'metric_8': metric_8(by_year, role_specs),
        'metric_9': metric_9(by_year, role_specs),
        'metric_10': metric_10(by_year, role_specs),
        'metric_11': metric_11(by_year, role_specs, base.quantile),
        'input_sha256': {
            'materialize_thresholds.py': base_hash,
            **input_hashes,
        },
        'simulation_outputs_read': False,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(f'output_json  {output}')
    print(json.dumps({
        'metric_8_envelope_counts': sum(len(roles) * 2 for roles in role_specs.values()),
        'metric_9_role_line_count': sum(len(roles) for roles in role_specs.values()),
        'metric_10_evaluable_count': sum(
            item['status'] == 'EVALUABLE'
            for stat in result['metric_10'].values() for item in stat.values()),
        'metric_11_tail_threshold_count': sum(
            len(tails) for roles in result['metric_11'].values() for tails in roles.values()),
        'active_roster_player_games': base_metric_7['active_roster_player_games'],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
