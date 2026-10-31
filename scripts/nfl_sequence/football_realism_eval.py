#!/usr/bin/env python3
"""Compare valid SLC seed ledgers with the pinned, cutoff-safe E3 NFL distributions.

This is a warning report, not a per-game acceptance gate. It retains seed coverage and failures,
compares only metrics with compatible definitions, and reports unsupported comparisons explicitly.
"""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = 'lp.nfl.football-realism-distribution-report.v1'
REFERENCE_SCHEMA = 'lp.nfl.e3-observed-distributions.v1'
JOINT_REFERENCE_SCHEMA = 'lp.nfl.e3-football-realism-joint-reference.v1'
BOX_SCHEMAS = {'lp-nfl-slc-boxscore-1', 'lp-nfl-slc-boxscore-2', 'lp-nfl-slc-boxscore-3'}
DEFAULT_REFERENCE = Path(__file__).resolve().parents[2] / 'docs/research/e3-observed-distributions-2026-10-24'
DEFAULT_JOINT_REFERENCE = (Path(__file__).resolve().parents[2]
                           / 'docs/research/e3-football-realism-joint-reference-2026-10-30')

GAME_METRICS = {
    'home_score': ('home_score', 'team points from the game score ledger'),
    'away_score': ('away_score', 'team points from the game score ledger'),
    'total_points': ('total_points', 'sum of home and away game score ledger points'),
    'home_margin': ('home_margin', 'home points minus away points'),
    'absolute_margin': ('absolute_margin', 'absolute home-away point difference'),
    'pass_attempts_per_game': ('pass_attempts_per_game', 'sum of team pass attempts'),
    'rush_attempts_per_game': ('rush_attempts_per_game', 'sum of team rushing attempts'),
    'scrimmage_plays_per_game': ('pass_run_rows_per_game',
                                 'sum of team run/pass scrimmage events, including sacks and turnovers'),
    'qb_dropbacks_per_game': ('qb_dropbacks_per_game', 'pass attempts plus sacks plus explicit QB scrambles'),
    'touchdowns_per_game': ('touchdowns_per_game', 'sum of team touchdowns, including return touchdowns'),
    'nonnull_drive_groups_per_game': ('nonnull_drive_groups_per_game', 'sum of home and away offensive drives'),
}

PLAYER_METRICS = {
    ('passing', 'attempts'): ('passing', 'att'),
    ('passing', 'completions'): ('passing', 'comp'),
    ('passing', 'passing_yards'): ('passing', 'yds'),
    ('passing', 'passing_touchdowns'): ('passing', 'td'),
    ('passing', 'interceptions'): ('passing', 'int'),
    ('passing', 'sacks'): ('passing', 'sacked'),
    ('rushing', 'attempts'): ('rushing', 'att'),
    ('rushing', 'rushing_yards'): ('rushing', 'yds'),
    ('rushing', 'rushing_touchdowns'): ('rushing', 'td'),
    ('receiving', 'targets'): ('receiving', 'tgt'),
    ('receiving', 'receptions'): ('receiving', 'rec'),
    ('receiving', 'receiving_yards'): ('receiving', 'yds'),
    ('receiving', 'receiving_touchdowns'): ('receiving', 'td'),
}

UNSUPPORTED = [
    {'metric': 'pbp_rows_per_game', 'status': 'NOT_COMPARABLE',
     'reason': 'the boxscore omits a complete PBP row stream, including all kickoffs, tries, and administrative rows.'},
    {'metric': 'player_zero_outcome_frequency', 'status': 'NOT_COMPARABLE',
     'reason': 'the historical player table includes role player-games with observed opportunities, while SLC zero-fills the frozen roster.'},
]

PLAYER_COMPARABILITY = {
    'passing': ('approximate', 'historical passer player-games also include dropback-only scrambles; the boxscore summary does not identify those per-player passing opportunities.'),
    'rushing': ('comparable', 'historical rusher identities are complete; historical rushing-yard player-games with missing yards are excluded and coverage is reported.'),
    'receiving': ('approximate', 'historical receiver IDs are missing on some pass attempts; coverage is reported in the source table.'),
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path):
    with Path(path).open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def _verified_reference(reference_dir):
    reference_dir = Path(reference_dir)
    manifest_path = reference_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema') != REFERENCE_SCHEMA:
        raise ValueError(f'unsupported observed reference schema: {manifest.get("schema")}')
    hashes = {'manifest.json': _sha256(manifest_path)}
    table_hashes = manifest.get('table_sha256') or {}
    required = {'game_distribution.csv', 'player_stat_distribution.csv', 'player_stat_coverage.csv'}
    if not required <= table_hashes.keys():
        raise ValueError(f'observed reference is missing required table hashes: {sorted(required - table_hashes.keys())}')
    for name, expected in sorted(table_hashes.items()):
        path = reference_dir / name
        if not path.is_file():
            raise ValueError(f'observed reference table is missing: {name}')
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f'observed reference hash mismatch for {name}: expected {expected}, got {actual}')
        hashes[name] = actual
    return manifest, hashes


