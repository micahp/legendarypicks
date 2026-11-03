"""Evaluate P3 defensive matchup on 2023 and 2024 for five outcomes: receiving yards per target to WR, TE and RB; rushing yards per
carry to RB; passing yards per attempt to QB.

For each season S in (2023, 2024): league rates and opponent offense strengths come from S-1 only. Each target is a
defense's game-level yards per opportunity in game t (opportunities greater than zero). Comparators: the league prior-season
rate (frozen baseline) and the same component with no opponent adjustment. Loss is squared error on yards per opportunity.
Intervals are game-clustered with 10,000 draws and seed 20261102. Writes outputs/p3_results.json and
outputs/p3_forecast_manifest.csv. Read only.

Run from the repository root:
    python3 docs/research/slc-v2-p3-defense-2026-11-02/p3_eval.py
"""
import collections
import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p3_defense as p3  # noqa: E402
import p2_usage as p2  # noqa: E402
from pbv1_sampler import game_bootstrap_ci, BOOTSTRAP_DRAWS, BOOTSTRAP_SEED  # noqa: E402

RAW = '/root/gridiron-playbooks-research/data/raw'
OUT = os.path.join(HERE, 'outputs')
SEASONS = (2022, 2023, 2024)
EVAL = (2023, 2024)
OUTCOMES = ('receiving_WR', 'receiving_TE', 'receiving_RB', 'rushing_RB', 'passing_QB')
STRENGTH = {'receiving_WR': 'pass', 'receiving_TE': 'pass', 'receiving_RB': 'pass', 'rushing_RB': 'run',
            'passing_QB': 'pass'}


def load_observations(positions, kickoffs):
    import pandas as pd
    frames = []
    for season in SEASONS:
        pbp = pd.read_csv(os.path.join(RAW, f'pbp_{season}.csv.gz'), compression='gzip', low_memory=False,
                          usecols=['game_id', 'season_type', 'posteam', 'defteam', 'play_type', 'yards_gained',
                                   'passer_player_id', 'rusher_player_id', 'receiver_player_id', 'sack'])
        frames.append(pbp[pbp['season_type'] == 'REG'].assign(season=season))
    pbp = pd.concat(frames, ignore_index=True)
    pbp = pbp[pbp['play_type'].isin(['pass', 'run']) & pbp['defteam'].notna() & pbp['posteam'].notna()]
    obs = collections.defaultdict(lambda: [0, 0.0])
    strength_sum = collections.defaultdict(lambda: [0, 0.0])
    for row in pbp.itertuples(index=False):
        yards = 0.0 if pd.isna(row.yards_gained) else float(row.yards_gained)
        if row.play_type == 'pass':
            if not pd.isna(row.receiver_player_id):
                group = positions.get(row.receiver_player_id)
                if group in ('WR', 'TE', 'RB'):
                    key = (row.season, row.game_id, row.defteam, row.posteam, f'receiving_{group}')
                    obs[key][0] += 1
                    obs[key][1] += yards
            if not pd.isna(row.passer_player_id) and row.sack != 1:
                strength_sum[(row.season, row.posteam, 'pass')][0] += 1
                strength_sum[(row.season, row.posteam, 'pass')][1] += yards
                if positions.get(row.passer_player_id) == 'QB':
                    key = (row.season, row.game_id, row.defteam, row.posteam, 'passing_QB')
                    obs[key][0] += 1
                    obs[key][1] += yards
        else:
            strength_sum[(row.season, row.posteam, 'run')][0] += 1
            strength_sum[(row.season, row.posteam, 'run')][1] += yards
            if not pd.isna(row.rusher_player_id) and positions.get(row.rusher_player_id) == 'RB':
                key = (row.season, row.game_id, row.defteam, row.posteam, 'rushing_RB')
                obs[key][0] += 1
                obs[key][1] += yards
    records = []
    unmatched = 0
    for (season, game, defense, offense, outcome), (opps, yards) in obs.items():
        kickoff = kickoffs.get(game)
        if kickoff is None:
            unmatched += 1
            continue
        records.append({'season': season, 'game_id': game, 'kickoff': kickoff, 'defense': defense,
                        'offense': offense, 'outcome': outcome, 'opportunities': opps,
                        'yards': yards / opps if opps else None})
    return records, strength_sum, unmatched


def season_strength(strength_sum, season, kind):
    offenses = {k[1]: v for k, v in strength_sum.items() if k[0] == season and k[2] == kind}
    total_n = sum(v[0] for v in offenses.values())
    total_y = sum(v[1] for v in offenses.values())
    league = total_y / total_n
    per_offense = {team: (v[1] / v[0]) for team, v in offenses.items() if v[0] > 0}
    return per_offense, league


def main():
    positions = p2.load_positions()
    kickoffs = p2.load_kickoffs()
    records, strength_sum, unmatched = load_observations(positions, kickoffs)
    if unmatched:
        raise SystemExit(f'{unmatched} defense-game observations without a kickoff; fix the join first')
    results = {'k_yards': p3.K_YARDS, 'lag_hours': p2.AVAILABILITY_LAG_HOURS,
               'bootstrap': {'draws': BOOTSTRAP_DRAWS, 'seed': BOOTSTRAP_SEED}, 'seasons': []}
    manifest = []
    for season in EVAL:
        prior_season = season - 1
        strengths = {kind: season_strength(strength_sum, prior_season, kind) for kind in ('pass', 'run')}
        for outcome in OUTCOMES:
            kind = STRENGTH[outcome]
            offense_strength, league_strength = strengths[kind]
            prior_rows = [r for r in records if r['season'] == prior_season and r['outcome'] == outcome]
            league = sum(r['yards'] * r['opportunities'] for r in prior_rows) / sum(r['opportunities'] for r in prior_rows)
            rows = [r for r in records if r['season'] == season and r['outcome'] == outcome]
            by_defense = collections.defaultdict(list)
            for r in rows:
                by_defense[r['defense']].append(r)
            per_game = collections.defaultdict(lambda: [0.0, 0])
            comp, noadj, base, volume, late = [], [], [], [], 0
            for target in rows:
                if not target['opportunities']:
                    continue
                y = target['yards']
                history = by_defense[target['defense']]
                feature = p3.defense_feature(history, target, league, offense_strength, k=p3.K_YARDS,
                                             league_strength=league_strength)
                plain = p3.defense_feature(history, target, league, None, k=p3.K_YARDS)
                c_err = (y - feature['prediction']) ** 2
                n_err = (y - plain['prediction']) ** 2
                b_err = (y - league) ** 2
                comp.append(c_err)
                noadj.append(n_err)
                base.append(b_err)
                volume.append(feature['volume_mean'])
                per_game[target['game_id']][0] += b_err - c_err
                per_game[target['game_id']][1] += 1
                used = set(feature['game_ids_used'])
                latest = max((g['kickoff'] for g in history if g['game_id'] in used), default=None)
                passed = latest is None or latest + dt.timedelta(hours=p2.AVAILABILITY_LAG_HOURS) <= feature['cutoff']
                late += 0 if passed else 1
                manifest.append({'season': season, 'outcome': outcome, 'defense': target['defense'],
                                 'offense': target['offense'], 'game_id': target['game_id'],
                                 'cutoff_utc': feature['cutoff'].isoformat(), 'games_used': feature['games_used'],
                                 'latest_used_kickoff_utc': latest.isoformat() if latest else '',
                                 'availability_check_passed': passed,
                                 'opponent_strength_source': f'{prior_season} {kind} yards per attempt',
                                 'prediction': round(feature['prediction'], 5), 'observed': round(y, 5)})
            if late:
                raise AssertionError(f'{season} {outcome}: {late} forecasts used a game after its cutoff')
            n = len(comp)
            ci = game_bootstrap_ci([tuple(v) for v in per_game.values()])
            results['seasons'].append({
                'season': season, 'outcome': outcome, 'targets': n, 'league_prior': round(league, 4),
                'mean_volume_per_defense_game': round(sum(volume) / n, 2),
                'mse_component': round(sum(comp) / n, 6), 'mse_no_opponent_adjust': round(sum(noadj) / n, 6),
                'mse_league_baseline': round(sum(base) / n, 6),
                'improvement_over_league_baseline': round((sum(base) - sum(comp)) / n, 6),
                'improvement_over_league_baseline_ci95': [round(v, 6) for v in ci],
                'improvement_over_no_opponent_adjust': round((sum(noadj) - sum(comp)) / n, 6),
                'late_violations': late,
            })
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, 'p3_results.json'), 'w', encoding='utf-8') as handle:
        json.dump(results, handle, indent=2)
    with open(os.path.join(OUT, 'p3_forecast_manifest.csv'), 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        writer.writerows(manifest)
    for row in results['seasons']:
        print(row)
    print('manifest rows', len(manifest))


if __name__ == '__main__':
    main()
