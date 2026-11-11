#!/usr/bin/env python3
"""Grade paired V1.5 outcome-multiplier ablations from saved worker artifacts."""
from __future__ import annotations

import argparse
import gzip
import json
import random
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

import run_paired_seed_ablation_matrix as matrix
import score_season_batches as season_score


LAYER = 'team_offense_defense_outcomes'
ARMS = {'control': 'control', 'ablation': f'without-{LAYER}'}


def _read_json_lines(path: Path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        for line in handle:
            yield json.loads(line)


def _interval(values_by_game: dict[str, list[float]], *, seed: int = 20261111, reps: int = 10000):
    game_values = [sum(values) / len(values) for values in values_by_game.values() if values]
    if not game_values:
        return None
    rng = random.Random(seed)
    means = sorted(sum(game_values[rng.randrange(len(game_values))] for _ in game_values) / len(game_values)
                   for _ in range(reps))
    return [means[int(.025 * reps)], means[int(.975 * reps) - 1]]


def _distribution(values: list[float]):
    return matrix._distribution(values)


def _actual_player_stats(db: Path, game_ids: list[str]):
    if not game_ids:
        return {}, {}
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    try:
        marks = ','.join('?' for _ in game_ids)
        rows = con.execute(
            f"SELECT game_id, team, source_player_key, stats FROM player_game_logs "
            f"WHERE league='nfl' AND season=2026 AND game_type='REG' AND game_id IN ({marks})",
            game_ids).fetchall()
    finally:
        con.close()
    player, team = {}, defaultdict(lambda: defaultdict(float))
    for game, club, player_id, raw in rows:
        stats = json.loads(raw or '{}')
        key = (game, club, str(player_id))
        player[key] = stats
        team[(game, club)]['sacks_taken'] += float(stats.get('sacks_taken') or 0)
        team[(game, club)]['turnovers'] += float(stats.get('intc') or 0) + float(stats.get('fum_lost') or 0)
    return player, team


def grade(run_root: Path, db: Path, *, allow_partial: bool = False):
    progress = json.loads((run_root / 'progress.json').read_text(encoding='utf-8'))
    completed = progress.get('completed', [])
    expected = int(progress.get('cohort_count', 121))
    if not allow_partial and len(completed) != expected:
        raise ValueError(f'cohort is incomplete: {len(completed)}/{expected} games')
    if progress.get('failed'):
        raise ValueError(f'cohort has failed games: {len(progress["failed"])}')
    game_ids = sorted(row['game'] for row in completed)
    if len(game_ids) != len(set(game_ids)):
        raise ValueError('duplicate game IDs in progress manifest')
    for row in completed:
        if (row.get('seed_count') != 20 or row.get('error_seeds')
                or not row.get('valid_for_complete_game_comparison')):
            raise ValueError(f'{row["game"]}: paired run is incomplete or has seed errors')

    with tempfile.TemporaryDirectory(prefix='slc-v15-ablation-score-') as tmp:
        score_root = Path(tmp)
        arm_dirs = {arm: score_root / arm for arm in ARMS}
        for path in arm_dirs.values():
            path.mkdir()
        for game in game_ids:
            for arm, dirname in ARMS.items():
                source = run_root / game / dirname / 'worker-01.json.gz'
                if not source.is_file():
                    source = run_root / game / dirname / 'worker-01.json'
                (arm_dirs[arm] / f'{game}.json.gz').symlink_to(source)
        season = season_score.score(arm_dirs['control'], arm_dirs['ablation'], db,
                                    list(range(1, 9)), season=2026, seed_rule='complete_game')

    actual_players, actual_team = _actual_player_stats(db, game_ids)
    actual_results, _unscored = season_score.load_results(db, 2026, list(range(1, 9)))
    player_rows = []
    player_errors = defaultdict(lambda: {'control': [], 'ablation': []})
    player_missing = defaultdict(int)
    team_values = defaultdict(lambda: {'control': [], 'ablation': []})
    team_errors = defaultdict(lambda: {'control': [], 'ablation': []})
    team_game_rows = []
    valid_pairs = 0
    for game in game_ids:
        report_path = run_root / game / f'without-{LAYER}.comparison.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('valid_for_complete_game_comparison') is not True:
            raise ValueError(f'{game}: comparison report is not valid for full-game grading')
        valid_pairs += int(report['paired_boxscore_summaries']['complete_boxscore_pair_count'])

        boxes = {}
        for arm, dirname in ARMS.items():
            box_path = run_root / game / dirname / 'worker-01.boxscores.jsonl.gz'
            if not box_path.is_file():
                box_path = run_root / game / dirname / 'worker-01.boxscores.jsonl'
            rows = {}
            for box in _read_json_lines(box_path):
                if box.get('type') == 'game':
                    rows[box['seed']] = box
            boxes[arm] = rows
        common_seeds = sorted(boxes['control'].keys() & boxes['ablation'].keys())
        if len(common_seeds) != 20:
            raise ValueError(f'{game}: expected 20 paired box-score seeds, found {len(common_seeds)}')
        outcome = actual_results.get(game)
        for seed in common_seeds:
            left, right = boxes['control'][seed], boxes['ablation'][seed]
            left_teams = {(r['team'], r['home_away']): r for r in left.get('teams', [])}
            right_teams = {(r['team'], r['home_away']): r for r in right.get('teams', [])}
            if left_teams.keys() != right_teams.keys():
                raise ValueError(f'{game}/{seed}: paired team identities differ')
        if outcome is None:
            continue
        for key in sorted(left_teams):
            club, side = key
            actual = {
                'points': outcome['home_points'] if side == 'home' else outcome['away_points'],
                'sacks_taken': actual_team[(game, club)].get('sacks_taken'),
                'turnovers': actual_team[(game, club)].get('turnovers'),
            }
            metric_predictions = defaultdict(lambda: {'control': [], 'ablation': []})
            for seed in common_seeds:
                for arm in ('control', 'ablation'):
                    row = next(r for r in boxes[arm][seed]['teams']
                               if r.get('team') == club and r.get('home_away') == side)
                    stats = row.get('stats') or {}
                    for metric in actual:
                        value = stats.get(metric)
                        if type(value) in (int, float):
                            metric_predictions[metric][arm].append(float(value))
            for metric, observed in actual.items():
                if observed is None:
                    continue
                pred = metric_predictions[metric]
                row = {'game_id': game, 'team': club, 'home_away': side, 'metric': metric,
                       'observed': observed, 'control': _distribution(pred['control']),
                       'ablation': _distribution(pred['ablation'])}
                team_game_rows.append(row)
                for arm in ('control', 'ablation'):
                    if pred[arm]:
                        team_values[metric][arm].append(sum(pred[arm]) / len(pred[arm]))
                        team_errors[metric][arm].append((game, abs(sum(pred[arm]) / len(pred[arm]) - observed)))

        report_players = report['paired_boxscore_summaries']['player_metrics']
        for row in report_players:
            metric = row.get('metric')
            if metric not in ('rush_attempts', 'targets'):
                continue
            player_id, club = str(row.get('player_id')), row.get('team')
            observed = actual_players.get((game, club, player_id), {}).get(
                'carries' if metric == 'rush_attempts' else 'targets')
            if not isinstance(observed, (int, float)) or observed <= 0:
                continue
            control = row['control'].get('mean')
            ablation = row['ablation'].get('mean')
            if control is None or ablation is None:
                player_missing[metric] += 1
                continue
            item = {'game_id': game, 'team': club, 'player_id': player_id,
                    'player_name': row.get('player_name'), 'metric': metric,
                    'observed_positive_touches': observed, 'control_mean': control,
                    'ablation_mean': ablation, 'control_abs_error': abs(control - observed),
                    'ablation_abs_error': abs(ablation - observed)}
            player_rows.append(item)
            player_errors[metric]['control'].append((game, item['control_abs_error']))
            player_errors[metric]['ablation'].append((game, item['ablation_abs_error']))

    summaries = {}
    for metric, arms in team_errors.items():
        per_game = {}
        for arm in ('control', 'ablation'):
            for game, error in arms[arm]:
                per_game.setdefault((game, arm), []).append(error)
        diffs = defaultdict(list)
        for (game, arm), errors in per_game.items():
            diffs[game].append((arm, sum(errors) / len(errors)))
        game_diffs = {
            game: dict(values)['ablation'] - dict(values)['control']
            for game, values in diffs.items() if len(values) == 2
        }
        summaries[metric] = {
            'team_game_count': len(arms['control']),
            'observed_mean': sum(r['observed'] for r in team_game_rows if r['metric'] == metric) /
                             max(1, sum(r['metric'] == metric for r in team_game_rows)),
            'control_predicted_mean': sum(team_values[metric]['control']) / max(1, len(team_values[metric]['control'])),
            'ablation_predicted_mean': sum(team_values[metric]['ablation']) / max(1, len(team_values[metric]['ablation'])),
            'control_mae': sum(e for _, e in arms['control']) / max(1, len(arms['control'])),
            'ablation_mae': sum(e for _, e in arms['ablation']) / max(1, len(arms['ablation'])),
            'paired_mae_difference_ablation_minus_control':
                sum(game_diffs.values()) / max(1, len(game_diffs)),
            'paired_mae_difference_95ci_game_clustered': _interval(
                {g: [v] for g, v in game_diffs.items()}),
        }
    workload = {}
    for metric in ('rush_attempts', 'targets'):
        by_game = defaultdict(lambda: {'control': [], 'ablation': []})
        for arm in ('control', 'ablation'):
            for game, error in player_errors[metric][arm]:
                by_game[game][arm].append(error)
        diffs = {game: [sum(values['ablation']) / len(values['ablation']) -
                        sum(values['control']) / len(values['control'])]
                 for game, values in by_game.items() if values['control'] and values['ablation']}
        workload[metric] = {
            'positive_observed_player_game_rows': sum(1 for r in player_rows if r['metric'] == metric),
            'games_with_scored_rows': len(diffs),
            'missing_prediction_rows': player_missing[metric],
            'control_mae': sum(e for _, e in player_errors[metric]['control']) /
                           max(1, len(player_errors[metric]['control'])),
            'ablation_mae': sum(e for _, e in player_errors[metric]['ablation']) /
                            max(1, len(player_errors[metric]['ablation'])),
            'paired_mae_difference_ablation_minus_control_game_balanced':
                sum(v[0] for v in diffs.values()) / max(1, len(diffs)),
            'paired_mae_difference_95ci_game_clustered': _interval(diffs),
            'participation_rule': 'Score only players with a positive observed carry/target count. A zero-touch or absent row is not treated as confirmed inactive.',
        }
    return {
        'schema': 'lp.nfl.v15-outcome-ablation-cohort-grade.v1',
        'cohort_game_count': len(game_ids), 'completed_paired_seed_count': valid_pairs,
        'seed_start': progress.get('seed_start'), 'seeds_per_game': progress.get('seeds_per_game'),
        'game_winner_and_points': season,
        'team_game_metrics': summaries,
        'player_workload': workload,
        'team_game_rows': team_game_rows,
        'player_workload_rows': player_rows,
        'source_database': str(db),
        'limits': ['Retrospective Week 1-8 cohort; not a locked holdout.',
                   'Sack and turnover actuals are sums from nflverse weekly player-game rows.',
                   'Player workload MAE includes positive observed carries/targets only.'],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args(argv)
    report = grade(args.run_root, args.db, allow_partial=args.allow_partial)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(f"graded {report['cohort_game_count']} games / {report['completed_paired_seed_count']} paired seeds -> {args.out}")


if __name__ == '__main__':
    main()
