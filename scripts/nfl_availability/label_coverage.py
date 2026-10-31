#!/usr/bin/env python3
"""Measure how far nflverse roster status codes and injury reports agree with stored game-level snap counts.

This is a consistency check, not a label. A player with offensive, defensive or special-teams snaps in a game was not
inactive for that game, so any INA code on such a player is a contradiction. A zero-snap row proves nothing either way:
it may be an inactive player, a healthy backup, or a player missing from the snap table. Those rows are counted and
reported as ambiguous, and nothing here treats them as inactive evidence.

The denominator is team-weeks in which the snap table shows the team played, so bye weeks drop out. Rosters are fetched
from nflverse on first use and cached with their sha256. The database is opened read-only.

Usage: python3 label_coverage.py --cache-dir DIR --out OUT.json [--db PATH] [--first-season 2019] [--last-season 2025]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nfl_team_codes  # noqa: E402

ROSTER_URL = 'https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{year}.parquet'
DEFAULT_DB = '/root/legendarypicks/backend/data/picks.db'
# Kept as an import-compatible alias; identity aliases live in scripts/nfl_team_codes.py.
TEAM_MAP = nfl_team_codes.FRANCHISE_TEAM_CODE_ALIASES
SNAP_COLS = ['offense_snaps', 'defense_snaps', 'st_snaps']
INJURY_STATUSES = ('Out', 'Doubtful', 'Questionable')


def fetch_roster(year, cache_dir):
    path = os.path.join(cache_dir, f'roster_weekly_{year}.parquet')
    if not os.path.exists(path):
        urllib.request.urlretrieve(ROSTER_URL.format(year=year), path)
    with open(path, 'rb') as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    return path, digest


def load_rosters(years, cache_dir):
    frames, digests = [], {}
    for year in years:
        path, digest = fetch_roster(year, cache_dir)
        digests[year] = digest
        frame = pd.read_parquet(path, columns=['season', 'game_type', 'week', 'team', 'gsis_id', 'status', 'full_name'])
        frames.append(frame)
    roster = pd.concat(frames, ignore_index=True)
    roster['team'] = roster['team'].replace(TEAM_MAP)
    return roster, digests


def load_snaps(con, years):
    rows = pd.read_sql(
        'select season, game_type, week, team, pfr_player_id, offense_snaps, defense_snaps, st_snaps '
        'from nfl_hist_snap_counts where season between ? and ?', con, params=(min(years), max(years)))
    rows[SNAP_COLS] = rows[SNAP_COLS].fillna(0)
    rows['snaps'] = rows[SNAP_COLS].sum(axis=1)
    rows['zero_row'] = rows['snaps'] == 0
    return rows


def load_pfr_map(con):
    ids = pd.read_sql('select gsis_id, pfr_id from nfl_hist_player_ids where pfr_id is not null', con)
    return ids.drop_duplicates('gsis_id')


def roster_consistency(roster, snaps, pfr_map):
    """Per season and game type: how roster INA/ACT codes line up with the snap table in games the team played."""
    played = snaps.groupby(['season', 'game_type', 'week', 'team'], as_index=False)['pfr_player_id'].count()
    played = played.rename(columns={'pfr_player_id': 'snap_rows'})
    roster = roster.merge(pfr_map, on='gsis_id', how='left')
    roster = roster.merge(played[['season', 'game_type', 'week', 'team']], on=['season', 'game_type', 'week', 'team'])
    per_player = snaps.groupby(['season', 'game_type', 'week', 'team', 'pfr_player_id'], as_index=False).agg(
        snaps=('snaps', 'sum'))
    roster = roster.merge(per_player, left_on=['season', 'game_type', 'week', 'team', 'pfr_id'],
                          right_on=['season', 'game_type', 'week', 'team', 'pfr_player_id'], how='left')
    roster['mapped'] = roster['pfr_id'].notna()
    roster['matched'] = roster['snaps'].notna()
    roster['took_snaps'] = roster['snaps'].fillna(0) > 0
    out = []
    for (season, game_type), group in roster.groupby(['season', 'game_type']):
        ina = group[group['status'] == 'INA']
        act = group[group['status'] == 'ACT']
        out.append({
            'season': int(season), 'game_type': game_type,
            'team_weeks': int(group[['week', 'team']].drop_duplicates().shape[0]),
            'roster_rows': len(group), 'unmapped_rows': int((~group['mapped']).sum()),
            'ina_rows': len(ina), 'ina_mapped': int(ina['mapped'].sum()),
            'ina_with_snaps': int(ina['took_snaps'].sum()),
            'ina_zero_snaps_matched': int((ina['matched'] & ~ina['took_snaps']).sum()),
            'ina_not_in_snap_table': int((ina['mapped'] & ~ina['matched']).sum()),
            'act_rows': len(act), 'act_zero_snaps_matched': int((act['matched'] & ~act['took_snaps']).sum()),
            'act_not_in_snap_table': int((act['mapped'] & ~act['matched']).sum()),
            'ina_per_team_week': round(len(ina) / max(1, group[['week', 'team']].drop_duplicates().shape[0]), 2),
        })
    return out


def snap_takers_by_roster_status(roster, snaps, pfr_map):
    """Every player with snaps in a game, and the roster status his team-week row carries for that game."""
    takers = snaps[snaps['snaps'] > 0][['season', 'game_type', 'week', 'team', 'pfr_player_id']].drop_duplicates()
    roster = roster.merge(pfr_map, on='gsis_id', how='left').dropna(subset=['pfr_id'])
    roster = roster[['season', 'game_type', 'week', 'team', 'pfr_id', 'status']].drop_duplicates(
        ['season', 'game_type', 'week', 'team', 'pfr_id'])
    merged = takers.merge(roster, left_on=['season', 'game_type', 'week', 'team', 'pfr_player_id'],
                          right_on=['season', 'game_type', 'week', 'team', 'pfr_id'], how='left')
    merged['status'] = merged['status'].fillna('NO_ROSTER_ROW')
    counts = merged.groupby(['season', 'game_type', 'status']).size().rename('players').reset_index()
    zeros = snaps.groupby(['season', 'game_type'])['zero_row'].sum().rename('zero_snap_rows').reset_index()
    return counts.to_dict('records'), zeros.to_dict('records')


def injury_consistency(con, snaps, pfr_map, years):
    injuries = pd.read_sql(
        'select season, game_type, week, team, gsis_id, report_status from nfl_hist_injuries '
        'where season between ? and ?', con, params=(min(years), max(years)))
    injuries['team'] = injuries['team'].replace(TEAM_MAP)
    injuries = injuries.merge(pfr_map, on='gsis_id', how='left')
    per_player = snaps.groupby(['season', 'game_type', 'week', 'team', 'pfr_player_id'], as_index=False).agg(
        snaps=('snaps', 'sum'))
    matched = injuries.merge(per_player, left_on=['season', 'game_type', 'week', 'team', 'pfr_id'],
                             right_on=['season', 'game_type', 'week', 'team', 'pfr_player_id'], how='left')
    matched['took_snaps'] = matched['snaps'].fillna(0) > 0
    matched['in_snaps'] = matched['snaps'].notna()
    snap_games = snaps[['season', 'game_type', 'week', 'team']].drop_duplicates()
    snap_team_weeks = snap_games.groupby(['season', 'game_type']).size().rename('played_team_weeks').reset_index()
    inj_team_weeks = injuries[['season', 'game_type', 'week', 'team']].drop_duplicates().groupby(
        ['season', 'game_type']).size().rename('injury_team_weeks').reset_index()
    inj_weeks = injuries.groupby(['season', 'game_type'])['week'].nunique().rename('injury_weeks').reset_index()
    summary = snap_team_weeks.merge(inj_team_weeks, how='left').merge(inj_weeks, how='left').fillna(0)
    rows = []
    for (season, game_type), group in matched.groupby(['season', 'game_type']):
        for status in INJURY_STATUSES:
            part = group[group['report_status'] == status]
            rows.append({
                'season': int(season), 'game_type': game_type, 'status': status, 'rows': len(part),
                'unmapped': int(part['pfr_id'].isna().sum()),
                'in_snap_table': int(part['in_snaps'].sum()),
                'took_snaps': int(part['took_snaps'].sum()),
            })
    return summary.to_dict('records'), rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cache-dir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--first-season', type=int, default=2019)
    ap.add_argument('--last-season', type=int, default=2025)
    args = ap.parse_args()
    os.makedirs(args.cache_dir, exist_ok=True)
    years = list(range(args.first_season, args.last_season + 1))
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    roster, digests = load_rosters(years, args.cache_dir)
    snaps = load_snaps(con, years)
    pfr_map = load_pfr_map(con)
    roster_rows = roster_consistency(roster, snaps, pfr_map)
    team_weeks, injury_rows = injury_consistency(con, snaps, pfr_map, years)
    taker_rows, zero_rows = snap_takers_by_roster_status(roster, snaps, pfr_map)
    summary = {
        'roster_sha256_by_season': digests,
        'roster_consistency': roster_rows,
        'snap_takers_by_roster_status': taker_rows,
        'snap_zero_rows': zero_rows,
        'snap_team_weeks': team_weeks,
        'injury_status_vs_snaps': injury_rows,
    }
    with open(args.out, 'w') as handle:
        json.dump(summary, handle, indent=1, sort_keys=True)
    print(json.dumps(summary['roster_consistency'], indent=1)[:3000])


if __name__ == '__main__':
    main()
