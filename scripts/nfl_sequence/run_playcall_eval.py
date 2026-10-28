"""Chronological evaluation of the situational play-calling model (research).

Validation: fit 2010 to 2022, score 2023. Penalties and recency are chosen there and nowhere else.
Tests: 2024 is fitted on 2010 to 2023; 2025 is fitted on 2010 to 2024. 2026 is never read.
Main results exclude plays whose score is flagged as a continuity exception. The sensitivity run includes them.

Each stage's wall-clock time and the number of L-BFGS iterations are written to the report, so runtime can be compared between
runs. The frame is cached in --cache, and a cache is reused only when its fingerprint matches the current sources.

Report version 2 scores the scenario table with the hierarchical_full fit. Version 1 scored it with the no_team fit, which was a
labelling error. Version 1 is kept as committed, and its other values are unchanged.

Usage: python3 run_playcall_eval.py --out JSON --cache NPZ
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_model as pm  # noqa: E402

GRID = (0.3, 3.0, 30.0, 300.0)
TAU_GRID = (None, 6.0, 3.0)
VALIDATION = 2023
ABLATIONS = {
    'hierarchical_full': pm.GROUP_NAMES,
    'no_team': tuple(g for g in pm.GROUP_NAMES if g != 'team_down'),
    'no_score_clock': tuple(g for g in pm.GROUP_NAMES if g != 'score_clock'),
    'no_era': tuple(g for g in pm.GROUP_NAMES if g != 'season'),
}
TESTS = (2024, 2025)
SCENARIOS = (
    ('2nd and 6, Q4 2 minutes, trailing by 7', 2, 6, 'opp_side', -7, 'q4_2min'),
    ('2nd and 6, Q4 2 minutes, tied', 2, 6, 'opp_side', 0, 'q4_2min'),
    ('2nd and 6, Q4 2 minutes, leading by 3', 2, 6, 'opp_side', 3, 'q4_2min'),
    ('2nd and 6, Q1, tied', 2, 6, 'opp_side', 0, 'q1'),
    ('2nd and 6, Q1, trailing by 7', 2, 6, 'opp_side', -7, 'q1'),
    ('3rd and 7, Q4 early, trailing by 4', 3, 7, 'opp_side', -4, 'q4'),
    ('3rd and 7, Q4 early, leading by 4', 3, 7, 'opp_side', 4, 'q4'),
)


def log(message):
    """Progress goes to stderr, unbuffered, so a long run shows where it is."""
    print(f'{time.strftime("%H:%M:%S")} {message}', file=sys.stderr, flush=True)


class Timer:
    def __init__(self):
        self.stages, self.iterations, self.fits = {}, 0, 0
        self.started = time.time()

    def stage(self, name, started):
        self.stages[name] = round(time.time() - started, 2)

    def fit(self, nit):
        self.iterations += nit
        self.fits += 1


def rows_for(season, primary_mask, seasons, primary):
    """Row indices for the given seasons; primary rows exclude flagged score exceptions."""
    mask = np.isin(season, np.asarray(seasons))
    if primary:
        mask &= primary_mask
    return np.flatnonzero(mask)


def metrics(p, y):
    return {'n': int(len(y)), 'log_loss': pm.log_loss(p, y), 'brier': pm.brier(p, y), 'ece': pm.calibration_error(p, y)}


def tune(design, frame, timer):
    """Coordinate search over the group penalties and recency tau, on the validation season only."""
    a = frame.a
    primary = ~a['flagged']
    train_rows = rows_for(a['season'], primary, range(2010, VALIDATION), primary=True)
    val_rows = rows_for(a['season'], primary, (VALIDATION,), primary=True)
    prep = pm.prepare(design, train_rows, pm.GROUP_NAMES)
    val_X = design.X[val_rows][:, prep['cols']]
    y_train, y_val = a['y'][train_rows].astype(float), a['y'][val_rows]
    season_train = a['season'][train_rows]
    penalties = {g: 10.0 for g in pm.GROUP_NAMES}

    def validation_loss(beta):
        return pm.log_loss(pm.expit(val_X @ beta), y_val)

    best_tau, best_beta, best = None, None, float('inf')
    for tau in TAU_GRID:
        weights = pm.recency_weights(season_train, VALIDATION, tau)
        beta, nit = pm.fit_prepared(design, prep, y_train, weights, penalties)
        timer.fit(nit)
        value = validation_loss(beta)
        log(f'tune recency tau={tau}: validation log loss {value:.6f} ({nit} iterations)')
        if value < best:
            best, best_tau, best_beta = value, tau, beta
    weights = pm.recency_weights(season_train, VALIDATION, best_tau)
    beta = best_beta
    for _ in range(2):
        for g in pm.GROUP_NAMES:
            for value in GRID:
                trial = dict(penalties, **{g: value})
                candidate, nit = pm.fit_prepared(design, prep, y_train, weights, trial, start=beta)
                timer.fit(nit)
                trial_loss = validation_loss(candidate)
                log(f'tune {g}={value}: validation log loss {trial_loss:.6f} ({nit} iterations)')
                if trial_loss < best:
                    best, penalties, beta = trial_loss, trial, candidate
    return penalties, best_tau, best


def slices(frame, rows, p, y):
    out = {}
    for name, values, labels in (
            ('score', frame.a['score'][rows], pm.SCORE_BUCKETS),
            ('clock', frame.a['clock'][rows], pm.CLOCK_BUCKETS),
            ('down', frame.a['down'][rows], ('1', '2', '3', '4'))):
        out[name] = {}
        for code, label in enumerate(labels):
            mask = values == code
            if mask.sum() >= 200:
                out[name][label] = {'n': int(mask.sum()), 'observed_dropback_rate': float(y[mask].mean()),
                                    'model_mean_probability': float(p[mask].mean()),
                                    'log_loss': pm.log_loss(p[mask], y[mask])}
    return out


def team_slices(frame, rows, p_full, p_base, y, names):
    out = {}
    teams = frame.a['team'][rows]
    for code, name in names.items():
        mask = teams == code
        if mask.sum() < 300:
            continue
        out[name] = {'n': int(mask.sum()), 'observed_dropback_rate': float(y[mask].mean()),
                     'full_log_loss': pm.log_loss(p_full[mask], y[mask]),
                     'cell24_log_loss': pm.log_loss(p_base[mask], y[mask])}
    return out


def scenario_table(frame, design, prep_cols, beta, train_rows):
    """Modelled dropback probability for each scenario, next to the observed rate in training plays for the same situation."""
    a = frame.a
    train_mask = np.zeros(len(frame), dtype=bool)
    train_mask[train_rows] = True
    rows = []
    for label, down, dist, field, diff, clock in SCENARIOS:
        model_p = pm.modelled_probability(design, prep_cols, beta, frame.teams, down, dist, field, diff, clock)
        mask = pm.situation_mask(frame, down, dist, field, diff, clock) & train_mask
        observed = float(a['y'][mask].mean()) if mask.any() else None
        rows.append({'situation': label, 'model_dropback_probability': round(model_p, 4),
                     'observed_dropback_rate': None if observed is None else round(observed, 4),
                     'observed_plays_in_training': int(mask.sum())})
    return rows


def evaluate_tests(frame, design, penalties, tau, timer):
    """Fit and score each test season on primary and including-flagged plays, with every ablation and both baselines.

    The scenario table is scored with the hierarchical_full coefficients, which are the full model's predictions.
    """
    a = frame.a
    names = {index: code for code, index in frame.teams.items()}
    primary = ~a['flagged']
    tests = {}
    for test_season in TESTS:
        for include_flagged in (False, True):
            key = f"{test_season}_{'including_flagged' if include_flagged else 'primary'}"
            primary_flag = not include_flagged
            train_rows = rows_for(a['season'], primary, range(2010, test_season), primary=primary_flag)
            test_rows = rows_for(a['season'], primary, (test_season,), primary=primary_flag)
            y_train, y_test = a['y'][train_rows].astype(float), a['y'][test_rows]
            entry = {'train_plays': int(len(train_rows)), 'test_plays': int(len(test_rows))}

            entry['league_prior'] = metrics(np.full(len(test_rows), float(y_train.mean())), y_test)
            rates = pm.cell24(y_train, pm.cell_index(a)[train_rows])
            p_base = rates[pm.cell_index(a)[test_rows]]
            entry['cell24_baseline'] = metrics(p_base, y_test)
            log(f'{key}: train {len(train_rows)} plays, test {len(test_rows)} plays')

            weights = pm.recency_weights(a['season'][train_rows], test_season, tau)
            for label, groups in ABLATIONS.items():
                prep = pm.prepare(design, train_rows, groups)
                beta, nit = pm.fit_prepared(design, prep, y_train, weights, penalties)
                timer.fit(nit)
                p = pm.predict_prepared(design, prep['cols'], beta, test_rows)
                entry[label] = metrics(p, y_test)
                log(f'{key} {label}: test log loss {entry[label]["log_loss"]:.6f} ({nit} iterations)')
                if label == 'hierarchical_full':
                    entry['slices'] = slices(frame, test_rows, p, y_test)
                    entry['by_team'] = team_slices(frame, test_rows, p, p_base, y_test, names)
                    train_sc = a['score'][train_rows] * len(pm.CLOCK_BUCKETS) + a['clock'][train_rows]
                    test_sc = a['score'][test_rows] * len(pm.CLOCK_BUCKETS) + a['clock'][test_rows]
                    support = np.bincount(train_sc, minlength=pm.GROUP_SIZES['score_clock'])[test_sc]
                    entry['coverage_score_clock_cell_ge_30'] = float(np.mean(support >= 30))
                    full_prep, full_beta = prep, beta
            entry['scenarios'] = scenario_table(frame, design, full_prep['cols'], full_beta, train_rows)
            tests[key] = entry
    return tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--cache', type=Path, required=True)
    args = ap.parse_args()
    timer = Timer()

    started = time.time()
    frame = pm.load_frame_cached(args.cache, range(2010, 2026), include_flagged=True)
    timer.stage('frame', started)
    log(f'frame ready: {len(frame)} scrimmage plays in {timer.stages["frame"]}s (cache {args.cache}: {frame.cache_status})')

    started = time.time()
    design = pm.Design(frame)
    timer.stage('design', started)
    log(f'design built: width {design.width}, nonzeros {design.X.nnz} in {timer.stages["design"]}s')

    a = frame.a
    report = {'report_version': 2, 'plays': len(frame), 'flagged_plays': int(a['flagged'].sum()), 'teams': len(frame.teams),
              'design_width': design.width, 'frame_cache': frame.cache_status,
              'frame_content_sha256': pm.frame_content_hash(frame),
              'source_fingerprint_sha256': hashlib.sha256(frame.fingerprint.encode()).hexdigest(),
              'scenario_coefficients': 'hierarchical_full'}

    started = time.time()
    penalties, tau, val_ll = tune(design, frame, timer)
    timer.stage('tune', started)
    report.update({'chosen_penalties': penalties, 'chosen_recency_tau': tau,
                   'validation_2023_log_loss': round(val_ll, 6)})

    started = time.time()
    report['tests'] = evaluate_tests(frame, design, penalties, tau, timer)
    timer.stage('tests', started)

    report['stage_seconds'] = timer.stages
    report['fits'] = timer.fits
    report['lbfgs_iterations'] = timer.iterations
    report['seconds_total'] = round(time.time() - timer.started, 2)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: report[k] for k in ('plays', 'flagged_plays', 'teams', 'design_width', 'chosen_penalties',
                                              'chosen_recency_tau', 'validation_2023_log_loss', 'stage_seconds',
                                              'fits', 'lbfgs_iterations', 'seconds_total')}, indent=1))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise
