#!/usr/bin/env python3
"""Extract the play flags the clock audit needs from the nflverse 2022 play-by-play parquet, weeks 1-9.

Run with the pyarrow environment (the only read that needs it):
    /root/.venvs/nfl-parquet/bin/python scripts/bdb/e3_extract_nflverse_flags.py

The source file's SHA-256 is checked against /root/nflverse-raw/SHA256SUMS before anything is read; a mismatch stops the run.
The dev database has no out_of_bounds or timeout column, so they come from the parquet, keyed on (game_id, play_id).
Output: docs/evidence/e3/inputs/nflverse-2022-w1-9-flags.csv and a manifest with the source hash.
"""
import csv
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('/root/nflverse-raw/play_by_play_2022.parquet')
SUMS = Path('/root/nflverse-raw/SHA256SUMS')
OUT = ROOT / 'docs' / 'evidence' / 'e3' / 'inputs'
COLUMNS = ['game_id', 'play_id', 'week', 'season_type', 'out_of_bounds', 'timeout', 'timeout_team']


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def expected_hash():
    for line in open(SUMS):
        digest, name = line.split(maxsplit=1)
        if name.strip().lstrip('*') == SOURCE.name:
            return digest
    raise SystemExit(f'{SOURCE.name} is not listed in {SUMS}')


def main():
    actual, expected = sha256(SOURCE), expected_hash()
    if actual != expected:
        raise SystemExit(f'source hash mismatch for {SOURCE.name}: {actual} != {expected}')
    table = pq.read_table(SOURCE, columns=COLUMNS).to_pylist()
    rows = [r for r in table if r['season_type'] == 'REG' and r['week'] is not None and 1 <= r['week'] <= 9]
    OUT.mkdir(parents=True, exist_ok=True)
    out_csv = OUT / 'nflverse-2022-w1-9-flags.csv'
    with open(out_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for r in sorted(rows, key=lambda r: (r['game_id'], r['play_id'])):
            writer.writerow({k: ('' if r[k] is None else r[k]) for k in COLUMNS})
    manifest = {'source': str(SOURCE), 'source_sha256': actual, 'rows': len(rows), 'columns': COLUMNS,
                'filter': 'season_type == REG and week in 1..9', 'output_sha256': sha256(out_csv),
                'generator': 'scripts/bdb/e3_extract_nflverse_flags.py'}
    (OUT / 'nflverse-2022-w1-9-flags.manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print(json.dumps(manifest, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
