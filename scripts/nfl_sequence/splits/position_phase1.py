"""Phase 1 of NFL-POSITION-DATA-PLAN-2026-10-27: identity and starting-quarterback validation. Read-only.

Checks:
  1. Identity: depth-chart gsis_id values that match players.parquet, and stats player_id values that match it.
  2. QB1 agreement, 2024 (week-level depth chart, no timestamp): the depth chart's QB1 for each team-week against the
     quarterback with the most attempts that week. This tests identity, not timing.
  3. QB1 agreement, 2025 (timestamped snapshots): the latest snapshot before kickoff for each team-week, against the same
     actual starter. This also tests whether the snapshot before kickoff already shows the starter.

Starter = the quarterback with the most attempts in the team-week (regular season). Ties are counted, not resolved.
Usage: python3 position_phase1.py
"""
import datetime as dt
import sqlite3
from collections import defaultdict

import pandas as pd
import pyarrow.parquet as pq
import pytz

RAW = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw'
DEV = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
CODE = {'LA': 'LAR', 'WAS': 'WSH', 'OAK': 'LV'}
ET = pytz.timezone('America/New_York')


def norm(team):
    return CODE.get(team, team)


def players_ids():
    p = pq.read_table(f'{RAW}/players/players.parquet', columns=['gsis_id']).to_pandas()
    return set(p.gsis_id.dropna())


def actual_starters(season):
    s = pq.read_table(f'{RAW}/stats_player/stats_player_week_{season}.parquet',
                      columns=['player_id', 'position', 'season', 'week', 'season_type', 'team', 'attempts']).to_pandas()
    s = s[(s.season_type == 'REG') & (s.position == 'QB') & s.attempts.notna() & (s.attempts > 0)]
    s['team'] = s.team.map(norm)
    out, ties = {}, 0
    for (week, team), g in s.groupby(['week', 'team']):
        top = g.attempts.max()
        best = g[g.attempts == top]
        if len(best) > 1:
            ties += 1
        out[(int(week), team)] = best.player_id.iloc[0]
    return out, ties, s


def schedule(con, season):
    rows = con.execute("""select game_id, week, gameday, gametime, home_team, away_team from nfl_schedule
        where season = ? and game_type = 'REG'""", (season,)).fetchall()
    kick = {}
    for gid, week, gameday, gametime, home, away in rows:
        if not gametime:
            continue
        naive = dt.datetime.strptime(f'{str(gameday)[:10]} {gametime[:5]}', '%Y-%m-%d %H:%M')
        utc = ET.localize(naive).astimezone(pytz.utc).replace(tzinfo=None)
        for team in (norm(home), norm(away)):
            kick[(int(week), team)] = utc
    return kick


def depth_2024(players):
    d = pq.read_table(f'{RAW}/depth_charts/depth_charts_2024.parquet',
                      columns=['season', 'club_code', 'week', 'game_type', 'depth_team', 'depth_position', 'gsis_id']).to_pandas()
    d = d[(d.game_type == 'REG') & (d.depth_position == 'QB') & (d.depth_team.astype(str) == '1')]
    d['team'] = d.club_code.map(norm)
    return {(int(w), t): g for w, t, g in zip(d.week, d.team, d.gsis_id)}, d


def depth_2025(players):
    d = pq.read_table(f'{RAW}/depth_charts/depth_charts_2025.parquet',
                      columns=['dt', 'team', 'gsis_id', 'pos_abb', 'pos_rank']).to_pandas()
    # pos_slot is 9 for every quarterback in this layout, so QB1 is pos_rank 1 (one per team-snapshot).
    d = d[(d.pos_abb == 'QB') & (d.pos_rank == 1)].copy()
    d['team'] = d.team.map(norm)
    d['when'] = pd.to_datetime(d.dt.str.replace('Z', ''), utc=True).dt.tz_localize(None)
    return d


def main():
    con = sqlite3.connect(DEV, uri=True)
    players = players_ids()
    print('players in the identity table:', len(players))

    for season in (2024, 2025):
        stats_ids = pq.read_table(f'{RAW}/stats_player/stats_player_week_{season}.parquet',
                                  columns=['player_id']).to_pandas().player_id.dropna()
        print(f'{season} stats player_id matched to players: {stats_ids.isin(players).mean():.4f}')

    starters = {}
    for season in (2024, 2025):
        starters[season], ties, _ = actual_starters(season)
        print(f'{season} team-weeks with a starter: {len(starters[season])}, ties in attempts: {ties}')

    d24, raw24 = depth_2024(players)
    print(f'2024 depth QB1 rows: {len(d24)}; gsis in players: {raw24.gsis_id.isin(players).mean():.4f}')
    agree = total = 0
    mism = []
    for key, starter in starters[2024].items():
        if key not in d24:
            continue
        total += 1
        if d24[key] == starter:
            agree += 1
        else:
            mism.append((key, d24[key], starter))
    print(f'2024 QB1 (week-level chart) agrees with the actual starter in {agree}/{total} team-weeks '
          f'({agree / total:.4f})')

    d25 = depth_2025(players)
    print(f'2025 QB1 snapshot rows: {len(d25)}; gsis in players: {d25.gsis_id.isin(players).mean():.4f}')
    kick = schedule(con, 2025)
    agree = total = unknown = 0
    no_snapshot = 0
    for key, starter in starters[2025].items():
        if key not in kick:
            continue
        before = d25[(d25.team == key[1]) & (d25.when < kick[key])]
        if before.empty:
            no_snapshot += 1
            continue
        latest = before.sort_values('when').iloc[-1]
        if pd.isna(latest.gsis_id):
            unknown += 1
            continue
        total += 1
        if latest.gsis_id == starter:
            agree += 1
    print(f'2025 QB1 at kickoff agrees with the actual starter in {agree}/{total} team-weeks ({agree / total:.4f}); '
          f'no snapshot before kickoff: {no_snapshot}; QB1 blank: {unknown}')
    print('\n2024 sample disagreements (team-week, chart QB, actual starter):')
    for m in mism[:8]:
        print('  ', m)


if __name__ == '__main__':
    main()