def _verified_joint_reference(reference_dir, simulation_season):
    reference_dir = Path(reference_dir)
    manifest_path = reference_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema') != JOINT_REFERENCE_SCHEMA:
        raise ValueError(f'unsupported joint observed reference schema: {manifest.get("schema")}')
    window = manifest.get('window') or {}
    if int(window.get('season_max', 0)) >= int(simulation_season):
        raise ValueError(f'joint historical reference is not cutoff-eligible: max season {window.get("season_max")} '
                         f'must be before simulation season {simulation_season}')
    table_hashes = manifest.get('table_sha256') or {}
    required = {'joint_distribution.csv', 'situational_action_distribution.csv'}
    if not required <= table_hashes.keys():
        raise ValueError(f'joint reference is missing table hashes: {sorted(required - table_hashes.keys())}')
    hashes = {'manifest.json': _sha256(manifest_path)}
    for name, expected in sorted(table_hashes.items()):
        path = reference_dir / name
        if not path.is_file():
            raise ValueError(f'joint reference table is missing: {name}')
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f'joint reference hash mismatch for {name}: expected {expected}, got {actual}')
        hashes[name] = actual
    return manifest, hashes, _read_csv(reference_dir / 'joint_distribution.csv'), \
        _read_csv(reference_dir / 'situational_action_distribution.csv')


def _compact_seed_row(row):
    outcome = row.get('outcome') if isinstance(row.get('outcome'), dict) else {}
    box = outcome.get('boxscore')
    if box is None and row.get('schema') in BOX_SCHEMAS:
        box = row
    if not isinstance(box, dict):
        return {'seed': row['seed'], 'status': outcome.get('status', 'missing_boxscore'),
                'game_id': outcome.get('game_id'), 'boxscore': None, 'playcall': outcome.get('playcall') or {}}

    teams = []
    for team in box.get('teams', []):
        stats = team.get('stats') or {}
        compact_stats = {key: stats.get(key) for key in (
            'points', 'plays', 'pass_attempts', 'completions', 'rushing_yards', 'rush_attempts',
            'sacks_taken', 'touchdowns', 'offensive_touchdowns', 'targets', 'drives')}
        compact_stats['red_zone'] = stats.get('red_zone')
        teams.append({'home_away': team.get('home_away'), 'team': team.get('team'), 'stats': compact_stats})
    players = []
    for player in box.get('players', []):
        categories = player
        stats = {category: {field: int((categories.get(category) or {}).get(field, 0) or 0)
                            for field in fields}
                 for category, fields in (
                     ('passing', ('att', 'comp', 'yds', 'td', 'int', 'sacked')),
                     ('rushing', ('att', 'yds', 'td')),
                     ('receiving', ('tgt', 'rec', 'yds', 'td')))}
        players.append(stats)
    compact_box = {
        'schema': box.get('schema'), 'game_id': box.get('game_id'), 'seed': box.get('seed'),
        'status': box.get('status'), 'reconciliation': box.get('reconciliation') or {},
        'teams': teams, 'players': players,
    }
    return {'seed': row['seed'], 'status': box.get('status', outcome.get('status', 'unknown')),
            'game_id': box.get('game_id'), 'boxscore': compact_box,
            'playcall': outcome.get('playcall') or {}}


def _load_seed_ledgers(paths):
    latest = {}
    duplicates = 0
    file_hashes = {}
    headers = {}
    rows_read = 0
    for source in paths:
        path = Path(source)
        file_hashes[str(path)] = _sha256(path)
        with path.open(encoding='utf-8') as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f'{path}:{line_number}: invalid JSON: {exc}') from exc
                if isinstance(row, dict) and isinstance(row.get('header'), dict):
                    headers[str(path)] = row['header']
                    continue
                if not isinstance(row, dict):
                    continue
                seed = row.get('seed')
                if type(seed) is not int:
                    continue
                rows_read += 1
                if seed in latest:
                    duplicates += 1
                latest[seed] = _compact_seed_row(row)
    if not latest:
        raise ValueError('no seed outcome rows found in the supplied JSONL files')
    return latest, rows_read, duplicates, file_hashes, headers


