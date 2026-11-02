"""Development fold B: train on 2022-2023, validate on 2024. Pre-2026 data only.

Same arm definitions, labels, penalties, K, tau, seed and bootstrap as fold A (fold_a.py), with the helpers copied here so
that this script imports only the pinned SLC modules. Nothing is selected on 2024: A0 keeps the production penalties (chosen
on 2023), A2 keeps K = 20. The reference season is the validation season (2024), as fold A used 2023. Frame equivalence is
checked row for row against the production frame for 2022-2024.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path('/root/lp-slc-v1/scripts/nfl_sequence')
RAW = Path('/root/gridiron-playbooks-research/data/raw')
sys.path.insert(0, str(SCRIPTS))
import e1_drive as e1  # noqa: E402
import playcall_model as pm  # noqa: E402

OUT = Path(__file__).resolve().parent
TRAIN, VALIDATE = (2022, 2023), 2024
REFERENCE = 2024
PENALTIES = {'clock': 0.3, 'down_dist': 0.3, 'down_field': 30.0, 'field': 3.0, 'score': 300.0,
             'score_clock': 3.0, 'season': 3.0, 'team_down': 30.0}
TAU = 3.0
K = 20.0
BOOT = 10000
SEED = 20261102
GATE_LOG_LOSS = 0.001
GATE_BRIER = 0.001
TEAM_CODES = {'LA': 'LAR', 'WAS': 'WSH'}
COLUMNS = ['season', 'season_type', 'game_id', 'play_id', 'posteam', 'play_type', 'qb_kneel', 'qb_spike', 'qb_scramble',
           'down', 'ydstogo', 'yardline_100', 'qtr', 'quarter_seconds_remaining', 'score_differential']


def raw_frame(season):
    df = pd.read_csv(RAW / f'pbp_{season}.csv.gz', compression='gzip', low_memory=False, usecols=COLUMNS)
    df = df[(df.season_type == 'REG') & df.posteam.notna() & df.play_type.isin(['run', 'pass'])
            & (df.qb_kneel.fillna(0) != 1) & (df.qb_spike.fillna(0) != 1)]
    df = df.dropna(subset=['down', 'ydstogo', 'yardline_100', 'qtr', 'score_differential'])
    return df.sort_values(['game_id', 'play_id'])


def arrays_from_raw(df, teams, games):
    n = len(df)
    arrays = {k: np.zeros(n, dtype=np.int64) for k in pm.FRAME_KEYS if k not in ('flagged', 'game')}
    arrays['flagged'] = np.zeros(n, dtype=bool)
    arrays['game'] = np.zeros(n, dtype=np.int64)
    game_index = {g: i for i, g in enumerate(games)}
    for i, row in enumerate(df.itertuples(index=False)):
        arrays['season'][i] = int(row.season)
        arrays['team'][i] = teams.setdefault(TEAM_CODES.get(row.posteam, row.posteam), len(teams))
        arrays['down'][i] = int(row.down) - 1
        arrays['dist'][i] = pm.distance_bucket(int(row.ydstogo))
        arrays['field'][i] = pm.field_bucket(int(row.yardline_100))
        arrays['score'][i] = pm.score_bucket(int(row.score_differential))
        seconds = None if pd.isna(row.quarter_seconds_remaining) else int(row.quarter_seconds_remaining)
        arrays['clock'][i] = pm.clock_bucket(int(row.qtr), seconds)
        arrays['y'][i] = int(row.play_type == 'pass')
        if row.game_id not in game_index:
            game_index[row.game_id] = len(games)
            games.append(row.game_id)
        arrays['game'][i] = game_index[row.game_id]
    return arrays


def production_labels(df):
    return ((df.play_type == 'pass') | (df.qb_scramble == 1)).astype(np.int64).to_numpy()


def key_rows(frame):
    inverse = {i: code for code, i in frame.teams.items()}
    return sorted((int(s), frame.games[int(g)], inverse[int(t)], int(d), int(dist), int(f), int(sc), int(c), int(y))
                  for s, g, t, d, dist, f, sc, c, y in zip(frame.a['season'], frame.a['game'], frame.a['team'],
                                                          frame.a['down'], frame.a['dist'], frame.a['field'],
                                                          frame.a['score'], frame.a['clock'], frame.a['y']))


def key_rows_raw(arrays, df, teams, games, y_prod):
    inverse = {i: code for code, i in teams.items()}
    return sorted((int(s), games[int(g)], inverse[int(t)], int(d), int(dist), int(f), int(sc), int(c), int(y))
                  for s, g, t, d, dist, f, sc, c, y in zip(arrays['season'], arrays['game'], arrays['team'],
                                                          arrays['down'], arrays['dist'], arrays['field'],
                                                          arrays['score'], arrays['clock'], y_prod))


def cells(a):
    down_dist = a['down'] * len(pm.DISTANCE_BUCKETS) + a['dist']
    down_dist_field = down_dist * len(pm.FIELD_BUCKETS) + a['field']
    full = (down_dist_field * len(pm.SCORE_BUCKETS) + a['score']) * len(pm.CLOCK_BUCKETS) + a['clock']
    return down_dist, down_dist_field, full


def cell_model(train, evaluate):
    league = float(train['y'].mean())
    dd_tr, ddf_tr, full_tr = cells(train)
    dd_ev, ddf_ev, full_ev = cells(evaluate)
    n_dd = pm.DOWN_COUNT * len(pm.DISTANCE_BUCKETS)
    n_ddf = n_dd * len(pm.FIELD_BUCKETS)
    n_full = n_ddf * len(pm.SCORE_BUCKETS) * len(pm.CLOCK_BUCKETS)
    c_dd = np.bincount(dd_tr, minlength=n_dd).astype(float)
    s_dd = np.bincount(dd_tr, weights=train['y'], minlength=n_dd)
    p_dd = (s_dd + K * league) / (c_dd + K)
    c_ddf = np.bincount(ddf_tr, minlength=n_ddf).astype(float)
    s_ddf = np.bincount(ddf_tr, weights=train['y'], minlength=n_ddf)
    p_ddf = (s_ddf + K * p_dd[np.arange(n_ddf) // len(pm.FIELD_BUCKETS)]) / (c_ddf + K)
    c_full = np.bincount(full_tr, minlength=n_full).astype(float)
    s_full = np.bincount(full_tr, weights=train['y'], minlength=n_full)
    parent = p_ddf[np.arange(n_full) // (len(pm.SCORE_BUCKETS) * len(pm.CLOCK_BUCKETS))]
    p_full = (s_full + K * parent) / (c_full + K)
    return p_full[full_ev]


def per_play_log_loss(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def game_bootstrap(per_play_diff, inverse, games_n, rng, draws):
    count = np.bincount(inverse, minlength=games_n).astype(float)
    total = np.bincount(inverse, weights=per_play_diff, minlength=games_n)
    estimates = np.empty(draws)
    for i in range(draws):
        pick = rng.integers(0, games_n, size=games_n)
        estimates[i] = total[pick].sum() / count[pick].sum()
    return float(total.sum() / count.sum()), estimates


def run(frame, label):
    a = frame.a
    train_rows = np.flatnonzero(np.isin(a['season'], TRAIN))
    val_rows = np.flatnonzero(a['season'] == VALIDATE)
    design = pm.Design(frame)
    prep = pm.prepare(design, train_rows, pm.GROUP_NAMES)
    weights = pm.recency_weights(a['season'][train_rows], REFERENCE, TAU)
    beta, nit = pm.fit_prepared(design, prep, a['y'][train_rows].astype(float), weights, PENALTIES)
    p0 = pm.predict_prepared(design, prep['cols'], beta, val_rows)

    keys = ('down', 'dist', 'field', 'score', 'clock', 'y')
    train = {k: a[k][train_rows] for k in keys}
    evaluate = {k: a[k][val_rows] for k in keys}
    p2 = cell_model(train, evaluate)
    cell24 = pm.cell24(train['y'], train['down'] * len(pm.DISTANCE_BUCKETS) + train['dist'])
    p_cell24 = cell24[evaluate['down'] * len(pm.DISTANCE_BUCKETS) + evaluate['dist']]
    p_league = np.full(len(val_rows), float(train['y'].mean()))

    y = a['y'][val_rows].astype(float)
    arms = {'A0_control_score_clock_logistic': p0, 'A2_situation_cell_K20': p2,
            'baseline_cell24': p_cell24, 'baseline_league_rate': p_league}
    summary = {}
    for name, p in arms.items():
        ll = per_play_log_loss(p, y)
        br = (p - y) ** 2
        summary[name] = {'plays': int(len(y)), 'log_loss': float(ll.mean()), 'brier': float(br.mean()),
                         'calibration_error': pm.calibration_error(p, y)}

    games_codes, inverse = np.unique(a['game'][val_rows], return_inverse=True)
    rng = np.random.default_rng(SEED)
    ll_diff = per_play_log_loss(p2, y) - per_play_log_loss(p0, y)
    br_diff = (p2 - y) ** 2 - (p0 - y) ** 2
    log_point, log_boot = game_bootstrap(ll_diff, inverse, len(games_codes), rng, BOOT)
    brier_point, brier_boot = game_bootstrap(br_diff, inverse, len(games_codes), rng, BOOT)
    log_ci = [float(np.percentile(log_boot, 2.5)), float(np.percentile(log_boot, 97.5))]
    brier_ci = [float(np.percentile(brier_boot, 2.5)), float(np.percentile(brier_boot, 97.5))]
    gate = bool(-log_point >= GATE_LOG_LOSS and log_ci[1] < 0 and brier_point <= GATE_BRIER)
    return {
        'label': label, 'fit_iterations': nit, 'train_plays': int(len(train_rows)), 'validate_plays': int(len(val_rows)),
        'validate_games': int(len(games_codes)), 'summary': summary,
        'A2_minus_A0': {'log_loss': log_point, 'log_loss_ci95': log_ci, 'brier': brier_point, 'brier_ci95': brier_ci},
        'gate_passed': gate,
    }


def main():
    teams, games = {}, []
    seasons = TRAIN + (VALIDATE,)
    frames_df = {season: raw_frame(season) for season in seasons}
    combined = pd.concat([frames_df[s] for s in seasons])
    arrays = arrays_from_raw(combined, teams, games)
    y_prod = production_labels(combined)
    y_freeze = arrays['y'].copy()

    db = pm.load_frame(seasons, db=e1.DEFAULT_DB, include_flagged=False)
    raw_key = key_rows_raw(arrays, combined, teams, games, y_prod)
    db_key = key_rows(db)
    equal = raw_key == db_key
    mismatch = int(len(set(raw_key) ^ set(db_key))) if not equal else 0
    check = {'rows_raw': len(raw_key), 'rows_db': len(db_key), 'multiset_equal': bool(equal),
             'symmetric_difference_rows': mismatch, 'db_frame_sha256': pm.frame_content_hash(db)}
    if not equal:
        raise SystemExit(json.dumps({'equivalence': check}, indent=1))

    frame_freeze = pm.Frame({**arrays, 'y': y_freeze}, teams, games)
    frame_prod = pm.Frame({**arrays, 'y': y_prod}, teams, games)
    primary = run(frame_freeze, 'primary_freeze_labels_pass_is_dropback')
    sensitivity = run(frame_prod, 'sensitivity_production_intent_scramble_is_dropback')
    report = {'fold': 'B', 'train': list(TRAIN), 'validate': [VALIDATE], 'reference_season': REFERENCE,
              'penalties': PENALTIES, 'recency_tau': TAU, 'K': K, 'bootstrap_draws': BOOT, 'seed': SEED,
              'equivalence_to_production_frame': check, 'primary': primary, 'sensitivity': sensitivity,
              'gate_rule': ('A2 advances only if A0 log loss minus A2 log loss >= 0.001, the paired 95% CI for A2 minus A0 '
                            'excludes 0, and A2 Brier minus A0 Brier <= 0.001. Penalties were chosen on 2023, so 2024 is '
                            'an independent validation for A0.')}
    (OUT / 'fold_b_results.json').write_text(json.dumps(report, indent=1, sort_keys=True) + '\n')
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
