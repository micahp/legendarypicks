"""Compare every V2 ablation arm with the control on the same games and seeds (spec section 7).

Reads grade.py's grading.json and the arm outputs. Each arm minus A00, with a 95% game-bootstrap interval (2,000
resamples of the 13 games). Log loss clips probabilities to [0.025, 0.975]: with 20 seeds a probability can be 0 or 1.
Usage: python3 compare_arms.py --grading grading.json --runs RUNS_DIR --out FILE
"""
import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

CLIP = 0.025


def ll(p, y):
    p = min(max(p, CLIP), 1 - CLIP)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def per_game_metrics(grading):
    """{model: {game: {metric: value}}} for game lines, and prop sums per game."""
    out = defaultdict(lambda: defaultdict(dict))
    for r in grading['game_rows']:
        m = out[r['model']][r['game_id']]
        m['win_brier'] = (r['home_win'] - r['home_won']) ** 2
        m['win_logloss'] = ll(r['home_win'], r['home_won'])
        m['cover_brier'] = (r['home_cover'] - r['home_covered']) ** 2
        m['over_brier'] = (r['over'] - r['went_over']) ** 2
        m['total_abs_error'] = abs(r['mean_total'] - r['actual_total'])
        m['margin_abs_error'] = abs(r['mean_margin'] - r['actual_margin'])
        m['valid_share'] = r['valid_full_games'] / r['requested_games']
    props = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0]))
    for r in grading['prop_rows']:
        if r.get('went_over') is None or r.get('sim_p_over') is None:
            continue
        cell = props[r['model']][r['game_id']]
        cell[0] += (r['sim_p_over'] - r['went_over']) ** 2
        cell[1] += ll(r['sim_p_over'], r['went_over'])
        cell[2] += 1
    return out, props


def boot(diffs_by_game, weights=None, reps=2000, seed=11):
    games = sorted(diffs_by_game)
    rng = random.Random(seed)
    def stat(sample):
        if weights is None:
            return mean(diffs_by_game[g] for g in sample)
        return sum(diffs_by_game[g] for g in sample) / max(sum(weights[g] for g in sample), 1)
    point = stat(games)
    draws = sorted(stat([rng.choice(games) for _ in games]) for _ in range(reps))
    return [round(point, 5), round(draws[int(0.025 * reps)], 5), round(draws[int(0.975 * reps)], 5)]


def team_points(runs, model):
    """Per team-game mean simulated points, and the SD across the 26 team-games."""
    pts = []
    for game_dir in sorted(Path(runs).glob('2026_11_*')):
        d = json.loads((game_dir / f'{model}.json').read_text())
        valid = [o for o in d['summary']['outcomes'] if o.get('valid_full_game')]
        if valid:
            pts.append(mean(o['home_points'] for o in valid))
            pts.append(mean(o['away_points'] for o in valid))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grading', required=True, type=Path)
    ap.add_argument('--runs', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    grading = json.loads(args.grading.read_text())
    games, props = per_game_metrics(grading)
    control = 'A00_control'
    actual = [s for g in grading['final_scores'].values() for s in (g['home'], g['away'])] \
        if isinstance(next(iter(grading['final_scores'].values())), dict) else None
    result = {'control': control, 'clip': CLIP, 'games': len(games[control]), 'arms': {}}
    for model in sorted(games):
        row = {}
        for metric in ('win_brier', 'win_logloss', 'cover_brier', 'over_brier', 'total_abs_error', 'margin_abs_error',
                       'valid_share'):
            row[metric] = round(mean(games[model][g][metric] for g in games[model]), 5)
            if model != control:
                row[metric + '_minus_control'] = boot({g: games[model][g][metric] - games[control][g][metric]
                                                       for g in games[model]})
        n = sum(props[model][g][2] for g in props[model])
        row['props_n'] = n
        row['prop_brier'] = round(sum(props[model][g][0] for g in props[model]) / n, 5)
        row['prop_logloss'] = round(sum(props[model][g][1] for g in props[model]) / n, 5)
        if model != control:
            w = {g: props[model][g][2] for g in props[model]}
            row['prop_brier_minus_control'] = boot({g: props[model][g][0] - props[control][g][0] for g in w}, w)
            row['prop_logloss_minus_control'] = boot({g: props[model][g][1] - props[control][g][1] for g in w}, w)
        pts = team_points(args.runs, model)
        row['team_points_mean'] = round(mean(pts), 3)
        row['team_points_sd'] = round(pstdev(pts), 3)
        result['arms'][model] = row
    if actual:
        result['actual_team_points_mean'] = round(mean(actual), 3)
        result['actual_team_points_sd'] = round(pstdev(actual), 3)
    args.out.write_text(json.dumps(result, indent=1) + '\n')
    hdr = f"{'arm':34} {'winB':>6} {'dWinB':>22} {'propB':>6} {'dPropB':>24} {'dPropLL':>24} {'valid':>5} {'ptsSD':>5}"
    print(hdr)
    for model, r in result['arms'].items():
        print(f"{model:34} {r['win_brier']:6.3f} {str(r.get('win_brier_minus_control', '')):>22} {r['prop_brier']:6.4f} "
              f"{str(r.get('prop_brier_minus_control', '')):>24} {str(r.get('prop_logloss_minus_control', '')):>24} "
              f"{r['valid_share']:5.2f} {r['team_points_sd']:5.2f}")


if __name__ == '__main__':
    main()
