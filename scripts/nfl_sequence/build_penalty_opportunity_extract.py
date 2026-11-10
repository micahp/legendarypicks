#!/usr/bin/env python3
"""Build a source-pinned NFL play/penalty extract and 2026 database overlay.

The extract preserves every keyed nflverse PBP row, including unknown penalty
labels and deleted/aborted/no-play rows. It does not silently turn missing
penalty status into zero, and it never writes to the source SQLite database.
"""
import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

try:
    import pyarrow.parquet as pq
except ImportError as exc:  # fail before touching outputs
    raise SystemExit('pyarrow is required to read the published parquet files') from exc


YEARS = range(1999, 2027)
SOURCE_COLUMNS = (
    'season', 'week', 'game_id', 'play_id', 'play_type', 'posteam', 'defteam',
    'qtr', 'down', 'ydstogo', 'yardline_100', 'game_seconds_remaining',
    'play_deleted', 'aborted_play', 'special_teams_play', 'penalty',
    'first_down_penalty', 'penalty_type', 'penalty_team', 'penalty_player_id',
    'penalty_yards',
)
KEY_COLUMNS = ('season', 'week', 'game_id', 'play_id')
PINNED_DB_SHA256 = '1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa'
PINNED_2026_SHA256 = '5edd7c42ed3f116f7e8914594c536088c337052fa53552ba7947499ba0f9f1b5'


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def key_int(value, name):
    if value is None:
        raise ValueError(f'null required key field: {name}')
    number = int(value)
    if float(value) != number:
        raise ValueError(f'non-integer key field {name}: {value!r}')
    return number


