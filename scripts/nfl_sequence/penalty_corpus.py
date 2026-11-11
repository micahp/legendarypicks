"""Build a retrospective, source-faithful penalty research corpus.

Rows are source records, not verified independent opportunities or adjudicated fouls.
The source flag and description markers are kept separately. No source is mutated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

COLUMNS = ('game_id', 'play_id', 'order_sequence', 'season', 'week', 'season_type',
           'game_date', 'home_team', 'away_team', 'posteam', 'defteam', 'down',
           'ydstogo', 'yardline_100', 'qtr', 'game_seconds_remaining',
           'total_home_score', 'total_away_score', 'play_type', 'play_type_nfl',
           'special_teams_play', 'desc', 'penalty', 'penalty_type', 'penalty_team',
           'penalty_player_id', 'penalty_yards', 'first_down_penalty', 'yards_gained',
           'rush_attempt', 'pass_attempt', 'sack', 'no_huddle', 'shotgun',
           'third_down_converted', 'third_down_failed', 'fourth_down_converted',
           'fourth_down_failed', 'play_deleted')


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def annotate(table: pa.Table) -> pa.Table:
    """Mark literal evidence, including on rows with penalty=0; never assign a ruling."""
    desc = pc.utf8_lower(pc.fill_null(table['desc'], ''))
    mentions = pc.count_substring_regex(desc, r'\bpenalt(?:y|ies)\b')
    markers = {name: pc.match_substring_regex(desc, pattern) for name, pattern in {
        'enforced': r'\benforced\b', 'declined': r'\bdeclined\b',
        'offsetting': r'\boffsetting\b|\boffset\b',
    }.items()}
    result = table.append_column('penalty_mentions', mentions)
    for name, values in markers.items():
        result = result.append_column('text_' + name, values)
    # These markers describe the text, not verified accepted or declined fouls.
    count = pc.add(pc.add(pc.cast(markers['enforced'], pa.int8()),
                          pc.cast(markers['declined'], pa.int8())),
                   pc.cast(markers['offsetting'], pa.int8()))
    single = pc.and_(pc.equal(mentions, 1), pc.equal(count, 1))
    return result.append_column('single_disposition_marker', single)


def build(manifest_path: Path, output: Path, seasons: list[int], batch_size: int = 32768) -> None:
    manifest = json.loads(manifest_path.read_text())
    sources = []
    for year in seasons:
        item = manifest['seasons'][str(year)]
        path = Path(item['source_path'])
        if digest(path) != item['source_sha256']:
            raise ValueError(f'source hash mismatch: {path}')
        source = pq.ParquetFile(path)
        missing = set(COLUMNS) - set(source.schema_arrow.names)
        if missing:
            raise ValueError(f'{year} missing fields: {sorted(missing)}')
        sources.append((year, item, source))
    output.mkdir(parents=True, exist_ok=False)
    result = {'source_manifest_sha256': digest(manifest_path), 'seasons': {},
              'interpretation': 'Retrospective source rows and literal text markers; not adjudicated fouls, independent opportunities, or cutoff-safe source vintages.'}
    for year, item, source in sources:
        path = output / f'penalty-source-rows-{year}.parquet'
        writer = None
        rows = 0
        try:
            for batch in source.iter_batches(batch_size=batch_size, columns=list(COLUMNS)):
                table = annotate(pa.Table.from_batches([batch]))
                if writer is None:
                    writer = pq.ParquetWriter(path, table.schema, compression='zstd')
                writer.write_table(table)
                rows += table.num_rows
        finally:
            if writer is not None:
                writer.close()
        if rows != source.metadata.num_rows:
            raise ValueError(f'{year} incomplete source: {rows} rows')
        result['seasons'][str(year)] = {'source_sha256': item['source_sha256'],
                                       'rows': rows, 'file': path.name, 'sha256': digest(path)}
    (output / 'manifest.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new output directory')
    parser.add_argument('--seasons', type=int, nargs='+', required=True)
    args = parser.parse_args()
    if len(set(args.seasons)) != len(args.seasons):
        parser.error('seasons must be unique')
    build(args.manifest, args.output, args.seasons)


if __name__ == '__main__':
    main()
