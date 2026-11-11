"""Assess source ordering and adjacent-row state coverage, not enforced outcomes."""
import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from audit_source_descriptions import digest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    manifest = json.loads(args.manifest.read_text())
    result = {}
    columns = ['game_id', 'play_id', 'order_sequence', 'penalty', 'posteam', 'down', 'ydstogo',
               'yardline_100', 'qtr', 'game_seconds_remaining']
    for year, item in sorted(manifest['seasons'].items()):
        path = Path(item['source_path'])
        source_hash = digest(path)
        if source_hash != item['source_sha256']:
            raise ValueError(f'{year} source hash mismatch: {path}')
        df = pq.read_table(path, columns=columns).to_pandas()
        flagged = df.penalty.eq(1)
        ordered = df.order_sequence.notna() & df.game_id.notna()
        dup = df.loc[ordered].duplicated(['game_id', 'order_sequence'], keep=False)
        duplicate_games = set(df.loc[ordered].loc[dup, 'game_id'])
        safe = df.loc[ordered & ~df.game_id.isin(duplicate_games)].sort_values(
            ['game_id', 'order_sequence'], kind='stable').copy()
        grouped = safe.groupby('game_id', sort=False)
        for col in ('play_id', 'posteam', 'down', 'ydstogo', 'yardline_100', 'qtr', 'game_seconds_remaining'):
            safe['next_' + col] = grouped[col].shift(-1)
        f = safe.loc[safe.penalty.eq(1)]
        next_exists = f.next_play_id.notna()
        next_state = next_exists.copy()
        for col in ('posteam', 'down', 'ydstogo', 'yardline_100', 'qtr', 'game_seconds_remaining'):
            next_state &= f['next_' + col].notna()
        result[year] = {'source_sha256': source_hash, 'flagged_rows': int(flagged.sum()),
                        'flagged_with_order': int((flagged & ordered).sum()),
                        'games_with_duplicate_order': len(duplicate_games),
                        'flagged_in_unambiguous_ordered_games': len(f),
                        'flagged_with_following_source_row': int(next_exists.sum()),
                        'flagged_with_complete_following_row_fields': int(next_state.sum())}
    payload = {'source_manifest_sha256': digest(args.manifest), 'seasons': result,
               'limitations': ('The next source row is not necessarily the post-enforcement state or the next '
                               'football opportunity. Administrative rows, period boundaries, possession changes, '
                               'and missing rows require review. Complete fields and unique order do not prove legality '
                               'or source acquisition before a historical kickoff.')}
    with args.output.open('x') as out:
        json.dump(payload, out, indent=2, sort_keys=True)
        out.write('\n')


if __name__ == '__main__':
    main()
