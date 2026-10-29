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
        fixed_ll, dm_ll, observed, pred_fixed, pred_dm, per_game_diff = [], [], defaultdict_list(), defaultdict_list(), \
            defaultdict_list(), []
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
                for p, b in shares.items():
                    observed[p].append(kept.get(p, 0))
                    mf, vf, zf = fixed_predictions(total, b)
                    md, vd, zd = dm_predictions(total, b, phi)
                    pred_fixed[p].append((mf, vf, zf))
                    pred_dm[p].append((md, vd, zd))
        low, high = sv.bootstrap_mean_interval(per_game_diff, reps=2000, seed=1)
        players = sorted(observed)
        obs_var = [statistics.variance(observed[p]) for p in players if len(observed[p]) > 1]
        result['roles'][role] = {
            'phi_fit': round(phi, 3), 'phi_interval_fit': [round(x, 3) for x in fitted['phi_interval']],
            'beta_binomial_phi_fit': fitted['beta_binomial_phi'], 'fit_team_games': fitted['team_games'],
            'test_team_games_scored': len(per_game_diff), 'players_scored': len(players),
            'loglik_per_team_game': {'fixed_share': round(statistics.fmean(fixed_ll), 4),
                                     'dirichlet_multinomial': round(statistics.fmean(dm_ll), 4)},
            'dirichlet_minus_fixed_per_team_game': {'mean': round(statistics.fmean(per_game_diff), 4),
                                                    'interval_95': [round(low, 4), round(high, 4)]},
            'calibration': {
                'observed_variance_mean_over_players': round(statistics.fmean(obs_var), 4),
                'fixed_share_predicted_variance': round(statistics.fmean(v for p in players for _m, v, _z in pred_fixed[p]), 4),
                'dirichlet_predicted_variance': round(statistics.fmean(v for p in players for _m, v, _z in pred_dm[p]), 4),
                'observed_zero_rate': round(statistics.fmean(1.0 if x == 0 else 0.0 for p in players for x in observed[p]), 4),
                'fixed_share_predicted_zero_rate': round(statistics.fmean(z for p in players for _m, _v, z in pred_fixed[p]), 4),
                'dirichlet_predicted_zero_rate': round(statistics.fmean(z for p in players for _m, _v, z in pred_dm[p]), 4),
            },
            'restriction': 'team-games scored on the players with fit-season history on the same team; zero-total team-games skipped',
        }
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps(result, indent=1, sort_keys=True))


def defaultdict_list():
    from collections import defaultdict
    return defaultdict(list)


if __name__ == '__main__':
    main()
