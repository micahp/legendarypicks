#!/usr/bin/env python3
"""Guide next actions 1 to 4, run together on team-adjusted outcomes.

1. Team-adjusted penalties and penalty yards in the E0, E2, E4, E5 and E7 families (same as the penalty-cell re-test).
2. Rolling-origin folds for the E0 factors: direction fixed on earlier seasons, checked on the next season.
3. Shrinkage across the outdoor temperature-by-wind cells (empirical Bayes toward the outdoor mean).
4. Cluster bootstrap by season and week for the penalty cell and the outdoor total effect.

Seasons 2022 to 2025, regular season. 2026 is never read. No betting columns are read.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parent
OUT = Path('/root/lp-snapshots/nfl-game-info/experiments/team-adjusted-v2')
DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
VENUES = json.loads(Path('/root/lp-snapshots/nfl-game-info/2026/week08/2026-10-27T1900Z/venues.json').read_text())
RESID = ['total_resid', 'margin_resid', 'penalties_resid', 'penalty_yards_resid']
FACTORS = ['roof', 'surface', 'temperature', 'wind', 'weekday', 'kickoff_slot_et', 'broadcast',
           'attendance_pct_of_listed_capacity', 'referee', 'venue']
OFFSET = {'Arizona': -7, 'Colorado': -7, 'California': -8, 'Washington': -8, 'Nevada': -8, 'Texas': -6,
          'Illinois': -6, 'Wisconsin': -6, 'Tennessee': -6, 'Louisiana': -6, 'Missouri': -6, 'Minnesota': -6,
          'Georgia': -5, 'Maryland': -5, 'New York': -5, 'North Carolina': -5, 'Ohio': -5, 'Michigan': -5,
          'Indiana': -5, 'Florida': -5, 'Massachusetts': -5, 'New Jersey': -5, 'Pennsylvania': -5}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bt = load_module('bt', REPO / 'backtest_splits.py')
rp = load_module('rp', REPO / 'retest_penalty_cell.py')
RNG = np.random.default_rng(bt.SEED)


def centre(df: pd.DataFrame) -> pd.DataFrame:
    for outcome in RESID:
        df[outcome + '_centred'] = df[outcome] - df.groupby('season')[outcome].transform('mean')
    return df


def family(df: pd.DataFrame, factors: list[str]) -> list[dict]:
    bt.OUTCOMES = {o: o for o in RESID}
    bt.FACTORS = factors
    return bt.run_tests(df)


def travel(df: pd.DataFrame) -> pd.DataFrame:
    venues = VENUES['venues']
    shared = VENUES['shared_venue_teams']
    state = {}
    for team in set(df.home_team) | set(df.away_team):
        key = shared.get(team, {'WSH': 'WAS', 'LAR': 'LA'}.get(team, team))
        state[team] = venues[key]['state']
    con = sqlite3.connect(DB, uri=True)
    rest = pd.read_sql("select game_id, home_rest, away_rest from nfl_schedule "
                       "where season between 2022 and 2025 and game_type='REG'", con)
    con.close()
    df = df.drop(columns=['home_rest', 'away_rest'], errors='ignore').merge(rest, on='game_id')
    shift = df.home_team.map(lambda t: OFFSET[state[t]]) - df.away_team.map(lambda t: OFFSET[state[t]])
    df['away_timezone_shift'] = np.select(
        [shift == 0, (shift.abs() <= 2) & (shift > 0), (shift.abs() <= 2) & (shift < 0),
         (shift.abs() >= 3) & (shift > 0), (shift.abs() >= 3) & (shift < 0)],
        ['no shift', '1-2h east', '1-2h west', '3h+ east', '3h+ west'], default='other')
    bins = ['6 days or fewer', '7 days', '8 days or more']
    df['home_rest_bin'] = pd.cut(df.home_rest, [-1, 6, 7, 99], labels=bins).astype(str)
    df['away_rest_bin'] = pd.cut(df.away_rest, [-1, 6, 7, 99], labels=bins).astype(str)
    return df


def officials_tests(df: pd.DataFrame) -> list[dict]:
    con = sqlite3.connect(DB, uri=True)
    off = pd.read_sql("select o.game_id, o.official_id, o.official_name from nfl_game_officials o "
                      "join nfl_schedule s on s.game_id=o.game_id where s.season between 2022 and 2025 "
                      "and s.game_type='REG' and o.official_id is not null", con)
    con.close()
    counts = off.groupby(['official_id', 'official_name']).game_id.nunique()
    rows = []
    for (oid, name), n in counts[counts >= 30].items():
        flag = df.game_id.isin(set(off[off.official_id == oid].game_id)).to_numpy()
        for outcome in RESID:
            values = df[outcome + '_centred'].to_numpy(float)
            effect = bt._effect(values, flag)
            lo, hi = bt._bootstrap_ci(values, flag, RNG)
            p = bt._permutation_p(values, flag, effect, RNG)
            rows.append({'factor': 'official', 'level': f'{name} ({oid})', 'outcome': outcome,
                         'n': int(flag.sum()), 'n_rest': int((~flag).sum()), 'effect': round(effect, 4),
                         'ci_low': round(lo, 4), 'ci_high': round(hi, 4), 'p': round(p, 5)})
    for r, q in zip(rows, bt._bh([r['p'] for r in rows])):
        r['q_bh'] = round(q, 5)
        r['verdict'] = bt.verdict({**r, 'holdout_effect': None})
    return sorted(rows, key=lambda r: r['q_bh'])


def rolling(df: pd.DataFrame, factor: str, level: str, outcome: str) -> dict:
    """Direction from the earlier seasons, checked on the next. Interval from the test season alone."""
    folds = []
    for test_season in [2023, 2024, 2025]:
        train = df[df.season < test_season]
        test = df[df.season == test_season]
        out = {'test_season': test_season}
        for name, part in [('train', train), ('test', test)]:
            known = part[part[factor].notna()]
            flag = (known[factor].astype(str) == level).to_numpy()
            values = known[outcome + '_centred'].to_numpy(float)
            if flag.sum() < 8 or (~flag).sum() < 8:
                out[name] = None
                continue
            out[name] = round(bt._effect(values, flag), 4)
            if name == 'test':
                lo, hi = bt._bootstrap_ci(values, flag, RNG)
                out['test_ci'] = [round(lo, 4), round(hi, 4)]
                out['test_n'] = int(flag.sum())
        folds.append(out)
    usable = [f for f in folds if f['train'] is not None and f['test'] is not None]
    agree = sum(1 for f in usable if np.sign(f['train']) == np.sign(f['test']) != 0)
    excludes = sum(1 for f in usable if 'test_ci' in f and (f['test_ci'][0] > 0 or f['test_ci'][1] < 0))
    verdict = ('rolling-consistent' if usable and agree == len(usable) and excludes >= 2 else
               'not consistent' if usable else 'insufficient folds')
    return {'factor': factor, 'level': level, 'outcome': outcome, 'folds': folds, 'folds_used': len(usable),
            'direction_agrees': agree, 'test_intervals_excluding_zero': excludes, 'verdict': verdict}


def rolling_family(df: pd.DataFrame) -> list[dict]:
    rows = []
    for factor in FACTORS:
        known = df[df[factor].notna()]
        levels = known[factor].astype(str).value_counts()
        for level, count in levels.items():
            if count < 40:
                continue
            for outcome in RESID:
                rows.append(rolling(df, factor, level, outcome))
    return rows


def cell_shrinkage(df: pd.DataFrame) -> list[dict]:
    outdoor = df[df.roof.isin(['outdoor', 'retractable_open'])].copy()
    outdoor['cell'] = (outdoor.temperature.astype(str) + ' | ' + outdoor.wind.astype(str)).where(
        outdoor.temperature.notna() & outdoor.wind.notna())
    cells = outdoor[outdoor.cell.notna()]
    out = []
    for outcome in ['penalties_resid', 'penalty_yards_resid', 'total_resid']:
        grouped = cells.groupby('cell')[outcome + '_centred']
        means, variances, counts = grouped.mean(), grouped.var(), grouped.count()
        se2 = variances / counts
        grand = float(np.average(means, weights=1 / se2))
        tau2 = max(0.0, float(means.var() - se2.mean()))
        for cell in means.index:
            weight = tau2 / (tau2 + se2[cell])
            out.append({'outcome': outcome, 'cell': cell, 'n': int(counts[cell]), 'raw_mean': round(float(means[cell]), 3),
                        'se': round(float(np.sqrt(se2[cell])), 3), 'shrunk_mean': round(grand + weight * (means[cell] - grand), 3),
                        'shrink_weight': round(weight, 3), 'grand_mean': round(grand, 3),
                        'between_cell_tau': round(float(np.sqrt(tau2)), 3)})
    return sorted(out, key=lambda r: (r['outcome'], -abs(r['shrunk_mean'])))


def cluster_ci(values: np.ndarray, flag: np.ndarray, clusters: np.ndarray, draws: int = 2000) -> tuple[float, float]:
    labels = np.unique(clusters)
    index = {c: np.where(clusters == c)[0] for c in labels}
    estimates = np.empty(draws)
    for i in range(draws):
        picked = RNG.choice(labels, labels.size, replace=True)
        rows = np.concatenate([index[c] for c in picked])
        y, f = values[rows], flag[rows]
        estimates[i] = y[f].mean() - y[~f].mean() if f.any() and (~f).any() else np.nan
    return float(np.nanpercentile(estimates, 2.5)), float(np.nanpercentile(estimates, 97.5))


def clustered(df: pd.DataFrame) -> list[dict]:
    outdoor = df[df.roof.isin(['outdoor', 'retractable_open'])].copy()
    outdoor['cell'] = (outdoor.temperature.astype(str) + ' | ' + outdoor.wind.astype(str)).where(
        outdoor.temperature.notna() & outdoor.wind.notna())
    known = df[df.roof.notna()].copy()
    # The penalty cell is compared with the other outdoor games. The outdoor effect is compared with all other roof groups.
    targets = [('penalties_resid', outdoor, outdoor.cell == '50-69F | 10-14 mph',
                'penalty cell, 50-69F | 10-14 mph vs other outdoor games'),
               ('total_resid', known, known.roof == 'outdoor', 'outdoor vs all other roof groups, total residual')]
    out = []
    for outcome, frame, mask, label in targets:
        values = frame[outcome + '_centred'].to_numpy(float)
        flag = mask.to_numpy()
        clusters = (frame.season * 100 + frame.week).to_numpy()
        effect = bt._effect(values, flag)
        game_lo, game_hi = bt._bootstrap_ci(values, flag, RNG)
        week_lo, week_hi = cluster_ci(values, flag, clusters)
        out.append({'target': label, 'outcome': outcome, 'n': int(flag.sum()), 'n_rest': int((~flag).sum()),
                    'effect': round(effect, 4), 'game_ci': [round(game_lo, 4), round(game_hi, 4)],
                    'season_week_cluster_ci': [round(week_lo, 4), round(week_hi, 4)]})
    return out


def main() -> None:
    base = bt.factors(bt.load())
    adjusted = centre(rp.team_adjusted(base))
    outdoor = adjusted[adjusted.roof.isin(['outdoor', 'retractable_open'])].copy()
    outdoor['temp_by_wind'] = (outdoor.temperature.astype(str) + ' | ' + outdoor.wind.astype(str)).where(
        outdoor.temperature.notna() & outdoor.wind.notna())
    e0 = family(adjusted, FACTORS)
    e2 = family(outdoor, ['temp_by_wind'])
    b = adjusted[adjusted.broadcast.notna()].copy()
    b['slot_by_broadcast'] = b.kickoff_slot_et + ' | ' + b.broadcast.astype(str)
    e5 = family(b, ['slot_by_broadcast'])
    t = centre(travel(adjusted))
    e7 = family(t, ['home_rest_bin', 'away_rest_bin', 'away_timezone_shift'])
    e4 = officials_tests(adjusted)
    roll = rolling_family(adjusted)
    shrink = cell_shrinkage(adjusted)
    clust = clustered(adjusted)
    families = {'E0': e0, 'E2': e2, 'E4': e4, 'E5': e5, 'E7': e7}
    digest = {k: {'tests': len(v), 'smallest_q': min((r['q_bh'] for r in v), default=None),
                  'candidates': sum(1 for r in v if r['verdict'].startswith('candidate'))}
              for k, v in families.items()}
    rolling_digest = {'rows': len(roll), 'rolling_consistent': [r for r in roll if r['verdict'] == 'rolling-consistent']}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'results.json').write_text(json.dumps({
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'outcomes': RESID, 'families': families, 'rolling_origin': roll, 'cell_shrinkage': shrink,
        'clustered': clust, 'digest': digest}, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(digest, indent=1))
    print('rolling-consistent:', len(rolling_digest['rolling_consistent']), 'of', len(roll))
    for r in rolling_digest['rolling_consistent'][:10]:
        print('  ', r['factor'], r['level'], r['outcome'], r['direction_agrees'], r['folds'])
    for r in clust:
        print('cluster', r['target'], r['effect'], r['game_ci'], r['season_week_cluster_ci'])
    for r in shrink[:6]:
        print('shrink', r['outcome'], r['cell'], r['n'], r['raw_mean'], r['shrunk_mean'], r['shrink_weight'])


if __name__ == '__main__':
    main()
