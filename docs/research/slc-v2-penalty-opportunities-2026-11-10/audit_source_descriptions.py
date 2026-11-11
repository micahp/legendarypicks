"""Count literal foul-description evidence; never infer official adjudication."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import pyarrow.parquet as pq


MARKERS = {
    'declined': re.compile(r'\bdeclined\b', re.I),
    'offsetting': re.compile(r'\boffsetting\b|\boffset\b', re.I),
    'enforced': re.compile(r'\benforced\b', re.I),
    'no_play': re.compile(r'\bno play\b', re.I),
    'half_distance': re.compile(r'\bhalf the distance\b|\bhalf distance\b', re.I),
    'automatic_first_down': re.compile(r'\bautomatic(?:ally)? first down\b', re.I),
}
FOUL = re.compile(r'\bpenalt(?:y|ies)\b', re.I)


def description_features(description):
    text = description or ''
    return {**{name: bool(pattern.search(text)) for name, pattern in MARKERS.items()},
            'multiple_penalty_mentions': len(FOUL.findall(text)) > 1}


def single_foul_evidence(description):
    """Return a literal marker only when one foul mention has one disposition marker."""
    text = description or ''
    if len(FOUL.findall(text)) != 1:
        return 'ambiguous_or_no_foul_mention'
    features = description_features(text)
    hits = [key for key in ('declined', 'offsetting', 'enforced') if features[key]]
    return hits[0] if len(hits) == 1 else 'ambiguous_or_no_disposition_marker'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    years = {}
    for year, source in sorted(manifest['seasons'].items()):
        path = Path(source['source_path'])
        actual = digest(path)
        if actual != source['source_sha256']:
            raise ValueError(f'{year} source hash mismatch: {path}')
        counts = Counter()
        parquet = pq.ParquetFile(path)
        columns = ['penalty', 'desc', 'game_id', 'play_id', 'order_sequence',
                   'down', 'ydstogo', 'yardline_100', 'game_seconds_remaining']
        missing = set(columns) - set(parquet.schema.names)
        if missing:
            raise ValueError(f'{year} missing columns: {sorted(missing)}')
        for batch in parquet.iter_batches(batch_size=32768, columns=columns):
            for row in batch.to_pylist():
                description = row['desc'] or ''
                features = description_features(description)
                if FOUL.search(description):
                    counts['single_foul_evidence_' + single_foul_evidence(description)] += 1
                for key, value in features.items():
                    counts['all_rows_' + key] += value
                    if row['penalty'] != 1:
                        counts['not_flagged_' + key] += value
                    if row['penalty'] == 0:
                        counts['zero_flag_' + key] += value
                    elif row['penalty'] is None:
                        counts['unknown_flag_' + key] += value
                if row['penalty'] != 1:
                    continue
                counts['flagged_rows'] += 1
                counts['description_present'] += bool(description.strip())
                for key, value in features.items():
                    counts[key] += value
                for field in ('game_id', 'play_id', 'order_sequence', 'down', 'ydstogo',
                              'yardline_100', 'game_seconds_remaining'):
                    counts[field + '_present'] += row[field] is not None
        years[year] = {'source_sha256': actual, 'counts': dict(counts)}
    result = {'source_manifest_sha256': digest(args.manifest), 'seasons': years,
              'limitations': ('Literal text markers may overlap, refer to different fouls, or miss alternate wording. '
                              'They do not establish accepted/declined disposition, enforcement spot, independent '
                              'foul counts, timing, official statistics, or successful next-state reconstruction. '
                              'Source revision and historical publication time are not established.')}
    with args.output.open('x') as out:
        json.dump(result, out, indent=2, sort_keys=True)
        out.write('\n')


if __name__ == '__main__':
    main()
