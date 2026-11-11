#!/usr/bin/env python3
"""Observed-context test of SLC's coverage-conditioned dropback event weights."""
import collections
import json
import math
import random
import sqlite3
from pathlib import Path

import audit
import decision_layer as dl

DB = audit.DB


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    coverage = {(g, int(p)): (name or 'UNKNOWN') for g, p, name in con.execute(
        "SELECT nflverse_game_id,play_id,defense_coverage_type FROM nfl_hist_participation "
        "WHERE season BETWEEN ? AND ? AND play_id IS NOT NULL", (min(audit.TRAIN), audit.TEST))}
    raw = con.execute("""SELECT game_id,play_id,season,posteam,down,ydstogo,yardline_100,
        sack,complete_pass,interception,fumble_lost,pass_attempt FROM nfl_pbp
        WHERE season BETWEEN ? AND ? AND week<=18 AND qtr BETWEEN 1 AND 4 AND play_type='pass'
        AND posteam IS NOT NULL AND down BETWEEN 1 AND 4 AND ydstogo IS NOT NULL
        AND yardline_100 IS NOT NULL AND penalty IS NOT 1 ORDER BY game_id,play_id""",
        (min(audit.TRAIN), audit.TEST)).fetchall()
    con.close()
    pool = []
    for g, p, season, team, down, dist, yl, sack, complete, interception, fumble, attempt in raw:
        event = audit.event_of(sack, complete, interception, fumble, attempt)
        if event:
            pool.append((g, int(p), season, team, dl.cell_of(down, dist, yl), event,
                         coverage.get((g, int(p)), 'UNKNOWN')))
    base = collections.defaultdict(collections.Counter)
    by_coverage = collections.defaultdict(collections.Counter)
    for game, play, season, team, cell, event, label in pool:
        if season not in audit.TRAIN:
            continue
        base[cell][event] += 1
        by_coverage[(cell, label)][event] += 1
    metric = collections.defaultdict(lambda: {'n': 0, 'll': 0.0, 'brier': 0.0,
                                               'actual': collections.Counter(), 'pred': collections.Counter()})
    per_game = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    rates = collections.defaultdict(collections.Counter)
    excluded = collections.Counter()
    for game, play, season, team, cell, actual, label in pool:
        if season != audit.TEST or label == 'UNKNOWN':
            if season == audit.TEST:
                excluded['unknown_coverage'] += 1
            continue
        counts = base.get(cell)
        if not counts or sum(counts.values()) < 30:
            excluded['low_cell_support'] += 1
            continue
        p0 = audit.normalize(counts)
        cond = by_coverage.get((cell, label), {})
        n_label = sum(cond.values())
        weights = {}
        for event in audit.EVENTS:
            base_share = counts.get(event, 0) / sum(counts.values())
            conditional = (cond.get(event, 0) + audit.PRIOR * base_share) / (n_label + audit.PRIOR)
            weights[event] = p0[event] * conditional / base_share if base_share else 0.0
        p1 = audit.normalize(weights)
        if p1 is None:
            excluded['zero_weight'] += 1
            continue
        rates[actual]['n'] += 1
        rates[actual][label] += 1
        for name, probs in (('situation_cell', p0), ('coverage_conditioned', p1)):
            item = metric[name]
            item['n'] += 1
            item['ll'] += audit.logloss(probs, actual)
            item['brier'] += audit.brier(probs, actual)
            item['actual'][actual] += 1
            for event in audit.EVENTS:
                item['pred'][event] += probs[event]
            per_game[game][name]['n'] += 1
            per_game[game][name]['ll'] += audit.logloss(probs, actual)
            per_game[game][name]['brier'] += audit.brier(probs, actual)
    result_metrics = {}
    for name, item in metric.items():
        n = item['n']
        result_metrics[name] = {'plays': n, 'multiclass_log_loss': item['ll']/n,
            'multiclass_brier': item['brier']/n,
            'actual_rate': {e:item['actual'][e]/n for e in audit.EVENTS},
            'mean_predicted_rate': {e:item['pred'][e]/n for e in audit.EVENTS}}
    games = sorted(per_game)
    rng = random.Random(20261111)
    deltas = {'log_loss': [], 'brier': []}
    for _ in range(500):
        chosen = [games[rng.randrange(len(games))] for _ in games]
        totals = {name: collections.Counter() for name in ('situation_cell','coverage_conditioned')}
        for game in chosen:
            for name in totals:
                totals[name].update(per_game[game][name])
        for key, field in (('log_loss','ll'),('brier','brier')):
            deltas[key].append(totals['coverage_conditioned'][field]/totals['coverage_conditioned']['n']-
                               totals['situation_cell'][field]/totals['situation_cell']['n'])
    interval = {key:[sorted(values)[12],sorted(values)[487]] for key,values in deltas.items()}
    result = {'database_sha256': json.loads(Path(__file__).with_name('audit-results.json').read_text())['database_sha256'],
        'training_seasons': list(audit.TRAIN), 'heldout_season': audit.TEST,
        'cohort': {'known_coverage_plays_scored': metric['situation_cell']['n'], 'excluded': dict(excluded)},
        'observed_coverage_rates_by_outcome': {event:{'n':counts['n'],
            'coverage_frequency':{label:counts[label]/counts['n'] for label in counts if label!='n'}}
            for event,counts in rates.items()},
        'models': result_metrics,
        'paired_game_cluster_bootstrap_95pct_delta_coverage_minus_situation': interval,
        'scope': '2025 observed pre-play coverage label; 2022-2024 exact situation-cell event frequencies and coverage-conditioned lifts. '
                 'Known-coverage plays only; no full-game or prospective coverage-choice evaluation.'}
    Path(__file__).with_name('coverage-audit-results.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__ == '__main__':
    main()