def _numeric_histogram(rows, value_field='value', count_field='count'):
    histogram = Counter()
    denominators = set()
    for row in rows:
        value = row.get(value_field)
        if value in (None, '', 'NULL'):
            continue
        number = float(value)
        histogram[number] += int(row[count_field])
        denominator = row.get('denominator') or row.get('denominator_player_games')
        if denominator not in (None, ''):
            denominators.add(int(denominator))
    if len(denominators) > 1:
        raise ValueError(f'observed histogram has inconsistent denominators: {sorted(denominators)}')
    return histogram


def _weighted_stats(histogram):
    n = sum(histogram.values())
    if not n:
        return {'sample_count': 0, 'mean': None, 'standard_deviation': None, 'median': None,
                'probability_zero': None, 'unique_values': 0, 'quantiles': {}, 'histogram': {}}
    values = []
    for value, count in histogram.items():
        values.extend([value] * count)
    values.sort()

    def quantile(p):
        index = (len(values) - 1) * p
        low, high = math.floor(index), math.ceil(index)
        return values[low] + (values[high] - values[low]) * (index - low)

    mean = sum(value * count for value, count in histogram.items()) / n
    variance = sum(((value - mean) ** 2) * count for value, count in histogram.items()) / n
    return {'sample_count': n, 'mean': mean, 'standard_deviation': math.sqrt(variance),
            'median': quantile(.5), 'probability_zero': histogram.get(0.0, 0) / n,
            'unique_values': len(histogram),
            'quantiles': {f'p{int(p * 100)}': quantile(p) for p in (.05, .10, .25, .50, .75, .90, .95)},
            'histogram': {str(int(value) if value.is_integer() else value): count
                          for value, count in sorted(histogram.items())}}


def _distances(simulated, observed):
    sim_n, obs_n = sum(simulated.values()), sum(observed.values())
    if not sim_n or not obs_n:
        return {'total_variation_distance': None, 'wasserstein_1': None}
    support = sorted(set(simulated) | set(observed))
    tv = .5 * sum(abs(simulated.get(x, 0) / sim_n - observed.get(x, 0) / obs_n) for x in support)
    cdf_diff = 0.0
    wasserstein = 0.0
    for index, value in enumerate(support):
        cdf_diff += simulated.get(value, 0) / sim_n - observed.get(value, 0) / obs_n
        if index + 1 < len(support):
            wasserstein += abs(cdf_diff) * (support[index + 1] - value)
    return {'total_variation_distance': tv, 'wasserstein_1': wasserstein}


def _comparison(metric, sim_hist, obs_hist, *, comparability='comparable', definition=None):
    if not sum(obs_hist.values()):
        comparability = 'no_reference_sample'
    return {'metric': metric, 'classification': 'DISTRIBUTION_WARNING',
            'comparability': comparability, 'definition': definition,
            'simulated': _weighted_stats(sim_hist), 'observed': _weighted_stats(obs_hist),
            'difference': _distances(sim_hist, obs_hist)}


