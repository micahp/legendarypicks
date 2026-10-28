"""Game-winner comparison on one common set of games, 2021 to 2025: LP v1 points, LP v2 EPA, S0b, S1, S2, closing market.

Read-only. The LP models are run from the LP backend functions, unchanged:
  - v1 points: nfl_backtest.backtest_season with the frozen configuration (model card, section "v1 points").
  - v2 EPA: nfl_epa_backtest. Its half-life and lambda are chosen on 2024 by the same grid and rule as its tune2024
    stage, then held fixed for 2021 to 2025. Each season uses the previous season as its prior.
  - market: the de-vigged closing moneyline stored with the v1 rows.
Our models (S0b, S1, S2) are rebuilt with s0_baseline.py and s1_s2_models.py, with the same windows: fit 2010 to 2017.

Common set: regular-season games in 2021 to 2025 that satisfy the S0b eligibility rule, are not tied, have a market
number, and have a probability from every model. Intervals are week-block bootstraps (resampling whole season-weeks,
2,000 draws, seed 20261027), paired on the same games.

Usage: python3 game_winner_comparison.py
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s0_baseline as s0  # noqa: E402
import s1_s2_models as s1  # noqa: E402

BACKEND = '/root/legendarypicks/backend'
sys.path.insert(0, BACKEND)
import nfl_epa_backtest as nfe  # noqa: E402
import nfl_epa_model as em  # noqa: E402
import nfl_elo_replica as er  # noqa: E402
import nfl_feature_backtest as fb  # noqa: E402
import nfl_backtest as nb  # noqa: E402
import nfl_metrics as mt  # noqa: E402
import numpy as np  # noqa: E402

RESULTS = '/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/nfl-splits/results'
WINDOW = range(2021, 2026)
S1_HALF_LIFE, S1_LAM = 13.0, 2.0          # chosen on 2018 to 2020 validation (s1_s2_models.py)
V1_SIGMA = 13.295


def epa_setting(con):
    """The tune2024 rule of nfl_epa_backtest: Brier to three decimals, then fewer non-default parameters."""
    v1_2024 = nfe.v1_rows(con, 2024)
    res = []
    for hl in nfe.GRID['half_life']:
        for lam in nfe.GRID['lam']:
            m = nfe.metrics(nfe.run_season(con, 2024, hl, lam), v1_2024)
            nd = (hl != nfe.DEFAULTS['half_life']) + (lam != nfe.DEFAULTS['lam'])
            res.append((round(m['brier_v2'], 3), nd, hl, lam))
    res.sort(key=lambda r: (r[0], r[1]))
    return res[0][2], res[0][3], res


def stack_probs(con):
    """v1 + Elo stack, as lock_nfl_elo.py defines it: margin = b0 + b1 * v1 margin + b2 * pre-game Elo gap, OLS on
    every earlier season's v1 walk-forward rows, win probability = Phi(margin / residual sd). Pre-game Elo is the
    replica's rating before each game, so no result from the game itself is used."""
    games = er.load_games(con)
    pre = er.run_elo(games, er.start_ratings(con))
    neutral = {g[0]: g[2] for g in games}
    rows = {s: nb.backtest_season(con, s, fb.FROZEN) for s in range(2010, max(WINDOW) + 1)}
    out = {}
    for season in WINDOW:
        X, y = [], []
        for s in range(2010, season):
            for r in rows[s]:
                eh, ea = pre[r['game_id']]
                X.append([1.0, r['proj_margin'], eh - ea + (0.0 if neutral[r['game_id']] else er.BASE['hfa'])])
                y.append(r['actual_margin'])
        beta = fb.ols(X, y)
        sigma = float(np.std(np.array(y) - np.array(X) @ beta, ddof=1))
        for r in rows[season]:
            eh, ea = pre[r['game_id']]
            gap = eh - ea + (0.0 if neutral[r['game_id']] else er.BASE['hfa'])
            m = float(beta[0] + beta[1] * r['proj_margin'] + beta[2] * gap)
            out[r['game_id']] = fb.phi(m / sigma)
    return out


