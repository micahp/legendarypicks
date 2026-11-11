#!/usr/bin/env python3
"""Historical A/D/E pass-label ordering audit; read-only against the simulation PBP database."""
import collections
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts' / 'nfl_sequence'))
import decision_layer as dl

DB = Path('/root/legendarypicks/backend/data/picks.dev.db')
TRAIN = (2022, 2023, 2024)
TEST = 2025
EVENTS = ('sack', 'pass_complete', 'pass_incomplete', 'interception', 'fumble_lost')
PASS_EVENTS = frozenset(EVENTS) - {'sack'}
CATS = ('A', 'D', 'E')
PRIOR = 20.0


def event_of(sack, complete, interception, fumble, attempt):
    if interception == 1:
        return 'interception'
    if fumble == 1:
        return 'fumble_lost'
    if sack == 1:
        return 'sack'
    if complete == 1:
        return 'pass_complete'
    if attempt == 1:
        return 'pass_incomplete'
    return None


def logloss(p, actual):
    return -math.log(max(1e-12, p.get(actual, 0.0)))


def brier(p, actual):
    return sum((p.get(event, 0.0) - (event == actual)) ** 2 for event in EVENTS)


def normalize(weights):
    total = sum(weights.values())
    return {event: weights.get(event, 0.0) / total for event in EVENTS} if total else None


def distributions(rows, prior_season):
    league = {cat: collections.defaultdict(collections.Counter) for cat in CATS}
    team = {cat: collections.defaultdict(collections.Counter) for cat in CATS}
    for row in rows:
        if row['season'] != prior_season:
            continue
        for cat in CATS:
            value = row['labels'].get(cat)
            if value is not None:
                league[cat][row['cell']][value] += 1
                team[cat][(row['team'], row['cell'])][value] += 1
    return league, team


def label_probabilities(league, team, team_name, cell, cat):
    counts = league[cat].get(cell, {})
    total = sum(counts.values())
    if not total:
        return None
    own = team[cat].get((team_name, cell), {})
    own_total = sum(own.values())
    values = dl.CAT_ROLES[cat]
    probs = {}
    for value in values:
        league_share = counts.get(value, 0) / total
        probs[value] = (own.get(value, 0) + PRIOR * league_share) / (own_total + PRIOR)
    z = sum(probs.values())
    return {value: p / z for value, p in probs.items()}


def fit_event_tables(db_rows, labels_by_key):
    base = collections.defaultdict(collections.Counter)
    labelled_base = collections.defaultdict(collections.Counter)
    by_label = {cat: collections.defaultdict(collections.Counter) for cat in CATS}
    for row in db_rows:
        game, play, season, team_name, down, dist, yl, event = row
        if season not in TRAIN or event not in EVENTS:
            continue
        cell = dl.cell_of(down, dist, yl)
        key = (game, int(play))
        labels = labels_by_key.get(key, {})
        base[cell][event] += 1
        if labels and any(labels.values()):
            labelled_base[cell][event] += 1
        for cat in CATS:
            value = labels.get(cat)
            if value is not None:
                by_label[cat][(cell, value)][event] += 1
    return base, labelled_base, by_label


def lift(cat, cell, event, value, labelled_base, by_label):
    all_labelled = labelled_base[cell]
    n_labelled = sum(all_labelled.values())
    if not n_labelled or not all_labelled[event]:
        return 1.0
    base_share = all_labelled[event] / n_labelled
    counts = by_label[cat].get((cell, value), {})
    n_value = sum(counts.values())
    conditional = (counts.get(event, 0) + PRIOR * base_share) / (n_value + PRIOR)
    return conditional / base_share


def event_probabilities(cell, base, labelled_base, by_label, priors, mode):
    counts = base.get(cell)
    if not counts or sum(counts.values()) < 30:
        return None
    p0 = normalize(counts)
    active_cats = CATS if mode in ('legacy', 'two_stage') else tuple(mode.split('_')[0]) if mode.endswith('_only') else ()
    present = [(cat, priors.get(cat)) for cat in active_cats if priors.get(cat)]
    # Include all possible label combinations from the prior. Their count is at most 4*2*3.
    combinations = [({}, 1.0)]
    for cat, distribution in present:
        combinations = [(dict(labels, **{cat: value}), weight * prob)
                        for labels, weight in combinations for value, prob in distribution.items()]
    if mode == 'off' or not combinations:
        return p0
    expected = collections.Counter()
    for labels, label_weight in combinations:
        weighted = {}
        for event in EVENTS:
            w = p0.get(event, 0.0)
            selected = [(cat, value) for cat, value in labels.items()]
            if (mode == 'legacy' or mode.endswith('_only')) and selected:
                lifts = [lift(cat, cell, event, value, labelled_base, by_label)
                         for cat, value in selected]
                w *= math.exp(sum(math.log(max(x, 1e-12)) for x in lifts) / len(lifts))
            elif mode == 'two_stage' and event in PASS_EVENTS and selected:
                lifts = [lift(cat, cell, event, value, labelled_base, by_label)
                         for cat, value in selected]
                w *= math.exp(sum(math.log(max(x, 1e-12)) for x in lifts) / len(lifts))
            weighted[event] = w
        if mode == 'two_stage':
            # First stage fixes sack-vs-pass mass at the no-A/D/E probability. The labels can only
            # reshape the conditional distribution among pass outcomes.
            pass_mass = sum(p0[e] for e in PASS_EVENTS)
            pass_z = sum(weighted[e] for e in PASS_EVENTS)
            for event in EVENTS:
                expected[event] += label_weight * (p0['sack'] if event == 'sack' else
                    (pass_mass * weighted[event] / pass_z if pass_z else 0.0))
        else:
            p = normalize(weighted)
            for event in EVENTS:
                expected[event] += label_weight * p[event]
    return dict(expected)


