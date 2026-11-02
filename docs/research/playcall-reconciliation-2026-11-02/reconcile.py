import gzip
import pandas as pd

PBP = '/root/gridiron-playbooks-research/data/raw/pbp_2026.csv.gz'
COLS = ['season', 'season_type', 'week', 'game_id', 'posteam', 'defteam', 'play_type', 'drive', 'rusher_player_name',
        'receiver_player_name', 'sack', 'qb_kneel', 'qb_spike', 'play_id']
df = pd.concat([pd.read_csv(PBP, usecols=COLS, low_memory=False), pd.read_csv('/root/gridiron-playbooks-research/data/raw/pbp_2026_week7.csv.gz', usecols=COLS, low_memory=False)], ignore_index=True).drop_duplicates(subset=['game_id','play_id'])
print('2026 rows', len(df), 'weeks present', sorted(df['week'].dropna().unique().astype(int).tolist()), 'season_types', df['season_type'].value_counts().to_dict())
df = df[(df['season'] == 2026) & (df['season_type'] == 'REG') & (df['week'] <= 7) & df['posteam'].notna()]
scrim = df[df['play_type'].isin(['run', 'pass']) & (df['qb_kneel'].fillna(0) == 0) & (df['qb_spike'].fillna(0) == 0)].copy()
scrim['is_run'] = scrim['play_type'].eq('run')
scrim['is_dropback'] = scrim['play_type'].eq('pass')
games = df.groupby('posteam')['game_id'].nunique()
print('games per team (wks1-7):', games.to_dict())
runs = scrim[scrim['is_run']].groupby('posteam').size()
team_runs_pg = (runs / games).round(2)
carries = scrim[scrim['is_run']].groupby(['posteam', 'rusher_player_name']).size()
team_carries = scrim[scrim['is_run']].groupby('posteam').size()
targets = scrim[scrim['is_dropback'] & scrim['receiver_player_name'].notna()].groupby(['posteam', 'receiver_player_name']).size()
team_targets = scrim[scrim['is_dropback'] & scrim['receiver_player_name'].notna()].groupby('posteam').size()
out = []
def add(label, value, num, den, note):
    out.append({'claim': label, 'value_2026_wk1_7': value, 'numerator': num, 'denominator': den, 'note': note})
add('DAL run attempts per game (claimed 22.86)', round(float(team_runs_pg['DAL']), 2), int(runs['DAL']), int(games['DAL']), 'runs per REG game, weeks 1-7')
dal_jw = int(carries[('DAL', 'J.Williams')]) if ('DAL', 'J.Williams') in carries.index else 0
add('J.Williams carries per game, DAL (claimed 15.71)', round(dal_jw / games['DAL'], 2), dal_jw, int(games['DAL']), 'carries per REG game')
add('J.Williams carry share, DAL (claimed 68.7%)', round(dal_jw / int(team_carries['DAL']), 4), dal_jw, int(team_carries['DAL']), 'carries / team run plays')
for name in ('M.Wilson', 'Mi.Wilson'):
    n = int(targets[('ARI', name)]) if ('ARI', name) in targets.index else 0
    add(f'{name} targets per game, ARI (claimed 9.43 for Michael Wilson)', round(n / games['ARI'], 2), n, int(games['ARI']), 'targets per REG game')
    add(f'{name} target share, ARI (claimed 23.3%)', round(n / int(team_targets['ARI']), 4), n, int(team_targets['ARI']), 'targets / team targets')
out.append({'claim': 'ARI team targets, wks1-7', 'value_2026_wk1_7': int(team_targets['ARI']), 'numerator': '', 'denominator': '', 'note': 'context'})
pd.DataFrame(out).to_csv('reconciliation_2026_wk1_7.csv', index=False)
for r in out:
    print(r)