def _simulation_histograms(games):
    result = {name: Counter() for name in GAME_METRICS}
    player_values = {key: Counter() for key in PLAYER_METRICS}
    for game in games:
        box = game['boxscore']
        teams = box['teams']
        by_location = {team['home_away']: team['stats'] for team in teams}
        if not {'home', 'away'} <= by_location.keys():
            raise ValueError(f"seed {game['seed']} game {box['game_id']}: boxscore must contain home and away team lines")
        home, away = by_location['home'], by_location['away']
        total_pass = sum(int(team['pass_attempts'] or 0) for team in by_location.values())
        total_rush = sum(int(team['rush_attempts'] or 0) for team in by_location.values())
        total_scrimmage_plays = sum(int(team['plays'] or 0) for team in by_location.values())
        total_sacks = sum(int(team['sacks_taken'] or 0) for team in by_location.values())
        total_td = sum(int(team['touchdowns'] or 0) for team in by_location.values())
        total_drives = sum(int(team['drives'] or 0) for team in by_location.values())
        values = {
            'home_score': int(home['points'] or 0), 'away_score': int(away['points'] or 0),
            'total_points': int(home['points'] or 0) + int(away['points'] or 0),
            'home_margin': int(home['points'] or 0) - int(away['points'] or 0),
            'absolute_margin': abs(int(home['points'] or 0) - int(away['points'] or 0)),
            'pass_attempts_per_game': total_pass, 'rush_attempts_per_game': total_rush,
            'scrimmage_plays_per_game': total_scrimmage_plays,
            'qb_dropbacks_per_game': total_pass + total_sacks + int(game['playcall'].get('qb_scramble', 0) or 0),
            'touchdowns_per_game': total_td, 'nonnull_drive_groups_per_game': total_drives,
        }
        for metric, value in values.items():
            result[metric][float(value)] += 1
        for player in box['players']:
            role_active = {
                'passing': player['passing']['att'] + player['passing']['sacked'] > 0,
                'rushing': player['rushing']['att'] > 0,
                'receiving': player['receiving']['tgt'] > 0,
            }
            for (role, metric), (category, field) in PLAYER_METRICS.items():
                if role_active[role]:
                    player_values[(role, metric)][float(player[category][field])] += 1
    return result, player_values


def _joint_diagnostics(games):
    rows = []
    for game in games:
        by_location = {team['home_away']: team['stats'] for team in game['boxscore']['teams']}
        total_points = sum(int(team['points'] or 0) for team in by_location.values())
        total_pass = sum(int(team['pass_attempts'] or 0) for team in by_location.values())
        total_rush = sum(int(team['rush_attempts'] or 0) for team in by_location.values())
        total_touchdowns = sum(int(team['touchdowns'] or 0) for team in by_location.values())
        rows.append({'total_points': total_points, 'pass_attempts': total_pass,
                     'rush_attempts': total_rush, 'touchdowns': total_touchdowns})

    def correlation(left, right):
        if len(rows) < 2:
            return None
        xs, ys = [row[left] for row in rows], [row[right] for row in rows]
        x_mean, y_mean = sum(xs) / len(xs), sum(ys) / len(ys)
        x_var = sum((x - x_mean) ** 2 for x in xs)
        y_var = sum((y - y_mean) ** 2 for y in ys)
        if not x_var or not y_var:
            return None
        return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / math.sqrt(x_var * y_var)

    pairs = (('total_points', 'pass_attempts'), ('total_points', 'rush_attempts'),
             ('total_points', 'touchdowns'), ('pass_attempts', 'rush_attempts'))
    return {
        'classification': 'DISTRIBUTION_WARNING',
        'sample_count': len(rows),
        'historical_joint_comparison': 'pending',
        'pearson_correlations': {f'{left}_vs_{right}': correlation(left, right) for left, right in pairs},
        'note': 'Correlations and empirical joint distances are descriptive; no pass threshold is applied.',
    }


def _counted_joint_histograms(rows):
    histograms = {}
    denominators = Counter()
    for row in rows:
        pair_id = row.get('pair_id')
        if not pair_id:
            raise ValueError('joint reference row has no pair_id')
        count = int(row['count'])
        denominator = int(row['denominator'])
        if count <= 0 or denominator < count:
            raise ValueError(f'joint reference has invalid count/denominator for {pair_id}')
        key = (int(row['x_value']), int(row['y_value']))
        histograms.setdefault(pair_id, Counter())[key] += count
        denominators[pair_id] = denominator
    for pair_id, histogram in histograms.items():
        if sum(histogram.values()) != denominators[pair_id]:
            raise ValueError(f'joint reference counts do not reconcile for {pair_id}')
    return histograms