def main():
    labels_rows = dl.load_rows(str(DB), list(TRAIN) + [TEST])
    labels_by_key = {(row['game_id'], row['play_id']): row['labels'] for row in labels_rows}
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute("""SELECT game_id,play_id,season,posteam,down,ydstogo,yardline_100,
        sack,complete_pass,interception,fumble_lost,pass_attempt
        FROM nfl_pbp WHERE season BETWEEN ? AND ? AND week<=18 AND qtr BETWEEN 1 AND 4
        AND play_type='pass' AND posteam IS NOT NULL AND down BETWEEN 1 AND 4
        AND ydstogo IS NOT NULL AND yardline_100 IS NOT NULL AND penalty IS NOT 1
        ORDER BY game_id,play_id""", (min(TRAIN), TEST)).fetchall()
    con.close()
    normalized = []
    for game, play, season, team_name, down, dist, yl, sack, complete, interception, fumble, attempt in rows:
        event = event_of(sack, complete, interception, fumble, attempt)
        if event:
            normalized.append((game, play, season, team_name, down, dist, yl, event))
    base, labelled_base, by_label = fit_event_tables(normalized, labels_by_key)
    prior_league, prior_team = distributions(labels_rows, TEST - 1)
    test_rows = [row for row in normalized if row[2] == TEST]
    models = ('legacy', 'off', 'two_stage', 'A_only', 'D_only', 'E_only')
    binary_targets = ('sack', 'interception', 'completion', 'turnover')
    counters = collections.defaultdict(lambda: {'n': 0, 'logloss': 0.0, 'brier': 0.0,
                                                 'events': collections.Counter(), 'pred': collections.Counter(),
                                                 'binary': collections.defaultdict(collections.Counter)})
    by_game = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    excluded = collections.Counter()
    prevalence = collections.defaultdict(collections.Counter)
    for row in test_rows:
        game, play, season, team_name, down, dist, yl, actual = row
        cell = dl.cell_of(down, dist, yl)
        labels = labels_by_key.get((game, int(play)), {})
        for cat in CATS:
            prevalence[actual][cat + '_n'] += 1
            prevalence[actual][cat + '_present'] += labels.get(cat) is not None
        priors = {cat: label_probabilities(prior_league, prior_team, team_name, cell, cat) for cat in CATS}
        if base.get(cell) is None or sum(base[cell].values()) < 30:
            excluded['unsupported_situation_cell'] += 1
            continue
        for mode in models:
            p = event_probabilities(cell, base, labelled_base, by_label, priors, mode)
            if p is None:
                excluded['no_prediction'] += 1
                continue
            d = counters[mode]
            d['n'] += 1
            d['logloss'] += logloss(p, actual)
            d['brier'] += brier(p, actual)
            d['events'][actual] += 1
            by_game[game][mode]['n'] += 1
            by_game[game][mode]['logloss'] += logloss(p, actual)
            by_game[game][mode]['brier'] += brier(p, actual)
            for event in EVENTS:
                d['pred'][event] += p[event]
            targets = {'sack': actual == 'sack', 'interception': actual == 'interception',
                       'completion': actual == 'pass_complete',
                       'turnover': actual in ('interception', 'fumble_lost')}
            for target in binary_targets:
                prob = p['sack'] if target == 'sack' else p['interception'] if target == 'interception' else \
                    p['pass_complete'] if target == 'completion' else p['interception'] + p['fumble_lost']
                y = int(targets[target])
                metric = d['binary'][target]
                metric['actual'] += y
                metric['pred'] += prob
                metric['brier'] += (prob - y) ** 2
                metric['logloss'] -= math.log(max(1e-12, prob if y else 1 - prob))
                by_game[game][mode][target + '_actual'] += y
                by_game[game][mode][target + '_pred'] += prob
                by_game[game][mode][target + '_brier'] += (prob - y) ** 2
                by_game[game][mode][target + '_logloss'] -= math.log(max(1e-12, prob if y else 1 - prob))
    results = {}
    for mode, d in counters.items():
        n = d['n']
        results[mode] = {'plays': n, 'multiclass_log_loss': d['logloss'] / n,
                         'multiclass_brier': d['brier'] / n,
                         'actual_rate': {e: d['events'][e] / n for e in EVENTS},
                         'mean_predicted_rate': {e: d['pred'][e] / n for e in EVENTS},
                         'binary': {target: {'observed_rate': d['binary'][target]['actual'] / n,
                                             'mean_predicted_probability': d['binary'][target]['pred'] / n,
                                             'brier': d['binary'][target]['brier'] / n,
                                             'log_loss': d['binary'][target]['logloss'] / n}
                                    for target in binary_targets}}
    import random
    rng = random.Random(20261111)
    games = sorted(by_game)
    boot = collections.defaultdict(lambda: collections.defaultdict(list))
    for _ in range(500):
        sampled = [games[rng.randrange(len(games))] for _ in games]
        totals = collections.defaultdict(collections.Counter)
        for game in sampled:
            for mode in models:
                for metric, value in by_game[game][mode].items():
                    totals[mode][metric] += value
        for mode in ('legacy', 'two_stage', 'A_only', 'D_only', 'E_only'):
            for metric in ('logloss', 'brier'):
                a = totals[mode][metric] / totals[mode]['n']
                b = totals['off'][metric] / totals['off']['n']
                boot[mode][metric].append(a - b)
    intervals = {mode: {metric: [sorted(boot[mode][metric])[12], sorted(boot[mode][metric])[487]]
                        for metric in ('logloss', 'brier')}
                 for mode in boot}
    label_rates = {}
    for event, c in prevalence.items():
        n = c['A_n']
        label_rates[event] = {'plays': n, **{cat: c[cat + '_present'] / n for cat in CATS}}
    digest = hashlib.sha256()
    with DB.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    result = {'database_sha256': digest.hexdigest(), 'training_seasons': list(TRAIN), 'heldout_season': TEST,
              'cohort': {'candidate_pass_rows': len(test_rows), 'scored': counters['legacy']['n'],
                         'excluded': dict(excluded)},
              'label_presence_by_outcome': label_rates, 'models': results,
              'paired_game_cluster_bootstrap_95pct_delta_vs_off': intervals,
              'scope': 'Observed 2025 dropback situations; prior-season situation-cell event rates with A/D/E only. '
                       'No coverage, strength, player, scramble, or full drive/game effects. Historical tiers only.'}
    out = Path(__file__).with_name('audit-results.json')
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
