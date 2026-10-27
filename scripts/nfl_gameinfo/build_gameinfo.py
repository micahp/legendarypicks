#!/usr/bin/env python3
"""Build the research game-info tables (crosswalk, officials, referee check) from nflverse release files.

Research database only: never picks.db or picks.dev.db. Rebuilt from scratch on each run.
Inputs are the nflverse schedules and officials parquet files; each is hashed into load_log.

Canonical key: the nflverse schedule game_id (for example 2023_11_DAL_CAR). Every other table is keyed to it.

Officials join, in order:
  1. gsis (schedule) = game_key (officials). Measured: this agrees with the referee name in every case checked, and
     it is the only key that matches the 2021 week 15 and 2022 week 1 games, where the legacy game_id is off.
  2. old_game_id (schedule) = game_id (officials), for games step 1 does not match. The 2019 Super Bowl joins this way.
Every game records which step matched it. Nothing is guessed beyond these two keys.

Seven-position crew: Referee, Umpire, Down Judge, Line Judge, Back Judge, Field Judge, Side Judge. "Head Linesman" is
mapped to "Down Judge" (2015-2016 naming; no game in the data has both). Replay Official, RA, AL and Alternate rows
stay in the raw table and are excluded from the crew. A game with fewer than seven positions keeps the rows it has
and is flagged; nothing is imputed.
"""
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
AVAIL = os.path.join(HERE, '..', 'avail')
SCHEDULES = os.path.join(AVAIL, 'schedules.parquet')
OFFICIALS = os.path.join(AVAIL, 'officials.parquet')
DB = os.path.join(HERE, 'gameinfo.sqlite')
SEVEN = ['Referee', 'Umpire', 'Down Judge', 'Line Judge', 'Back Judge', 'Field Judge', 'Side Judge']
POSITION_MAP = {'Head Linesman': 'Down Judge'}
FIRST_SEASON, LAST_SEASON = 2015, 2026

SCHEMA = """
CREATE TABLE load_log (source TEXT, path TEXT, sha256 TEXT, rows INTEGER, loaded_at TEXT);
CREATE TABLE nfl_game_xwalk (
    game_id TEXT PRIMARY KEY, season INTEGER, game_type TEXT, week INTEGER, gameday TEXT,
    home_team TEXT, away_team TEXT, old_game_id TEXT, gsis TEXT, pfr TEXT, espn TEXT,
    old_id_collision INTEGER, officials_legacy_id TEXT, officials_join_method TEXT,
    crew_positions INTEGER, referee_schedule TEXT, stadium TEXT, home_score REAL, away_score REAL);
CREATE TABLE nfl_game_officials_raw (
    game_id_legacy TEXT, game_key TEXT, season INTEGER, season_type TEXT, week INTEGER,
    position_published TEXT, official_name TEXT, official_id TEXT, jersey_number INTEGER);
CREATE TABLE nfl_game_officials (
    game_id TEXT, position TEXT, position_published TEXT, official_id TEXT, official_name TEXT,
    PRIMARY KEY (game_id, position));
CREATE TABLE referee_check (
    game_id TEXT PRIMARY KEY, referee_schedule TEXT, referee_officials TEXT, agreement TEXT);
"""


def sha256(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def norm_name(text):
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z]', '', text)


def last_name(text):
    parts = re.sub(r'\b(jr|sr|ii|iii|iv)\b\.?', '', str(text), flags=re.I).split()
    return norm_name(parts[-1]) if parts else ''


def text_or_none(value):
    return None if value is None or pd.isna(value) else str(value)


