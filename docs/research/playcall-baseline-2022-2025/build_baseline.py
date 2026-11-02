import os
import pandas as pd

RAW = '/root/gridiron-playbooks-research/data/raw'
OUT = os.path.dirname(os.path.abspath(__file__))
SEASONS = (2022, 2023, 2024, 2025)
COLS = ['season', 'season_type', 'game_id', 'posteam', 'defteam', 'play_type', 'drive', 'down', 'ydstogo',
        'yardline_100', 'rusher_player_name', 'receiver_player_name', 'passer_player_name', 'sack', 'qb_kneel',
        'qb_spike', 'play_id', 'rush_attempt', 'pass_attempt']


def load():
    frames = []
    for y in SEASONS:
        df = pd.read_csv(os.path.join(RAW, f'pbp_{y}.csv.gz'), usecols=COLS, low_memory=False)
        frames.append(df[df['season'] == y])
    df = pd.concat(frames, ignore_index=True)
    df = df[(df['season_type'] == 'REG') & df['posteam'].notna()]
    scrim = df[df['play_type'].isin(['run', 'pass']) & (df['qb_kneel'].fillna(0) == 0) & (df['qb_spike'].fillna(0) == 0)].copy()
    scrim['is_run'] = scrim['play_type'].eq('run')
    scrim['is_dropback'] = scrim['play_type'].eq('pass')
    scrim['is_sack'] = scrim['sack'].fillna(0).eq(1)
    return df, scrim


def team_season(scrim):
    g = scrim.groupby(['season', 'posteam'])
    out = pd.DataFrame({
        'games': g['game_id'].nunique(),
        'scrimmage_plays': g.size(),
        'runs': g['is_run'].sum(),
        'dropbacks': g['is_dropback'].sum(),
        'sacks': g['is_sack'].sum(),
        'drives': g['drive'].nunique(),
    }).reset_index().rename(columns={'posteam': 'team'})
    out['plays_per_drive'] = (out['scrimmage_plays'] / out['drives']).round(3)
    out['runs_per_game'] = (out['runs'] / out['games']).round(2)
    out['dropbacks_per_game'] = (out['dropbacks'] / out['games']).round(2)
    out['scrimmage_plays_per_game'] = (out['scrimmage_plays'] / out['games']).round(2)
    return out


def player_season(scrim):
    carries = scrim[scrim['is_run']].groupby(['season', 'posteam', 'rusher_player_name']).size().rename('carries').reset_index()
    targets = scrim[scrim['is_dropback'] & scrim['receiver_player_name'].notna()] \
        .groupby(['season', 'posteam', 'receiver_player_name']).size().rename('targets').reset_index()
    carries = carries.rename(columns={'posteam': 'team', 'rusher_player_name': 'player'})
    targets = targets.rename(columns={'posteam': 'team', 'receiver_player_name': 'player'})
    out = pd.merge(carries, targets, on=['season', 'team', 'player'], how='outer').fillna(0)
    for c in ('carries', 'targets'):
        out[c] = out[c].astype(int)
    totals = out.groupby(['season', 'team'])[['carries', 'targets']].transform('sum')
    out['carry_share'] = (out['carries'] / totals['carries']).round(4)
    out['target_share'] = (out['targets'] / totals['targets']).round(4)
    return out.sort_values(['season', 'team', 'carries'], ascending=[True, True, False])


def main():
    df, scrim = load()
    ts = team_season(scrim)
    ps = player_season(scrim)
    ts.to_csv(os.path.join(OUT, 'team_season.csv'), index=False)
    ps.to_csv(os.path.join(OUT, 'player_season.csv'), index=False)
    dal = ts[(ts['team'] == 'DAL')]
    print(dal[['season', 'games', 'runs', 'runs_per_game', 'dropbacks_per_game', 'plays_per_drive']].to_string(index=False))
    print('rows team_season', len(ts), 'rows player_season', len(ps))


if __name__ == '__main__':
    main()
