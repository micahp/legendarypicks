#!/usr/bin/env python3
"""Re-test the outdoor temperature-by-wind penalty cell with penalties adjusted for team tendency, on all four seasons.

Team adjustment. For each team-season, the expectation for a game is the team's leave-one-out average of flagged penalties
it committed per game (and yards). A game's expected penalties are the home expectation plus the away expectation. The
residual is actual minus expected. The same leave-one-out logic as the team-strength residuals in backtest_splits.py.

Test. The E2 family (temperature by wind, outdoor and retractable-open games) on the residual outcomes, with the same
bootstrap, permutation and Benjamini-Hochberg machinery. Then the cell's effect season by season, for 2022, 2023, 2024 and
2025, each against the other games in that season. 2026 is not read. No betting columns are read.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
import nfl_team_codes  # noqa: E402
REPO_BT = HERE / 'backtest_splits.py'
spec = importlib.util.spec_from_file_location('bt', REPO_BT)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
OUT = Path('/root/lp-snapshots/nfl-game-info/experiments/penalty-cell-retest')
PENALTY_TEAM_TO_SCHEDULE = nfl_team_codes.PBP_TEAM_CODE_ALIASES
CELL = '50-69F | 10-14 mph'
SEASONS = [2022, 2023, 2024, 2025]


def penalties_by_team_game() -> pd.DataFrame:
    con = sqlite3.connect(DB, uri=True)
    rows = pd.read_sql(
        "select game_id, penalty_team as team, count(*) as n, sum(penalty_yards) as yards from nfl_pbp_penalty "
        "where season between 2022 and 2025 and season_type='REG' and penalty=1 group by game_id, penalty_team", con)
    con.close()
    rows['team'] = rows.team.map(nfl_team_codes.to_pbp_team_code)
    return rows


def team_adjusted(df: pd.DataFrame) -> pd.DataFrame:
    committed = penalties_by_team_game()
    long = pd.concat([
        df[['game_id', 'season', 'home_team']].rename(columns={'home_team': 'team'}).assign(side='home'),
        df[['game_id', 'season', 'away_team']].rename(columns={'away_team': 'team'}).assign(side='away')],
        ignore_index=True)
    long = long.merge(committed, on=['game_id', 'team'], how='left')
    long['n'] = long.n.fillna(0).astype(float)
    long['yards'] = long.yards.fillna(0).astype(float)
    grouped = long.groupby(['season', 'team'])
    long['games'] = grouped.game_id.transform('count')
    long['loo_n'] = (grouped.n.transform('sum') - long.n) / (long.games - 1)
    long['loo_yards'] = (grouped.yards.transform('sum') - long.yards) / (long.games - 1)
    home = long[long.side == 'home'][['game_id', 'n', 'yards', 'loo_n', 'loo_yards']].rename(
        columns={'n': 'h_n', 'yards': 'h_yards', 'loo_n': 'h_loo_n', 'loo_yards': 'h_loo_yards'})
    away = long[long.side == 'away'][['game_id', 'n', 'yards', 'loo_n', 'loo_yards']].rename(
        columns={'n': 'a_n', 'yards': 'a_yards', 'loo_n': 'a_loo_n', 'loo_yards': 'a_loo_yards'})
    out = df.merge(home, on='game_id').merge(away, on='game_id')
    out['penalties_resid'] = (out.h_n + out.a_n) - (out.h_loo_n + out.a_loo_n)
    out['penalty_yards_resid'] = (out.h_yards + out.a_yards) - (out.h_loo_yards + out.a_loo_yards)
    return out


def family_rows(df: pd.DataFrame, outcomes: dict) -> list[dict]:
    bt.OUTCOMES = outcomes
    for outcome in outcomes:
        df[outcome + '_centred'] = df[outcome] - df.groupby('season')[outcome].transform('mean')
    bt.FACTORS = ['temp_by_wind']
    return bt.run_tests(df)


def season_cell(df: pd.DataFrame, outcome: str, rng: np.random.Generator) -> list[dict]:
    rows = []
    for season in SEASONS:
        sub = df[df.season == season]
        flag = (sub.temp_by_wind.astype(str) == CELL).to_numpy()
        values = sub[outcome + '_centred'].to_numpy(float)
        if flag.sum() < 5 or (~flag).sum() < 5:
            rows.append({'season': season, 'outcome': outcome, 'n_cell': int(flag.sum()), 'effect': None})
            continue
        effect = bt._effect(values, flag)
        lo, hi = bt._bootstrap_ci(values, flag, rng)
        rows.append({'season': season, 'outcome': outcome, 'n_cell': int(flag.sum()), 'n_rest': int((~flag).sum()),
                     'effect': round(effect, 4), 'ci_low': round(lo, 4), 'ci_high': round(hi, 4)})
    return rows


def main() -> None:
    base = bt.factors(bt.load())
    adjusted = team_adjusted(base)
    outdoor = adjusted[adjusted.roof.isin(['outdoor', 'retractable_open'])].copy()
    outdoor['temp_by_wind'] = (outdoor.temperature.astype(str) + ' | ' + outdoor.wind.astype(str)).where(
        outdoor.temperature.notna() & outdoor.wind.notna())
    rng = np.random.default_rng(bt.SEED)

    adjusted_rows = family_rows(outdoor.copy(), {
        'penalties_resid': 'flagged penalties minus team-season expectation',
        'penalty_yards_resid': 'flagged penalty yards minus team-season expectation'})
    unadjusted_rows = family_rows(outdoor.copy(), {
        'penalties': 'flagged penalties, raw', 'penalty_yards': 'flagged penalty yards, raw'})

    rows_for_cell = [r for r in adjusted_rows if r['level'] == CELL]
    raw_for_cell = [r for r in unadjusted_rows if r['level'] == CELL]
    seasons = {}
    for outcome in ['penalties_resid', 'penalty_yards_resid']:
        df_out = outdoor.copy()
        df_out[outcome + '_centred'] = df_out[outcome] - df_out.groupby('season')[outcome].transform('mean')
        seasons[outcome] = season_cell(df_out, outcome, rng)
    for outcome in ['penalties', 'penalty_yards']:
        df_out = outdoor.copy()
        df_out[outcome + '_centred'] = df_out[outcome] - df_out.groupby('season')[outcome].transform('mean')
        seasons['raw_' + outcome] = season_cell(df_out, outcome, rng)

    cell_games = int((outdoor.temp_by_wind.astype(str) == CELL).sum())
    payload = {
        'generated_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'cell': CELL, 'cell_games_all_seasons': cell_games, 'outdoor_games': len(outdoor),
        'family_tests_adjusted': len(adjusted_rows), 'family_tests_raw': len(unadjusted_rows),
        'adjusted_cell': rows_for_cell, 'raw_cell': raw_for_cell, 'season_cell': seasons,
        'adjusted_family_top': sorted(adjusted_rows, key=lambda r: r['q_bh'])[:6],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'retest.json').write_text(json.dumps(payload, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps({k: payload[k] for k in ['cell_games_all_seasons', 'outdoor_games', 'family_tests_adjusted']},
                     indent=1))
    for r in rows_for_cell:
        print('ADJUSTED', r['outcome'], r['n'], round(r['effect'], 2), [round(r['ci_low'], 2), round(r['ci_high'], 2)],
              'p', r['p'], 'q', r['q_bh'], r['verdict'])
    for r in raw_for_cell:
        print('RAW     ', r['outcome'], r['n'], round(r['effect'], 2), [round(r['ci_low'], 2), round(r['ci_high'], 2)],
              'p', r['p'], 'q', r['q_bh'])
    for key, rows in seasons.items():
        for r in rows:
            print(key, r['season'], r.get('n_cell'), r.get('effect'), r.get('ci_low'), r.get('ci_high'))


if __name__ == '__main__':
    main()