def main():
    con = sqlite3.connect(s0.DEV_DB, uri=True)
    hl, lam, grid = epa_setting(con)
    stack = stack_probs(con)
    print('v2 EPA setting chosen on 2024 (half-life, lambda):', hl, lam)

    epa, v1, mkt = {}, {}, {}
    for s in WINDOW:
        prev = (nfe.season_plays(con, s - 1), nfe.sched(con, s - 1), nfe.teams_of(con, s - 1))
        for r, ph, pa, sig in nfe.run_season(con, s, hl, lam, prev=prev):
            epa[r[1]] = em.phi((ph - pa) / sig)
        for gid, x in nfe.v1_rows(con, s).items():
            v1[gid] = x['p_model']
            mkt[gid] = x['p_market']

    games, _ = s1.load_games(con)
    s1.attach_strict(games)
    s1.prior_counts(games)
    fit = [g for g in games if g['strict'] and g['season'] in s0.FIT and g['y'] is not None]
    w0 = s0.fit_logistic([[1.0, g['x']] for g in fit], [g['y'] for g in fit])
    for g in games:
        if g['strict']:
            g['p_s0b'] = s0.sigmoid(w0[0] + w0[1] * g['x'])
    m = s1.ridge_margins(games, S1_HALF_LIFE, S1_LAM)
    for g in games:
        g['m1'] = m[g['game_id']]
    fit_m = [g for g in fit if g['m1'] is not None]
    a, b = s0.fit_logistic([[1.0, g['m1']] for g in fit_m], [g['y'] for g in fit_m])
    w2 = s0.fit_logistic([s1.s2_design(g, s1.GROUPS, 'm1') for g in fit_m], [g['y'] for g in fit_m])
    for g in games:
        if g['m1'] is None:
            continue
        g['p_s1'] = s0.sigmoid(a + b * g['m1'])
        g['p_s2'] = s0.sigmoid(sum(wi * xi for wi, xi in zip(w2, s1.s2_design(g, s1.GROUPS, 'm1'))))

    rows = []
    for g in games:
        gid = g['game_id']
        if g['season'] not in WINDOW or not g['strict'] or g['y'] is None:
            continue
        if any(key not in g for key in ('p_s0b', 'p_s1', 'p_s2')):
            continue
        if gid not in v1 or gid not in epa or gid not in stack or mkt.get(gid) is None:
            continue
        rows.append({'game_id': gid, 'season': g['season'], 'week': g['week'], 'y': g['y'],
                     'market': mkt[gid], 'v1': v1[gid], 'epa': epa[gid], 'stack': stack[gid],
                     'S0b': g['p_s0b'], 'S1': g['p_s1'], 'S2': g['p_s2']})
    print(f'common set: {len(rows)} games, seasons {min(r["season"] for r in rows)} to {max(r["season"] for r in rows)}')

    models = ['market', 'v1', 'epa', 'stack', 'S0b', 'S1', 'S2']
    names = {'market': 'Closing market', 'v1': 'LP v1 points', 'epa': 'LP v2 EPA',
             'stack': 'v1+Elo stack', 'S0b': 'S0b (ours)', 'S1': 'S1 (ours)', 'S2': 'S2 (ours)'}

    def block(rs, label):
        out = {'label': label, 'n': len(rs), 'models': {}}
        for mname in models:
            ps = [r[mname] for r in rs]
            ys = [r['y'] for r in rs]
            out['models'][mname] = {'brier': sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(rs),
                                    'log_loss': mt.log_loss(ps, ys)}
        return out

    subsets = {
        '2021 to 2025 (all)': rows,
        '2021 to 2023 (least examined)': [r for r in rows if r['season'] <= 2023],
        '2024 (EPA setting chosen here)': [r for r in rows if r['season'] == 2024],
        '2025 (v1 and v2 second look)': [r for r in rows if r['season'] == 2025],
    }
    tables = {label: block(rs, label) for label, rs in subsets.items()}

    def paired(rs, a_key, b_key):
        gap, lo, hi = s0.block_bootstrap_brier_gap(rs, [r[a_key] for r in rs], [r[b_key] for r in rs])
        return {'gap': gap, 'lo': lo, 'hi': hi}

    diffs = {}
    for label, rs in subsets.items():
        diffs[label] = {
            'model minus market': {k: paired(rs, k, 'market') for k in ['v1', 'epa', 'stack', 'S0b', 'S1', 'S2']},
            'LP v2 EPA minus LP v1': paired(rs, 'epa', 'v1'),
            'v1+Elo stack minus LP v1': paired(rs, 'stack', 'v1'),
            'v1+Elo stack minus LP v2 EPA': paired(rs, 'stack', 'epa'),
            'v1+Elo stack minus S1': paired(rs, 'stack', 'S1'),
            'S1 minus LP v1': paired(rs, 'S1', 'v1'),
            'S1 minus S0b': paired(rs, 'S1', 'S0b'),
            'S2 minus S1': paired(rs, 'S2', 'S1'),
        }

    print('\nBrier and log loss on the common set (lower is better)')
    for label, t in tables.items():
        print(f"\n{label}: n {t['n']}")
        for mname in models:
            v = t['models'][mname]
            print(f"  {names[mname]:16s} Brier {v['brier']:.4f}  log loss {v['log_loss']:.4f}")
    print('\nPaired Brier differences, week-block 95% interval')
    for label, d in diffs.items():
        print(f"\n{label}")
        for mname in ['v1', 'epa', 'stack', 'S0b', 'S1', 'S2']:
            x = d['model minus market'][mname]
            print(f"  {names[mname]:16s} minus market {x['gap']:+.4f} [{x['lo']:+.4f}, {x['hi']:+.4f}]")
        for k in ['LP v2 EPA minus LP v1', 'v1+Elo stack minus LP v1', 'v1+Elo stack minus LP v2 EPA',
                  'v1+Elo stack minus S1', 'S1 minus LP v1', 'S1 minus S0b', 'S2 minus S1']:
            x = d[k]
            print(f"  {k:24s} {x['gap']:+.4f} [{x['lo']:+.4f}, {x['hi']:+.4f}]")

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, 'game_winner_comparison.json'), 'w') as handle:
        json.dump({'epa_setting': {'half_life': hl, 'lam': lam, 'grid_2024': grid}, 'n': len(rows),
                   'tables': tables, 'diffs': diffs}, handle, indent=1, default=str)
    print(f"\nwrote {os.path.join(RESULTS, 'game_winner_comparison.json')}")


if __name__ == '__main__':
    main()
