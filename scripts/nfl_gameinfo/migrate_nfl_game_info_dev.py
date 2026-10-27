#!/usr/bin/env python3
"""One-shot, dev only: add the NFL game-info tables to picks.dev.db.

Purely additive. Creates new tables and copies rows into them from the research database built by build_gameinfo.py,
build_penalties.py and build_espn_context.py. No existing table is altered. Not registered in migrate_schema's ledger,
so migrate_all.py (which targets prod and dev together) will not apply it to prod.

Rollback: DROP the new tables listed in NEW_TABLES. Nothing else changes.

Dry run by default. Refuses to run if any target table already exists. Refuses any path other than picks.dev.db.

Usage:
  python3 migrate_nfl_game_info_dev.py            # dry run: prints what would be created and copied
  python3 migrate_nfl_game_info_dev.py --apply    # writes to picks.dev.db in one transaction
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEV_DB = '/root/legendarypicks/backend/data/picks.dev.db'
SOURCE_DB = os.path.join(HERE, 'gameinfo.sqlite')

DDL = {
    'nfl_game_xwalk': """
        CREATE TABLE nfl_game_xwalk (
            game_id TEXT PRIMARY KEY, season INTEGER, game_type TEXT, week INTEGER, gameday TEXT,
            home_team TEXT, away_team TEXT, old_game_id TEXT, gsis TEXT, pfr TEXT, espn TEXT,
            old_id_collision INTEGER, officials_legacy_id TEXT, officials_join_method TEXT,
            crew_positions INTEGER, referee_schedule TEXT, stadium TEXT, home_score REAL, away_score REAL)""",
    'nfl_game_officials_raw': """
        CREATE TABLE nfl_game_officials_raw (
            game_id_legacy TEXT, game_key TEXT, season INTEGER, season_type TEXT, week INTEGER,
            position_published TEXT, official_name TEXT, official_id TEXT, jersey_number INTEGER)""",
    'nfl_game_officials': """
        CREATE TABLE nfl_game_officials (
            game_id TEXT, position TEXT, position_published TEXT, official_id TEXT, official_name TEXT,
            PRIMARY KEY (game_id, position))""",
    'referee_check': """
        CREATE TABLE referee_check (
            game_id TEXT PRIMARY KEY, referee_schedule TEXT, referee_officials TEXT, agreement TEXT)""",
    'nfl_pbp_penalty': """
        CREATE TABLE nfl_pbp_penalty (
            game_id TEXT, play_id INTEGER, season INTEGER, season_type TEXT, week INTEGER,
            penalty INTEGER, penalty_type TEXT, penalty_yards REAL, penalty_team TEXT,
            penalty_player_id TEXT, penalty_player_name TEXT, first_down_penalty INTEGER,
            drive_yards_penalized REAL, pbp_game_id TEXT, PRIMARY KEY (game_id, play_id))""",
    'nfl_game_context': """
        CREATE TABLE nfl_game_context (
            game_id TEXT PRIMARY KEY, espn_event_id TEXT, season INTEGER, week INTEGER,
            attendance INTEGER, attendance_suspect INTEGER, broadcast_networks TEXT, venue_name TEXT,
            venue_city TEXT, venue_state TEXT, neutral_site INTEGER, completed INTEGER, source TEXT,
            source_url TEXT, source_sha256 TEXT, fetched_at TEXT, attendance_known_at TEXT,
            broadcast_known_at TEXT)""",
    'nfl_game_info_load_log': """
        CREATE TABLE nfl_game_info_load_log (
            source TEXT, path TEXT, sha256 TEXT, rows INTEGER, loaded_at TEXT, copied_from TEXT)""",
}
NEW_TABLES = list(DDL)


def copy_sql(table, src_cols):
    cols = ', '.join(src_cols)
    if table == 'nfl_game_context':
        # attendance_suspect is computed here: 0 is plausible only in 2020 (no-fan season); elsewhere it is a flag
        return (f"INSERT INTO {table} (game_id, espn_event_id, season, week, attendance, attendance_suspect, "
                f"broadcast_networks, venue_name, venue_city, venue_state, neutral_site, completed, source, "
                f"source_url, source_sha256, fetched_at, attendance_known_at, broadcast_known_at) "
                f"SELECT game_id, espn_event_id, season, week, attendance, "
                f"CASE WHEN attendance = 0 AND season <> 2020 THEN 1 ELSE 0 END, broadcast_networks, venue_name, "
                f"venue_city, venue_state, neutral_site, completed, source, source_url, source_sha256, fetched_at, "
                f"attendance_known_at, broadcast_known_at FROM src.{table}")
    return f'INSERT INTO {table} ({cols}) SELECT {cols} FROM src.{table}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    if not os.path.isfile(DEV_DB):
        sys.exit(f'dev database not found: {DEV_DB}')
    if not os.path.isfile(SOURCE_DB):
        sys.exit(f'source database not found: {SOURCE_DB}')
    dev = sqlite3.connect(f'file:{DEV_DB}', uri=True, timeout=60)
    existing = {r[0] for r in dev.execute("select name from sqlite_master where type='table'")}
    clash = [t for t in NEW_TABLES if t in existing]
    if clash:
        sys.exit(f'refusing: tables already exist in dev: {clash}')
    dev.execute('ATTACH DATABASE ? AS src', (f'file:{SOURCE_DB}?mode=ro',))
    counts = {}
    for t in NEW_TABLES:
        if t == 'nfl_game_info_load_log':
            counts[t] = dev.execute('SELECT COUNT(*) FROM src.load_log').fetchone()[0]
        else:
            counts[t] = dev.execute(f'SELECT COUNT(*) FROM src.{t}').fetchone()[0]
    print('would create and copy:')
    for t in NEW_TABLES:
        print(f'  {t}: {counts[t]} rows')
    if not args.apply:
        print('dry run: nothing written. Re-run with --apply to write to picks.dev.db.')
        return
    try:
        dev.execute('BEGIN')
        for t in NEW_TABLES:
            dev.execute(DDL[t])
        for t in NEW_TABLES:
            if t == 'nfl_game_info_load_log':
                now = datetime.now(timezone.utc).isoformat()
                dev.execute('INSERT INTO nfl_game_info_load_log SELECT source, path, sha256, rows, loaded_at, '
                            '? FROM src.load_log', (f'research database {SOURCE_DB}',))
                continue
            src_cols = [r[1] for r in dev.execute(f'PRAGMA src.table_info({t})')]
            dev.execute(copy_sql(t, src_cols))
        dev.commit()
    except Exception:
        dev.rollback()
        raise
    print('applied:')
    for t in NEW_TABLES:
        n = dev.execute(f'SELECT COUNT(*) FROM main.{t}').fetchone()[0]
        print(f'  {t}: {n} rows (expected {counts[t]})')
    dev.execute('DETACH DATABASE src')
    dev.close()


if __name__ == '__main__':
    main()
