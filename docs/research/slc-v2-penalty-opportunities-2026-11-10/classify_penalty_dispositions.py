"""Build a clause-level, evidence-labeled retrospective penalty dataset.

Labels are derived only from the disposition wording local to each parsed foul
clause. They are not official adjudications or simulator training labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from audit_penalty_clauses import FOUL_MENTION, parse_clauses


INPUT_COLUMNS = (
    'game_id', 'play_id', 'order_sequence', 'season', 'week', 'season_type',
    'game_date', 'home_team', 'away_team', 'posteam', 'defteam', 'qtr',
    'down', 'ydstogo', 'yardline_100', 'game_seconds_remaining', 'penalty',
    'penalty_type', 'penalty_team', 'penalty_player_id', 'penalty_yards',
    'first_down_penalty', 'desc',
)
OUTPUT_SCHEMA = pa.schema([
    ('game_id', pa.string()), ('play_id', pa.float64()),
    ('order_sequence', pa.float64()), ('season', pa.int64()),
    ('week', pa.int64()), ('season_type', pa.string()),
    ('game_date', pa.string()), ('home_team', pa.string()),
    ('away_team', pa.string()), ('posteam', pa.string()),
    ('defteam', pa.string()), ('qtr', pa.float64()), ('down', pa.float64()),
    ('ydstogo', pa.float64()), ('yardline_100', pa.float64()),
    ('game_seconds_remaining', pa.float64()), ('source_penalty', pa.int8()),
    ('source_penalty_type', pa.string()), ('source_penalty_team', pa.string()),
    ('source_penalty_player_id', pa.string()), ('source_penalty_yards', pa.float64()),
    ('source_first_down_penalty', pa.int8()), ('clause_index', pa.int16()),
    ('foul_team_text', pa.string()), ('foul_type_text', pa.string()),
    ('clause_text', pa.string()), ('clause_tail_text', pa.string()),
    ('text_markers', pa.list_(pa.string())), ('disposition', pa.string()),
    ('disposition_basis', pa.string()), ('source_scalar_matches_clause', pa.bool_()),
])
BATCH_SIZE = 32768


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def scalar_matches_clause(row: dict, clause: dict) -> bool:
    source_type = row['penalty_type']
    source_team = row['penalty_team']
    return bool(source_type and source_team and clause['type_text']
                and source_type.strip().casefold() == clause['type_text'].casefold()
                and source_team.upper() == clause['team_text'])


def make_record(row: dict, clause: dict, index: int) -> dict:
    source_flag = row['penalty']
    first_down_penalty = row['first_down_penalty']
    return {
        'game_id': row['game_id'], 'play_id': row['play_id'],
        'order_sequence': row['order_sequence'], 'season': row['season'],
        'week': row['week'], 'season_type': row['season_type'],
        'game_date': row['game_date'], 'home_team': row['home_team'],
        'away_team': row['away_team'], 'posteam': row['posteam'],
        'defteam': row['defteam'], 'qtr': row['qtr'], 'down': row['down'],
        'ydstogo': row['ydstogo'], 'yardline_100': row['yardline_100'],
        'game_seconds_remaining': row['game_seconds_remaining'],
        'source_penalty': None if source_flag is None else int(source_flag),
        'source_penalty_type': row['penalty_type'],
        'source_penalty_team': row['penalty_team'],
        'source_penalty_player_id': row['penalty_player_id'],
        'source_penalty_yards': row['penalty_yards'],
        'source_first_down_penalty': (None if first_down_penalty is None
                                      else int(first_down_penalty)),
        'clause_index': index, 'foul_team_text': clause['team_text'],
        'foul_type_text': clause['type_text'], 'clause_text': clause['clause_text'],
        'clause_tail_text': clause['tail_text'],
        'text_markers': clause['text_markers'],
        'disposition': clause['disposition'],
        'disposition_basis': clause['disposition_basis'],
        'source_scalar_matches_clause': scalar_matches_clause(row, clause),
    }


def build(corpus_dir: Path, source_manifest_path: Path, output: Path,
          summary_path: Path) -> dict:
    if output.exists() or summary_path.exists():
        raise FileExistsError('refusing to overwrite an output or summary')
    corpus_manifest_path = corpus_dir / 'manifest.json'
    corpus_manifest = json.loads(corpus_manifest_path.read_text())
    source_manifest_sha = sha256(source_manifest_path)
    source_manifest = json.loads(source_manifest_path.read_text())
    if corpus_manifest['source_manifest_sha256'] != source_manifest_sha:
        raise ValueError('corpus was built from a different source manifest')

    output.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    by_season: dict[str, Counter] = {}
    total = Counter()
    corpus_hashes = {}
    try:
        for season, item in sorted(corpus_manifest['seasons'].items(),
                                   key=lambda pair: int(pair[0])):
            corpus_path = corpus_dir / item['file']
            actual_hash = sha256(corpus_path)
            if actual_hash != item['sha256']:
                raise ValueError(f'{season} corpus file hash mismatch: {corpus_path}')
            source_item = source_manifest['seasons'][season]
            if actual_hash and item['source_sha256'] != source_item['source_sha256']:
                raise ValueError(f'{season} source hash differs from pinned manifest')
            counts = Counter()
            source = pq.ParquetFile(corpus_path)
            if set(INPUT_COLUMNS) - set(source.schema_arrow.names):
                raise ValueError(f'{season} corpus is missing required columns')
            for batch in source.iter_batches(batch_size=BATCH_SIZE,
                                             columns=list(INPUT_COLUMNS)):
                records = []
                for row in batch.to_pylist():
                    counts['source_rows'] += 1
                    clauses = parse_clauses(row['desc'])
                    counts['rows_with_parsed_clause'] += bool(clauses)
                    has_mention = bool(FOUL_MENTION.search(row['desc'] or ''))
                    counts['rows_with_penalty_mention'] += has_mention
                    counts['rows_with_multiple_clauses'] += len(clauses) > 1
                    counts['rows_with_foul_mention_but_no_clause'] += has_mention and not clauses
                    for index, clause in enumerate(clauses, start=1):
                        records.append(make_record(row, clause, index))
                        counts['clauses_total'] += 1
                        counts['disposition_' + clause['disposition']] += 1
                        counts['basis_' + clause['disposition_basis']] += 1
                        counts['source_scalar_match'] += scalar_matches_clause(row, clause)
                        counts['clause_on_penalty_flag_' + (
                            'unknown' if row['penalty'] is None else str(int(row['penalty']))
                        )] += 1
                if records:
                    table = pa.Table.from_pylist(records, schema=OUTPUT_SCHEMA)
                    if writer is None:
                        writer = pq.ParquetWriter(output, OUTPUT_SCHEMA,
                                                  compression='zstd', compression_level=8)
                    writer.write_table(table)
            if counts['source_rows'] != item['rows']:
                raise ValueError(f'{season} row count mismatch')
            by_season[season] = counts
            total.update(counts)
            corpus_hashes[season] = {
                'source_sha256': item['source_sha256'],
                'corpus_sha256': actual_hash,
                'source_rows': counts['source_rows'],
            }
    finally:
        if writer is not None:
            writer.close()

    if writer is None:
        raise ValueError('no foul clauses found in corpus')
    result = {
        'label_schema': {
            'accepted': 'Clause-local explicit “enforced” or “placed at” wording. “Placed at” is retained as its own evidence basis; it is not inferred from penalty=1.',
            'declined': 'Clause-local explicit “declined” wording.',
            'offsetting': 'Clause-local explicit “offsetting” wording; an accompanying “enforced at” describes the spot, not acceptance.',
            'superseded': 'Clause-local explicit “superseded” wording; retained separately and not forced into accepted/declined/offsetting.',
            'ambiguous': 'Conflicting disposition markers within one parsed clause.',
            'unknown': 'Parsed foul clause has no local disposition marker.',
        },
        'interpretation': ('Retrospective text-evidence labels at parsed-foul-clause level. These are not official adjudications, '
                           'not one row per independent opportunity, and not penalty-model training labels. The source penalty '
                           'flag and scalar team/type fields are retained as evidence but never determine disposition.'),
        'source_manifest_sha256': source_manifest_sha,
        'corpus_manifest_sha256': sha256(corpus_manifest_path),
        'generator_sha256': sha256(Path(__file__).resolve()),
        'output': {'path': output.name, 'sha256': sha256(output),
                   'rows': pq.ParquetFile(output).metadata.num_rows},
        'total': dict(total),
        'seasons': {season: dict(counts) for season, counts in by_season.items()},
        'input_hashes': corpus_hashes,
    }
    with summary_path.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus-dir', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True,
                        help='manifest used to build the source-faithful corpus')
    parser.add_argument('--output', type=Path, required=True,
                        help='new clause-level Parquet path; existing files are refused')
    parser.add_argument('--summary', type=Path, required=True,
                        help='new JSON summary path; existing files are refused')
    args = parser.parse_args()
    result = build(args.corpus_dir, args.source_manifest, args.output, args.summary)
    print(json.dumps({'rows': result['output']['rows'], 'total': result['total'],
                      'output': str(args.output), 'summary': str(args.summary)}, indent=2))


if __name__ == '__main__':
    main()
