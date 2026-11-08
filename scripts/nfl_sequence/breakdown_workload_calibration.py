"""By-position breakdown of the allocation models (research, exploratory; no game is simulated).

Uses the same rolling, leakage-checked predictions as evaluate_workload_calibration.py and scores them per position group:
RB carries, WR targets, TE targets and QB rushing. Models C (current Dirichlet) and D (in-season adaptive) are scored. Each group is
scored with a beta-binomial on the group's real count, given the team total N, with the group's summed concentration. Players are
split into new (no prior-season usage for the team), returning, and role-changed (position-group share moved by more than
ROLE_CHANGE between the prior season and the current season to date). Eligibility is not verified in this data, so every game is
counted under 'unknown eligibility'. Every prediction is checked to use only games from earlier weeks.
"""
import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate_workload_calibration as ev  # noqa: E402
import player_shares as ps  # noqa: E402
import share_distributions as sd  # noqa: E402

GROUPS = {'receive': {'WR': ('WR',), 'TE': ('TE',), 'RB': ('RB',)}, 'carry': {'RB': ('RB',), 'QB': ('QB',)}}
ROLE_CHANGE = 0.10
INTERVAL_DRAWS = 300


def beta_binomial_loglik(k, n, a, b):
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + math.lgamma(k + a) + math.lgamma(n - k + b) - math.lgamma(n + a + b)
            + math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b))


def player_status(pid, prior_team, prior_total, current_counts, current_total):
    """new: no prior-season usage for this team. role_changed: his own share of team usage moved by more than ROLE_CHANGE
    between the prior season and the current season before this game. Otherwise returning."""
    if prior_team.get(pid, 0) == 0:
        return 'new'
    if current_total > 1 and abs(prior_team[pid] / prior_total - current_counts.get(pid, 0) / current_total) > ROLE_CHANGE:
        return 'role_changed'
    return 'returning'


def score(db, season, role, last_week=None, seed=0):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        games = ev.load_games(con, season, role, last_week)
        prior_games = ev.load_games(con, season - 1, role)
        pooled_games = [g for s in range(ps.FIRST_SEASON, season) for g in ev.load_games(con, s, role)]
    finally:
        con.close()
    positions = sd.player_positions(db)
    prior_by_team = ev.team_totals(prior_games)
    pooled_by_team = ev.team_totals(pooled_games)
    phi_c = sd.fit_from_counts(*ev._fit_inputs(prior_games), season - 1)['phi']
    table_a = ev.rank_table(prior_games, positions)
    rng = np.random.default_rng(seed)
    earlier = defaultdict(list)
    rows = []
    checks = {'games_scored': 0, 'future_game_used': 0}
    for game in games:
        team = game['team']
        made = ev.predictions(game, earlier, prior_by_team, pooled_by_team, table_a, positions, phi_c)
        for past in earlier[team]:
            if past['week'] >= game['week']:
                checks['future_game_used'] += 1
        if made is None or sum(game['counts'].values()) == 0:
            earlier[team].append(game)
            continue
        candidates, inputs = made
        checks['games_scored'] += 1
        total = sum(game['counts'].get(p, 0) for p in candidates) + sum(
            n for p, n in game['counts'].items() if p not in candidates)
        prior_team = prior_by_team.get(team, {})
        prior_total = sum(prior_team.values()) or 1
        current_counts = defaultdict(int)
        for past in earlier[team]:
            for p, n in past['counts'].items():
                current_counts[p] += n
        current_total = sum(current_counts.values()) or 1
        for group_name, allowed in GROUPS[role].items():
            members = [p for p in candidates if positions.get(p, '?') in allowed]
            if not members:
                continue
            group_real = sum(n for p, n in game['counts'].items() if positions.get(p, '?') in allowed)
            for model in ('C', 'D'):
                share, phi = inputs[model]
                group_mass = sum(share[p] for p in members)
                a = phi * group_mass
                b = phi * (1 - group_mass)
                nll = -beta_binomial_loglik(group_real, total, a, b) if b > 0 and a > 0 else float('nan')
                rng_draws = rng.beta(max(a, 1e-9), max(b, 1e-9), size=INTERVAL_DRAWS)
                lo, hi = np.quantile(rng_draws * total, [0.1, 0.9])
                covered = int(lo <= group_real <= hi)
                for p in members:
                    real_share = game['counts'].get(p, 0) / total
                    model_share = share[p]
                    rows.append({'model': model, 'group': group_name, 'game_id': game['game_id'], 'week': game['week'],
                                 'team': team, 'player': p, 'status': player_status(
                                     p, prior_team, prior_total, current_counts, current_total),
                                 'unknown_eligibility': 1, 'abs_share_error': abs(real_share - model_share),
                                 'group_nll': nll, 'group_covered': covered, 'total': total})
        earlier[team].append(game)
    return rows, checks, phi_c


def summarise(rows):
    out = {}
    for model in ('C', 'D'):
        for group in sorted({r['group'] for r in rows}):
            sub = [r for r in rows if r['model'] == model and r['group'] == group]
            if not sub:
                continue
            games_seen = {(r['game_id'], r['team']) for r in sub}
            key = f'{model}:{group}'
            nll_rows = {(r['game_id'], r['team'], r['group']): r['group_nll'] for r in sub if not math.isnan(r['group_nll'])}
            out[key] = {
                'team_games': len(games_seen), 'player_rows': len(sub),
                'group_nll_mean': float(np.mean(list(nll_rows.values()))) if nll_rows else None,
                'abs_share_error_mean': float(np.mean([r['abs_share_error'] for r in sub])),
                'interval_80_coverage_group': float(np.mean(list({(r['game_id'], r['team'], r['group']): r['group_covered']
                                                                  for r in sub}.values()))),
                'by_status': {status: {'player_rows': sum(1 for r in sub if r['status'] == status),
                                       'abs_share_error_mean': float(np.mean([r['abs_share_error'] for r in sub
                                                                              if r['status'] == status]))
                                       if any(r['status'] == status for r in sub) else None}
                              for status in ('new', 'returning', 'role_changed')},
                'unknown_eligibility_rows': sum(r['unknown_eligibility'] for r in sub),
            }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='/root/legendarypicks/backend/data/picks.dev.db')
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--role', choices=('receive', 'carry'), required=True)
    ap.add_argument('--last-week', type=int, default=None)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    rows, checks, phi_c = score(args.db, args.season, args.role, args.last_week)
    if checks['future_game_used']:
        raise AssertionError(f"{checks['future_game_used']} predictions used a game from the same or a later week")
    summary = summarise(rows)
    Path(args.out).write_text(json.dumps({'season': args.season, 'role': args.role, 'last_week': args.last_week,
                                          'phi_c': phi_c, 'checks': checks, 'summary': summary,
                                          'role_change_threshold': ROLE_CHANGE, 'eligibility': 'unknown for all rows'},
                                         indent=1, sort_keys=True) + '\n')
    print(json.dumps({'checks': checks, 'summary': summary}, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
