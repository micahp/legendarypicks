"""Paired, game-clustered uncertainty and feature contributions for the play-call model (research, not adopted).

The penalties and recency come from the committed evaluation report, and nothing is re-chosen here. Each block refits the models
it names on the split the report used: 2023 is the development block (fit on 2010 to 2022, and used to choose the penalties), and
2024 and 2025 are the test blocks (fit on all earlier seasons). Results use primary plays, which exclude flagged score exceptions.

Differences are per-play paired losses averaged over a block. Their intervals come from a bootstrap that resamples whole games
within the block, so plays from one game are not treated as independent. Game identity is stored in the frame itself.

Usage: python3 playcall_uncertainty.py --cache NPZ --report JSON --out JSON
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import scipy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import playcall_model as pm  # noqa: E402
import playcall_observations as pco  # noqa: E402
import run_playcall_eval as rpe  # noqa: E402

BOOTSTRAP_REPS = 2000
SEED = 20261028
FIRST_SEASON, LAST_SEASON = 2010, 2025
DEVELOPMENT_SEASON = 2023
TEST_SEASONS = (2024, 2025)
BLOCKS = (DEVELOPMENT_SEASON,) + TEST_SEASONS
METRICS = ('log_loss', 'brier')
ABLATIONS = {name: rpe.ABLATIONS[name] for name in ('no_score_clock', 'no_team', 'no_era')}
ABLATIONS['no_score_and_clock'] = tuple(g for g in pm.GROUP_NAMES if g not in ('score', 'clock', 'score_clock'))


def log(message):
    print(f'{time.strftime("%H:%M:%S")} {message}', file=sys.stderr, flush=True)


def fit_predict(frame, design, train, test, groups, penalties, tau, season):
    a = frame.a
    prep = pm.prepare(design, train, groups)
    weights = pm.recency_weights(a['season'][train], season, tau)
    beta, nit = pm.fit_prepared(design, prep, a['y'][train].astype(float), weights, penalties)
    return pm.predict_prepared(design, prep['cols'], beta, test), prep, beta, nit


def baselines(frame, train, test):
    a = frame.a
    y_train = a['y'][train].astype(float)
    cells = pm.cell_index(a)
    rates = pm.cell24(y_train, cells[train])
    return {'league_prior': np.full(len(test), y_train.mean()), 'cell24_baseline': rates[cells[test]]}


def per_play_losses(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return {'log_loss': -(y * np.log(p) + (1 - y) * np.log(1 - p)), 'brier': (p - y) ** 2}


def paired(first, second, games):
    """Mean per-play difference (first minus second) with a bootstrap that resamples whole games within the block."""
    diff = first - second
    codes, inverse = np.unique(games, return_inverse=True)
    sums = np.bincount(inverse, weights=diff, minlength=len(codes))
    counts = np.bincount(inverse, minlength=len(codes)).astype(float)
    draws = np.random.default_rng(SEED).integers(0, len(codes), size=(BOOTSTRAP_REPS, len(codes)))
    replicates = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    low, high = np.percentile(replicates, [2.5, 97.5])
    return {'mean_difference': float(diff.mean()), 'ci95': [float(low), float(high)], 'games': int(len(codes))}


def compare(losses, games, first, second):
    return {metric: paired(losses[first][metric], losses[second][metric], games) for metric in METRICS}


def independent_z(y, p, games):
    """Observed minus expected dropbacks in binomial standard deviations, treating every play as independent."""
    return float((y.sum() - p.sum()) / np.sqrt(np.sum(p * (1 - p))))


def game_z(y, p, games):
    """The same deviation with its variance taken from the games themselves, so plays in one game are not counted as
    independent. Each game contributes one residual. Under no unmodelled effect this is about N(0, 1)."""
    codes, inverse = np.unique(games, return_inverse=True)
    residual = np.bincount(inverse, weights=y - p, minlength=len(codes))
    return float(residual.sum() / np.sqrt(np.sum(residual ** 2)))


def team_season_z(y, team, p, games, z_fn):
    z = []
    for code in np.unique(team):
        m = team == code
        z.append(z_fn(y[m], p[m], games[m]))
    z = np.array(z)
    return {'mean_z_squared': float(np.mean(z ** 2)), 'share_abs_z_over_2': float(np.mean(np.abs(z) > 2)),
            'z': [round(float(v), 3) for v in z]}


def diagnose(frame, design, test, probs, full_fit, season, games):
    """Descriptive checks on the out-of-sample predictions. Under no unmodelled team-season or league-level effect, the mean
    squared team-season z is about 1 and the league z is about 0, when the variance is taken by game. The independent-plays
    versions are reported beside them. Nothing here changes a fit."""
    y, team = frame.a['y'][test], frame.a['team'][test]
    prep, beta = full_fit
    groups = design.col_group[prep['cols']]
    season_beta = dict(zip((int(s) for s in design.seasons), beta[groups == pm.GROUP_CODE['season']].tolist()))
    return {
        'test_season_coefficient': season_beta[season],
        'season_coefficients': season_beta,
        'team_down_coefficient_sd': float(np.std(beta[groups == pm.GROUP_CODE['team_down']])),
        'league_z': {name: {'by_game': game_z(y, probs[name], games),
                            'independent_plays': independent_z(y, probs[name], games)}
                     for name in ('full', 'no_team', 'no_era')},
        'team_season_z': {name: {'by_game': team_season_z(y, team, probs[name], games, game_z),
                                 'independent_plays': team_season_z(y, team, probs[name], games, independent_z)}
                          for name in ('full', 'no_team')},
    }


def run_block(frame, design, games, season, penalties, tau):
    a = frame.a
    primary = ~a['flagged']
    train = rpe.rows_for(a['season'], primary, range(FIRST_SEASON, season), primary=True)
    test = rpe.rows_for(a['season'], primary, (season,), primary=True)
    y = a['y'][test]
    log(f'{season}: train {len(train)} plays, test {len(test)} plays')

    probs, full_fit = {}, None
    for name, groups in [('full', pm.GROUP_NAMES)] + list(ABLATIONS.items()):
        p, prep, beta, nit = fit_predict(frame, design, train, test, groups, penalties, tau, season)
        probs[name] = p
        if name == 'full':
            full_fit = (prep, beta)
        log(f'{season} {name}: {nit} iterations')

    base = baselines(frame, train, test)
    losses = {name: per_play_losses(p, y) for name, p in {**base, **probs}.items()}
    metrics = {name: {metric: float(losses[name][metric].mean()) for metric in METRICS} for name in losses}
    if abs(metrics['full']['log_loss'] - pm.log_loss(probs['full'], y)) > 1e-12:
        raise ValueError('per-play losses do not average to the evaluation metric')
    return {
        'train_plays': int(len(train)), 'test_plays': int(len(test)), 'metrics': metrics,
        'loss_reduction_vs_baseline': {name: compare(losses, games[test], name, 'full') for name in base},
        'cost_of_removing': {name: compare(losses, games[test], name, 'full') for name in ABLATIONS},
        'diagnostics': diagnose(frame, design, test, probs, full_fit, season, games[test]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    args = ap.parse_args()

    committed = json.loads(args.report.read_text())
    penalties, tau = committed['chosen_penalties'], committed['chosen_recency_tau']
    frame = pm.load_frame_cached(args.cache, range(FIRST_SEASON, LAST_SEASON + 1), include_flagged=True, db=args.db)
    log(f'frame: {len(frame)} rows from {frame.cache_status}, content {pm.frame_content_hash(frame)[:12]}')
    games = np.asarray(frame.games)[frame.a['game']]
    log(f'games: {len(frame.games)} distinct game ids on {len(games)} plays')
    design = pm.Design(frame)

    a = frame.a
    primary = ~a['flagged']
    league_by_season = {int(s): float(a['y'][primary & (a['season'] == s)].mean()) for s in np.unique(a['season'])}
    blocks = {str(season): {'role': 'development' if season == DEVELOPMENT_SEASON else 'test',
                            **run_block(frame, design, games, season, penalties, tau)} for season in BLOCKS}
    out = {
        'inputs': {'cache': str(args.cache), 'cache_status': frame.cache_status,
                   'frame_sha256': pm.frame_content_hash(frame), 'frame_rows': len(frame),
                   'report': str(args.report), 'report_sha256': pco.sha256(args.report), 'db': str(args.db),
                   'seed': SEED, 'bootstrap_reps': BOOTSTRAP_REPS, 'python': sys.version.split()[0],
                   'numpy': np.__version__, 'scipy': scipy.__version__},
        'chosen': {'penalties': penalties, 'recency_tau': tau},
        'observed_league_dropback_rate_by_season': league_by_season,
        'blocks': blocks,
    }
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    for season in TEST_SEASONS:
        reduction = blocks[str(season)]['loss_reduction_vs_baseline']
        log(f'{season} log loss reduction vs league prior: {reduction["league_prior"]["log_loss"]}')
        log(f'{season} log loss reduction vs 24-cell: {reduction["cell24_baseline"]["log_loss"]}')
    log(f'wrote {args.out}')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise
