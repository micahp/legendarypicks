"""Evaluate the P2 usage component against the frozen baselines on regular-season player shares.

Metrics: target_share (share of team targets) and off_pct (share of offensive snaps), both from the published weekly logs.
Development run (default): evaluation seasons 2023 and 2024, priors from the prior season only. Retrospective run: `--retro`,
evaluation season 2025, previously exposed, run only after the candidate is frozen.

Comparators: the position-group prior-season mean (frozen baseline) and the prior-only estimate with no in-season update.
Loss is squared error. Paired intervals are game-clustered with 10,000 draws and seed 20261102.

Writes outputs/p2_results_<tag>.json, outputs/p2_forecast_manifest_<metric>_<tag>.csv and, for the development run, outputs/
p2_examples.json. Read only.

Run from the repository root:
    python3 docs/research/slc-v2-p2-usage-2026-11-02/p2_eval.py          # development
    python3 docs/research/slc-v2-p2-usage-2026-11-02/p2_eval.py --retro  # 2025 retrospective, after freeze
"""
import collections
import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p2_usage as p2  # noqa: E402
from pbv1_sampler import game_bootstrap_ci, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED  # noqa: E402

OUT = os.path.join(HERE, 'outputs')
LOAD_SEASONS = (2022, 2023, 2024, 2025)
METRICS = ('target_share', 'off_pct')
RETRO_METRICS = ('target_share',)
MIN_COVERAGE = 0.95


def prior_tables(logs, season, metric, positions):
    prior = [r for r in logs if r['season'] == season - 1 and r['game_type'] == 'REG' and r[metric] is not None]
    by_gsis = collections.defaultdict(list)
    by_group = collections.defaultdict(list)
    for r in prior:
        by_gsis[r['gsis']].append(r[metric])
        by_group[p2.position_group_of(r['gsis'], positions)].append(r[metric])
    prior_by_gsis = {g: (len(v), sum(v) / len(v)) for g, v in by_gsis.items()}
    prior_pos = {grp: sum(v) / len(v) for grp, v in by_group.items()}
    return prior_by_gsis, prior_pos


def run_metric(logs, season, metric, positions, examples):
    prior_by_gsis, prior_pos = prior_tables(logs, season, metric, positions)
    history = [r for r in logs if r['season'] == season and r['game_type'] == 'REG']
    by_gsis = collections.defaultdict(list)
    for r in history:
        by_gsis[r['gsis']].append(r)
    targets = [r for r in history if r[metric] is not None]
    per_game = collections.defaultdict(lambda: [0.0, 0])
    per_game_prior = collections.defaultdict(lambda: [0.0, 0])
    comp_sq, base_sq, prior_sq, with_history, nulls_total, late_violations = [], [], [], 0, 0, 0
    manifest = []
    for target in targets:
        group = p2.position_group_of(target['gsis'], positions)
        base_pred = prior_pos.get(group, prior_pos.get('OTHER', 0.0))
        feature = p2.player_feature(by_gsis[target['gsis']], target, prior_by_gsis, base_pred, group, metric=metric)
        y = target[metric]
        c_err = (y - feature['estimate']) ** 2
        b_err = (y - base_pred) ** 2
        p_err = (y - feature['prior_value']) ** 2
        comp_sq.append(c_err)
        base_sq.append(b_err)
        prior_sq.append(p_err)
        per_game[target['game_id']][0] += b_err - c_err
        per_game[target['game_id']][1] += 1
        per_game_prior[target['game_id']][0] += p_err - c_err
        per_game_prior[target['game_id']][1] += 1
        nulls_total += feature['null_target_share_games']
        if feature['games_used'] > 0:
            with_history += 1
        used = set(feature['game_ids_used'])
        used_max = max((g['kickoff'] for g in by_gsis[target['gsis']] if g['game_id'] in used), default=None)
        passed = used_max is None or used_max + dt.timedelta(hours=p2.AVAILABILITY_LAG_HOURS) <= feature['cutoff']
        late_violations += 0 if passed else 1
        manifest.append({'season': season, 'metric': metric, 'game_id': target['game_id'], 'gsis': target['gsis'],
                         'position_group': group, 'cutoff_utc': feature['cutoff'].isoformat(),
                         'games_used': feature['games_used'],
                         'latest_used_kickoff_utc': used_max.isoformat() if used_max else '',
                         'lag_hours': p2.AVAILABILITY_LAG_HOURS, 'availability_check_passed': passed,
                         'prior_source': feature['prior_source'], 'prior_value': round(feature['prior_value'], 5),
                         'estimate': round(feature['estimate'], 5), 'observed': y,
                         'null_metric_games': feature['null_target_share_games']})
        if metric == 'target_share' and len(examples) < 12 and feature['games_used'] >= 4 and group in ('WR', 'TE', 'RB'):
            example = {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in feature.items()}
            example.update({'observed': y, 'baseline': base_pred, 'position_group': group})
            examples.append(example)
    if late_violations:
        raise AssertionError(f'{season} {metric}: {late_violations} forecasts used a game after its cutoff')
    n = len(targets)
    result = {
        'metric': metric, 'season': season, 'targets': n, 'games': len(per_game),
        'targets_with_usable_history': with_history, 'null_metric_games_excluded': nulls_total,
        'mse_component': round(sum(comp_sq) / n, 6), 'mse_baseline': round(sum(base_sq) / n, 6),
        'improvement_component_over_baseline': round((sum(base_sq) - sum(comp_sq)) / n, 6),
        'improvement_ci95': [round(v, 6) for v in game_bootstrap_ci([tuple(v) for v in per_game.values()])],
        'mse_prior_only': round(sum(prior_sq) / n, 6),
        'improvement_over_prior_only': round((sum(prior_sq) - sum(comp_sq)) / n, 6),
        'improvement_over_prior_only_ci95': [round(v, 6) for v in game_bootstrap_ci(
            [tuple(v) for v in per_game_prior.values()])],
        'late_violations': late_violations,
    }
    return result, manifest


