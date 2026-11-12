"""Compare simple false starts with the next recorded pre-play state.

This is a source consistency check, not independent official adjudication.
"""
import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from audit_source_descriptions import digest

COLS = ['game_id', 'play_id', 'order_sequence', 'desc', 'penalty', 'penalty_type',
        'penalty_team', 'penalty_yards', 'play_type', 'posteam', 'down', 'ydstogo',
        'yardline_100', 'qtr', 'game_seconds_remaining', 'total_home_score',
        'total_away_score']
STATE = ['play_id', 'posteam', 'down', 'ydstogo', 'yardline_100', 'qtr',
         'game_seconds_remaining', 'total_home_score', 'total_away_score']


def audit(df):
    ordered = df.order_sequence.notna() & df.game_id.notna()
    ordered_df = df.loc[ordered]
    duplicates = set(ordered_df.loc[ordered_df.duplicated(['game_id', 'order_sequence'], keep=False), 'game_id'])
    d = ordered_df.loc[~ordered_df.game_id.isin(duplicates)].sort_values(
        ['game_id', 'order_sequence'], kind='stable').copy()
    group = d.groupby('game_id', sort=False)
    for col in STATE:
        d['next_' + col] = group[col].shift(-1)
    text = d.desc.fillna('')
    # Exclude multi-foul, declined and ambiguous descriptions and half-distance cases.
    eligible = (d.penalty.eq(1) & d.penalty_type.eq('False Start') &
                d.penalty_team.eq(d.posteam) & d.penalty_yards.eq(5) &
                d.play_type.eq('no_play') & text.str.count(r'(?i)\bpenalty\b').eq(1) &
                text.str.contains(r'(?i)\benforced\b', regex=True) &
                ~text.str.contains(r'(?i)\b(?:declined|offsetting|half the distance)\b', regex=True) &
                d.down.between(1, 4) & d.ydstogo.gt(0) & d.yardline_100.between(1, 90))
    candidates = d.loc[eligible].copy()
    present = candidates[['posteam', 'down', 'ydstogo', 'yardline_100', 'qtr',
                          'game_seconds_remaining', 'total_home_score', 'total_away_score'] +
                         ['next_' + col for col in STATE]].notna().all(axis=1)
    same_context = (present & candidates.posteam.eq(candidates.next_posteam) &
                    candidates.qtr.eq(candidates.next_qtr) &
                    candidates.total_home_score.eq(candidates.next_total_home_score) &
                    candidates.total_away_score.eq(candidates.next_total_away_score))
    check = candidates.loc[same_context].copy()
    matches = (check.next_down.eq(check.down) & check.next_ydstogo.eq(check.ydstogo + 5) &
               check.next_yardline_100.eq(check.yardline_100 + 5) &
               check.next_game_seconds_remaining.le(check.game_seconds_remaining))
    examples = []
    for _, row in check.loc[~matches].head(20).iterrows():
        examples.append({k: (None if pd.isna(row[k]) else row[k].item() if hasattr(row[k], 'item') else row[k])
                         for k in ['game_id', 'play_id', 'desc', 'down', 'ydstogo', 'yardline_100',
                                   'game_seconds_remaining', 'next_play_id', 'next_down', 'next_ydstogo',
                                   'next_yardline_100', 'next_game_seconds_remaining']})
    return {'duplicate_order_games_excluded': len(duplicates), 'simple_false_start_candidates': len(candidates),
            'complete_same_team_period_score_next_rows': len(check), 'matching_expected_state': int(matches.sum()),
            'nonmatching_expected_state': int((~matches).sum()), 'nonmatching_examples': examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seasons', type=int, nargs='+', default=[2025, 2026])
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    result = {}
    for season in args.seasons:
        item = manifest['seasons'][str(season)]
        path = Path(item['source_path'])
        source_hash = digest(path)
        if source_hash != item['source_sha256']:
            raise ValueError(f'{season} source hash mismatch: {path}')
        result[str(season)] = {'source_sha256': source_hash, **audit(pq.read_table(path, columns=COLS).to_pandas())}
    output = {'source_manifest_sha256': digest(args.manifest), 'seasons': result,
              'limitations': 'Immediate next source row only; no independent official record validation. '
              'Clock check permits elapsed time and does not validate a clock rule. '
              'Half-distance, multiple fouls, possession changes and period changes are excluded.'}
    with args.output.open('x') as f:
        json.dump(output, f, indent=2, sort_keys=True)
        f.write('\n')


if __name__ == '__main__':
    main()
