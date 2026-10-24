#!/usr/bin/env python3
"""Build the kick-result table (extra points and two-point tries) from the nflverse play-by-play parquet.

The curated dev `nfl_pbp` table keeps `success` but not `extra_point_result` or `two_point_conv_result`. Those two columns
are the publisher's outcome fields, so the rates are rebuilt from them here, from the raw files, not from `success`.

Run with a Python that has pyarrow (the repo's own Python does not):
    /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_kick_results.py [--source-dir DIR]

Input: play_by_play_2022.parquet .. play_by_play_2025.parquet in --source-dir. Their SHA-256 values are recorded in the
manifest, so the table can be checked against the publisher's files later.
Output: docs/fixtures/e2/kick_results_2022_2025.csv and the same name with .manifest.json.
Window: season 2022-2025, regular season, week <= 18 (the window every E2 rate uses).
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEASONS = (2022, 2023, 2024, 2025)
COLUMNS = ('game_id', 'play_id', 'season', 'week', 'season_type', 'play_type', 'posteam', 'defteam', 'yardline_100',
           'two_point_attempt', 'extra_point_result', 'two_point_conv_result', 'field_goal_result', 'kick_distance',
           'success', 'series_result')
DEFAULT_OUT = REPO / 'docs' / 'fixtures' / 'e2' / 'kick_results_2022_2025.csv'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    import pyarrow.parquet as pq  # imported here: only this script needs it

    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', default='/root/nflverse-raw')
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    args = ap.parse_args()
    src = Path(args.source_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'generator': 'scripts/nfl_sequence/build_kick_results.py', 'generator_sha256': sha256(__file__),
                'columns': list(COLUMNS), 'window': 'season 2022-2025, season_type REG, week <= 18',
                'sources': {}, 'rows': {}}
    rows, seen = [], Counter()
    for season in SEASONS:
        path = src / f'play_by_play_{season}.parquet'
        manifest['sources'][path.name] = sha256(path)
        table = pq.read_table(path, columns=list(COLUMNS))
        data = table.to_pydict()
        for i in range(table.num_rows):
            if data['season_type'][i] != 'REG' or (data['week'][i] or 0) > 18:
                continue
            kind = data['play_type'][i]
            if kind not in ('extra_point', 'field_goal') and data['two_point_attempt'][i] != 1:
                continue
            seen[(season, kind or 'two_point_attempt')] += 1
            rows.append({c: data[c][i] for c in COLUMNS})
    rows.sort(key=lambda r: (r['season'], r['game_id'], r['play_id']))
    with open(out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    manifest['rows'] = {f'{s}|{k}': n for (s, k), n in sorted(seen.items())}
    manifest['output'] = {'path': str(out.relative_to(REPO)) if out.is_relative_to(REPO) else str(out),
                          'sha256': sha256(out), 'rows': len(rows)}
    Path(str(out) + '.manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print(f'wrote {out} ({len(rows)} rows)')
    for key, n in sorted(manifest['rows'].items()):
        print(f'  {key}: {n}')


if __name__ == '__main__':
    main()