def main(argv):
    retro = '--retro' in argv
    eval_seasons = (2025,) if retro else (2023, 2024)
    tag = 'retro2025' if retro else 'dev'
    positions = p2.load_positions()
    raw = p2.load_logs(LOAD_SEASONS)
    logs, missing = p2.attach_kickoffs(raw, p2.load_kickoffs())
    regular_missing = [g for g, n in missing.items() if any(r['game_id'] == g and r['game_type'] == 'REG' for r in raw)]
    if regular_missing:
        raise AssertionError(f'regular-season game IDs without a kickoff: {regular_missing[:5]}')
    results = {'tag': tag, 'availability_lag_hours': p2.AVAILABILITY_LAG_HOURS, 'min_prior_games': p2.MIN_PRIOR_GAMES,
               'k': p2.K, 'bootstrap': {'draws': BOOTSTRAP_DRAWS, 'seed': BOOTSTRAP_SEED},
               'logs_without_kickoff': sum(missing.values()), 'results': []}
    os.makedirs(OUT, exist_ok=True)
    examples = []
    for metric in (RETRO_METRICS if retro else METRICS):
        for season in eval_seasons:
            reg = [r for r in logs if r['season'] == season and r['game_type'] == 'REG']
            coverage = sum(r[metric] is not None for r in reg) / len(reg)
            if coverage < MIN_COVERAGE:
                results['results'].append({'metric': metric, 'season': season, 'skipped': True,
                                           'reason': f'coverage {coverage:.4f} of regular-season rows below {MIN_COVERAGE}'})
                print(f'skipped {metric} {season}: coverage {coverage:.4f}')
                continue
            result, manifest = run_metric(logs, season, metric, positions, examples)
            results['results'].append(result)
            with open(os.path.join(OUT, f'p2_forecast_manifest_{metric}_{tag}.csv'), 'w', newline='',
                      encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
                writer.writeheader()
                writer.writerows(manifest)
            print(result)
    with open(os.path.join(OUT, f'p2_results_{tag}.json'), 'w', encoding='utf-8') as handle:
        json.dump(results, handle, indent=2)
    if not retro:
        with open(os.path.join(OUT, 'p2_examples.json'), 'w', encoding='utf-8') as handle:
            json.dump(examples, handle, indent=2, default=str)


if __name__ == '__main__':
    main(sys.argv[1:])