def main():
    if os.path.exists(DB):
        os.remove(DB)
    now = datetime.now(timezone.utc).isoformat()

    sched = pd.read_parquet(SCHEDULES)
    sched = sched[sched.season.between(FIRST_SEASON, LAST_SEASON)].copy()
    sched['old_game_id'] = sched.old_game_id.map(text_or_none)
    sched['gsis'] = sched.gsis.map(lambda v: None if pd.isna(v) else str(int(v)))
    dup_old = set(sched.old_game_id[sched.old_game_id.duplicated(keep=False)].dropna())
    sched['old_id_collision'] = sched.old_game_id.isin(dup_old).astype(int)

    off = pd.read_parquet(OFFICIALS)
    off = off[off.season.between(FIRST_SEASON, LAST_SEASON)].copy()
    off['game_id'] = off.game_id.astype(str)
    off['game_key'] = off.game_key.astype(str)
    pairs = off[['game_id', 'game_key']].drop_duplicates()

    by_gsis = sched[sched.gsis.notna()][['game_id', 'gsis']].merge(
        pairs, left_on='gsis', right_on='game_key')
    by_legacy = sched[sched.old_game_id.notna()][['game_id', 'old_game_id']].merge(
        pairs, left_on='old_game_id', right_on='game_id', suffixes=('_sched', '_off'))
    off_to_sched, method, conflicts = {}, {}, Counter()
    for off_id, sched_id in zip(by_gsis.game_id_off if 'game_id_off' in by_gsis else by_gsis.game_id_y,
                                by_gsis.game_id_sched if 'game_id_sched' in by_gsis else by_gsis.game_id_x):
        off_to_sched.setdefault(off_id, sched_id)
        method.setdefault(off_id, 'gsis_key')
    for off_id, sched_id in zip(by_legacy.game_id_off, by_legacy.game_id_sched):
        if off_id not in off_to_sched:
            off_to_sched[off_id] = sched_id
            method[off_id] = 'legacy_id'
    sched_to_off = {}
    for off_id, sched_id in off_to_sched.items():
        if sched_id in sched_to_off:
            conflicts['two_officials_games_one_schedule_game'] += 1
        sched_to_off[sched_id] = off_id
    unmatched_off = sorted(set(pairs.game_id) - set(off_to_sched))

    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.execute('INSERT INTO load_log VALUES (?,?,?,?,?)',
                ('nflverse_schedules', SCHEDULES, sha256(SCHEDULES), len(sched), now))
    con.execute('INSERT INTO load_log VALUES (?,?,?,?,?)',
                ('nflverse_officials', OFFICIALS, sha256(OFFICIALS), len(off), now))

    crew, duplicates = {}, Counter()
    for r in off.itertuples(index=False):
        pos = POSITION_MAP.get(r.position, r.position)
        sched_id = off_to_sched.get(r.game_id)
        if pos not in SEVEN or sched_id is None:
            continue
        key = (sched_id, pos)
        if key in crew:
            duplicates[pos] += 1
            continue
        crew[key] = (r.position, text_or_none(r.official_id), r.official_name)
    crew_size = Counter(g for (g, _p) in crew)
    ref_crew = {g: v[2] for (g, p), v in crew.items() if p == 'Referee'}

    xw_rows, checks = [], []
    for r in sched.itertuples(index=False):
        off_id = sched_to_off.get(r.game_id)
        ref_s = text_or_none(r.referee)
        ref_o = ref_crew.get(r.game_id)
        if off_id is None:
            label = 'no_officials_row'
        elif ref_o is None:
            label = 'officials_no_referee_row'
        elif ref_s is None:
            label = 'schedule_referee_null'
        elif norm_name(ref_s) == norm_name(ref_o):
            label = 'same'
        elif last_name(ref_s) == last_name(ref_o):
            label = 'same_last_name_different_first'
        else:
            label = 'different_person'
        checks.append((r.game_id, ref_s, ref_o, label))
        xw_rows.append((r.game_id, int(r.season), r.game_type, int(r.week), text_or_none(r.gameday),
                        r.home_team, r.away_team, r.old_game_id, r.gsis, text_or_none(r.pfr), text_or_none(r.espn),
                        int(r.old_id_collision), off_id, method.get(off_id),
                        crew_size.get(r.game_id, 0), ref_s, text_or_none(r.stadium),
                        None if pd.isna(r.home_score) else float(r.home_score),
                        None if pd.isna(r.away_score) else float(r.away_score)))
    con.executemany('INSERT INTO nfl_game_xwalk VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', xw_rows)
    con.executemany('INSERT INTO nfl_game_officials_raw VALUES (?,?,?,?,?,?,?,?,?)', [
        (r.game_id, r.game_key, int(r.season), r.season_type, int(r.week), r.position, r.official_name,
         text_or_none(r.official_id), None if pd.isna(r.jersey_number) else int(r.jersey_number))
        for r in off.itertuples(index=False)])
    con.executemany('INSERT INTO nfl_game_officials VALUES (?,?,?,?,?)',
                    [(g, p, v[0], v[1], v[2]) for (g, p), v in crew.items()])
    con.executemany('INSERT INTO referee_check VALUES (?,?,?,?)', checks)
    con.commit()

    xw = pd.DataFrame(xw_rows, columns=['game_id', 'season', 'game_type', 'week', 'gameday', 'home', 'away',
                                        'old', 'gsis', 'pfr', 'espn', 'coll', 'off_id', 'method', 'crew', 'ref',
                                        'stadium', 'hs', 'as'])
    played = xw[xw.hs.notna()]
    report = {
        'schedule_games_2015_2026': len(xw), 'officials_rows_raw': len(off),
        'officials_games': int(pairs.game_id.nunique()),
        'joined_games': int(xw.off_id.notna().sum()), 'join_method': dict(Counter(xw.method.dropna())),
        'officials_games_unmatched': unmatched_off[:20], 'officials_games_unmatched_count': len(unmatched_off),
        'conflicts': dict(conflicts), 'old_game_id_collisions_in_schedule': sorted(dup_old),
        'seven_position_duplicates': dict(duplicates),
        'crew_positions_on_joined_games': {str(k): int(v) for k, v in sorted(Counter(
            xw.loc[xw.off_id.notna(), 'crew']).items())},
        'referee_check': dict(Counter(c[3] for c in checks)),
        'played_games_without_officials_by_season': {str(k): int(v) for k, v in played[
            played.off_id.isna()].groupby('season').size().items()},
    }
    con.close()
    with open(os.path.join(HERE, 'build_report.json'), 'w') as handle:
        json.dump(report, handle, indent=1, sort_keys=True)
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
