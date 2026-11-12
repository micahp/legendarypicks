#!/usr/bin/env python3
"""Create a compact, transaction-consistent read-only source extract for V1.6 offline audits."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

PBP_COLUMNS = (
    'game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'home_team', 'away_team', 'qtr',
    'down', 'ydstogo', 'yardline_100', 'game_seconds_remaining', 'play_type', 'yards_gained',
    'touchdown', 'sack', 'complete_pass', 'interception', 'fumble_lost', 'qb_scramble', 'penalty',
    'pass_attempt', 'rush_attempt', 'pass_location', 'run_gap', 'shotgun', 'receiver_player_id',
    'rusher_player_id',
)
CHART_COLUMNS = (
    'nflverse_game_id', 'nflverse_play_id', 'season', 'week', 'starting_hash', 'qb_location',
    'n_offense_backfield', 'n_defense_box', 'is_play_action', 'is_motion', 'n_blitzers', 'n_pass_rushers',
)


def _copy_table(source, destination, table, columns):
    quoted = ','.join(f'"{column}"' for column in columns)
    marks = ','.join('?' for _ in columns)
    destination.execute(f'CREATE TABLE {table} ({quoted})')
    cursor = source.execute(
        f'SELECT {quoted} FROM {table} WHERE season BETWEEN 2022 AND 2025 AND week BETWEEN 1 AND 18')
    count = 0
    while True:
        rows = cursor.fetchmany(10000)
        if not rows:
            return count
        destination.executemany(f'INSERT INTO {table} VALUES ({marks})', rows)
        count += len(rows)


def build(source_path, output_path):
    source_path = Path(source_path).resolve()
    output_path = Path(output_path)
    if output_path.exists():
        raise FileExistsError(f'refusing to overwrite {output_path}')
    source = sqlite3.connect(f'file:{source_path}?mode=ro', uri=True, timeout=60)
    destination = sqlite3.connect(output_path)
    try:
        source.execute('BEGIN')
        source_version = source.execute('PRAGMA data_version').fetchone()[0]
        pbp_rows = _copy_table(source, destination, 'nfl_pbp', PBP_COLUMNS)
        chart_rows = _copy_table(source, destination, 'nfl_hist_ftn_charting', CHART_COLUMNS)
        destination.execute('CREATE TABLE extract_metadata (source_path TEXT, source_data_version INTEGER, '
                            'copied_pbp_rows INTEGER, copied_charting_rows INTEGER, seasons TEXT)')
        destination.execute('INSERT INTO extract_metadata VALUES (?,?,?,?,?)',
                            (str(source_path), source_version, pbp_rows, chart_rows,
                             '2022-2025 regular season weeks 1-18'))
        destination.commit()
    except BaseException:
        destination.close()
        source.close()
        output_path.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        source.close()
    digest = hashlib.sha256()
    with output_path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return {'output': str(output_path.resolve()), 'sha256': digest.hexdigest(),
            'size_bytes': output_path.stat().st_size, 'pbp_rows': pbp_rows,
            'charting_rows': chart_rows, 'source_data_version_at_read_start': source_version}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source_db, args.output), sort_keys=True))


if __name__ == '__main__':
    main()
