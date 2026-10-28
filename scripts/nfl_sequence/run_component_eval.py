"""Component models on the play-call protocol: score-by-clock alone and team tendency alone (research, not adopted).

Each component is fitted with only its own groups plus the intercept. Its penalties and recency are tuned on the 2023 validation
season only (fit 2010 to 2022), then it is tested chronologically: fit 2010 to 2023 and score 2024, fit 2010 to 2024 and score 2025.
Primary plays only, excluding flagged score exceptions. Reference rows are the league prior, the 24-cell baseline and the full
committed model (penalties and recency taken from the committed report, which were also chosen on 2023).

Paired differences are per-play loss averages with a bootstrap over whole games within each test season.

Usage: python3 run_component_eval.py --cache NPZ --report JSON --out JSON
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import playcall_model as pm  # noqa: E402
import playcall_uncertainty as pu  # noqa: E402
import run_playcall_eval as rpe  # noqa: E402

TEST_SEASONS = (2024, 2025)
VALIDATION = 2023
COMPONENTS = {
    'score_clock_only': ('score', 'clock', 'score_clock'),
    'team_tendency_only': ('team_down',),
}


def log(message):
    print(f'{time.strftime("%H:%M:%S")} {message}', file=sys.stderr, flush=True)


def tune(design, frame, groups):
    """Penalties and recency for one component, chosen on the 2023 validation season only."""
    a = frame.a
    primary = ~a['flagged']
    train = rpe.rows_for(a['season'], primary, range(2010, VALIDATION), primary=True)
    val = rpe.rows_for(a['season'], primary, (VALIDATION,), primary=True)
    prep = pm.prepare(design, train, groups)
    val_X = design.X[val][:, prep['cols']]
    y_train, y_val = a['y'][train].astype(float), a['y'][val]
    season_train = a['season'][train]
    penalties = {g: 10.0 for g in pm.GROUP_NAMES}

    loss, tau, beta = float('inf'), None, None
    for candidate_tau in rpe.TAU_GRID:
        weights = pm.recency_weights(season_train, VALIDATION, candidate_tau)
        b, _ = pm.fit_prepared(design, prep, y_train, weights, penalties)
        value = pm.log_loss(pm.expit(val_X @ b), y_val)
        if value < loss:
            loss, tau, beta = value, candidate_tau, b
    weights = pm.recency_weights(season_train, VALIDATION, tau)
    for _ in range(2):
        for g in groups:
            for value in rpe.GRID:
                trial = dict(penalties, **{g: value})
                candidate, nit = pm.fit_prepared(design, prep, y_train, weights, trial, start=beta)
                trial_loss = pm.log_loss(pm.expit(val_X @ candidate), y_val)
                log(f'tune {g}={value}: validation log loss {trial_loss:.6f} ({nit} iterations)')
                if trial_loss < loss:
                    loss, penalties, beta = trial_loss, trial, candidate
    return {g: penalties[g] for g in groups}, tau, loss


def predict(frame, design, groups, penalties, tau, season):
    a = frame.a
    primary = ~a['flagged']
    train = rpe.rows_for(a['season'], primary, range(2010, season), primary=True)
    test = rpe.rows_for(a['season'], primary, (season,), primary=True)
    prep = pm.prepare(design, train, groups)
    weights = pm.recency_weights(a['season'][train], season, tau)
    beta, _ = pm.fit_prepared(design, prep, a['y'][train].astype(float), weights, penalties)
    return pm.predict_prepared(design, prep['cols'], beta, test), train, test


def metrics(p, y):
    return {'log_loss': pm.log_loss(p, y), 'brier': pm.brier(p, y), 'ece': pm.calibration_error(p, y)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    args = ap.parse_args()

    committed = json.loads(args.report.read_text())
    frame = pm.load_frame_cached(args.cache, range(2010, 2026), include_flagged=True, db=args.db)
    log(f'frame: {len(frame)} rows from {frame.cache_status}, content {pm.frame_content_hash(frame)[:12]}')
    games = np.asarray(frame.games)[frame.a['game']]
    design = pm.Design(frame)

    tuned, out = {}, {'inputs': {'cache': str(args.cache), 'cache_status': frame.cache_status,
                                 'frame_sha256': pm.frame_content_hash(frame), 'report': str(args.report),
                                 'report_sha256': pu.pco.sha256(args.report), 'db': str(args.db)},
                      'protocol': {'validation_season': VALIDATION, 'test_seasons': list(TEST_SEASONS),
                                   'primary_plays_only': True, 'tuning': 'coordinate search over the component groups on 2023'},
                      'tuned': {}, 'tests': {}}
    for name, groups in COMPONENTS.items():
        started = time.time()
        penalties, tau, validation = tune(design, frame, groups)
        tuned[name] = (groups, penalties, tau)
        out['tuned'][name] = {'groups': list(groups), 'penalties': penalties, 'recency_tau': tau,
                              'validation_2023_log_loss': round(validation, 6), 'seconds': round(time.time() - started, 2)}
        log(f'{name}: penalties {penalties}, tau {tau}, validation log loss {validation:.6f}')

    models = {'full_committed': (pm.GROUP_NAMES, committed['chosen_penalties'], committed['chosen_recency_tau']), **tuned}
    for season in TEST_SEASONS:
        probs, train, test = {}, None, None
        for name, (groups, penalties, tau) in models.items():
            probs[name], train, test = predict(frame, design, groups, penalties, tau, season)
        y = frame.a['y'][test]
        base = pu.baselines(frame, train, test)
        probs_all = {**base, **probs}
        losses = {name: pu.per_play_losses(p, y) for name, p in probs_all.items()}
        block = {'train_plays': int(len(train)), 'test_plays': int(len(test)),
                 'metrics': {name: metrics(p, y) for name, p in probs_all.items()},
                 'reduction_vs_baseline': {}, 'component_minus_full': {}}
        for name in models:
            block['reduction_vs_baseline'][name] = {
                b: {metric: pu.paired(losses[b][metric], losses[name][metric], games[test]) for metric in pu.METRICS}
                for b in base}
            if name != 'full_committed':
                block['component_minus_full'][name] = {
                    metric: pu.paired(losses[name][metric], losses['full_committed'][metric], games[test])
                    for metric in pu.METRICS}
        out['tests'][str(season)] = block
        for name in models:
            log(f'{season} {name}: log loss {block["metrics"][name]["log_loss"]:.6f}, Brier {block["metrics"][name]["brier"]:.6f}, '
                f'ECE {block["metrics"][name]["ece"]:.4f}')
    for name in base:
        log(f'baseline {name}: log loss {pm.log_loss(base[name], y):.6f}, Brier {pm.brier(base[name], y):.6f}')

    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    log(f'wrote {args.out}')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise
