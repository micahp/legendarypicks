"""S1 (opponent-adjusted team strength) and S2 (S1 plus calendar, rest, travel and division), chronological research.

Design (fixed before the run; see docs/NFL-S1-S2-RESULTS-2026-10-27.md):

  Windows. Fit 2010 to 2017 (estimate calibration and feature weights). Validation 2018 to 2020 (choose S1 settings and
  S2 groups). Test 2021 to 2025 (previously examined: the S0b test was inspected earlier, so these results are reported as
  such). 2026 is not read.

  Cohorts. S (strict): the S0b rule, both teams with at least 4 earlier games in the season, non-tied, with a moneyline.
  Every model is scored on exactly this set. L (ladder 2010 to 2020, weeks 2 on): the games the benchmark ladder grades
  (LP v1 backtest rows with a market number and a 538 Elo row). T (2021 to 2025, weeks 2 on): same without Elo.

  S1. Margin = hfa * [not neutral] + rating(home) - rating(away). Ratings from a ridge fit (penalty lambda) on every REG
  game with a date strictly before the target date (any season), with recency weights 0.5 ** (days / (7 * half_life)).
  Settings are chosen on validation Brier of the calibrated win probability. Win probability = sigmoid(a + b * margin),
  with a and b fitted on the fit window. Margin distribution = normal(margin, sigma), sigma from the fit window.

  S2. Logistic on [1, S1 margin / 10] plus the features of one group (or all). Groups: weekday (Thursday, Monday,
  Saturday; Sunday is the base), kickoff (late afternoon 14:30 to 19:59 ET, primetime 20:00 or later; early is the base),
  rest (home minus away rest days, clipped at plus or minus 7; short rest at 5 days or fewer for each team), travel (away
  team's time-zone crossings east and west, in hours, 0 at neutral sites), division. Fitted on the fit window only.

Metrics: Brier, log loss, calibration slope, reliability bins with at least 20 games, margin CRPS (normal) and MAE.
Paired differences use week-block bootstrap intervals. Every subgroup with fewer than 30 games is not interpreted.

Usage: python3 s1_s2_models.py   (writes results/s1_s2.json under the scratchpad, prints the tables)
"""
import datetime
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s0_baseline as s0  # noqa: E402

BACKEND = '/root/legendarypicks/backend'
sys.path.insert(0, BACKEND)
import nfl_backtest as nb  # noqa: E402
import benchmark_ladder_2010_2020 as bl  # noqa: E402
import nfl_metrics as nm  # noqa: E402

RESULTS = '/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/nfl-splits/results'
FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "sigma": 13.295}
HALF_LIVES = (None, 26.0, 13.0)
LAMBDAS = (2.0, 10.0, 50.0)
GROUPS = ('weekday', 'kickoff', 'rest', 'travel', 'division')
# Time-zone index, hours west of Eastern. Teams are placed by home city; ARI has no daylight saving, placed at Mountain.
TZ = {'BAL': 0, 'BUF': 0, 'CIN': 0, 'CLE': 0, 'DET': 0, 'IND': 0, 'MIA': 0, 'NE': 0, 'NYG': 0, 'NYJ': 0, 'PHI': 0,
      'PIT': 0, 'ATL': 0, 'CAR': 0, 'JAX': 0, 'TB': 0, 'WSH': 0,
      'CHI': 1, 'DAL': 1, 'GB': 1, 'HOU': 1, 'KC': 1, 'MIN': 1, 'NO': 1, 'TEN': 1,
      'DEN': 2, 'ARI': 2, 'LAC': 3, 'LAR': 3, 'LV': 3, 'SEA': 3, 'SF': 3}
ELO_CODE = bl.ELO_CODE


def load_games(dev):
    cur = dev.execute("""select game_id, season, week, gameday, weekday, gametime, home_team, away_team, location,
        home_score, away_score, home_rest, away_rest, div_game, roof, home_moneyline, away_moneyline
        from nfl_schedule where game_type = 'REG' and season between 2010 and 2025 order by season, week, game_id""")
    names = [c[0] for c in cur.description]
    games = [dict(zip(names, r)) for r in cur.fetchall()]
    scored = [g for g in games if g['home_score'] is not None and g['away_score'] is not None]
    for g in scored:
        g['home'], g['away'] = g['home_team'], g['away_team']
        g['date'] = datetime.date.fromisoformat(str(g['gameday'])[:10])
        g['neutral'] = (g['location'] or '').strip().lower() == 'neutral'
        g['margin'] = float(g['home_score'] - g['away_score'])
    return scored, len(games) - len(scored)


def attach_strict(games):
    """S0b's rule and its prior margin feature, from s0_baseline.scored_features."""
    tuples = [(g['game_id'], g['season'], g['week'], g['home'], g['away'], g['home_score'], g['away_score'])
              for g in games]
    feats = {f['game_id']: f for f in s0.scored_features(tuples)}
    for g in games:
        f = feats[g['game_id']]
        g['strict'], g['x'], g['y'], g['tie'] = f['scored'], f['x'], f['y'], f['tie']


def prior_counts(games):
    """Earlier games played by each team before the game's date, any season."""
    seen = defaultdict(int)
    by_date = defaultdict(list)
    for g in games:
        by_date[g['date']].append(g)
    for d in sorted(by_date):
        for g in by_date[d]:
            g['prior_home'], g['prior_away'] = seen[g['home']], seen[g['away']]
        for g in by_date[d]:
            seen[g['home']] += 1
            seen[g['away']] += 1


def ridge_margins(games, half_life, lam):
    """S1 margin for every game from games strictly earlier in date. None where no earlier game exists."""
    teams = sorted({g['home'] for g in games} | {g['away'] for g in games})
    idx = {t: i for i, t in enumerate(teams)}
    X = np.zeros((len(games), len(teams) + 1))
    y = np.zeros(len(games))
    ordn = np.zeros(len(games))
    for i, g in enumerate(games):
        X[i, 0] = 0.0 if g['neutral'] else 1.0
        X[i, 1 + idx[g['home']]] = 1.0
        X[i, 1 + idx[g['away']]] = -1.0
        y[i] = g['margin']
        ordn[i] = g['date'].toordinal()
    Lam = np.diag([1e-6] + [lam] * len(teams))
    by_date = defaultdict(list)
    for i, g in enumerate(games):
        by_date[g['date']].append(i)
    out = {}
    for d in sorted(by_date):
        train = ordn < d.toordinal()
        targets = by_date[d]
        if not train.any():
            for i in targets:
                out[games[i]['game_id']] = None
            continue
        if half_life is None:
            w = np.ones(int(train.sum()))
        else:
            w = 0.5 ** (((d.toordinal() - ordn[train]) / 7.0) / half_life)
        Xt = X[train]
        A = Xt.T @ (w[:, None] * Xt) + Lam
        beta = np.linalg.solve(A, Xt.T @ (w * y[train]))
        for i in targets:
            out[games[i]['game_id']] = float(X[i] @ beta)
    return out


def ols(xs, ys):
    k = len(xs[0])
    A = [[sum(x[i] * x[j] for x in xs) for j in range(k)] for i in range(k)]
    b = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(k)]
    return s0.solve(A, b)


def sd(vals):
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def tz_crossing(away, home):
    east = max(0, TZ[away] - TZ[home])   # away team's home is further west: travelling east
    west = max(0, TZ[home] - TZ[away])
    return min(east, 3), min(west, 3)


def kickoff_hours(gametime):
    h, m = str(gametime)[:5].split(':')
    return int(h) + int(m) / 60.0


def group_features(g, groups):
    f = []
    if 'weekday' in groups:
        f += [g['weekday'] == 'Thursday', g['weekday'] == 'Monday', g['weekday'] == 'Saturday']
    if 'kickoff' in groups:
        t = kickoff_hours(g['gametime']) if g['gametime'] else 13.0
        f += [14.5 <= t < 20.0, t >= 20.0]
    if 'rest' in groups:
        hr = g['home_rest'] if g['home_rest'] is not None else 7
        ar = g['away_rest'] if g['away_rest'] is not None else 7
        hr, ar = min(hr, 14), min(ar, 14)
        f += [max(-7, min(7, hr - ar)) / 7.0, hr <= 5, ar <= 5]
    if 'travel' in groups:
        east, west = (0, 0) if g['neutral'] else tz_crossing(g['away'], g['home'])
        f += [east / 3.0, west / 3.0]
    if 'division' in groups:
        f += [bool(g['div_game'])]
    return [float(v) for v in f]


def s2_design(g, groups, margin_key):
    return [1.0, g[margin_key] / 10.0] + group_features(g, groups)


