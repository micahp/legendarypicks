"""Extract literal penalty clauses and audit scalar-field alignment.

Clause parses are source-text evidence, not official adjudications. The report
counts parse coverage and source-field agreement without producing training labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import pyarrow.parquet as pq


FOUL_MENTION = re.compile(r'\bpenalt(?:y|ies)\b', re.I)
CLAUSE = re.compile(
    r'\bpenalt(?:y|ies)\s+on\s+'
    r'(?P<team>[A-Z]{2,3})(?:-(?P<player>[^,;]+))?,\s*'
    r'(?P<type>[^,;]+),\s*(?P<tail>[^.;]*)', re.I)
STATUS_MARKERS = {
    'declined_text': re.compile(r'\bdeclined\b', re.I),
    'offsetting_text': re.compile(r'\boffsetting\b', re.I),
    'enforced_text': re.compile(r'\benforced\b', re.I),
    'placed_text': re.compile(r'\bplaced at\b', re.I),
}
BATCH_SIZE = 32768
COLUMNS = ('penalty', 'penalty_type', 'penalty_team', 'desc')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_clauses(description: str | None) -> list[dict]:
    """Extract explicit foul clauses and literal evidence fields from a row."""
    clauses = []
    for match in CLAUSE.finditer(description or ''):
        tail = match.group('tail').strip()
        markers = [name for name, pattern in STATUS_MARKERS.items()
                   if pattern.search(tail)]
        clauses.append({'team_text': match.group('team').upper(),
                        'type_text': match.group('type').strip(),
                        'text_markers': markers,
                        'unclassified_text': not markers})
    return clauses


def _scalar_match(row: dict, clause: dict) -> bool:
    if (row['penalty_type'] is None or row['penalty_team'] is None
            or row['penalty_type'].strip().casefold() != clause['type_text'].casefold()
            or row['penalty_team'].upper() != clause['team_text']):
        return False
    return True


def audit_year(path: Path) -> dict:
    counts = Counter()
    flagged_scalar_match_rows = 0
    for batch in pq.ParquetFile(path).iter_batches(
            batch_size=BATCH_SIZE, columns=list(COLUMNS)):
        for row in batch.to_pylist():
            description = row['desc'] or ''
            has_foul_mention = bool(FOUL_MENTION.search(description))
            clauses = parse_clauses(description)
            flag = row['penalty']
            if flag == 1:
                counts['penalty_flag_1_rows'] += 1
            elif flag == 0:
                counts['penalty_flag_0_rows'] += 1
            else:
                counts['penalty_flag_unknown_rows'] += 1
            if has_foul_mention:
                counts['rows_with_penalty_word'] += 1
            counts['rows_with_parsed_clause'] += bool(clauses)
            counts['parsed_clause_count'] += len(clauses)
            counts['rows_with_multiple_parsed_clauses'] += len(clauses) > 1
            counts['rows_with_foul_word_but_no_parsed_clause'] += (
                has_foul_mention and not clauses)
            for clause in clauses:
                counts['clauses_without_status_marker'] += clause['unclassified_text']
                for marker in clause['text_markers']:
                    counts['clause_' + marker] += 1
                if flag == 0:
                    counts['parsed_clauses_on_penalty_flag_0_rows'] += 1
                elif flag is None:
                    counts['parsed_clauses_on_unknown_flag_rows'] += 1
            if flag != 1:
                continue
            matches = [clause for clause in clauses if _scalar_match(row, clause)]
            if matches:
                counts['flagged_rows_scalar_team_type_matches_any_clause'] += 1
                if clauses and matches[0] is clauses[0]:
                    counts['flagged_rows_scalar_matches_first_clause'] += 1
                else:
                    counts['flagged_rows_scalar_matches_later_clause'] += 1
            else:
                counts['flagged_rows_scalar_team_type_matches_no_clause'] += 1
                types = {clause['type_text'].casefold() for clause in clauses}
                teams = {clause['team_text'] for clause in clauses}
                if row['penalty_type'] is None:
                    counts['flagged_rows_scalar_type_missing'] += 1
                elif row['penalty_type'].strip().casefold() not in types:
                    counts['flagged_rows_scalar_type_not_in_text_clauses'] += 1
                if row['penalty_team'] is None:
                    counts['flagged_rows_scalar_team_missing'] += 1
                elif row['penalty_team'].upper() not in teams:
                    counts['flagged_rows_scalar_team_not_in_text_clauses'] += 1
                if (row['penalty_type'] is not None and row['penalty_team'] is not None
                        and row['penalty_type'].strip().casefold() in types
                        and row['penalty_team'].upper() in teams):
                    counts['flagged_rows_scalar_type_and_team_present_but_not_same_clause'] += 1
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    seasons = {}
    for year, item in sorted(manifest['seasons'].items(), key=lambda pair: int(pair[0])):
        path = Path(item['source_path'])
        actual = sha256(path)
        if actual != item['source_sha256']:
            raise ValueError(f'{year} source hash mismatch: {path}')
        seasons[year] = {
            'source_sha256': actual,
            'source_rows': item['rows'],
            'counts': audit_year(path),
        }
    result = {
        'source_manifest_sha256': sha256(args.manifest),
        'batch_size': BATCH_SIZE,
        'seasons': seasons,
        'interpretation': (
            'A parsed clause is a literal source-text unit, not a verified foul or ruling. '
            'Marker counts can overlap. Scalar alignment is a source-internal check. '
            'The official sample validates selected 2025 examples only; no corpus-wide '
            'official adjudication is implied.'),
    }
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(f'audited {len(seasons)} seasons; output: {args.output}')


if __name__ == '__main__':
    main()
