"""Fit adaptive within-position concentrations using prior-season, rolling-week predictions."""
import argparse
import gzip
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import breakdown_workload_calibration as breakdown
import evaluate_workload_calibration as ev
import player_shares as ps
import share_distributions as sd


def samples(db, season, role, last_week=None, frozen=None):
    if frozen is not None:
        def load(year):
            return frozen['games'].get(str(year), {}).get(role, [])
        games = [game for game in load(season) if last_week is None or game['week'] <= last_week]
        prior = load(season - 1)
        pooled = [game for year in range(ps.FIRST_SEASON, season) for game in load(year)]
        positions = frozen['positions']
    else:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            games = ev.load_games(con, season, role, last_week)
            prior = ev.load_games(con, season - 1, role)
            pooled = [g for year in range(ps.FIRST_SEASON, season) for g in ev.load_games(con, year, role)]
        finally:
            con.close()
        positions = sd.player_positions(db)
    prior_team, pooled_team = ev.team_totals(prior), ev.team_totals(pooled)
    rank = ev.rank_table(prior, positions)
    earlier = defaultdict(list)
    out = defaultdict(list)
    for game in games:
        team = game['team']
        if any(g['week'] >= game['week'] for g in earlier[team]):
            raise ValueError('same-week or future training data')
        prediction = ev.predictions(game, earlier, prior_team, pooled_team, rank, positions, 1.0)
        if prediction:
            candidates, models = prediction
            for group, allowed in breakdown.GROUPS[role].items():
                members = [p for p in candidates if positions.get(p) in allowed]
                if members:
                    out[group].append((game['counts'], candidates, members, models['D'][0], positions, allowed))
        earlier[team].append(game)
    return out


def fit(training):
    result = {}
    for group, rows in training.items():
        scores = [(phi, sum(breakdown.within_group_nll(*row[:4], phi, *row[4:]) for row in rows))
                  for phi in sd.PHI_GRID]
        phi, nll = min(scores, key=lambda pair: pair[1])
        result[group] = {'phi': phi, 'team_games': len(rows), 'training_nll': nll,
                         'grid_boundary': phi in (min(sd.PHI_GRID), max(sd.PHI_GRID))}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db')
    parser.add_argument('--frozen-input')
    parser.add_argument('--train-season', type=int, required=True)
    parser.add_argument('--test-season', type=int, required=True)
    parser.add_argument('--last-week', type=int)
    parser.add_argument('--role', choices=tuple(breakdown.GROUPS), required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.train_season >= args.test_season:
        raise ValueError('training season must precede test season')
    if not args.db and not args.frozen_input:
        parser.error('provide --db or --frozen-input')
    frozen = json.load(gzip.open(args.frozen_input, 'rt')) if args.frozen_input else None
    fitted = fit(samples(args.db, args.train_season, args.role, frozen=frozen))
    heldout = samples(args.db, args.test_season, args.role, args.last_week, frozen=frozen)
    for group, fit_result in fitted.items():
        rows = heldout.get(group, [])
        fit_result['heldout_team_games'] = len(rows)
        fit_result['heldout_mean_nll'] = (sum(breakdown.within_group_nll(*row[:4], fit_result['phi'], *row[4:])
                                               for row in rows) / len(rows)) if rows else None
    Path(args.out).write_text(json.dumps({'train_season': args.train_season, 'test_season': args.test_season,
                                         'last_week': args.last_week, 'role': args.role,
                                         'eligibility': 'unknown', 'groups': fitted}, indent=2) + '\n')


if __name__ == '__main__':
    main()
