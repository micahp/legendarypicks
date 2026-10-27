"""Phase 0 of NFL-POSITION-DATA-PLAN-2026-10-27: coverage and overlap of position data. Read-only.

Writes the coverage and overlap tables to a research store outside the repo and production:
  /root/lp-snapshots/nfl-position-2026-10-27/inventory.sqlite

Tables:
  release_coverage  one row per release and season (downloaded parquet)
  dev_coverage      one row per dev table and season (picks.dev.db, mode=ro)
  overlap           per season, the rows the dev table and the release share on the same keys

Usage: python3 position_inventory.py
"""
import os
import sqlite3

import pandas as pd
import pyarrow.parquet as pq

RAW = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw'
STORE_DIR = '/root/lp-snapshots/nfl-position-2026-10-27'
STORE = os.path.join(STORE_DIR, 'inventory.sqlite')
DEV = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
# Team codes that differ between the two sources for the same franchise (the penalty table uses the same two).
TEAM_ALIAS = {'LA': 'LAR', 'WAS': 'WSH'}


def season_files(tag, prefix):
    out = []
    for name in sorted(os.listdir(os.path.join(RAW, tag))):
        if name.startswith(prefix) and name.endswith('.parquet'):
            digits = ''.join(ch for ch in name[len(prefix):] if ch.isdigit())
            if len(digits) >= 4:
                out.append((int(digits[:4]), os.path.join(RAW, tag, name)))
    return sorted(out)


def read(path, wanted):
    """The wanted columns that the file has. A column missing from this file's layout is filled with None and named."""
    have = pq.read_schema(path).names
    frame = pq.read_table(path, columns=[c for c in wanted if c in have]).to_pandas()
    for c in wanted:
        if c not in have:
            frame[c] = None
    return frame


def release_coverage():
    rows = []
    for season, path in season_files('depth_charts', 'depth_charts_'):
        names = pq.read_schema(path).names
        if 'dt' in names:
            d = read(path, ['dt', 'team', 'gsis_id'])
            marks, first, last, field = d.dt.nunique(), d.dt.min(), d.dt.max(), 'dt (snapshot time)'
        else:
            d = read(path, ['club_code', 'week', 'gsis_id', 'depth_team'])
            d['team'] = d.club_code
            marks, first, last, field = d.week.nunique(), None, None, 'none (week only)'
        rows.append(dict(release='depth_charts', season=season, rows=len(d), teams=d.team.nunique(),
                         players=d.gsis_id.nunique(), time_marks=marks, time_field=field, first_time=first,
                         last_time=last))
    for season, path in season_files('weekly_rosters', 'roster_weekly_'):
        d = read(path, ['season', 'team', 'gsis_id', 'week', 'status', 'game_type'])
        rows.append(dict(release='weekly_rosters', season=season, rows=len(d), teams=d.team.nunique(),
                         players=d.gsis_id.nunique(), time_marks=d.week.nunique(), time_field='none (week only)',
                         first_time=None, last_time=None))
    for season, path in season_files('injuries', 'injuries_'):
        d = read(path, ['season', 'team', 'gsis_id', 'week', 'report_status', 'practice_status', 'game_type',
                        'date_modified'])
        stamped = d.date_modified.notna().mean() > 0.5
        rows.append(dict(release='injuries', season=season, rows=len(d), teams=d.team.nunique(),
                         players=d.gsis_id.nunique(), time_marks=d.week.nunique(),
                         time_field='date_modified (last change)' if stamped else 'none (week only)',
                         first_time=str(d.date_modified.min()) if stamped else None,
                         last_time=str(d.date_modified.max()) if stamped else None))
    for season, path in season_files('snap_counts', 'snap_counts_'):
        d = read(path, ['game_id', 'team', 'pfr_player_id', 'week', 'game_type'])
        rows.append(dict(release='snap_counts', season=season, rows=len(d), teams=d.team.nunique(),
                         players=d.pfr_player_id.nunique(), time_marks=d.game_id.nunique(),
                         time_field='post-game', first_time=None, last_time=None))
    return pd.DataFrame(rows)