def _stat_value(stats, field):
    value = stats.get(field)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _joint_pair_values(game, sample_unit, x_metric, y_metric):
    teams = game['boxscore']['teams']
    if sample_unit == 'game':
        by_location = {team['home_away']: team['stats'] for team in teams}
        if not {'home', 'away'} <= by_location.keys():
            return []
        home, away = by_location['home'], by_location['away']
        metric_values = {}
        for field in ('points', 'pass_attempts', 'rush_attempts', 'offensive_touchdowns'):
            left, right = _stat_value(home, field), _stat_value(away, field)
            metric_values[field] = left + right if left is not None and right is not None else None
        sources = {'total_points': 'points', 'pass_attempts': 'pass_attempts',
                   'rush_attempts': 'rush_attempts', 'offensive_touchdowns': 'offensive_touchdowns'}
        values = {metric: metric_values[source] for metric, source in sources.items()}
        if values.get(x_metric) is None or values.get(y_metric) is None:
            return []
        return [(values[x_metric], values[y_metric])]
    if sample_unit != 'team_game':
        raise ValueError(f'unsupported joint sample unit: {sample_unit}')

    values = []
    for team in teams:
        stats = team['stats']
        red_zone = stats.get('red_zone')
        metrics = {
            'team_points': _stat_value(stats, 'points'),
            'team_plays': _stat_value(stats, 'plays'),
            'pass_attempts': _stat_value(stats, 'pass_attempts'),
            'offensive_touchdowns': _stat_value(stats, 'offensive_touchdowns'),
            'receiver_targets_with_id': _stat_value(stats, 'targets'),
        }
        for metric in ('red_zone_trips', 'red_zone_touchdowns', 'red_zone_field_goal_attempts',
                       'red_zone_field_goals_made'):
            raw = (red_zone or {}).get(metric) if isinstance(red_zone, dict) else None
            metrics[metric] = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
        x_value, y_value = metrics.get(x_metric), metrics.get(y_metric)
        if x_value is not None and y_value is not None:
            values.append((x_value, y_value))
    return values


def _simulated_joint_histograms(games, historical_rows):
    definitions = {}
    for row in historical_rows:
        definition = (row['sample_unit'], row['x_metric'], row['y_metric'])
        previous = definitions.setdefault(row['pair_id'], definition)
        if previous != definition:
            raise ValueError(f'joint reference has inconsistent metric definitions for {row["pair_id"]}')
    result = {pair_id: Counter() for pair_id in definitions}
    samples = Counter()
    for game in games:
        for pair_id, (unit, x_metric, y_metric) in definitions.items():
            for values in _joint_pair_values(game, unit, x_metric, y_metric) or []:
                result[pair_id][values] += 1
                samples[pair_id] += 1
    return result, samples, definitions


def _situational_action_counts(games):
    fields = ('team', 'quarter', 'down', 'distance_bucket', 'field_bucket', 'score_bucket', 'clock_bucket')
    counts = Counter()
    malformed = 0
    for game in games:
        rows = game.get('playcall', {}).get('situational_decision_counts') or []
        for row in rows:
            if any(row.get(field) is None for field in (*fields, 'action', 'count')):
                malformed += 1
                continue
            count = int(row['count'])
            if count <= 0:
                malformed += 1
                continue
            key = tuple(str(row[field]) for field in fields) + (str(row['action']),)
            counts[key] += count
    return counts, malformed


def _action_distribution_comparison(sim_counts, observed_rows, *, fourth_down=False):
    fields = ('team', 'quarter', 'down', 'distance_bucket', 'field_bucket', 'score_bucket', 'clock_bucket')
    observed = Counter()
    for row in observed_rows:
        if fourth_down and str(row['down']) != '4':
            continue
        key = tuple(str(row[field]) for field in fields) + (str(row['action']),)
        observed[key] += int(row['count'])
    simulated = Counter({key: value for key, value in sim_counts.items()
                         if not fourth_down or key[2] == '4'})
    sim_groups, obs_groups = defaultdict(Counter), defaultdict(Counter)
    for key, count in simulated.items():
        sim_groups[key[:-1]][key[-1]] += count
    for key, count in observed.items():
        obs_groups[key[:-1]][key[-1]] += count
    shared = sorted(sim_groups.keys() & obs_groups.keys())
    weighted_tvd = 0.0
    sim_n = obs_n = 0
    context_rows = []
    for context in shared:
        sim, obs = sim_groups[context], obs_groups[context]
        sim_total, obs_total = sum(sim.values()), sum(obs.values())
        if not sim_total or not obs_total:
            continue
        support = set(sim) | set(obs)
        tvd = .5 * sum(abs(sim.get(action, 0) / sim_total - obs.get(action, 0) / obs_total)
                       for action in support)
        weighted_tvd += tvd * sim_total
        sim_n += sim_total
        obs_n += obs_total
        context_rows.append({'context': dict(zip(fields, context)), 'simulated_decisions': sim_total,
                             'historical_decisions': obs_total, 'total_variation_distance': tvd})
    return {
        'classification': 'DISTRIBUTION_WARNING',
        'comparability': 'comparable' if shared else 'no_shared_situation_cells',
        'fourth_down_only': fourth_down,
        'contexts_compared': len(context_rows),
        'simulated_decisions_in_shared_contexts': sim_n,
        'historical_decisions_in_shared_contexts': obs_n,
        'simulated_only_contexts': len(sim_groups.keys() - obs_groups.keys()),
        'historical_only_contexts': len(obs_groups.keys() - sim_groups.keys()),
        'weighted_mean_context_total_variation_distance': weighted_tvd / sim_n if sim_n else None,
        'context_comparisons': context_rows,
    }


