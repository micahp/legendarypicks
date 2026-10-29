#!/usr/bin/env python3
"""Split backtests for game-information factors on 2022 to 2025 regular-season games.

Inputs (read-only, picks.dev.db): nfl_schedule (scores, roof, surface, observed temperature and wind, referee, kickoff
time, weekday), nfl_game_context (attendance, broadcast networks), nfl_pbp_penalty (flagged penalties and yards).
Betting-line columns are never read. The 2026 season is not read at all.

Method. Each outcome is centred on its season's mean, so season-level scoring drift cannot create a split. For each
factor level L, the effect is mean(outcome | L) minus mean(outcome | every other game with a known level of that factor).
Confidence intervals come from 2000 bootstrap resamples within each side. p-values come from 2000 permutations of the
level labels within the factor. All tests are controlled together with Benjamini-Hochberg. The holdout re-estimates each
effect on 2022 to 2024 and reports the 2025 effect with its own interval; a sign change is reported as unstable.

Verdicts do not promote anything to the model. They rank which splits deserve a variant experiment.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
VENUES = Path('/root/lp-snapshots/nfl-game-info/2026/week08/2026-10-27T1900Z/venues.json')
SEASONS = [2022, 2023, 2024, 2025]
TRAIN = [2022, 2023, 2024]
TEST = [2025]
N_BOOT = 2000
N_PERM = 2000
MIN_N = {'referee': 30, 'venue': 30}
DEFAULT_MIN_N = 40
SEED = 20261027
DB_TO_VENUE = {'WSH': 'WAS', 'LAR': 'LA', 'LAC': 'LAC'}
OUTCOMES = {'total_resid': 'total points minus leave-one-out team-season expectation',
            'margin_resid': 'home margin minus leave-one-out team-season expectation',
            'penalties': 'flagged penalties (penalty == 1)', 'penalty_yards': 'yards on flagged penalties'}


def load() -> pd.DataFrame:
    con = sqlite3.connect(DB, uri=True)
    sch = pd.read_sql(
        "select game_id, season, week, gameday, gametime, weekday, home_team, away_team, location, home_score, away_score, "
        "roof, surface, temp, wind, referee from nfl_schedule "
        "where season between 2022 and 2025 and game_type='REG' and home_score is not null", con)
    ctx = pd.read_sql(
        "select game_id, attendance, attendance_suspect, broadcast_networks from nfl_game_context "
        "where season between 2022 and 2025", con)
    pen = pd.read_sql(
        "select game_id, sum(penalty=1) as penalties, "
        "sum(case when penalty=1 then penalty_yards else 0 end) as penalty_yards "
        "from nfl_pbp_penalty where season between 2022 and 2025 and season_type='REG' group by game_id", con)
    con.close()
    df = sch.merge(ctx, on='game_id', how='left').merge(pen, on='game_id', how='left')
    df['penalties'] = df.penalties.fillna(0).astype(float)
    df['penalty_yards'] = df.penalty_yards.fillna(0).astype(float)
    return df


def team_strength_residuals(df: pd.DataFrame) -> pd.DataFrame:
    """Residual total and margin against leave-one-out team-season points for and against.

    A team's expectation excludes the game being scored, so no game explains its own residual. Expected home points
    are the average of the home team's points for and the away team's points against, and symmetrically for away.
    """
    home = df[['game_id', 'season', 'home_team', 'home_score', 'away_score']].rename(
        columns={'home_team': 'team', 'home_score': 'pf', 'away_score': 'pa'}).assign(side='home')
    away = df[['game_id', 'season', 'away_team', 'away_score', 'home_score']].rename(
        columns={'away_team': 'team', 'away_score': 'pf', 'home_score': 'pa'}).assign(side='away')
    long = pd.concat([home, away], ignore_index=True)
    grouped = long.groupby(['season', 'team'])
    long['n'] = grouped.pf.transform('count')
    long['loo_pf'] = (grouped.pf.transform('sum') - long.pf) / (long.n - 1)
    long['loo_pa'] = (grouped.pa.transform('sum') - long.pa) / (long.n - 1)
    h = long[long.side == 'home'][['game_id', 'loo_pf', 'loo_pa']].rename(columns={'loo_pf': 'h_pf', 'loo_pa': 'h_pa'})
    a = long[long.side == 'away'][['game_id', 'loo_pf', 'loo_pa']].rename(columns={'loo_pf': 'a_pf', 'loo_pa': 'a_pa'})
    df = df.merge(h, on='game_id').merge(a, on='game_id')
    exp_home = (df.h_pf + df.a_pa) / 2
    exp_away = (df.a_pf + df.h_pa) / 2
    df['total_resid'] = (df.home_score + df.away_score) - (exp_home + exp_away)
    df['margin_resid'] = (df.home_score - df.away_score) - (exp_home - exp_away)
    return df


def factors(df: pd.DataFrame) -> pd.DataFrame:
    df = team_strength_residuals(df.copy())
    df['total_points'] = df.home_score + df.away_score
    df['margin_home'] = df.home_score - df.away_score
    roof = {'outdoors': 'outdoor', 'open': 'retractable_open', 'closed': 'retractable_closed', 'dome': 'fixed_dome'}
    df['roof'] = df.roof.map(roof)
    surface = {'grass': 'grass', 'fieldturf': 'turf', 'matrixturf': 'turf', 'sportturf': 'turf', 'a_turf': 'turf',
               'astroturf': 'turf'}
    df['surface'] = df.surface.map(surface)
    outdoor = df.roof.isin(['outdoor', 'retractable_open'])
    df['temperature_observed'] = df.temp.where(outdoor)
    df['temperature'] = pd.cut(df.temperature_observed, [-99, 31.5, 49.5, 69.5, 199],
                               labels=['under 32F', '32-49F', '50-69F', '70F and up'])
    df['wind'] = pd.cut(df.wind.where(outdoor), [-1, 9.5, 14.5, 199],
                        labels=['under 10 mph', '10-14 mph', '15 mph and up'])
    df['weekday'] = df.weekday.where(df.weekday.isin(['Sunday', 'Monday', 'Thursday', 'Saturday']), 'Friday or Wednesday')
    hour = df.gametime.str.slice(0, 2).astype(int)
    df['kickoff_slot_et'] = np.select([hour <= 10, hour <= 13, hour <= 16, hour >= 17],
                                      ['before 11am (international)', '1pm window', '4pm window', 'night'],
                                      default='other')
    first = df.broadcast_networks.fillna('').str.split('|').str[0]
    df['broadcast'] = np.select(
        [first.str.contains('NBC'), first.str.contains('CBS'), first.str.contains('Fox'),
         first.str.contains('ABC|ESPN'), first.str.contains('Prime'), first.str.contains('NFL Net')],
        ['NBC', 'CBS', 'Fox', 'ESPN/ABC', 'Prime Video', 'NFL Network'], default=np.nan)
    df['broadcast'] = df.broadcast.where(df.broadcast.notna(), None)
    venue_doc = json.loads(VENUES.read_text())
    venues = venue_doc['venues']
    shared = venue_doc['shared_venue_teams']

    def venue_key(team: str) -> str:
        return shared.get(team, DB_TO_VENUE.get(team, team))

    cap = df.home_team.map(lambda t: venues[venue_key(t)]['listed_capacity'])
    pct = df.attendance / cap
    pct = pct.where(df.attendance_suspect.fillna(0) == 0)
    df['attendance_pct_of_listed_capacity'] = pd.cut(pct, [0, 0.85, 0.95, 1.0, 9],
                                                     labels=['under 85%', '85-94%', '95-99%', '100% and up'],
                                                     right=False)
    df['venue'] = df.home_team.map(venue_key)
    for outcome in OUTCOMES:
        df[outcome + '_centred'] = df[outcome] - df.groupby('season')[outcome].transform('mean')
    return df


FACTORS = ['roof', 'surface', 'temperature', 'wind', 'weekday', 'kickoff_slot_et', 'broadcast',
           'attendance_pct_of_listed_capacity', 'referee', 'venue']


def _effect(values: np.ndarray, flag: np.ndarray) -> float:
    return float(values[flag].mean() - values[~flag].mean())


def _bootstrap_ci(values, flag, rng):
    inside, outside = values[flag], values[~flag]
    draws = np.empty(N_BOOT)
    for i in range(N_BOOT):
        draws[i] = rng.choice(inside, inside.size).mean() - rng.choice(outside, outside.size).mean()
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def _permutation_p(values, flag, observed, rng):
    labels = flag.copy()
    count = 0
    for _ in range(N_PERM):
        rng.shuffle(labels)
        if abs(_effect(values, labels)) >= abs(observed):
            count += 1
    return (count + 1) / (N_PERM + 1)


def _bh(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    m = len(pvalues)
    q = np.empty(m)
    running = 1.0
    for rank, idx in reversed(list(enumerate(order, start=1))):
        running = min(running, pvalues[idx] * m / rank)
        q[idx] = running
    return q.tolist()


def run_tests(df: pd.DataFrame) -> list[dict]:
    rng = np.random.default_rng(SEED)
    rows = []
    for factor in FACTORS:
        known = df[df[factor].notna()]
        min_n = MIN_N.get(factor, DEFAULT_MIN_N)
        counts = known[factor].astype(str).value_counts()
        for level in counts.index:
            if counts[level] < min_n:
                continue
            for outcome in OUTCOMES:
                values = known[outcome + '_centred'].to_numpy(float)
                flag = (known[factor].astype(str) == level).to_numpy()
                if flag.sum() < min_n or (~flag).sum() < min_n:
                    continue
                effect = _effect(values, flag)
                lo, hi = _bootstrap_ci(values, flag, rng)
                p = _permutation_p(values, flag, effect, rng)
                rows.append({'factor': factor, 'level': str(level), 'outcome': outcome, 'n': int(flag.sum()),
                             'n_rest': int((~flag).sum()), 'effect': round(effect, 4),
                             'ci_low': round(lo, 4), 'ci_high': round(hi, 4), 'p': round(p, 5),
                             'seasons_train_effect': None, 'holdout_effect': None, 'holdout_ci_low': None,
                             'holdout_ci_high': None, 'holdout_n': None})
                # holdout: fit on TRAIN, report TEST
                train = known.season.isin(TRAIN).to_numpy()
                test = known.season.isin(TEST).to_numpy()
                tf, tv = flag[train], values[train]
                ef, ev = flag[test], values[test]
                if tf.sum() >= 10 and (~tf).sum() >= 10 and ef.sum() >= 5 and (~ef).sum() >= 5:
                    rows[-1]['seasons_train_effect'] = round(_effect(tv, tf), 4)
                    rows[-1]['holdout_effect'] = round(_effect(ev, ef), 4)
                    hlo, hhi = _bootstrap_ci(ev, ef, rng)
                    rows[-1]['holdout_ci_low'] = round(hlo, 4)
                    rows[-1]['holdout_ci_high'] = round(hhi, 4)
                    rows[-1]['holdout_n'] = int(ef.sum())
    q = _bh([r['p'] for r in rows])
    for r, qv in zip(rows, q):
        r['q_bh'] = round(qv, 5)
        r['verdict'] = verdict(r)
    rows.sort(key=lambda r: (r['q_bh'], -abs(r['effect'])))
    return rows


def verdict(r: dict) -> str:
    if r['q_bh'] >= 0.10:
        return 'no evidence after multiple-comparison control'
    if r['q_bh'] >= 0.05:
        return 'weak: not promoted'
    if r['holdout_effect'] is None:
        return 'significant but no holdout estimate'
    if np.sign(r['holdout_effect']) != np.sign(r['effect']):
        return 'unstable: 2025 holdout has the opposite sign'
    return 'candidate for a variant experiment (not promoted)'


def write_report(rows: list[dict], df: pd.DataFrame, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    counts = {s: int((df.season == s).sum()) for s in SEASONS}
    payload = {'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'seasons': SEASONS, 'train': TRAIN, 'holdout': TEST, 'games_by_season': counts,
               'n_bootstrap': N_BOOT, 'n_permutation': N_PERM, 'seed': SEED,
               'outcomes': OUTCOMES, 'tests': len(rows), 'results': rows}
    (out / 'results.json').write_text(json.dumps(payload, indent=1, sort_keys=True) + '\n')
    pd.DataFrame(rows).to_csv(out / 'results.csv', index=False)
    lines = ['# Game-information split backtests (2022 to 2025 regular season)', '',
             f'Games by season: {counts}. Tests: {len(rows)}. Bootstrap {N_BOOT}, permutations {N_PERM}, seed {SEED}.',
             'Outcomes are centred on each season. Effects are level minus all other games with a known level of the factor.',
             'Holdout: effect re-estimated on 2025 alone after the 2022 to 2024 estimate. 2026 is not used.', '',
             '| factor | level | outcome | n | effect | 95% CI | p | q (BH) | 2025 holdout | verdict |',
             '|---|---|---|---:|---:|---|---:|---:|---|---|']
    for r in rows:
        hold = ('n/a' if r['holdout_effect'] is None else
                f"{r['holdout_effect']:+.2f} [{r['holdout_ci_low']:+.2f}, {r['holdout_ci_high']:+.2f}] n={r['holdout_n']}")
        lines.append(f"| {r['factor']} | {r['level']} | {r['outcome']} | {r['n']} | {r['effect']:+.2f} | "
                     f"[{r['ci_low']:+.2f}, {r['ci_high']:+.2f}] | {r['p']:.4f} | {r['q_bh']:.4f} | {hold} | "
                     f"{r['verdict']} |")
    (out / 'report.md').write_text('\n'.join(lines) + '\n')


def main() -> None:
    df = factors(load())
    rows = run_tests(df)
    write_report(rows, df, HERE / 'backtest')
    promoted = [r for r in rows if r['verdict'].startswith('candidate')]
    print(f"games {len(df)}; tests {len(rows)}; candidates for a variant experiment: {len(promoted)}")
    for r in promoted[:20]:
        print(r['factor'], r['level'], r['outcome'], r['effect'], r['q_bh'], r['holdout_effect'])


if __name__ == '__main__':
    main()
