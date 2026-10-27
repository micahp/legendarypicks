#!/usr/bin/env python3
"""Sparse play flags that the curated dev table lacks: timeouts called and plays ending out of bounds.

Run with the pyarrow venv: /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_play_extras.py

Input: play_by_play_2022..2025.parquet in --source-dir (the same files as build_kick_results.py; SHA-256 in the
manifest). Output: docs/fixtures/e2/play_extras_2022_2025.csv, one row per play with timeout == 1 or out_of_bounds == 1,
and a manifest. Only rows in the E2 window (regular season, week <= 18) are kept.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEASONS = (2022, 2023, 2024, 2025)
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'posteam', 'defteam', 'timeout', 'timeout_team', 'out_of_bounds')
DEFAULT_OUT = REPO / 'docs' / 'fixtures' / 'e2' / 'play_extras_2022_2025.csv'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', default='/root/nflverse-raw')
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    args = ap.parse_args()
    src, out = Path(args.source_dir), Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'generator': 'scripts/nfl_sequence/build_play_extras.py', 'generator_sha256': sha256(__file__),
                'columns': list(COLUMNS), 'window': 'season 2022-2025, season_type REG, week <= 18',
                'sources': {}, 'rows': {}}
    rows, counts = [], Counter()
    for season in SEASONS:
        path = src / f'play_by_play_{season}.parquet'
        manifest['sources'][path.name] = sha256(path)
        columns = ['game_id', 'play_id', 'season', 'week', 'season_type', 'posteam', 'defteam', 'timeout',
                   'timeout_team', 'out_of_bounds']
        table = pq.read_table(path, columns=columns)
        data = table.to_pydict()
        for i in range(table.num_rows):
            if data['season_type'][i] != 'REG' or (data['week'][i] or 0) > 18:
                continue
            if data['timeout'][i] != 1 and data['out_of_bounds'][i] != 1:
                continue
            counts[(season, 'timeout' if data['timeout'][i] == 1 else 'out_of_bounds')] += 1
            rows.append({'game_id': data['game_id'][i], 'play_id': data['play_id'][i], 'season': data['season'][i],
                         'week': data['week'][i], 'posteam': data['posteam'][i], 'defteam': data['defteam'][i],
                         'timeout': int(data['timeout'][i] == 1),
                         'timeout_team': data['timeout_team'][i] or '',
                         'out_of_bounds': int(data['out_of_bounds'][i] == 1)})
    rows.sort(key=lambda r: (r['season'], r['game_id'], r['play_id']))
    with open(out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    manifest['rows'] = {f'{s}|{k}': n for (s, k), n in sorted(counts.items())}
    manifest['output'] = {'path': str(out.relative_to(REPO)), 'sha256': sha256(out), 'rows': len(rows)}
    Path(str(out) + '.manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print(f'wrote {out} ({len(rows)} rows)')
    for key, n in sorted(manifest['rows'].items()):
        print(f'  {key}: {n}')


if __name__ == '__main__':
    main()