def json_value(value):
    if value is None:
        return None
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-root', type=Path, required=True,
                        help='Directory containing raw/pbp/play_by_play_YEAR.parquet for 1999-2025')
    parser.add_argument('--source-2026', type=Path, required=True,
                        help='Pinned published 2026 PBP parquet')
    parser.add_argument('--database', type=Path, required=True,
                        help='Read-only simulation SQLite database, used only for 2026 key reconciliation')
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--allow-unpinned-inputs', action='store_true',
                        help='Permit changed DB/2026 hashes while recording their actual hashes')
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    history_path = args.out_dir / 'penalty-opportunity-plays-1999-2026.csv.gz'
    overlay_path = args.out_dir / 'penalty-source-overlay-2026.csv.gz'
    manifest_path = args.out_dir / 'manifest.json'
    if any(path.exists() for path in (history_path, overlay_path, manifest_path)):
        raise SystemExit('refusing to overwrite an existing output artifact')

    db_hash = file_sha(args.database)
    source_2026_hash = file_sha(args.source_2026)
    if not args.allow_unpinned_inputs:
        if db_hash != PINNED_DB_SHA256:
            raise SystemExit(f'database SHA mismatch: expected {PINNED_DB_SHA256}, got {db_hash}')
        if source_2026_hash != PINNED_2026_SHA256:
            raise SystemExit(f'2026 source SHA mismatch: expected {PINNED_2026_SHA256}, got {source_2026_hash}')

    start = time.monotonic()
    season_manifest = {}
    db_connection = sqlite3.connect(f'file:{args.database}?mode=ro', uri=True, timeout=30)
    try:
        db_columns = {row[1] for row in db_connection.execute('PRAGMA table_info(nfl_pbp)')}
        required_db = {'season', 'week', 'game_id', 'play_id'}
        if not required_db <= db_columns:
            raise ValueError(f'database is missing key fields: {sorted(required_db - db_columns)}')
        db_keys = set()
        db_week_by_key = {}
        for season, week, game_id, play_id in db_connection.execute(
                'SELECT season,week,game_id,play_id FROM nfl_pbp WHERE season=2026'):
            key = (int(season), int(week), str(game_id), key_int(play_id, 'db.play_id'))
            if key in db_keys:
                raise ValueError(f'duplicate 2026 database key: {key}')
            db_keys.add(key)
            db_week_by_key[(int(season), str(game_id), key[3])] = int(week)

        source_keys = set()
        source_2026_rows = 0
        source_2026_matched = Counter()
        source_2026_week_mismatch = 0
        with history_path.open('wb') as history_raw, overlay_path.open('wb') as overlay_raw:
            with gzip.GzipFile(fileobj=history_raw, mode='wb', filename='', mtime=0) as history_gz, \
                    gzip.GzipFile(fileobj=overlay_raw, mode='wb', filename='', mtime=0) as overlay_gz:
                import io
                history_text = io.TextIOWrapper(history_gz, encoding='utf-8', newline='')
                overlay_text = io.TextIOWrapper(overlay_gz, encoding='utf-8', newline='')
                history_writer = csv.DictWriter(history_text, fieldnames=SOURCE_COLUMNS, lineterminator='\n')
                overlay_writer = csv.DictWriter(overlay_text, fieldnames=SOURCE_COLUMNS, lineterminator='\n')
                history_writer.writeheader()
                overlay_writer.writeheader()
                for season in YEARS:
                    path = args.source_2026 if season == 2026 else args.archive_root / f'play_by_play_{season}.parquet'
                    parquet = pq.ParquetFile(path)
                    available = set(parquet.schema.names)
                    missing = set(SOURCE_COLUMNS) - available
                    if missing:
                        raise ValueError(f'{season} source is missing required fields: {sorted(missing)}')
                    source_hash = source_2026_hash if season == 2026 else file_sha(path)
                    statuses = Counter()
                    first_down_statuses = Counter()
                    play_types = Counter()
                    source_rows = 0
                    season_keys = set()
                    for batch in parquet.iter_batches(columns=list(SOURCE_COLUMNS), batch_size=8192):
                        columns = batch.to_pydict()
                        for index in range(batch.num_rows):
                            row = {name: json_value(columns[name][index]) for name in SOURCE_COLUMNS}
                            if key_int(row['season'], 'season') != season:
                                raise ValueError(f'{path} contains row from season {row["season"]}')
                            key = (season, key_int(row['week'], 'week'), str(row['game_id']),
                                   key_int(row['play_id'], 'play_id'))
                            if key in season_keys:
                                raise ValueError(f'duplicate source key in {season}: {key}')
                            season_keys.add(key)
                            source_rows += 1
                            statuses['unknown' if row['penalty'] is None else str(int(row['penalty']))] += 1
                            first_down_statuses['unknown' if row['first_down_penalty'] is None
                                                else str(int(row['first_down_penalty']))] += 1
                            play_types[str(row['play_type']) if row['play_type'] is not None else 'unknown'] += 1
                            history_writer.writerow(row)
                            if season == 2026:
                                source_2026_rows += 1
                                source_keys.add(key)
                                overlay_writer.writerow(row)
                                if key in db_keys:
                                    source_2026_matched[statuses_label(row['penalty'])] += 1
                                    if db_week_by_key.get((season, key[2], key[3])) != key[1]:
                                        source_2026_week_mismatch += 1
                    season_manifest[str(season)] = {
                        'source_path': str(path), 'source_sha256': source_hash,
                        'source_bytes': path.stat().st_size, 'rows': source_rows,
                        'unique_keys': len(season_keys), 'penalty_status': dict(sorted(statuses.items())),
                        'first_down_penalty_status': dict(sorted(first_down_statuses.items())),
                        'play_type_rows': dict(sorted(play_types.items())),
                    }
                    history_text.flush()
                    overlay_text.flush()
                    print(f'processed {season}: {source_rows} rows; elapsed {time.monotonic()-start:.1f}s',
                          file=sys.stderr, flush=True)
                history_text.detach()
                overlay_text.detach()

        source_only = source_keys - db_keys
        db_only = db_keys - source_keys
        if db_only:
            raise ValueError(f'{len(db_only)} database keys are absent from the pinned source')
        manifest = {
            'dataset': 'nflverse-pbp-penalty-opportunity-plays',
            'source_rows_definition': 'All published play-by-play rows with keyed season/week/game/play fields; deleted, aborted, null-play-type, special-team, penalty-tagged, and unknown-label rows are retained.',
            'penalty_label_semantics': '0 and 1 are published values; null is unknown and is preserved. The extract does not infer acceptance, decline, enforcement, or a zero from null.',
            'columns': list(SOURCE_COLUMNS),
            'seasons': season_manifest,
            '2026_reconciliation': {
                'database_path': str(args.database), 'database_sha256': db_hash,
                'database_bytes': args.database.stat().st_size,
                'database_rows': len(db_keys), 'database_unique_keys': len(db_keys),
                'source_rows': len(source_keys), 'source_unique_keys': len(source_keys),
                'matched_rows': len(source_keys & db_keys), 'source_only_keys': len(source_only),
                'database_only_keys': len(db_only), 'matched_penalty_status': dict(sorted(source_2026_matched.items())),
                'season_week_mismatches': source_2026_week_mismatch,
                'database_penalty_column_exists': 'penalty' in db_columns,
                'database_first_down_penalty_column_exists': 'first_down_penalty' in db_columns,
                'database_penalty_null_rows': db_connection.execute(
                    'SELECT count(*) FROM nfl_pbp WHERE season=2026 AND penalty IS NULL').fetchone()[0],
            },
            'outputs': {
                history_path.name: {'sha256': file_sha(history_path), 'bytes': history_path.stat().st_size},
                overlay_path.name: {'sha256': file_sha(overlay_path), 'bytes': overlay_path.stat().st_size},
            },
            'generator': 'scripts/nfl_sequence/build_penalty_opportunity_extract.py',
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        print(json.dumps({'manifest': str(manifest_path), 'history': manifest['outputs'][history_path.name],
                          'overlay': manifest['outputs'][overlay_path.name],
                          'reconciliation': manifest['2026_reconciliation']}, sort_keys=True))
    finally:
        db_connection.close()


def statuses_label(value):
    return 'unknown' if value is None else str(int(value))


if __name__ == '__main__':
    main()
