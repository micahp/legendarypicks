"""Post-recovery endpoint audit: who recovered, whether the fumbler recovered, and where the play ended.

Output: one row per fumble play with a recovery in the description. Columns record what the text says. Rows whose end
cannot be placed carry terminal='unparsed' and are not used for movement.
"""
import re
import sys
import pandas as pd
import pyarrow.parquet as pq

BACKFILL = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp'
RECENT = '/root/nflverse-raw'
OUT = sys.argv[1]
SEASONS = list(range(1999, 2026))
TEAM = r'([A-Za-z]{2,3})'
REC_SENT = re.compile(r'RECOVERED by ' + TEAM + r'-(\d+)-[^ ]+(?: [A-Z]\.[^ ]+)*? at ' + TEAM + r' (-?\d+)'
                      r'|RECOVERED by ' + TEAM + r'-(\d+)-[^ ]+(?: [A-Z]\.[^ ]+)*? at (-?\d+)'
                      r'|and recovers at ' + TEAM + r' (-?\d+)|recovered at ' + TEAM + r' (-?\d+)', re.I)
FUMBLER = re.compile(r'FUMBLES \((\d+)-', re.I)
SPOT = re.compile(r'(?:to|at|ob at|out of bounds at|tackled at|touched at) ' + TEAM + r' (-?\d+)', re.I)
ANY_SPOT = re.compile(r'(?:to|at) (\d+)\b')


def yl(team, n, posteam):
    return 100 - n if team.upper() == posteam else n


def parse(desc, posteam, defteam):
    d = str(desc)
    out = {'rec_team': None, 'rec_yl': None, 'rec_parse': None, 'fumbler_recovers': None, 'terminal': 'unparsed',
           'end_yl': None, 'tail': None, 'kick': ('MUFFS' in d or 'punts' in d or 'kicks' in d)}
    m = REC_SENT.search(d)
    if not m:
        return out
    g = m.groups()
    rec_num = None
    if g[0] is not None:            # RECOVERED by TEAM-num-name at TEAM spot
        rec_team, rec_num, st, sn = g[0].upper(), g[1], g[2].upper(), int(g[3])
        rec_yl = yl(st, sn, posteam)
        out['rec_parse'] = 'recovered_by_team_spot'
    elif g[4] is not None:          # RECOVERED by TEAM-num-name at spot number only
        rec_team, rec_num, sn = g[4].upper(), g[5], int(g[6])
        rec_yl = 50 if sn == 50 else None   # a bare number is ambiguous unless it is midfield
        out['rec_parse'] = 'recovered_by_team_no_side'
    elif g[7] is not None:          # and recovers at TEAM spot: the fumbler recovers his own fumble
        rec_team, rec_num = posteam, None
        rec_yl = yl(g[7].upper(), int(g[8]), posteam)
        out['rec_parse'] = 'self_recovery'
        out['fumbler_recovers'] = True
    else:                           # recovered at TEAM spot
        rec_team, rec_num = posteam, None
        rec_yl = yl(g[9].upper(), int(g[10]), posteam)
        out['rec_parse'] = 'recovered_at'
    out.update(rec_team=rec_team, rec_yl=rec_yl)
    if out['fumbler_recovers'] is None and rec_num is not None:
        f = FUMBLER.search(d[:m.start()])
        if f:
            out['fumbler_recovers'] = f.group(1) == rec_num
    tail = d[m.end():]
    out['tail'] = tail[:200]
    if 'TOUCHDOWN' in tail:
        out['terminal'] = 'touchdown'
    elif 'SAFETY' in tail:
        out['terminal'] = 'safety'
    elif 'Touchback' in tail:
        out['terminal'] = 'touchback'
    elif re.search(r'\bincomplete\b', tail, re.I):
        out['terminal'] = 'incomplete'
        out['end_yl'] = rec_yl
    else:
        spots = SPOT.findall(tail)
        if spots:
            t, n = spots[-1]
            out['end_yl'] = yl(t.upper(), int(n), posteam)
            out['terminal'] = 'out_of_bounds' if re.search(r'out of bounds|ran ob', tail, re.I) else 'spot'
    return out


parts = []
for y in SEASONS:
    path = f'{RECENT}/play_by_play_{y}.parquet' if y >= 2022 else f'{BACKFILL}/play_by_play_{y}.parquet'
    cols = pq.ParquetFile(path).schema_arrow.names
    use = [c for c in ['season', 'game_id', 'play_id', 'posteam', 'defteam', 'qtr', 'down', 'ydstogo',
                       'game_seconds_remaining', 'yardline_100', 'yards_gained', 'fumble', 'fumble_lost', 'sack',
                       'touchdown', 'safety', 'desc'] if c in cols]
    df = pd.read_parquet(path, columns=use)
    f = df[df.fumble == 1].reset_index(drop=True)
    p = f.apply(lambda r: pd.Series(parse(r.desc, r.posteam, r.defteam)), axis=1)
    f = pd.concat([f, p], axis=1)
    f['season'] = y
    parts.append(f.drop(columns=['desc', 'tail']).assign(tail=p['tail'].astype(str).str.slice(0, 120)))
    print(y, len(f), 'recovered', int(f.rec_team.notna().sum()), flush=True)
a = pd.concat(parts, ignore_index=True)
a.to_csv(OUT, index=False)
print('wrote', len(a), OUT)
