#!/usr/bin/env python3
"""Offline V1.6 yardage/chain and fourth-down policy audits; never simulates games or writes to the database."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics

import e0_single_play as e0

MIN_EXACT_DISTANCE_SUPPORT = 50
YARDAGE_SHRINKAGE = 25.0
POLICY_SHRINKAGE = 30.0
EVENTS = ('run', 'pass_complete', 'pass_incomplete', 'interception', 'fumble_lost', 'sack')
ACTIONS = ('go', 'punt', 'field_goal')


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _bucket_distance(value):
    return '1-2' if value <= 2 else '3-5' if value <= 5 else '6-9' if value <= 9 else '10+'


def _event(row):
    if row['sack'] == 1:
        return 'sack'
    if row['interception'] == 1:
        return 'interception'
    if row['fumble_lost'] == 1:
        return 'fumble_lost'
    if row['play_type'] == 'run':
        return 'run'
    if row['play_type'] == 'pass' and row['complete_pass'] == 1:
        return 'pass_complete'
    if row['play_type'] == 'pass' and row['complete_pass'] == 0:
        return 'pass_incomplete'
    return None


def _crps_scorer(samples, weights=None):
    if not samples:
        return None
    pairs = sorted(zip(samples, weights or [1.0] * len(samples)))
    weight_total = sum(weight for _, weight in pairs)
    if weight_total <= 0:
        return None
    values = []
    cumulative_weights = []
    cumulative_value_weights = []
    left_weight = 0.0
    left_value_weight = 0.0
    pair_distance = 0.0
    for sample, raw_weight in pairs:
        weight = raw_weight / weight_total
        pair_distance += weight * (sample * left_weight - left_value_weight)
        left_weight += weight
        left_value_weight += weight * sample
        values.append(sample)
        cumulative_weights.append(left_weight)
        cumulative_value_weights.append(left_value_weight)

    def score(value):
        index = bisect_left(values, value)
        left_weight = cumulative_weights[index - 1] if index else 0.0
        left_value = cumulative_value_weights[index - 1] if index else 0.0
        right_weight = 1.0 - left_weight
        right_value = left_value_weight - left_value
        absolute_error = value * left_weight - left_value + right_value - value * right_weight
        return absolute_error - pair_distance

    return score


def _bootstrap_game_delta(by_game, reps=2000, seed=20261111):
    games = sorted(by_game)
    if not games:
        return None
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        picked = [games[rng.randrange(len(games))] for _ in games]
        n = sum(by_game[game][0] for game in picked)
        draws.append(sum(by_game[game][1] for game in picked) / max(1, n))
    draws.sort()
    return [draws[int(.025 * (reps - 1))], draws[int(.975 * (reps - 1))]]


def _load(database, first_season, test_season):
    columns = ('game_id,play_id,season,week,qtr,down,ydstogo,yardline_100,play_type,yards_gained,'
               'touchdown,sack,complete_pass,interception,fumble_lost,qb_scramble,penalty,posteam,game_seconds_remaining')
    con = sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True, timeout=30)
    try:
        rows = con.execute(
            f"SELECT {columns} FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week BETWEEN 1 AND 18 "
            "AND qtr BETWEEN 1 AND 4 AND down BETWEEN 1 AND 4 AND ydstogo > 0 "
            "AND yardline_100 BETWEEN 1 AND 99 AND penalty=0 "
            "AND play_type IN ('run','pass','punt','field_goal')",
            (first_season, test_season)).fetchall()
        eligibility = con.execute(
            "SELECT season,penalty,count(*) FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week BETWEEN 1 AND 18 "
            "AND qtr BETWEEN 1 AND 4 AND down BETWEEN 1 AND 4 AND play_type IN ('run','pass','punt','field_goal') "
            "GROUP BY season,penalty ORDER BY season,penalty", (first_season, test_season)).fetchall()
    finally:
        con.close()
    names = columns.split(',')
    return [dict(zip(names, row)) for row in rows], eligibility


def _yardage_audit(rows, train_seasons, test_season):
    base_yards = defaultdict(list)
    exact_yards = defaultdict(list)
    base_success = defaultdict(Counter)
    exact_success = defaultdict(Counter)
    test = []
    for row in rows:
        if row['play_type'] not in ('run', 'pass') or row['yards_gained'] is None:
            continue
        event = _event(row)
        if event not in EVENTS:
            continue
        intent = 'run' if row['play_type'] == 'run' else 'dropback'
        down = int(row['down'])
        togo = int(row['ydstogo'])
        key = (down, e0.ydstogo_bucket(togo), e0.yardline_bucket(int(row['yardline_100'])), event)
        chain_key = key[:3] + (intent,)
        if int(row['season']) in train_seasons:
            base_yards[key].append(int(row['yards_gained']))
            exact_yards[key + (togo,)].append(int(row['yards_gained']))
            success = int(int(row['yards_gained']) >= togo or row['touchdown'] == 1)
            base_success[chain_key].update({'n': 1, 'success': success})
            exact_success[chain_key + (togo,)].update({'n': 1, 'success': success})
        elif int(row['season']) == test_season:
            test.append((row, event, intent, key, chain_key, togo))

    score_rows = []
    base_crps = {}
    exact_crps = {}
    support_used = Counter()
    for row, event, intent, key, chain_key, togo in test:
        baseline = base_yards.get(key, ())
        if len(baseline) < 30:
            continue
        specific = exact_yards.get(key + (togo,), ())
        specific_used = len(specific) >= MIN_EXACT_DISTANCE_SUPPORT
        observed = int(row['yards_gained'])
        if key not in base_crps:
            base_crps[key] = _crps_scorer(baseline)
        base_crps_value = base_crps[key](observed)
        exact_key = key + (togo,)
        if specific_used:
            if exact_key not in exact_crps:
                alpha = len(specific) / (len(specific) + YARDAGE_SHRINKAGE)
                values = list(baseline) + list(specific)
                weights = ([(1.0 - alpha) / len(baseline)] * len(baseline)
                           + [alpha / len(specific)] * len(specific))
                exact_crps[exact_key] = _crps_scorer(values, weights)
            exact_crps_value = exact_crps[exact_key](observed)
            support_used['exact_distance'] += 1
        else:
            exact_crps_value = base_crps_value
            support_used['bucket_fallback'] += 1

        base_chain = base_success.get(chain_key)
        if not base_chain or base_chain['n'] == 0:
            continue
        p_base = base_chain['success'] / base_chain['n']
        exact_chain = exact_success.get(chain_key + (togo,), Counter())
        if exact_chain['n'] >= MIN_EXACT_DISTANCE_SUPPORT:
            alpha = exact_chain['n'] / (exact_chain['n'] + YARDAGE_SHRINKAGE)
            p_exact = (1 - alpha) * p_base + alpha * exact_chain['success'] / exact_chain['n']
        else:
            p_exact = p_base
        observed_success = int(observed >= togo or row['touchdown'] == 1)
        score_rows.append({'game_id': row['game_id'], 'down': int(row['down']),
                           'distance': _bucket_distance(togo), 'intent': intent,
                           'base_crps': base_crps_value, 'exact_crps': exact_crps_value,
                           'base_brier': (p_base - observed_success) ** 2,
                           'exact_brier': (p_exact - observed_success) ** 2,
                           'exact_support': len(specific), 'observed_success': observed_success})

    def summarize(selected):
        if not selected:
            return {'n': 0}
        return {'n': len(selected), 'games': len({row['game_id'] for row in selected}),
                'baseline_crps': statistics.mean(row['base_crps'] for row in selected),
                'exact_distance_crps': statistics.mean(row['exact_crps'] for row in selected),
                'baseline_line_to_gain_brier': statistics.mean(row['base_brier'] for row in selected),
                'exact_distance_line_to_gain_brier': statistics.mean(row['exact_brier'] for row in selected),
                'baseline_success_rate': statistics.mean(row['observed_success'] for row in selected),
                'exact_support_coverage': sum(row['exact_support'] >= MIN_EXACT_DISTANCE_SUPPORT
                                              for row in selected) / len(selected)}

    by_game = defaultdict(lambda: [0, 0.0])
    for row in score_rows:
        by_game[row['game_id']][0] += 1
        by_game[row['game_id']][1] += row['exact_brier'] - row['base_brier']
    def paired(selected):
        ids = {row['game_id'] for row in selected}
        return _bootstrap_game_delta({game: by_game[game] for game in ids}) if ids else None
    return {
        'train_seasons': sorted(train_seasons), 'test_season': test_season,
        'event_yardage': summarize(score_rows),
        'line_to_gain': summarize(score_rows),
        'line_to_gain_brier_delta_exact_minus_bucket_game_clustered_95ci': paired(score_rows),
        'third_down': summarize([row for row in score_rows if row['down'] == 3]),
        'third_down_by_distance': {distance: summarize([row for row in score_rows
                                                       if row['down'] == 3 and row['distance'] == distance])
                                   for distance in ('1-2', '3-5', '6-9', '10+')},
        'support': dict(support_used),
        'candidate': {'minimum_exact_distance_training_rows': MIN_EXACT_DISTANCE_SUPPORT,
                      'shrinkage_k': YARDAGE_SHRINKAGE,
                      'fallback': 'Use bucket distribution when exact-distance support is below threshold.'},
        'limitations': ['Observed-context, no-draw comparison; it does not reproduce generated full-game state frequencies.',
                        'Data are known-clean PBP rows only; this does not model penalties.'],
    }


def _fourth_down_audit(rows, train_seasons, test_season):
    league = defaultdict(Counter)
    teams = defaultdict(Counter)
    test = []
    for row in rows:
        if int(row['down']) != 4:
            continue
        if row['play_type'] in ('run', 'pass'):
            action = 'go'
        elif row['play_type'] == 'punt':
            action = 'punt'
        elif row['play_type'] == 'field_goal':
            action = 'field_goal'
        else:
            continue
        context = (_bucket_distance(int(row['ydstogo'])), e0.yardline_bucket(int(row['yardline_100'])))
        if int(row['season']) in train_seasons:
            league[context][action] += 1
            teams[(context, row['posteam'])][action] += 1
        elif int(row['season']) == test_season:
            test.append((row, context, action))
    scored = []
    for row, context, observed in test:
        cell_counts = league[context]
        cell_n = sum(cell_counts.values())
        if cell_n < 30:
            continue
        probs = {action: (cell_counts[action] + 1.0) / (cell_n + len(ACTIONS)) for action in ACTIONS}
        own = teams[(context, row['posteam'])]
        own_n = sum(own.values())
        own_probs = {action: (own[action] + POLICY_SHRINKAGE * probs[action]) / (own_n + POLICY_SHRINKAGE)
                     for action in ACTIONS}
        scored.append({'game_id': row['game_id'], 'actual': observed, 'league': probs, 'team': own_probs,
                       'team_support': own_n})
    metric_totals = {'league': {'ll': 0.0, 'brier': 0.0}, 'team': {'ll': 0.0, 'brier': 0.0}}
    game_deltas = defaultdict(lambda: [0, 0.0])
    for row in scored:
        for model in ('league', 'team'):
            prob = row[model]
            metric_totals[model]['ll'] -= __import__('math').log(max(prob[row['actual']], 1e-15))
            metric_totals[model]['brier'] += sum((prob[action] - (action == row['actual'])) ** 2 for action in ACTIONS)
        game_deltas[row['game_id']][0] += 1
        game_deltas[row['game_id']][1] += (
            -__import__('math').log(max(row['team'][row['actual']], 1e-15))
            + __import__('math').log(max(row['league'][row['actual']], 1e-15)))
    n = len(scored)
    return {
        'train_seasons': sorted(train_seasons), 'test_season': test_season,
        'test_fourth_downs': n, 'games': len(game_deltas),
        'league_situation_cell': {metric: value / max(n, 1) for metric, value in metric_totals['league'].items()},
        'team_specific_shrunk': {metric: value / max(n, 1) for metric, value in metric_totals['team'].items()},
        'team_minus_league_log_loss_game_clustered_95ci': _bootstrap_game_delta(game_deltas),
        'team_support': {'no_team_history': sum(row['team_support'] == 0 for row in scored),
                         'support_lt_20': sum(row['team_support'] < 20 for row in scored),
                         'support_ge_20': sum(row['team_support'] >= 20 for row in scored)},
        'policy': {'actions': list(ACTIONS), 'context': ['yards_to_go_bin', 'yardline_bin'],
                   'team_prior_shrinkage_k': POLICY_SHRINKAGE,
                   'penalty_policy': 'penalty=0 only'},
        'interpretation': 'This tests conditional choice on observed fourth-down situations; it does not test how often SLC generates each situation.',
    }


def evaluate(database, first_season=2022, test_season=2025):
    rows, eligibility = _load(database, first_season, test_season)
    train = set(range(first_season, test_season))
    status = defaultdict(Counter)
    for season, penalty, count in eligibility:
        name = 'unknown' if penalty is None else 'known_clean' if penalty == 0 else 'penalty_tagged' if penalty == 1 else 'other'
        status[str(season)][name] += count
    path = Path(database)
    stat = path.stat()
    return {
        'schema': 'slc-v1.6-mechanism-gate-audit-1',
        'status': 'offline_historical_development_audit',
        'code_sha256': {'evaluator': _sha256(Path(__file__)),
                        'yardage_bucket_source': _sha256(Path(__file__).with_name('e0_single_play.py'))},
        'input': {'database_path': str(path.resolve()), 'size_bytes': stat.st_size,
                  'mtime_ns': stat.st_mtime_ns, 'database_sha256': _sha256(path),
                  'eligibility_by_season': {season: dict(counts) for season, counts in sorted(status.items())},
                  'query_uses': 'read-only SQLite URI; only penalty=0 rows enter either analysis'},
        'yardage_and_chain_advancement': _yardage_audit(rows, train, test_season),
        'fourth_down_policy': _fourth_down_audit(rows, train, test_season),
        'limitations': ['This is a single retrospective holdout and is development-exposed.',
                        'Model candidate settings are fixed in source; do not tune them against the 2025 holdout.',
                        'A conditional-policy score cannot identify generated fourth-down opportunity errors.'],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('/root/legendarypicks/backend/data/picks.dev.db'))
    parser.add_argument('--first-season', type=int, default=2022)
    parser.add_argument('--test-season', type=int, default=2025)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f'refusing to overwrite existing output: {args.output}')
    result = evaluate(args.database, args.first_season, args.test_season)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'output': str(args.output),
                      'yardage': result['yardage_and_chain_advancement']['event_yardage'],
                      'fourth_down': result['fourth_down_policy']}, sort_keys=True))


if __name__ == '__main__':
    main()
