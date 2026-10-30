#!/usr/bin/env python3
"""Evaluate the QB run-role adjustment on 2025 and pre-Week-8 2026 PBP.

This is a conditional role-rate diagnostic. It does not replace a paired full-game
SLC ablation, because its control probability is the historical team run-role rate
rather than the decision-label model's per-situation probability.
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import qb_decisions  # noqa: E402


SCHEMA = 'lp.nfl.qb-run-role-holdout.v1'
TRAIN_SEASONS = (2022, 2023, 2024)
HOLDOUT_SEASON = 2025
SCORE_CUTOFF = 1e-12


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _int(value):
    if value in (None, '', 'NA', 'NULL'):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _base_context_valid(row):
    return (row.get('posteam') not in (None, '')
            and _int(row.get('down')) in (1, 2, 3, 4)
            and _int(row.get('ydstogo')) is not None
            and _int(row.get('yardline_100')) is not None
            and _int(row.get('penalty')) != 1
            and _int(row.get('two_point_attempt')) != 1)


def primary_quarterbacks(dropback_counts):
    """Map each team-game to its unique dropback leader; omit tied QB1s."""
    primary = {}
    ambiguous = 0
    for game_team, counts in dropback_counts.items():
        maximum = max(counts.values())
        leaders = sorted(player for player, count in counts.items() if count == maximum)
        if len(leaders) == 1:
            primary[game_team] = leaders[0]
        else:
            ambiguous += 1
    return primary, ambiguous


def classify_run(row, primary_qb, positions):
    """Return 1 for primary-QB run, 0 for other run, None for excluded exposure."""
    if (_int(row.get('rush_attempt')) != 1 or _int(row.get('qb_scramble')) == 1
            or _int(row.get('qb_dropback')) == 1 or _int(row.get('two_point_attempt')) == 1
            or _int(row.get('penalty')) == 1):
        return None
    rusher = row.get('rusher_player_id') or None
    position = positions.get(rusher)
    if position == 'QB' and (rusher is None or primary_qb is None or rusher != primary_qb):
        return None
    return int(position == 'QB' and rusher == primary_qb)


def load_player_identity(path):
    positions = {}
    names = {}
    all_positions = defaultdict(set)
    with Path(path).open('rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row.get('league') and row['league'].lower() != 'nfl':
                continue
            player = row.get('gsis_id') or row.get('nfl_gsis_id')
            if not player:
                continue
            position = row.get('position') or ''
            all_positions[player].add(position)
            names.setdefault(player, row.get('display_name') or player)
    conflicts = {player: sorted(values) for player, values in all_positions.items() if len(values) > 1}
    if conflicts:
        sample = dict(list(sorted(conflicts.items()))[:5])
        raise ValueError(f'conflicting player positions in pinned identity file: {sample}')
    positions.update({player: next(iter(values)) for player, values in all_positions.items()})
    return positions, names


def scan_season(path, season, positions, *, max_week=18):
    """Return primary-QB map, eligible run rows, and source coverage counts."""
    dropbacks = defaultdict(Counter)
    run_rows = []
    pbp_rows = 0
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            pbp_rows += 1
            week = _int(row.get('week'))
            if week is None or not 1 <= week <= max_week or not _base_context_valid(row):
                continue
            game = row.get('game_id')
            team = row.get('posteam')
            if _int(row.get('qb_dropback')) == 1:
                passer = row.get('passer_player_id') or None
                rusher = row.get('rusher_player_id') or None
                qb = passer if positions.get(passer) == 'QB' else None
                if qb is None and _int(row.get('qb_scramble')) == 1 and positions.get(rusher) == 'QB':
                    qb = rusher
                if qb is not None:
                    dropbacks[(game, team)][qb] += 1
            if row.get('play_type') == 'run' and _int(row.get('rush_attempt')) == 1:
                run_rows.append(row)
    primary, ambiguous = primary_quarterbacks(dropbacks)
    observations = []
    excluded_no_primary = 0
    excluded_relief_qb = 0
    for row in run_rows:
        game_team = (row.get('game_id'), row.get('posteam'))
        primary_qb = primary.get(game_team)
        if primary_qb is None:
            excluded_no_primary += 1
            continue
        action = classify_run(row, primary_qb, positions)
        if action is None:
            if positions.get(row.get('rusher_player_id') or None) == 'QB':
                excluded_relief_qb += 1
            continue
        observations.append({
            'season': season,
            'game_id': row.get('game_id'),
            'team': row.get('posteam'),
            'qb': primary_qb,
            'action': action,
            'down': _int(row['down']),
            'togo': _int(row['ydstogo']),
            'yardline': _int(row['yardline_100']),
        })
    return observations, {
        'pbp_rows': pbp_rows,
        'team_games_with_unique_primary_qb': len(primary),
        'ambiguous_primary_qb_team_games': ambiguous,
        'ordinary_team_run_rows': len(run_rows),
        'excluded_runs_without_unique_primary_qb': excluded_no_primary,
        'excluded_relief_qb_runs': excluded_relief_qb,
        'eligible_run_role_observations': len(observations),
    }


def fit_role_table(observations):
    table = {
        'qb_run_player_cell': defaultdict(Counter),
        'qb_run_team_cell': defaultdict(Counter),
        'qb_run_league_cell': defaultdict(Counter),
        'qb_run_player_all': defaultdict(Counter),
        'qb_run_team_all': defaultdict(Counter),
        'qb_run_league_all': Counter(),
    }
    for row in observations:
        cell = qb_decisions.cell_of(row['down'], row['togo'], row['yardline'])
        action = 'qb' if row['action'] else 'other'
        table['qb_run_player_cell'][(row['team'], row['qb'], cell)][action] += 1
        table['qb_run_team_cell'][(row['team'], cell)][action] += 1
        table['qb_run_league_cell'][cell][action] += 1
        table['qb_run_player_all'][(row['team'], row['qb'])][action] += 1
        table['qb_run_team_all'][row['team']][action] += 1
        table['qb_run_league_all'][action] += 1
    return table


def team_rate(table, team, cell):
    league_all = table['qb_run_league_all']
    league_n = sum(league_all.values())
    league_rate = league_all.get('qb', 0) / league_n if league_n else 0.0
    league_cell = table['qb_run_league_cell'].get(cell, Counter())
    league_cell_n = sum(league_cell.values())
    league_cell_rate = league_cell.get('qb', 0) / league_cell_n if league_cell_n else league_rate
    team_all = table['qb_run_team_all'].get(team, Counter())
    team_overall, _ = qb_decisions._qb_run_rate(team_all, league_rate)
    team_cell = table['qb_run_team_cell'].get((team, cell), Counter())
    result, _ = qb_decisions._qb_run_rate(team_cell, league_cell_rate)
    return result, team_overall


def role_probabilities(table, team, qb, down, togo, yardline):
    cell = qb_decisions.cell_of(down, togo, yardline)
    base, _team_overall = team_rate(table, team, cell)
    role, style = qb_decisions.adjust_qb_run_role(
        table, team, qb, down, togo, yardline,
        {'QB': base, 'RB': 1.0 - base}, 'qb-run-role-holdout-evaluation')
    del role
    adjusted = (style.get('adjusted_qb_probability', base) if style is not None else base)
    return base, max(0.0, min(1.0, adjusted)), style


def _loss(actual, probability):
    probability = min(1.0 - SCORE_CUTOFF, max(SCORE_CUTOFF, probability))
    return (actual - probability) ** 2, -(actual * math.log(probability)
                                          + (1 - actual) * math.log1p(-probability))


def _score(rows):
    if not rows:
        return {'n': 0, 'qb_run_rate': None, 'mean_control_probability': None,
                'mean_style_probability': None, 'control_brier': None, 'style_brier': None,
                'delta_brier_style_minus_control': None, 'control_log_loss': None,
                'style_log_loss': None, 'delta_log_loss_style_minus_control': None}
    control_brier = style_brier = control_log = style_log = 0.0
    for row in rows:
        cb, cl = _loss(row['actual'], row['control'])
        sb, sl = _loss(row['actual'], row['style'])
        control_brier += cb
        style_brier += sb
        control_log += cl
        style_log += sl
    n = len(rows)
    return {
        'n': n,
        'qb_run_count': sum(row['actual'] for row in rows),
        'qb_run_rate': sum(row['actual'] for row in rows) / n,
        'mean_control_probability': sum(row['control'] for row in rows) / n,
        'mean_style_probability': sum(row['style'] for row in rows) / n,
        'control_brier': control_brier / n,
        'style_brier': style_brier / n,
        'delta_brier_style_minus_control': (style_brier - control_brier) / n,
        'control_log_loss': control_log / n,
        'style_log_loss': style_log / n,
        'delta_log_loss_style_minus_control': (style_log - control_log) / n,
    }


def _cluster_bootstrap_delta(rows, repetitions=2000, seed=20261030):
    by_game = defaultdict(list)
    for row in rows:
        control_loss, _ = _loss(row['actual'], row['control'])
        style_loss, _ = _loss(row['actual'], row['style'])
        by_game[row['game_id']].append(style_loss - control_loss)
    games = sorted(by_game)
    if len(games) < 2:
        return {'cluster_n': len(games), 'repetitions': 0, 'low_95': None, 'high_95': None}
    rng = random.Random(seed)
    deltas = []
    for _ in range(repetitions):
        total = count = 0
        for _ in games:
            selected = rng.choice(games)
            values = by_game[selected]
            total += sum(values)
            count += len(values)
        deltas.append(total / count)
    deltas.sort()
    return {'cluster_n': len(games), 'repetitions': repetitions,
            'seed': seed,
            'low_95': deltas[int(0.025 * (repetitions - 1))],
            'high_95': deltas[int(0.975 * (repetitions - 1))]}


def verify_pinned_inputs(data_dir, reference_manifest):
    manifest = json.loads(Path(reference_manifest).read_text())
    expected = manifest.get('sources', {}).get('local_source_files', {})
    names = [*(f'pbp_{year}.csv.gz' for year in (*TRAIN_SEASONS, HOLDOUT_SEASON)),
             'pbp_2026_week7.csv.gz', 'players.csv']
    actual = {}
    for name in names:
        path = Path(data_dir) / name
        if not path.is_file():
            raise FileNotFoundError(path)
        actual[name] = sha256(path)
        if expected.get(name) != actual[name]:
            raise ValueError(f'pinned input hash mismatch for {name}: expected {expected.get(name)}, got {actual[name]}')
    return actual


def score_window(table, holdout, names):
    scored = []
    support = Counter()
    adjustments = 0
    for row in holdout:
        control, style_probability, style = role_probabilities(
            table, row['team'], row['qb'], row['down'], row['togo'], row['yardline'])
        level = str((style or {}).get('support_level', 'no_player_history'))
        adjusted = bool((style or {}).get('adjusted'))
        support[level] += 1
        adjustments += int(adjusted)
        scored.append({**row, 'actual': row['action'], 'control': control, 'style': style_probability,
                       'support_level': level, 'adjusted': adjusted})
    player_groups = defaultdict(list)
    for row in scored:
        player_groups[(row['team'], row['qb'])].append(row)
    player_scores = []
    for (team, qb), rows in sorted(player_groups.items(), key=lambda item: (names.get(item[0][1], item[0][1]), item[0][0])):
        summary = _score(rows)
        summary['support_levels'] = dict(sorted(Counter(row['support_level'] for row in rows).items()))
        summary['player_specific_adjustment_decisions'] = sum(row['adjusted'] for row in rows)
        summary.update({'team': team, 'player_id': qb, 'player_name': names.get(qb, qb)})
        player_scores.append(summary)
    summary = _score(scored)
    summary['player_specific_adjustment_decisions'] = adjustments
    summary['support_levels'] = dict(sorted(support.items()))
    summary['game_cluster_bootstrap_delta_brier_95'] = _cluster_bootstrap_delta(scored)
    brissett = [row for row in player_scores if row['player_name'].casefold() == 'jacoby brissett'.casefold()]
    return {'summary': summary, 'jacoby_brissett': brissett,
            'player_holdout_scores': player_scores}


def evaluate(data_dir, reference_manifest):
    input_hashes = verify_pinned_inputs(data_dir, reference_manifest)
    positions, names = load_player_identity(Path(data_dir) / 'players.csv')
    training_2022_24 = []
    coverage = {}
    for season in TRAIN_SEASONS:
        rows, counts = scan_season(Path(data_dir) / f'pbp_{season}.csv.gz', season, positions)
        training_2022_24.extend(rows)
        coverage[str(season)] = counts
    holdout_2025, coverage[str(HOLDOUT_SEASON)] = scan_season(
        Path(data_dir) / f'pbp_{HOLDOUT_SEASON}.csv.gz', HOLDOUT_SEASON, positions)
    target_2026, coverage['2026_weeks_1_7'] = scan_season(
        Path(data_dir) / 'pbp_2026_week7.csv.gz', 2026, positions, max_week=7)
    result_2025 = score_window(fit_role_table(training_2022_24), holdout_2025, names)
    result_2026 = score_window(fit_role_table(training_2022_24 + holdout_2025), target_2026, names)
    return {
        'schema': SCHEMA,
        'reference_manifest_sha256': sha256(reference_manifest),
        'code_sha256': {
            'evaluate_qb_run_role_style.py': sha256(Path(__file__)),
            'qb_decisions.py': sha256(HERE / 'qb_decisions.py'),
        },
        'validation_windows': {
            'heldout_2025': {
                'training_seasons': list(TRAIN_SEASONS),
                'holdout_season': HOLDOUT_SEASON,
                **result_2025,
            },
            'target_2026_weeks_1_7': {
                'training_seasons': [*TRAIN_SEASONS, HOLDOUT_SEASON],
                'holdout_season': 2026,
                'holdout_week_max': 7,
                **result_2026,
            },
        },
        'cutoff_rule': ('the 2025 diagnostic fits 2022–2024; the forecast-target diagnostic fits 2022–2025 '
                        'and scores only 2026 Weeks 1–7, with no Week 8 or later outcomes read'),
        'role_event_definition': ('team run attempt with a unique team-game primary QB, excluding explicit scrambles, '
                                  'QB dropbacks, penalties, and two-point plays; relief-QB runs excluded'),
        'control_definition': 'team QB-run role rate by situation, shrunk toward league situation rate',
        'style_definition': ('the SLC qb_run_role_style function applied to that team rate; player-v-team log-odds '
                            'adjustment with the configured 20-opportunity shrinkage'),
        'limitation': ('conditional run-role rate evaluation only; it does not use the decision-label B probability '
                       'and is not a full-game same-seed SLC ablation'),
        'input_sha256': input_hashes,
        'coverage': coverage,
    }


def _canonicalize_floats(value):
    """Remove insignificant summation noise from machine-readable report values."""
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _canonicalize_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize_floats(item) for item in value]
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--reference-manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = _canonicalize_floats(evaluate(args.data_dir, args.reference_manifest))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({window: {key: values['summary'].get(key) for key in (
        'n', 'qb_run_count', 'qb_run_rate', 'control_brier', 'style_brier',
        'delta_brier_style_minus_control', 'delta_log_loss_style_minus_control',
        'player_specific_adjustment_decisions', 'support_levels',
        'game_cluster_bootstrap_delta_brier_95')}
        for window, values in result['validation_windows'].items()}, sort_keys=True))
    print(f'wrote {args.out}')


if __name__ == '__main__':
    main()
