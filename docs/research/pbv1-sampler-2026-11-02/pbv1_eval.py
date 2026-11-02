"""Run the pre-registered PBV1 folds (docs/research/PBV1-SAMPLER-SPEC-2026-11-02.md).

Development folds: fit 2022 score 2023; fit 2022 to 2023 score 2024. Retrospective fold: fit 2022 to 2024 score 2025, scored
once. Primary K = 20. Sensitivity K = 5 and K = 80. Target sensitivity: the RB-only code. Writes outputs/pbv1_results.json and
outputs/pbv1_package_shares.csv. Reads the database and raw files through the HPV1 frame builder, read only.

Run from the repository root:
    python3 docs/research/pbv1-sampler-2026-11-02/pbv1_eval.py
"""
import collections
import csv
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', '..', 'gridiron-playbooks-research', 'pipeline'))
import hpv1_build as hb  # noqa: E402
import pbv1_sampler as pb  # noqa: E402

OUT_DIR = os.path.join(HERE, 'outputs')
SEASONS = (2022, 2023, 2024, 2025)
FOLDS = (
    {'name': 'dev_2023', 'train': (2022,), 'test': 2023, 'role': 'development'},
    {'name': 'dev_2024', 'train': (2022, 2023), 'test': 2024, 'role': 'development'},
    {'name': 'retro_2025', 'train': (2022, 2023, 2024), 'test': 2025, 'role': 'previously exposed retrospective'},
)
PRIMARY_K = 20
SENSITIVITY_K = (5, 80)


def load_plays():
    plays, excluded = [], collections.Counter()
    for season in SEASONS:
        rows, _ = hb.season_frame(season)
        for r in rows.itertuples(index=False):
            if r.play_class != 'scrimmage':
                continue
            if r.season_type != 'REG':
                excluded['not_regular_season'] += 1
                continue
            if r.play_family not in ('run', 'pass') or r.down_label == 'UNKNOWN' or r.distance == 'UNKNOWN' \
                    or r.distance == 'OUT_OF_RANGE' or r.red_zone == 'UNKNOWN':
                excluded['unknown_cell_field'] += 1
                continue
            plays.append({'season': int(season), 'game_id': r.game_id, 'team': r.posteam,
                          'family': r.play_family, 'down': r.down_label, 'distance': r.distance,
                          'red_zone': int(r.red_zone), 'package': r.package_comparable, 'package_rb': r.package})
    return plays, excluded


def arm_scores(model, plays, K, target):
    out = []
    for play in plays:
        scored = pb.score_play(model, dict(play, package=play[target]), K)
        out.append((play, scored))
    return out