def _historical_joint_diagnostics(games, joint_rows, situation_rows):
    simulated, simulated_samples, definitions = _simulated_joint_histograms(games, joint_rows)
    observed = _counted_joint_histograms(joint_rows)
    comparisons = []
    for pair_id in sorted(set(definitions) | set(observed) | set(simulated)):
        sim_hist, obs_hist = simulated.get(pair_id, Counter()), observed.get(pair_id, Counter())
        sim_n, obs_n = sum(sim_hist.values()), sum(obs_hist.values())
        support = set(sim_hist) | set(obs_hist)
        tvd = (.5 * sum(abs(sim_hist.get(key, 0) / sim_n - obs_hist.get(key, 0) / obs_n)
                         for key in support) if sim_n and obs_n else None)
        unit, x_metric, y_metric = definitions.get(pair_id, (None, None, None))
        comparisons.append({
            'pair_id': pair_id, 'sample_unit': unit, 'x_metric': x_metric, 'y_metric': y_metric,
            'comparability': 'comparable' if sim_n and obs_n else 'no_samples',
            'simulated_sample_count': sim_n, 'historical_sample_count': obs_n,
            'total_variation_distance': tvd,
            'simulated_histogram': [{'x_value': x, 'y_value': y, 'count': count}
                                    for (x, y), count in sorted(sim_hist.items())],
            'historical_histogram': [{'x_value': x, 'y_value': y, 'count': count}
                                     for (x, y), count in sorted(obs_hist.items())],
        })
    sim_situations, malformed = _situational_action_counts(games)
    situation_comparison = _action_distribution_comparison(sim_situations, situation_rows)
    fourth_down_comparison = _action_distribution_comparison(sim_situations, situation_rows, fourth_down=True)
    diagnostics = _joint_diagnostics(games)
    diagnostics['historical_joint_comparison'] = 'compared with the hash-pinned, cutoff-eligible joint reference'
    diagnostics['historical_joint_distributions'] = comparisons
    diagnostics['situational_action_comparison'] = situation_comparison
    diagnostics['fourth_down_action_comparison'] = fourth_down_comparison
    diagnostics['malformed_simulated_situation_rows'] = malformed
    return diagnostics