def crps_normal(y, mu, sigma):
    z = (y - mu) / sigma
    phi = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    Phi = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return sigma * (z * (2 * Phi - 1) + 2 * phi - 1 / math.sqrt(math.pi))


def window(rows, years):
    return [r for r in rows if r['season'] in years]


def scored_rows(rows, fit=False):
    return [r for r in rows if r['y'] is not None]


def summarize(rows, prob_key, mu_key=None, sigma=None):
    probs = [r[prob_key] for r in rows]
    out = s0.metrics(rows, probs)
    if mu_key is not None:
        crps = [crps_normal(r['margin'], r[mu_key], sigma) for r in rows]
        mae = [abs(r['margin'] - r[mu_key]) for r in rows]
        out['margin_crps'] = sum(crps) / len(crps)
        out['margin_mae'] = sum(mae) / len(mae)
    return out


def paired(rows, key_a, key_b):
    """Brier(A) minus Brier(B) with a week-block bootstrap interval, on the same rows."""
    gap, lo, hi = s0.block_bootstrap_brier_gap(rows, [r[key_a] for r in rows], [r[key_b] for r in rows])
    return gap, lo, hi


def fmt_diff(d):
    gap, lo, hi = d
    return f"{gap:+.4f} [{lo:+.4f}, {hi:+.4f}]"


