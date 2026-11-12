#!/usr/bin/env python3
"""Walk-forward evaluation of the calibrated conditional A/D/E pass-outcome model."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import decision_layer
import e0_single_play as e0
from pass_label_outcomes import OUTCOMES, PassLabelOutcomeModel


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def event_of(row):
    if row['sack'] == 1:
        return 'sack_fumble_lost' if row['fumble_lost'] == 1 else 'sack'
    if row['interception'] == 1:
        return 'interception'
    if row['fumble_lost'] == 1:
        return 'fumble_lost'
    if row['complete_pass'] == 1:
        return 'pass_complete'
    if row['pass_attempt'] == 1:
        return 'pass_incomplete'
    return None


def is_conditional_pass_outcome(event):
    return event in OUTCOMES


def is_turnover_event(event):
    return event in ('interception', 'fumble_lost', 'sack_fumble_lost')


def score(probabilities, actual):
    return (-math.log(max(1e-15, probabilities.get(actual, 0.0))),
            sum((probabilities.get(event, 0.0) - (event == actual)) ** 2 for event in OUTCOMES))


def load_plays(database, first_season, test_season):
    connection = sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True, timeout=30)
    try:
        eligibility = connection.execute(
            """SELECT season, penalty, count(*)
               FROM nfl_pbp
               WHERE season BETWEEN ? AND ? AND week BETWEEN 1 AND 18 AND qtr BETWEEN 1 AND 4
                 AND play_type='pass' AND posteam IS NOT NULL AND down BETWEEN 1 AND 4
                 AND ydstogo IS NOT NULL AND yardline_100 IS NOT NULL
               GROUP BY season, penalty ORDER BY season, penalty""", (first_season, test_season)).fetchall()
        rows = connection.execute(
            """SELECT game_id,play_id,season,posteam,down,ydstogo,yardline_100,
                      sack,complete_pass,interception,fumble_lost,pass_attempt
               FROM nfl_pbp
               WHERE season BETWEEN ? AND ? AND week BETWEEN 1 AND 18 AND qtr BETWEEN 1 AND 4
                 AND play_type='pass' AND posteam IS NOT NULL AND down BETWEEN 1 AND 4
                 AND ydstogo IS NOT NULL AND yardline_100 IS NOT NULL AND penalty=0
               ORDER BY game_id,play_id""", (first_season, test_season)).fetchall()
    finally:
        connection.close()
    output = []
    for (game_id, play_id, season, team, down, togo, yardline, sack, complete,
         interception, fumble_lost, pass_attempt) in rows:
        event = event_of({'sack': sack, 'complete_pass': complete, 'interception': interception,
                          'fumble_lost': fumble_lost, 'pass_attempt': pass_attempt})
        if event:
            output.append({'game_id': str(game_id), 'play_id': int(play_id), 'season': int(season),
                           'team': team, 'context': e0.pool_key(down, togo, yardline),
                           'label_cell': decision_layer.cell_of(down, togo, yardline), 'event': event})
    status_by_season = defaultdict(lambda: {'known_clean': 0, 'penalty_tagged': 0,
                                             'unknown': 0, 'other': 0})
    for season, penalty, count in eligibility:
        key = ('unknown' if penalty is None else 'known_clean' if penalty == 0
               else 'penalty_tagged' if penalty == 1 else 'other')
        status_by_season[str(int(season))][key] += int(count)
    eligibility_summary = {
        'policy': 'Only rows with penalty=0 are included; NULL and unrecognized penalty status are excluded.',
        'by_season': {season: counts for season, counts in sorted(status_by_season.items())},
        'included_known_clean_rows': sum(counts['known_clean'] for counts in status_by_season.values()),
        'excluded_penalty_tagged_rows': sum(counts['penalty_tagged'] for counts in status_by_season.values()),
        'excluded_unknown_penalty_status_rows': sum(counts['unknown'] for counts in status_by_season.values()),
        'excluded_other_penalty_status_rows': sum(counts['other'] for counts in status_by_season.values()),
    }
    return output, eligibility_summary


def evaluate(database, test_season, bootstrap_reps, bootstrap_seed):
    first_season = decision_layer.FIRST_CHARTED_SEASON
    labelled = decision_layer.load_rows(str(database), range(first_season, test_season + 1),
                                        known_clean_only=True)
    labels = {(row['game_id'], int(row['play_id'])): row for row in labelled}
    plays, penalty_eligibility = load_plays(database, first_season, test_season)
    training_pool = defaultdict(list)
    test_rows = []
    test_event_counts = Counter()
    test_turnover_count = 0
    for play in plays:
        if play['season'] == test_season:
            test_event_counts[play['event']] += 1
            test_turnover_count += int(is_turnover_event(play['event']))
            if is_conditional_pass_outcome(play['event']):
                label_row = labels.get((play['game_id'], play['play_id']))
                test_rows.append((play, {} if label_row is None else label_row['labels']))
        elif play['season'] < test_season:
            label_row = labels.get((play['game_id'], play['play_id']))
            row = {'season': play['season'], 'penalty': 0,
                   'labels': {} if label_row is None else label_row['labels']}
            training_pool[play['context']].append((play['event'], row, 0.0, 0))

    model = PassLabelOutcomeModel.fit(training_pool)
    label_table = decision_layer.fit(labelled, prior_season=test_season - 1)
    totals = {'baseline': Counter(), 'conditional': Counter()}
    by_game = defaultdict(lambda: {'n': 0, 'log_loss_delta': 0.0, 'brier_delta': 0.0})
    for play, row_labels in test_rows:
        base = model.base_probabilities(play['context'])
        label_prior = {
            category: decision_layer.distribution(label_table, play['team'], play['label_cell'], category)
            if label_table['league'][category].get(play['label_cell']) else {None: 1.0}
            for category in ('A', 'D', 'E')
        }
        conditional = {
            event: base[event] * model.ratio(
                play['context'], row_labels, event, label_prior=label_prior,
                calibration_key=(play['team'], play['label_cell']))
            for event in OUTCOMES
        }
        norm = sum(conditional.values())
        conditional = {event: value / norm for event, value in conditional.items()}
        for name, probabilities in (('baseline', base), ('conditional', conditional)):
            ll, brier = score(probabilities, play['event'])
            totals[name]['n'] += 1
            totals[name]['log_loss'] += ll
            totals[name]['brier'] += brier
        baseline_ll = score(base, play['event'])[0]
        conditional_ll, conditional_brier = score(conditional, play['event'])
        baseline_brier = score(base, play['event'])[1]
        game = by_game[play['game_id']]
        game['n'] += 1
        game['log_loss_delta'] += conditional_ll - baseline_ll
        game['brier_delta'] += conditional_brier - baseline_brier

    games = sorted(by_game)
    rng = random.Random(bootstrap_seed)
    draws = {'log_loss': [], 'brier': []}
    for _ in range(bootstrap_reps):
        sampled = [games[rng.randrange(len(games))] for _ in games]
        n = sum(by_game[game]['n'] for game in sampled)
        for metric, key in (('log_loss', 'log_loss_delta'), ('brier', 'brier_delta')):
            draws[metric].append(sum(by_game[game][key] for game in sampled) / n)
    result = {
        'status': 'research_conditional_pass_outcome_evaluation',
        'fit_seasons': list(range(first_season, test_season)),
        'test_season': test_season,
        'cohort': {'pass_outcomes': totals['baseline']['n'], 'games': len(games)},
        'test_event_counts': dict(sorted(test_event_counts.items())),
        'test_turnover_event_count': test_turnover_count,
        'penalty_eligibility': penalty_eligibility,
        'baseline': {metric: totals['baseline'][metric] / totals['baseline']['n']
                     for metric in ('log_loss', 'brier')},
        'conditional': {metric: totals['conditional'][metric] / totals['conditional']['n']
                        for metric in ('log_loss', 'brier')},
        'paired_game_bootstrap_delta_conditional_minus_baseline_95ci': {
            metric: [sorted(values)[int(0.025 * (bootstrap_reps - 1))],
                     sorted(values)[int(0.975 * (bootstrap_reps - 1))]]
            for metric, values in draws.items()},
        'model_manifest': model.manifest,
        'database_sha256': sha256(database),
        'source_sha256': {
            'players': sha256(decision_layer.PLAYERS_PARQUET),
            **{f'pbp_{season}': sha256(decision_layer.PBP_PARQUET.format(season=season))
               for season in range(first_season, test_season + 1)},
            **{f'ftn_{season}': sha256(decision_layer.FTN_PARQUET.format(season=season))
               for season in range(first_season, test_season + 1)},
        },
        'code_sha256': {
            name: sha256(HERE / name)
            for name in ('evaluate_pass_label_outcomes.py', 'pass_label_outcomes.py',
                         'decision_layer.py', 'slc_playcall.py')
        },
        'limitations': [
            'The 2025 historical cohort is development-exposed.',
            'Scores are conditional on observed A/D/E labels; this is not a full-game validation.',
            'Sacks are excluded from the conditional pass-outcome stage and retain the separate first-stage probability.',
        ],
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('/root/legendarypicks/backend/data/picks.dev.db'))
    parser.add_argument('--test-season', type=int, default=2025)
    parser.add_argument('--bootstrap-reps', type=int, default=2000)
    parser.add_argument('--bootstrap-seed', type=int, default=20261111)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f'refusing to overwrite existing output: {args.output}')
    result = evaluate(args.database, args.test_season, args.bootstrap_reps, args.bootstrap_seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'output': str(args.output), 'cohort': result['cohort'],
                      'penalty_eligibility': result['penalty_eligibility'],
                      'baseline': result['baseline'], 'conditional': result['conditional'],
                      'paired_ci': result['paired_game_bootstrap_delta_conditional_minus_baseline_95ci']},
                     sort_keys=True))


if __name__ == '__main__':
    main()