def evaluate(seed_ledger_paths, *, reference_dir=DEFAULT_REFERENCE,
             joint_reference_dir=DEFAULT_JOINT_REFERENCE, simulation_season, out_path=None):
    manifest, reference_hashes = _verified_reference(reference_dir)
    window = manifest.get('window') or {}
    if int(window.get('season_max', 0)) >= int(simulation_season):
        raise ValueError(f'historical reference is not cutoff-eligible: max season {window.get("season_max")} '
                         f'must be before simulation season {simulation_season}')
    joint_manifest, joint_hashes, joint_rows, situation_rows = _verified_joint_reference(
        joint_reference_dir, simulation_season)
    latest, rows_read, duplicates, ledger_hashes, ledger_headers = _load_seed_ledgers(seed_ledger_paths)
    game_ids = sorted({row.get('game_id') for row in latest.values() if row.get('game_id')}
                      | {header.get('game_id') for header in ledger_headers.values() if header.get('game_id')})
    implied_seasons = {int(game_id.split('_', 1)[0]) for game_id in game_ids
                       if game_id.split('_', 1)[0].isdigit()}
    if implied_seasons and implied_seasons != {int(simulation_season)}:
        raise ValueError(f'--simulation-season {simulation_season} disagrees with seed ledger game IDs '
                         f'for seasons {sorted(implied_seasons)}')
    status_counts = Counter(row['status'] for row in latest.values())
    valid_games = []
    missing_boxscores = 0
    for seed, row in sorted(latest.items()):
        box = row.get('boxscore')
        if box is None:
            missing_boxscores += 1
            continue
        if box.get('status') != 'valid_complete':
            continue
        if (box.get('reconciliation') or {}).get('status') != 'passed':
            raise ValueError(f"STAT_ACCOUNTING: game_id={box.get('game_id')} seed={seed}: "
                             f"valid game has reconciliation={(box.get('reconciliation') or {}).get('status')}")
        valid_games.append(row)

    game_hist, player_hist = _simulation_histograms(valid_games)
    observed_game_rows = _read_csv(Path(reference_dir) / 'game_distribution.csv')
    observed_player_rows = _read_csv(Path(reference_dir) / 'player_stat_distribution.csv')
    comparisons = []
    for metric, (observed_metric, definition) in GAME_METRICS.items():
        sim_hist = game_hist[metric]
        obs_hist = _numeric_histogram([row for row in observed_game_rows if row['metric'] == observed_metric])
        comparisons.append(_comparison(metric, sim_hist, obs_hist, definition=definition))
    for key, fields in PLAYER_METRICS.items():
        role, metric = key
        obs_hist = _numeric_histogram([row for row in observed_player_rows
                                       if row['role'] == role and row['metric'] == metric],
                                      count_field='count')
        comparability, note = PLAYER_COMPARABILITY[role]
        comparisons.append(_comparison(f'player.{role}.{metric}', player_hist[key], obs_hist,
                                       comparability=comparability,
                                       definition=f'role player-game distribution; only player-games with an observed opportunity are included. {note}'))

    report = {
        'schema': SCHEMA,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'classification': 'DISTRIBUTION_WARNING',
        'threshold_policy': 'No pass/fail thresholds are applied; differences are descriptive warnings.',
        'simulation': {
            'season': int(simulation_season), 'game_ids': game_ids, 'ledger_rows': rows_read,
            'unique_seeds': len(latest), 'duplicate_or_retry_rows': duplicates,
            'valid_complete_games': len(valid_games), 'missing_boxscore_rows': missing_boxscores,
            'latest_seed_status_counts': dict(sorted(status_counts.items())),
            'seed_ledger_sha256': ledger_hashes,
            'seed_ledger_headers': [
                {'path': path, 'sha256': hashlib.sha256(json.dumps(header, sort_keys=True,
                                                                   separators=(',', ':')).encode()).hexdigest(),
                 'metadata': {key: header.get(key) for key in (
                     'game_id', 'as_of', 'source_snapshot_sha256', 'observed_reference_sha256',
                     'source_commit', 'producer_file_sha256', 'playcall_artifact_sha256',
                     'seed_start', 'boxscore_export', 'playcall_enabled_layers',
                     'playcall_source_cutoff', 'playcall_optional_input_sha256')},
                 'profile': {key: (header.get('slc_profile') or {}).get(key)
                             for key in ('model_id', 'configuration_hash', 'evaluation_class')}}
                for path, header in sorted(ledger_headers.items())],
        },
        'reference': {
            'schema': manifest['schema'], 'window': window,
            'source_measurements': manifest.get('source_measurements'),
            'source_cutoff_eligible': True, 'sha256': reference_hashes,
            'source_coverage': _read_csv(Path(reference_dir) / 'player_stat_coverage.csv'),
            'joint': {
                'schema': joint_manifest['schema'], 'window': joint_manifest.get('window'),
                'source_measurements': joint_manifest.get('source_measurements'),
                'source_cutoff_eligible': True, 'sha256': joint_hashes,
            },
        },
        'comparisons': comparisons,
        'joint_diagnostics': _historical_joint_diagnostics(valid_games, joint_rows, situation_rows),
        'unsupported_or_noncomparable': UNSUPPORTED,
    }
    if out_path is not None:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-ledger', type=Path, action='append', required=True,
                        help='append-only worker-*.seeds.jsonl; pass once per shard')
    parser.add_argument('--simulation-season', type=int, required=True)
    parser.add_argument('--reference-dir', type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument('--out', type=Path, required=True, help='new report JSON path; existing files are refused')
    args = parser.parse_args()
    report = evaluate(args.seed_ledger, reference_dir=args.reference_dir,
                      simulation_season=args.simulation_season, out_path=args.out)
    sim = report['simulation']
    print(f"wrote {args.out}: {sim['valid_complete_games']}/{sim['unique_seeds']} valid complete games; "
          f"{len(report['comparisons'])} warning comparisons; "
          f"reference seasons {report['reference']['window']['season_min']}-"
          f"{report['reference']['window']['season_max']}")


if __name__ == '__main__':
    main()
