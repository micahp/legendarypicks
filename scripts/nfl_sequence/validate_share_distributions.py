"""Chronological held-out check of per-game opportunity shares (research). Fit on one season, score the next, never the reverse.

Both models use the same base shares from the fit season. The fixed-share adapter predicts multinomial counts with those shares. The
Dirichlet-multinomial predicts with per-game shares around them, with phi fitted on the fit season by maximum likelihood. Scored on the
held-out season's team-games: the log-likelihood per team-game (the difference has a bootstrap interval over games), and for each
role's players the observed count mean, variance and zero rate against each model's prediction. Team-games where a player has no fit-
season history are scored on the players that do; the restriction is recorded in the output.

Usage: python3 validate_share_distributions.py --fit-season 2024 --test-season 2025 --out JSON
"""
import argparse
import json
import math
import sqlite3
import statistics
from pathlib import Path

import share_distributions as sdm
import share_validation as sv

DB = '/root/legendarypicks/backend/data/picks.dev.db'


def dm_predictions(total, base, phi):
    """Predicted mean, variance and zero probability of a player's count under the Dirichlet-multinomial (beta-binomial marginal)."""
    a, c = phi * base, phi * (1.0 - base)
    mean = total * base
    variance = total * base * (1.0 - base) * (1.0 + (total - 1) / (phi + 1.0))
    zero = math.exp(math.lgamma(a + c) - math.lgamma(a + c + total) + math.lgamma(c + total) - math.lgamma(c))  # B(a, c+n)/B(a, c)
    return mean, variance, zero


def fixed_predictions(total, base):
    return total * base, total * base * (1.0 - base), (1.0 - base) ** total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fit-season', type=int, default=2024)
    ap.add_argument('--test-season', type=int, default=2025)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    result = {'fit_season': args.fit_season, 'test_season': args.test_season, 'roles': {}}
    for role in ('receive', 'carry'):
        fit_games, fit_season_counts = sdm.team_game_counts(DB, args.fit_season, role)
        fitted = sdm.fit_from_counts(fit_games, fit_season_counts, args.fit_season)
        base = fitted['base']
        phi = fitted['phi']
        test_games, _ = sdm.team_game_counts(DB, args.test_season, role)
        fixed_ll, dm_ll, observed, pred_fixed, pred_dm, test_totals, unit_share, per_game_diff = (
            [], [], defaultdict_list(), defaultdict_list(), defaultdict_list(), defaultdict_list(), {}, [])
        per_game_diff_by_game = defaultdict_list()
        for team, by_game in test_games.items():
            roster = {p: base[(team, p)] for p in fit_season_counts.get(team, {})}
            if not roster:
                continue
            norm = sum(roster.values())
            shares = {p: b / norm for p, b in roster.items()}
            for game, counts in by_game.items():
                kept = {p: n for p, n in counts.items() if p in roster}
                total = sum(kept.values())
                if total == 0:
                    continue
                f = sv.multinomial_loglik(kept, total, shares)
                d = sv.dirichlet_loglik(kept, total, shares, phi)
                fixed_ll.append(f)
                dm_ll.append(d)
                per_game_diff.append(d - f)
                per_game_diff_by_game[game].append(d - f)
                for p, b in shares.items():
                    unit = (team, p)  # keep traded players separate in player-level calibration summaries
                    observed[unit].append(kept.get(p, 0))
                    test_totals[unit].append(total)
                    unit_share[unit] = b
                    mf, vf, zf = fixed_predictions(total, b)
                    md, vd, zd = dm_predictions(total, b, phi)
                    pred_fixed[unit].append((mf, vf, zf))
                    pred_dm[unit].append((md, vd, zd))
        low, high = sv.bootstrap_cluster_mean_interval(per_game_diff_by_game, reps=2000, seed=1)
        units = sorted(observed)
        observed_quantiles = [sv.empirical_count_quantiles(observed[unit]) for unit in units]
        fixed_quantiles = [sv.predictive_quantiles(test_totals[unit], unit_share[unit]) for unit in units]
        dm_quantiles = [sv.predictive_quantiles(test_totals[unit], unit_share[unit], phi=phi) for unit in units]

        def mean_quantiles(summaries):
            return {q: round(statistics.fmean(summary[q] for summary in summaries), 4) for q in ('10', '50', '90')}

        variance_units = [unit for unit in units if len(observed[unit]) > 1]
        obs_var = [statistics.variance(observed[unit]) for unit in variance_units]
        fixed_var = [sv.predictive_sample_variance([(mean, variance) for mean, variance, _zero in pred_fixed[unit]])
                     for unit in variance_units]
        dm_var = [sv.predictive_sample_variance([(mean, variance) for mean, variance, _zero in pred_dm[unit]])
                  for unit in variance_units]
        observed_mean = statistics.fmean(value for unit in units for value in observed[unit])
        fixed_mean = statistics.fmean(mean for unit in units for mean, _var, _zero in pred_fixed[unit])
        dm_mean = statistics.fmean(mean for unit in units for mean, _var, _zero in pred_dm[unit])
        result['roles'][role] = {
            'phi_fit': round(phi, 3), 'phi_interval_fit': [round(x, 3) for x in fitted['phi_interval']],
            'beta_binomial_phi_fit': fitted['beta_binomial_phi'], 'fit_team_games': fitted['team_games'],
            'fit_game_clusters': len({game for by_game in fit_games.values() for game in by_game}),
            'fit_teams': fitted['teams'], 'test_team_games_scored': len(per_game_diff),
            'test_game_clusters_scored': len(per_game_diff_by_game),
            'unique_players_scored': len({player for _team, player in units}), 'player_team_units_scored': len(units),
            'loglik_per_team_game': {'fixed_share': round(statistics.fmean(fixed_ll), 4),
                                     'dirichlet_multinomial': round(statistics.fmean(dm_ll), 4)},
            'dirichlet_minus_fixed_per_team_game': {'mean': round(statistics.fmean(per_game_diff), 4),
                                                    'interval_95': [round(low, 4), round(high, 4)]},
            'calibration': {
                'observed_mean_count': round(observed_mean, 4),
                'fixed_share_predicted_mean_count': round(fixed_mean, 4),
                'dirichlet_predicted_mean_count': round(dm_mean, 4),
                'observed_variance_mean_over_player_team_units': round(statistics.fmean(obs_var), 4),
                'fixed_share_predicted_variance': round(statistics.fmean(fixed_var), 4),
                'dirichlet_predicted_variance': round(statistics.fmean(dm_var), 4),
                'variance_player_team_units': len(variance_units),
                'observed_zero_rate': round(statistics.fmean(1.0 if x == 0 else 0.0 for unit in units for x in observed[unit]), 4),
                'fixed_share_predicted_zero_rate': round(statistics.fmean(z for unit in units for _m, _v, z in pred_fixed[unit]), 4),
                'dirichlet_predicted_zero_rate': round(statistics.fmean(z for unit in units for _m, _v, z in pred_dm[unit]), 4),
                'mean_count_quantiles_over_player_team_units': {
                    'observed': mean_quantiles(observed_quantiles),
                    'fixed_share': mean_quantiles(fixed_quantiles),
                    'dirichlet_multinomial': mean_quantiles(dm_quantiles),
                },
            },
            'restriction': 'team-games scored on the players with fit-season history on the same team; zero-total team-games skipped; uncertainty resamples both teams together by game id',
        }
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, indent=1, sort_keys=True))


def defaultdict_list():
    from collections import defaultdict
    return defaultdict(list)


if __name__ == '__main__':
    main()
