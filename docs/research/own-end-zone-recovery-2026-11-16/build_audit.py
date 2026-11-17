import re, sys
import pandas as pd
import pyarrow.parquet as pq

BACKFILL = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp'
RECENT = '/root/nflverse-raw'
OUT = sys.argv[1]
SEASONS = list(range(1999, 2026))  # 2026 is partial and excluded


def path(y):
    return f'{RECENT}/play_by_play_{y}.parquet' if y >= 2022 else f'{BACKFILL}/play_by_play_{y}.parquet'


def era(y):
    return '1999-2009' if y < 2010 else '2010-2021' if y < 2022 else '2022-2025'


WANT = ['season', 'game_id', 'play_id', 'posteam', 'defteam', 'play_type', 'yardline_100', 'yards_gained',
        'fumble', 'fumble_lost', 'sack', 'touchdown', 'safety', 'touchback', 'td_team', 'desc']
REC_TEAM = re.compile(r'recovered by ([A-Za-z]{2,3})-.+? at ([A-Za-z]{2,3}) (-?\d+)', re.I)
REC_MID = re.compile(r'recovered by [A-Za-z]{2,3}-.+? at (50)\b', re.I)
REC_SELF = re.compile(r'and recovers at ([A-Za-z]{2,3}) (-?\d+)', re.I)
FUM_SPOT = re.compile(r'(?:touched at|FUMBLES(?: \(Aborted\))? at) ([A-Za-z]{2,3}) (-?\d+)', re.I)


def yl(team, n, posteam):
    """nflverse yardline_100 for 'team n': distance to the opponent's end zone from the offense's view."""
    return 100 - n if team.upper() == posteam else n


def classify(r):
    d = str(r.desc)
    out = {'rec_team': None, 'rec_yl': None, 'rec_parse': 'none'}
    m = REC_TEAM.search(d)
    if m:
        out.update(rec_team=m.group(1).upper(), rec_yl=yl(m.group(2).upper(), int(m.group(3)), r.posteam), rec_parse='recovered_by')
    elif REC_MID.search(d):
        out.update(rec_team=None, rec_yl=50.0, rec_parse='midfield_team_unknown')
    else:
        m = REC_SELF.search(d)
        if m:
            out.update(rec_team=(r.defteam if 'MUFFS' in d else r.posteam),
                       rec_yl=yl(m.group(1).upper(), int(m.group(2)), r.posteam), rec_parse='self_recovery')
    if out['rec_team'] is not None:
        out['rec_side'] = 'offense' if out['rec_team'] == r.posteam else 'defense' if out['rec_team'] == r.defteam else 'other'
    else:
        out['rec_side'] = None
    fs = FUM_SPOT.search(d)
    out['fum_yl_desc'] = yl(fs.group(1).upper(), int(fs.group(2)), r.posteam) if fs else None
    out['fum_yl_nfl'] = r.yardline_100 - r.yards_gained
    out['touchback_text'] = 'Touchback' in d
    out['oob_text'] = 'out of bounds' in d.lower()
    return pd.Series(out)


def zone(v):
    if pd.isna(v): return 'unknown'
    return 'posteam_EZ' if v > 100 else 'defteam_EZ' if v < 0 else 'field'


def expected(x):
    if x.rec_side is None: return 'unresolved'
    if x.rec_zone == 'posteam_EZ': return 'touchdown' if x.rec_side == 'defense' else 'safety'
    if x.rec_zone == 'defteam_EZ': return 'touchback' if x.rec_side == 'defense' else 'touchdown'
    return 'return_or_none'


parts = []
for y in SEASONS:
    cols = pq.ParquetFile(path(y)).schema_arrow.names
    use = [c for c in WANT if c in cols]
    df = pd.read_parquet(path(y), columns=use)
    f = df[df.fumble == 1].copy()
    for c in ['touchback', 'td_team']:
        if c not in f.columns: f[c] = None
    f = f.reset_index(drop=True)
    cls = f.apply(classify, axis=1)
    f = pd.concat([f, cls], axis=1)
    f['era'] = era(y)
    f['rec_zone'] = f.rec_yl.apply(zone)
    f['official'] = f.apply(lambda x: 'touchdown' if x.touchdown == 1 else 'safety' if x.safety == 1
                            else 'touchback' if x.touchback_text else 'none', axis=1)
    f['expected'] = f.apply(expected, axis=1)
    parts.append(f.drop(columns=[c for c in ['desc'] if c in f.columns]).assign(desc=f.desc.astype(str).str.slice(0, 220)))
    print(y, 'fumble plays', len(f), 'parsed', int(f.rec_side.notna().sum()), flush=True)

a = pd.concat(parts, ignore_index=True)
a.to_csv(OUT, index=False)
print('wrote', OUT, len(a), 'rows')
