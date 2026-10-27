"""Validate the staged nflverse penalty and return extract against the dev database, season by season.

Where both sources cover a season (2015 to 2025) the penalty flags, penalty yards by team and penalty first downs are
compared game by game. Where only the extract covers a season (2010 to 2014, 2026) its coverage is reported.
Nothing is written to the dev database.

Usage: python3 validate_nflverse_penalty.py
"""
import sqlite3

import pandas as pd

OUT_DIR = '/root/lp-snapshots/nfl-backfill-2026-10-27'
DEV_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
PEN = {'LA': 'LAR', 'WAS': 'WSH'}


def extract(season):
    return pd.read_parquet(f'{OUT_DIR}/extract/penalty_return_{season}.parquet')


def dev_penalties(con, season):
    flags = pd.read_sql("""select game_id, penalty_team, sum(penalty_yards) yards, sum(first_down_penalty) fdp, count(*) n
        from nfl_pbp_penalty where season = ? and penalty = 1 and penalty_team is not null group by game_id, penalty_team""",
                        con, params=(season,))
    flags['penalty_team'] = flags['penalty_team'].replace(PEN)
    return flags.set_index(['game_id', 'penalty_team'])


def nflverse_penalties(df):
    p = df[(df['penalty'] == 1) & df['penalty_team'].notna()].copy()
    p['penalty_team'] = p['penalty_team'].replace(PEN)
    return p.groupby(['game_id', 'penalty_team']).agg(yards=('penalty_yards', 'sum'),
                                                       fdp=('first_down_penalty', 'sum'),
                                                       n=('penalty_yards', 'size'))


def main():
    con = sqlite3.connect(DEV_DB, uri=True)
    print(f"{'season':6s} {'nfl games':>9s} {'dev games':>9s} {'flag rows':>10s} {'flag match':>10s} "
          f"{'yards match':>11s} {'1st down match':>14s} {'flag null':>9s}")
    for season in range(2010, 2027):
        df = extract(season)
        ngames = df['game_id'].nunique()
        flag_null = int(df['penalty'].isna().sum())
        dev_games = con.execute('select count(distinct game_id) from nfl_pbp where season = ?', (season,)).fetchone()[0]
        if season < 2015 or season == 2026:
            print(f"{season:<6d} {ngames:9d} {dev_games:9d} {'-':>10s} {'-':>10s} {'-':>11s} {'-':>14s} {flag_null:9d}"
                  f"  (dev has no penalty table for this season)")
            continue
        ours = nflverse_penalties(df)
        dev = dev_penalties(con, season)
        joined = ours.join(dev, how='outer', lsuffix='_nfl', rsuffix='_dev')
        both = joined.dropna()
        flag_match = (both['n_nfl'] == both['n_dev']).mean()
        yards_match = (both['yards_nfl'] == both['yards_dev']).mean()
        fdp_match = (both['fdp_nfl'] == both['fdp_dev']).mean()
        print(f"{season:<6d} {ngames:9d} {dev_games:9d} {len(joined):10d} {flag_match:10.4f} {yards_match:11.4f} "
              f"{fdp_match:14.4f} {flag_null:9d}")
    print('\nnot in either source: accepted or declined penalty status (no column in the release).')


if __name__ == '__main__':
    main()