def main():
    os.makedirs(RESULTS, exist_ok=True)
    dev = sqlite3.connect(s0.DEV_DB, uri=True)
    games, unscored = load_games(dev)
    attach_strict(games)
    prior_counts(games)
    print(f"regular-season games with scores 2010 to 2025: {len(games)} (unscored skipped: {unscored})")

    # S0b, refitted here on the fit window only (same specification as s0_baseline.py).
    fit_strict = [g for g in games if g['strict'] and g['season'] in s0.FIT and g['y'] is not None]
    s0w = s0.fit_logistic([[1.0, g['x']] for g in fit_strict], [g['y'] for g in fit_strict])
    s0m = ols([[1.0, g['x']] for g in games if g['strict'] and g['season'] in s0.FIT],
              [g['margin'] for g in games if g['strict'] and g['season'] in s0.FIT])
    for g in games:
        if g['strict']:
            g['p_s0b'] = s0.sigmoid(s0w[0] + s0w[1] * g['x'])
            g['mu_s0b'] = s0m[0] + s0m[1] * g['x']
    sig_s0b = sd([g['margin'] - g['mu_s0b'] for g in fit_strict])

    # S1: choose ridge settings on validation Brier of the calibrated win probability.
    selection = []
    best = None
    for hl in HALF_LIVES:
        for lam in LAMBDAS:
            m = ridge_margins(games, hl, lam)
            for g in games:
                g['m_try'] = m[g['game_id']]
            tr = [g for g in fit_strict if g['m_try'] is not None]
            a, b = s0.fit_logistic([[1.0, g['m_try']] for g in tr], [g['y'] for g in tr])
            va = [g for g in games if g['strict'] and g['season'] in s0.VALIDATION and g['y'] is not None
                  and g['m_try'] is not None]
            brier = sum((s0.sigmoid(a + b * g['m_try']) - g['y']) ** 2 for g in va) / len(va)
            selection.append(dict(half_life=hl, lam=lam, val_brier=brier, a=a, b=b, n_val=len(va)))
            if best is None or brier < best['val_brier']:
                best = selection[-1]
    print('S1 selection (validation Brier, calibrated):')
    for s in selection:
        print(f"  half_life {str(s['half_life']):5s} lambda {s['lam']:5.1f}  val Brier {s['val_brier']:.4f}")
    print(f"  chosen: half_life {best['half_life']}, lambda {best['lam']}")
    m_best = ridge_margins(games, best['half_life'], best['lam'])
    for g in games:
        g['m1'] = m_best[g['game_id']]
        if g['m1'] is not None:
            g['p_s1'] = s0.sigmoid(best['a'] + best['b'] * g['m1'])
    s1_fit = [g for g in fit_strict if g['m1'] is not None]
    s1m = ols([[1.0, g['m1']] for g in s1_fit], [g['margin'] for g in s1_fit])
    for g in games:
        if g['m1'] is not None:
            g['mu_s1'] = s1m[0] + s1m[1] * g['m1']
    sig_s1 = sd([g['margin'] - g['mu_s1'] for g in s1_fit])

    # S2 variants: one group at a time, and all groups. Fitted on the fit window; the same design for margin.
    variants = {'S2 weekday': ('weekday',), 'S2 kickoff': ('kickoff',), 'S2 rest': ('rest',),
                'S2 travel': ('travel',), 'S2 division': ('division',), 'S2 all groups': GROUPS}
    s2_fit_info = {}
    for name, groups in variants.items():
        s2_fit = [g for g in fit_strict if g['m1'] is not None]
        w2 = s0.fit_logistic([s2_design(g, groups, 'm1') for g in s2_fit], [g['y'] for g in s2_fit])
        mm = ols([s2_design(g, groups, 'm1') for g in s2_fit], [g['margin'] for g in s2_fit])
        key = name.replace(' ', '_').replace('-', '_').lower()
        for g in games:
            if g['m1'] is not None:
                d = s2_design(g, groups, 'm1')
                g['p_' + key] = s0.sigmoid(sum(wi * xi for wi, xi in zip(w2, d)))
                g['mu_' + key] = sum(wi * xi for wi, xi in zip(mm, d))
        res = [g['margin'] - g['mu_' + key] for g in s2_fit]
        s2_fit_info[name] = dict(weights=w2, sigma=sd(res), key=key)
    print('\nS2 weights (intercept, margin/10, groups) on the fit window, all groups:')
    print('  ', [round(v, 3) for v in s2_fit_info['S2 all groups']['weights']])

    # v1 and the market, from the frozen LP v1 walk-forward (read-only), keyed by game.
    v1 = {}
    for s in range(2010, 2026):
        for x in nb.backtest_season(dev, s, FROZEN):
            v1[x['game_id']] = x
    home_rate = bl.home_rate_by_game(dev)
    elo = bl.elo_by_game(dev)
    for g in games:
        x = v1.get(g['game_id'])
        g['v1_margin'] = x['proj_margin'] if x else None
        g['p_v1'] = x['p_model'] if x else None
        # v1's backtest starts at week 2, so week 1 takes the same de-vigged moneyline from the schedule.
        if x is not None:
            g['p_mkt'] = x['p_market']
        elif g['home_moneyline'] is not None and g['away_moneyline'] is not None:
            g['p_mkt'] = nm.devig_home_prob(g['home_moneyline'], g['away_moneyline'])
        else:
            g['p_mkt'] = None
        g['p_home'] = home_rate.get(g['game_id'])
        key = (str(g['gameday'])[:10], g['home'], g['away'])
        if key in elo:
            g['p_elo'] = elo[key]
        elif (key[0], key[2], key[1]) in elo:
            g['p_elo'] = 1.0 - elo[(key[0], key[2], key[1])]
        else:
            g['p_elo'] = None
        g['week_ok'] = g['week'] >= 2
        g['y_all'] = None if g['tie'] else (1 if g['margin'] > 0 else 0)
        g['y'] = g['y_all']

    fit_rows = [g for g in games if g['season'] in s0.FIT and g['strict'] and g['y'] is not None]
    S_val = [g for g in games if g['season'] in s0.VALIDATION and g['strict'] and g['y'] is not None
             and g['p_v1'] is not None and g['p_mkt'] is not None and g['m1'] is not None]
    S_test = [g for g in games if g['season'] in s0.TEST and g['strict'] and g['y'] is not None
              and g['p_v1'] is not None and g['p_mkt'] is not None and g['m1'] is not None]
    for g in S_val + S_test:
        g['p_coin'] = 0.5
    sigma_v1 = sd([g['margin'] - g['v1_margin'] for g in fit_rows if g['v1_margin'] is not None])
    for g in games:
        if g['v1_margin'] is not None:
            g['mu_v1'] = g['v1_margin']

    out = {'selection': selection, 'best': {k: best[k] for k in ('half_life', 'lam', 'a', 'b')},
           'sigma': {'s0b': sig_s0b, 's1': sig_s1, 'v1': sigma_v1},
           's2_weights': {k: v['weights'] for k, v in s2_fit_info.items()},
           's2_sigma': {k: v['sigma'] for k, v in s2_fit_info.items()}}
    s2_keys = [v['key'] for v in s2_fit_info.values()]

    def table(name, rows, models):
        if not rows:
            print(f"\n{name}: n 0 (no games)")
            return {}
        print(f"\n{name}: n {len(rows)}, home win rate {sum(r['y'] for r in rows) / len(rows):.4f}")
        block = {}
        for label, pkey, mkey, sig in models:
            missing = sum(1 for r in rows if r.get(pkey) is None)
            if missing:
                print(f"  {label:18s} not evaluated: {missing} rows without a value")
                continue
            m = summarize(rows, pkey, mkey, sig)
            slope = 'n/a' if m['calibration_slope'] is None else f"{m['calibration_slope']:.3f}"
            crps = '' if 'margin_crps' not in m else f"  margin CRPS {m['margin_crps']:.3f} MAE {m['margin_mae']:.3f}"
            print(f"  {label:18s} Brier {m['brier']:.4f}  log loss {m['logloss']:.4f}  slope {slope}{crps}")
            block[label] = {k: v for k, v in m.items() if k != 'reliability'}
        return block

    models_strict = [('coin flip', 'p_coin', None, None), ('home only', 'p_home', None, None),
                     ('S0b', 'p_s0b', 'mu_s0b', sig_s0b), ('v1 points', 'p_v1', 'mu_v1', sigma_v1),
                     ('market', 'p_mkt', None, None), ('S1', 'p_s1', 'mu_s1', sig_s1)]
    models_strict += [(n, 'p_' + v['key'], 'mu_' + v['key'], v['sigma']) for n, v in s2_fit_info.items()]
    for g in S_val + S_test:
        g['p_home'] = g['p_home'] if g['p_home'] is not None else 0.5
    out['strict_val'] = table('STRICT cohort, validation 2018 to 2020 (selection window)', S_val, models_strict)
    out['strict_test'] = table('STRICT cohort, test 2021 to 2025 (previously examined)', S_test, models_strict)

    print('\npaired Brier differences (negative = first model better), week-block 95% interval:')
    pairs = [('S1', 'S0b'), ('S2 weekday', 'S1'), ('S2 kickoff', 'S1'), ('S2 rest', 'S1'), ('S2 travel', 'S1'),
             ('S2 division', 'S1'), ('S2 all groups', 'S1'), ('S2 all groups', 'S0b'), ('v1 points', 'S0b'),
             ('S1', 'v1 points'), ('S2 all groups', 'v1 points'), ('market', 'S0b'), ('market', 'S1')]
    key_of = {'S0b': 'p_s0b', 'S1': 'p_s1', 'v1 points': 'p_v1', 'market': 'p_mkt', 'coin flip': 'p_coin',
              'home only': 'p_home', '538 Elo': 'p_elo'}
    key_of.update({n: 'p_' + v['key'] for n, v in s2_fit_info.items()})
    out['pairs'] = {}
    for label, rows in (('validation', S_val), ('test (previously examined)', S_test)):
        print(f"  {label}:")
        for a, b in pairs:
            d = paired(rows, key_of[a], key_of[b])
            out['pairs'][f'{label}|{a} minus {b}'] = d
            print(f"    {a:16s} minus {b:10s} {fmt_diff(d)}")

    # Ladder cohort 2010 to 2020, weeks 2 on, identical rungs including Elo.
    ladder = [g for g in games if g['season'] <= 2020 and g['week_ok'] and g['y'] is not None
              and g['p_v1'] is not None and g['p_mkt'] is not None and g['p_elo'] is not None and g['m1'] is not None]
    for g in ladder:
        g['p_coin'] = 0.5
    out['ladder_2010_2020'] = table('LADDER cohort 2010 to 2020, weeks 2 on (includes fit years; descriptive)', ladder,
                                    [('coin flip', 'p_coin', None, None), ('home only', 'p_home', None, None),
                                     ('538 Elo', 'p_elo', None, None), ('v1 points', 'p_v1', 'mu_v1', sigma_v1),
                                     ('market', 'p_mkt', None, None), ('S1', 'p_s1', 'mu_s1', sig_s1)]
                                    + [(n, 'p_' + v['key'], 'mu_' + v['key'], v['sigma'])
                                       for n, v in s2_fit_info.items() if n == 'S2 all groups'])
    print('\npaired Brier differences, ladder cohort (negative = first model better), week-block 95% interval:')
    for a, b in (('S1', '538 Elo'), ('v1 points', '538 Elo'), ('S1', 'v1 points'), ('market', 'S1'),
                 ('market', 'v1 points'), ('538 Elo', 'home only')):
        d = paired(ladder, key_of[a], key_of[b])
        out['pairs'][f'ladder|{a} minus {b}'] = d
        print(f"    {a:16s} minus {b:10s} {fmt_diff(d)}")
    early = [g for g in ladder if g['week'] <= 4]
    out['early_weeks_2_4'] = table('LADDER cohort, weeks 2 to 4 only (early season)', early,
                                   [('v1 points', 'p_v1', 'mu_v1', sigma_v1), ('market', 'p_mkt', None, None),
                                    ('S1', 'p_s1', 'mu_s1', sig_s1)]
                                   + [('S2 all groups', 'p_s2_all_groups', 'mu_s2_all_groups',
                                       s2_fit_info['S2 all groups']['sigma'])])
    for a, b in (('S1', 'v1 points'), ('market', 'S1')):
        d = paired(early, key_of[a], key_of[b])
        out['pairs'][f'early_2_4|{a} minus {b}'] = d
        print(f"    early weeks 2 to 4: {a:12s} minus {b:10s} {fmt_diff(d)}")

    # Full slate, weeks 1 to 4 from 2011: v1 has no week 1 forecast, so the comparison is S1 against coin, home, market.
    # S1 uses prior-season ratings here, so this table is the direct test of the preseason prior.
    w14 = [g for g in games if g['season'] >= 2011 and g['week'] <= 4 and g['y'] is not None
           and g['p_mkt'] is not None and g['m1'] is not None and g['p_home'] is not None]
    for g in w14:
        g['p_coin'] = 0.5
    wk1 = [g for g in w14 if g['week'] == 1]
    out['weeks_1_4_full_slate'] = table('FULL SLATE, weeks 1 to 4, 2011 to 2025', w14,
                                        [('coin flip', 'p_coin', None, None), ('home only', 'p_home', None, None),
                                         ('S1 (prior-season prior)', 'p_s1', 'mu_s1', sig_s1),
                                         ('market', 'p_mkt', None, None)])
    table('FULL SLATE, week 1 only, 2011 to 2025', wk1,
          [('coin flip', 'p_coin', None, None), ('home only', 'p_home', None, None),
           ('S1 (prior-season prior)', 'p_s1', 'mu_s1', sig_s1), ('market', 'p_mkt', None, None)])
    d = paired(w14, 'p_s1', 'p_home')
    out['pairs']['weeks_1_4|S1 minus home only'] = d
    print(f"    weeks 1 to 4 full slate: S1 minus home only {fmt_diff(d)}")

    # Splits on the strict test and validation rows: weekday, kickoff window, roof, season.
    def label_of(g):
        t = kickoff_hours(g['gametime']) if g['gametime'] else None
        window = None if t is None else ('primetime' if t >= 20 else ('late_afternoon' if t >= 14.5 else 'early'))
        return {'weekday': g['weekday'], 'kickoff': window,
                'roof': 'dome' if (g['roof'] or '') in ('dome', 'closed') else 'outdoors', 'season': g['season']}

    print('\nsplits (strict, validation plus test pooled): Brier difference S1 minus S0b, and S2 all minus S1')
    pooled = S_val + S_test
    split_out = {}
    for dim in ('weekday', 'kickoff', 'roof', 'season'):
        levels = defaultdict(list)
        for g in pooled:
            levels[label_of(g)[dim]].append(g)
        for level, rs in sorted(levels.items(), key=lambda kv: str(kv[0])):
            d1 = paired(rs, 'p_s1', 'p_s0b') if len(rs) >= 30 else None
            d2 = paired(rs, 'p_s2_all_groups', 'p_s1') if len(rs) >= 30 else None
            split_out[f'{dim}={level}'] = dict(n=len(rs), s1_minus_s0b=d1, s2_minus_s1=d2)
            flag = '' if len(rs) >= 30 else '  (n < 30, not interpreted)'
            print(f"  {dim:8s} {str(level):15s} n {len(rs):4d}  S1-S0b {fmt_diff(d1) if d1 else '-':36s} "
                  f"S2-S1 {fmt_diff(d2) if d2 else '-'}{flag}")
    out['splits'] = split_out

    with open(os.path.join(RESULTS, 's1_s2.json'), 'w') as handle:
        json.dump(out, handle, indent=1, default=str)
    print(f"\nwrote {os.path.join(RESULTS, 's1_s2.json')}")


if __name__ == '__main__':
    main()