def fold_metrics(plays, fold, K, target):
    train = [dict(p, package=p[target]) for p in plays]
    model = pb.fit(train, train_seasons=fold['train'])
    test = [p for p in plays if p['season'] == fold['test']]
    scored = arm_scores(model, test, K, target)
    n = len(test)
    unsupported = {arm: sum(1 for _, s in scored if s[arm] is None) for arm in ('sampler', 'b0', 'b1')}
    comparable = [(p, s) for p, s in scored if all(s[a] is not None for a in ('sampler', 'b0', 'b1'))]
    ll = {arm: sum(math.log(s[arm]) for _, s in comparable) / len(comparable) for arm in ('sampler', 'b0', 'b1')}
    per_game = collections.defaultdict(lambda: [0.0, 0])
    for p, s in comparable:
        per_game[p['game_id']][0] += math.log(s['sampler']) - math.log(s['b0'])
        per_game[p['game_id']][1] += 1
    ci_b0 = pb.game_bootstrap_ci([tuple(v) for v in per_game.values()])
    per_game_b1 = collections.defaultdict(lambda: [0.0, 0])
    for p, s in comparable:
        per_game_b1[p['game_id']][0] += math.log(s['sampler']) - math.log(s['b1'])
        per_game_b1[p['game_id']][1] += 1
    ci_b1 = pb.game_bootstrap_ci([tuple(v) for v in per_game_b1.values()])
    supported_sampler = [(p, s) for p, s in scored if s['sampler'] is not None]
    cell_cache = {}
    predicted = collections.Counter()
    observed = collections.Counter()
    for p, s in supported_sampler:
        cell = pb.cell_key(dict(p, package=p[target]))
        if cell not in cell_cache:
            cell_cache[cell] = pb.sampler_dist(model, cell, K)
        for package, prob in cell_cache[cell].items():
            predicted[package] += prob
        observed[p[target]] += 1
    m = len(supported_sampler)
    packages = set(predicted) | set(observed)
    tv = 0.5 * sum(abs(predicted[k] / m - observed[k] / m) for k in packages)
    train_counts = model['marginal']
    zero_rate = sum(1 for p in test if train_counts.get(p[target], 0) == 0) / n
    team_game = collections.Counter((p['season'], p['game_id'], p['team']) for p in plays)
    per_season_team_game = collections.defaultdict(list)
    for (season, game, team), count in team_game.items():
        per_season_team_game[season].append(count)
    opportunities = {
        str(season): round(sum(v) / len(v), 2) for season, v in sorted(per_season_team_game.items())
    }
    return {
        'fold': fold['name'], 'role': fold['role'], 'K': K, 'target': target,
        'test_plays': n, 'comparable_plays': len(comparable), 'games': len({p['game_id'] for p in test}),
        'unsupported': {arm: {'count': unsupported[arm], 'rate': round(unsupported[arm] / n, 5)} for arm in unsupported},
        'mean_log_likelihood': {arm: round(ll[arm], 5) for arm in ll},
        'sampler_minus_b0': {'diff': round(ll['sampler'] - ll['b0'], 5), 'ci95': [round(v, 5) for v in ci_b0]},
        'sampler_minus_b1': {'diff': round(ll['sampler'] - ll['b1'], 5), 'ci95': [round(v, 5) for v in ci_b1]},
        'package_total_variation': round(tv, 5),
        'zero_training_package_rate': round(zero_rate, 5),
        'team_game_plays_mean_by_season': opportunities,
        'package_predicted_vs_observed': {k: [round(predicted[k] / m, 5), round(observed[k] / m, 5)]
                                          for k in sorted(packages)},
    }


def package_shares(plays, target):
    shares = collections.defaultdict(collections.Counter)
    for p in plays:
        shares[p['season']][p[target]] += 1
    rows = []
    for season in sorted(shares):
        total = sum(shares[season].values())
        for package, count in sorted(shares[season].items()):
            rows.append({'season': season, 'package': package, 'plays': count, 'share': round(count / total, 5)})
    return rows


def main():
    plays, excluded = load_plays()
    results = {'seasons': list(SEASONS), 'scrimmage_regular_season_plays': len(plays),
               'excluded': dict(excluded), 'bootstrap': {'draws': pb.BOOTSTRAP_DRAWS, 'seed': pb.BOOTSTRAP_SEED},
               'folds': []}
    for fold in FOLDS:
        results['folds'].append(fold_metrics(plays, fold, PRIMARY_K, 'package'))
    for k in SENSITIVITY_K:
        for fold in FOLDS[:2]:
            results['folds'].append(fold_metrics(plays, fold, k, 'package'))
    for fold in FOLDS[:2]:
        results['folds'].append(fold_metrics(plays, fold, PRIMARY_K, 'package_rb'))
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, 'pbv1_results.json'), 'w', encoding='utf-8') as handle:
        json.dump(results, handle, indent=2)
    with open(os.path.join(OUT_DIR, 'pbv1_package_shares.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['season', 'package', 'plays', 'share'])
        writer.writeheader()
        writer.writerows(package_shares(plays, 'package'))
    print('regular-season scrimmage plays', len(plays), 'excluded', dict(excluded))
    for row in results['folds']:
        print(row['fold'], 'K', row['K'], row['target'], 'n', row['test_plays'],
              'll', row['mean_log_likelihood'], 'd_b0', row['sampler_minus_b0'], 'd_b1', row['sampler_minus_b1'],
              'tv', row['package_total_variation'], 'unsup', {a: v['count'] for a, v in row['unsupported'].items()})


if __name__ == '__main__':
    main()
