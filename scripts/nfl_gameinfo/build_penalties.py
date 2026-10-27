#!/usr/bin/env python3
"""Backfill nflverse penalty fields into the research game-info database, one season at a time.

Source: nflverse play-by-play release files (play_by_play_{season}.parquet). Only the penalty columns and the keys are
read, so memory stays small. Every play row is kept, so penalty rates keep their denominator.

Keys: nflverse pbp game_id is the legacy GSIS-style id. It is mapped to the schedule game_id through the crosswalk's
old_game_id. Plays whose game does not map are counted and reported, not dropped silently.

Downloads are cached under pbp/ with their sha256 written to load_log. The research database is only written here
and in build_gameinfo.py.
"""
import hashlib
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'gameinfo.sqlite')
PBP_DIR = os.path.join(HERE, 'pbp')
URL = 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet'
SEASONS = range(2015, 2026)
COLUMNS = ['game_id', 'play_id', 'season', 'season_type', 'week', 'penalty', 'penalty_type', 'penalty_yards',
           'penalty_team', 'penalty_player_id', 'penalty_player_name', 'first_down_penalty',
           'drive_yards_penalized', 'desc']
SCHEMA = """
CREATE TABLE IF NOT EXISTS nfl_pbp_penalty (
    game_id TEXT, play_id INTEGER, season INTEGER, season_type TEXT, week INTEGER,
    penalty INTEGER, penalty_type TEXT, penalty_yards REAL, penalty_team TEXT,
    penalty_player_id TEXT, penalty_player_name TEXT, first_down_penalty INTEGER,
    drive_yards_penalized REAL, pbp_game_id TEXT, PRIMARY KEY (game_id, play_id));
"""


def sha256(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def fetch(season):
    os.makedirs(PBP_DIR, exist_ok=True)
    path = os.path.join(PBP_DIR, f'play_by_play_{season}.parquet')
    if not os.path.exists(path):
        urllib.request.urlretrieve(URL.format(season=season), path)
    return path


def main():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.execute('DELETE FROM nfl_pbp_penalty')
    schedule_ids = set(pd.read_sql('select game_id from nfl_game_xwalk', con).game_id)
    report = {}
    for season in SEASONS:
        path = fetch(season)
        digest = sha256(path)
        df = pd.read_parquet(path, columns=COLUMNS)
        df['pbp_game_id'] = df.game_id.astype(str)
        df['game_id'] = df.pbp_game_id.where(df.pbp_game_id.isin(schedule_ids))
        unmapped = int(df.game_id.isna().sum())
        mapped = df[df.game_id.notna()].copy()
        mapped['play_id'] = mapped.play_id.astype(int)
        out = mapped[['game_id', 'play_id', 'season', 'season_type', 'week', 'penalty', 'penalty_type',
                      'penalty_yards', 'penalty_team', 'penalty_player_id', 'penalty_player_name',
                      'first_down_penalty', 'drive_yards_penalized', 'pbp_game_id']]
        out = out.assign(penalty=out.penalty.map(lambda v: None if pd.isna(v) else int(v)),
                         first_down_penalty=out.first_down_penalty.map(lambda v: None if pd.isna(v) else int(v)))
        con.executemany('INSERT INTO nfl_pbp_penalty VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        [tuple(None if (isinstance(v, float) and pd.isna(v)) else v for v in row)
                         for row in out.itertuples(index=False)])
        con.execute('INSERT INTO load_log VALUES (?,?,?,?,?)',
                    ('nflverse_pbp_penalty', path, digest, len(df), datetime.now(timezone.utc).isoformat()))
        penalty_plays = int((mapped.penalty == 1).sum())
        report[season] = {'plays': len(df), 'unmapped_plays': unmapped, 'penalty_plays': penalty_plays,
                          'penalty_type_null_on_penalty': int(mapped[(mapped.penalty == 1) &
                                                                      mapped.penalty_type.isna()].shape[0])}
        print(season, report[season], flush=True)
    con.commit()
    con.close()
    print(report)


if __name__ == '__main__':
    main()