def dev_coverage(con):
    specs = [
        ('nfl_hist_depth_charts', 'club_code', 'gsis_id', 'week'),
        ('nfl_hist_injuries', 'team', 'gsis_id', 'date_modified'),
        ('nfl_hist_snap_counts', 'team', 'pfr_player_id', 'week'),
        ('nfl_snap_counts', 'team', 'player_id', 'week'),
        ('nfl_depth_chart', 'team', 'gsis_id', 'snapshot_at'),
        ('player_game_availability', 'team', 'player_id', 'week'),
    ]
    rows = []
    for table, team, player, time in specs:
        for season, n, teams, players, marks in con.execute(
                f'select season, count(*), count(distinct {team}), count(distinct {player}), count(distinct {time}) '
                f'from {table} group by season'):
            rows.append(dict(table=table, season=int(season), rows=n, teams=teams, players=players, time_marks=marks))
    return pd.DataFrame(rows)


def overlap(con):
    """Share of dev rows that the release also has, on the same keys, for the regular season."""
    out = []
    dev_inj = pd.read_sql("""select season, week, team, gsis_id from nfl_hist_injuries where game_type = 'REG'
        and gsis_id is not null""", con)
    dev_snap = pd.read_sql("""select season, week, team, pfr_player_id from nfl_hist_snap_counts
        where game_type = 'REG' and pfr_player_id is not null""", con)
    for season, path in season_files('injuries', 'injuries_'):
        if season not in set(dev_inj.season.astype(int)):
            continue
        rel = read(path, ['season', 'week', 'team', 'gsis_id', 'game_type'])
        rel = rel[(rel.game_type == 'REG') & rel.gsis_id.notna()]
        d = dev_inj[dev_inj.season == season].copy()
        for frame in (d, rel):
            frame['team'] = frame.team.replace(TEAM_ALIAS)
        keys = ['week', 'team', 'gsis_id']
        both = d.merge(rel[keys].drop_duplicates(), on=keys, how='inner')
        out.append(dict(pair='injuries (dev vs release)', season=season, dev_rows=len(d), release_rows=len(rel),
                        matched_dev=len(both), share_of_dev=round(len(both) / len(d), 4) if len(d) else None))
    for season, path in season_files('snap_counts', 'snap_counts_'):
        if season not in set(dev_snap.season.astype(int)):
            continue
        rel = read(path, ['season', 'week', 'team', 'pfr_player_id', 'game_type'])
        rel = rel[(rel.game_type == 'REG') & rel.pfr_player_id.notna()]
        d = dev_snap[dev_snap.season == season].copy()
        for frame in (d, rel):
            frame['team'] = frame.team.replace(TEAM_ALIAS)
        keys = ['week', 'team', 'pfr_player_id']
        both = d.merge(rel[keys].drop_duplicates(), on=keys, how='inner')
        out.append(dict(pair='snap_counts (dev vs release)', season=season, dev_rows=len(d), release_rows=len(rel),
                        matched_dev=len(both), share_of_dev=round(len(both) / len(d), 4) if len(d) else None))
    return pd.DataFrame(out)


def main():
    os.makedirs(STORE_DIR, exist_ok=True)
    con = sqlite3.connect(DEV, uri=True)
    rel = release_coverage()
    dev = dev_coverage(con)
    ov = overlap(con)
    store = sqlite3.connect(STORE)
    for name, frame in (('release_coverage', rel), ('dev_coverage', dev), ('overlap', ov)):
        frame.to_sql(name, store, if_exists='replace', index=False)
    store.commit()
    store.close()
    pd.set_option('display.width', 200)
    print('release coverage (rows by season, first and last few):')
    print(rel.groupby('release').agg(seasons=('season', 'nunique'), first=('season', 'min'), last=('season', 'max'),
                                     rows=('rows', 'sum')).to_string())
    print('\ndev coverage by table:')
    print(dev.groupby('table').agg(seasons=('season', 'nunique'), first=('season', 'min'), last=('season', 'max'),
                                   rows=('rows', 'sum')).to_string())
    print('\noverlap, dev rows that the release also has (regular season):')
    print(ov.to_string(index=False))
    print(f'\nwrote {STORE}')


if __name__ == '__main__':
    main()
