"""Evaluate the P1 team play-calling component on team-game metrics: pass_share, plays (tempo) and go_rate (fourth-down aggression).

Development run (default): evaluation seasons 2023 and 2024, priors from the prior season only. Retrospective run:
`--retro`, evaluation season 2025, previously exposed, run only after the candidate is frozen (see the M4/M6 freeze document).

Comparators: the league prior-season mean (frozen baseline), the coach-era prior with no in-season update, and the team prior
with no in-season update. Loss is squared error. Paired intervals are game-clustered with 10,000 draws and seed 20261102.

Writes outputs/p1_results_<tag>.json and outputs/p1_forecast_manifest_<metric>_<tag>.csv. Read only.

Run from the repository root:
    python3 docs/research/slc-v2-p1-team-2026-11-02/p1_eval.py          # development
    python3 docs/research/slc-v2-p1-team-2026-11-02/p1_eval.py --retro  # 2025 retrospective, after freeze
"""
import collections
import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p1_team as p1  # noqa: E402
import p2_usage as p2  # noqa: E402
from pbv1_sampler import game_bootstrap_ci, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED  # noqa: E402

OUT = os.path.join(HERE, 'outputs')
LOAD_SEASONS = (2022, 2023, 2024, 2025)
RETRO_METRICS = ('pass_share',)


def prior_tables(records, season, metric):
    prior_all = [r for r in records if r['season'] == season - 1]
    prior = [r for r in prior_all if r[metric] is not None]
    by_coach, by_team = collections.defaultdict(list), collections.defaultdict(list)
    for r in prior:
        by_coach[r['coach']].append(r[metric])
        by_team[r['team']].append(r[metric])
    league = sum(r[metric] for r in prior) / len(prior)
    coach_tab = {c: (len(v), sum(v) / len(v)) for c, v in by_coach.items()}
    team_tab = {t: (len(v), sum(v) / len(v)) for t, v in by_team.items()}
    last_coach = {}
    for r in sorted(prior_all, key=lambda r: r['kickoff']):
        last_coach[r['team']] = r['coach']
    return coach_tab, team_tab, league, last_coach


def run_metric(records, season, metric):
    coach_tab, team_tab, league, last_coach = prior_tables(records, season, metric)
    history = [r for r in records if r['season'] == season]
    by_team = collections.defaultdict(list)
    for r in history:
        by_team[r['team']].append(r)
    per_game = collections.defaultdict(lambda: [0.0, 0])
    per_game_prior = collections.defaultdict(lambda: [0.0, 0])
    per_game_era = collections.defaultdict(lambda: [0.0, 0])
    comp, base, team_only, era_only, source_counts = [], [], [], [], collections.Counter()
    nulls_target, nulls_history, late, manifest = 0, 0, 0, []
    for target in history:
        if target[metric] is None:
            nulls_target += 1
            continue
        team_rows = by_team[target['team']]
        coach, coach_source = p1.carried_coach(team_rows, target['kickoff'] - dt.timedelta(hours=1),
                                               last_coach.get(target['team']))
        prior, prior_source = p1.prior_for(coach, target['team'], coach_tab, team_tab, league)
        feature = p1.team_feature(team_rows, target, prior, prior_source, metric=metric)
        y = target[metric]
        c_err = (y - feature['estimate']) ** 2
        b_err = (y - league) ** 2
        t_prior, _ = p1.prior_for('UNKNOWN', target['team'], {}, team_tab, league)
        t_err = (y - t_prior) ** 2
        e_err = (y - prior) ** 2
        comp.append(c_err)
        base.append(b_err)
        team_only.append(t_err)
        era_only.append(e_err)
        for store, err in ((per_game, b_err), (per_game_prior, t_err), (per_game_era, e_err)):
            store[target['game_id']][0] += err - c_err
            store[target['game_id']][1] += 1
        source_counts[prior_source] += 1
        nulls_history += feature['null_metric_games']
        used = set(feature['game_ids_used'])
        latest = max((g['kickoff'] for g in team_rows if g['game_id'] in used), default=None)
        passed = latest is None or latest + dt.timedelta(hours=p2.AVAILABILITY_LAG_HOURS) <= feature['cutoff']
        late += 0 if passed else 1
        manifest.append({'season': season, 'metric': metric, 'game_id': target['game_id'], 'team': target['team'],
                         'coach_used': coach, 'coach_source': coach_source, 'prior_source': prior_source,
                         'prior': round(prior, 5), 'games_used': feature['games_used'],
                         'cutoff_utc': feature['cutoff'].isoformat(),
                         'latest_used_kickoff_utc': latest.isoformat() if latest else '',
                         'availability_check_passed': passed, 'estimate': round(feature['estimate'], 5),
                         'observed': round(y, 5)})
    if late:
        raise AssertionError(f'{season} {metric}: {late} forecasts used a game after its cutoff')
    n = len(comp)
    result = {
        'metric': metric, 'season': season, 'targets': n, 'games': len(per_game),
        'null_target_games_excluded': nulls_target, 'null_history_games': nulls_history,
        'league_prior': round(league, 5), 'prior_sources': dict(source_counts),
        'mse_component': round(sum(comp) / n, 6), 'mse_league_baseline': round(sum(base) / n, 6),
        'mse_team_prior_only': round(sum(team_only) / n, 6), 'mse_coach_era_prior_only': round(sum(era_only) / n, 6),
        'improvement_over_league_baseline': round((sum(base) - sum(comp)) / n, 6),
        'improvement_over_league_baseline_ci95': [round(v, 6) for v in game_bootstrap_ci(
            [tuple(v) for v in per_game.values()])],
        'improvement_over_team_prior_only': round((sum(team_only) - sum(comp)) / n, 6),
        'improvement_over_team_prior_only_ci95': [round(v, 6) for v in game_bootstrap_ci(
            [tuple(v) for v in per_game_prior.values()])],
        'improvement_over_coach_era_prior_only': round((sum(era_only) - sum(comp)) / n, 6),
        'improvement_over_coach_era_prior_only_ci95': [round(v, 6) for v in game_bootstrap_ci(
            [tuple(v) for v in per_game_era.values()])],
        'late_violations': late,
    }
    return result, manifest


def main(argv):
    retro = '--retro' in argv
    eval_seasons = (2025,) if retro else (2023, 2024)
    tag = 'retro2025' if retro else 'dev'
    records, unmatched = p1.load_team_games(LOAD_SEASONS)
    if unmatched:
        raise SystemExit(f'{unmatched} team-games did not join to a schedule row; fix the join before evaluating')
    results = {'tag': tag, 'lag_hours': p2.AVAILABILITY_LAG_HOURS, 'min_coach_games': p1.MIN_COACH_GAMES,
               'k': p1.K, 'bootstrap': {'draws': BOOTSTRAP_DRAWS, 'seed': BOOTSTRAP_SEED}, 'results': []}
    os.makedirs(OUT, exist_ok=True)
    for metric in (RETRO_METRICS if retro else p1.METRICS):
        for season in eval_seasons:
            result, manifest = run_metric(records, season, metric)
            results['results'].append(result)
            with open(os.path.join(OUT, f'p1_forecast_manifest_{metric}_{tag}.csv'), 'w', newline='',
                      encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
                writer.writeheader()
                writer.writerows(manifest)
            print(result)
    with open(os.path.join(OUT, f'p1_results_{tag}.json'), 'w', encoding='utf-8') as handle:
        json.dump(results, handle, indent=2)


if __name__ == '__main__':
    main(sys.argv[1:])
