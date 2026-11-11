"""Count literal foul-description evidence; never infer official adjudication."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


DISPOSITION_MARKERS = ('declined', 'offsetting', 'enforced')
FOUL_PATTERN = r'\bpenalt(?:y|ies)\b'
FOUL = re.compile(FOUL_PATTERN, re.I)
MARKER_PATTERNS = {
    'declined': re.compile(r'\bdeclined\b', re.I),
    'offsetting': re.compile(r'\boffsetting\b|\boffset\b', re.I),
    'enforced': re.compile(r'\benforced\b', re.I),
    'no_play': re.compile(r'\bno play\b', re.I),
    'half_distance': re.compile(r'\bhalf the distance\b|\bhalf distance\b', re.I),
    'automatic_first_down': re.compile(r'\bautomatic(?:ally)? first down\b', re.I),
}


def description_features(description):
    text = description or ''
    return {**{name: bool(pattern.search(text))
               for name, pattern in MARKER_PATTERNS.items()},
            'multiple_penalty_mentions': len(FOUL.findall(text)) > 1}


def single_foul_evidence(description):
    """Return one literal marker only when the row names one foul and ruling."""
    text = description or ''
    if len(FOUL.findall(text)) != 1:
        return 'ambiguous_or_no_foul_mention'
    hits = [key for key in ('declined', 'offsetting', 'enforced')
            if MARKER_PATTERNS[key].search(text)]
    return hits[0] if len(hits) == 1 else 'ambiguous_or_no_disposition_marker'


def _count(mask):
    """Count true values in an Arrow boolean array, treating null as false."""
    return pc.sum(pc.cast(pc.fill_null(mask, False), pa.int64())).as_py() or 0


def _and(left, right):
    return pc.fill_null(pc.and_(left, right), False)


def _not(mask):
    return pc.fill_null(pc.invert(mask), False)


def _add_if_positive(counts, key, amount):
    if amount:
        counts[key] += amount


def count_batch(counts, batch):
    """Accumulate all report counters with vectorized Arrow kernels."""
    descriptions = pc.utf8_lower(pc.fill_null(batch['desc'], ''))
    mentions = pc.count_substring_regex(descriptions, FOUL_PATTERN)
    markers = {
        'declined': pc.match_substring_regex(descriptions, r'\bdeclined\b'),
        'offsetting': pc.match_substring_regex(descriptions, r'\boffsetting\b|\boffset\b'),
        'enforced': pc.match_substring_regex(descriptions, r'\benforced\b'),
        'no_play': pc.match_substring_regex(descriptions, r'\bno play\b'),
        'half_distance': pc.match_substring_regex(
            descriptions, r'\bhalf the distance\b|\bhalf distance\b'),
        'automatic_first_down': pc.match_substring_regex(
            descriptions, r'\bautomatic(?:ally)? first down\b'),
    }
    features = {**markers, 'multiple_penalty_mentions': pc.greater(mentions, 1)}
    penalty = batch['penalty']
    flagged = pc.fill_null(pc.equal(penalty, 1), False)
    zero_flag = pc.fill_null(pc.equal(penalty, 0), False)
    unknown_flag = pc.is_null(penalty)
    not_flagged = _not(flagged)

    for name, values in features.items():
        counts['all_rows_' + name] += _count(values)
        counts['not_flagged_' + name] += _count(_and(not_flagged, values))
        counts['zero_flag_' + name] += _count(_and(zero_flag, values))
        counts['unknown_flag_' + name] += _count(_and(unknown_flag, values))
        counts[name] += _count(_and(flagged, values))

    has_foul_mention = pc.greater(mentions, 0)
    disposition_count = pc.add(
        pc.add(*(pc.cast(markers[name], pa.int8()) for name in DISPOSITION_MARKERS[:2])),
        pc.cast(markers[DISPOSITION_MARKERS[2]], pa.int8()))
    one_foul = pc.equal(mentions, 1)
    one_disposition = pc.equal(disposition_count, 1)
    clear_single = _and(one_foul, one_disposition)
    _add_if_positive(counts, 'single_foul_evidence_enforced',
                     _count(_and(clear_single, markers['enforced'])))
    _add_if_positive(counts, 'single_foul_evidence_declined',
                     _count(_and(clear_single, markers['declined'])))
    _add_if_positive(counts, 'single_foul_evidence_offsetting',
                     _count(_and(clear_single, markers['offsetting'])))
    _add_if_positive(counts, 'single_foul_evidence_ambiguous_or_no_foul_mention',
                     _count(_and(has_foul_mention, _not(one_foul))))
    _add_if_positive(counts, 'single_foul_evidence_ambiguous_or_no_disposition_marker',
                     _count(_and(one_foul, _not(one_disposition))))

    counts['flagged_rows'] += _count(flagged)
    description_present = pc.match_substring_regex(descriptions, r'\S')
    counts['description_present'] += _count(_and(flagged, description_present))
    for field in ('game_id', 'play_id', 'order_sequence', 'down', 'ydstogo',
                  'yardline_100', 'game_seconds_remaining'):
        counts[field + '_present'] += _count(_and(flagged, pc.is_valid(batch[field])))


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
            count_batch(counts, batch)
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
