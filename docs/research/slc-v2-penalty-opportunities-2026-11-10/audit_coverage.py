"""Summarize the existing historical extract without inferring penalty enforcement."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def audit(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    totals = {}
    columns = ['season', 'game_id', 'play_type', 'posteam', 'defteam', 'down', 'ydstogo',
               'yardline_100', 'game_seconds_remaining', 'penalty', 'penalty_type',
               'penalty_team', 'penalty_player_id', 'penalty_yards', 'first_down_penalty']
    for chunk in pd.read_csv(path, usecols=columns, chunksize=100_000, low_memory=False):
        flag = pd.to_numeric(chunk.penalty, errors='coerce')
        marked = flag.eq(1)
        team_known = chunk.penalty_team.notna()
        scrimmage = chunk.play_type.isin(['run', 'pass', 'no_play'])
        contextual = (chunk.posteam.notna() & chunk.defteam.notna() & chunk.down.between(1, 4)
                      & chunk.ydstogo.notna() & chunk.yardline_100.notna()
                      & chunk.game_seconds_remaining.notna())
        measures = pd.DataFrame({'season': chunk.season, 'rows': 1, 'penalty_flagged': marked,
            'known_nonpenalty': flag.eq(0), 'unknown_penalty': flag.isna(),
            'other_penalty_flag': flag.notna() & ~flag.isin([0, 1]),
            'no_play_rows': chunk.play_type.eq('no_play'),
            'no_play_flagged': chunk.play_type.eq('no_play') & marked,
            'penalty_type_known': marked & chunk.penalty_type.notna(),
            'penalty_team_known': marked & team_known,
            'penalty_team_matches_side': marked & team_known &
                (chunk.penalty_team.eq(chunk.posteam) | chunk.penalty_team.eq(chunk.defteam)),
            'penalty_player_known': marked & chunk.penalty_player_id.notna(),
            'penalty_yards_known': marked & chunk.penalty_yards.notna(),
            'first_down_penalty_known': marked & chunk.first_down_penalty.notna(),
            'contextual_scrimmage_rows': scrimmage & contextual,
            'contextual_scrimmage_known_flag': scrimmage & contextual & flag.isin([0, 1]),
            'contextual_scrimmage_flagged': scrimmage & contextual & marked})
        for season, values in measures.groupby('season').sum().to_dict('index').items():
            row = totals.setdefault(int(season), {key: 0 for key in values})
            for key, value in values.items():
                row[key] += int(value)
    return {'input': str(path), 'input_sha256': digest.hexdigest(),
            'interpretation': ('Counts are source rows, not unique foul events, accepted penalties, or validated '
                               'opportunities. The extract lacks descriptions, enforcement, and source availability '
                               'timestamps. no_play is a provider play type, not proof of a pre-snap foul.'),
            'seasons': totals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = audit(args.input)
    with args.output.open('x', encoding='utf-8') as out:
        json.dump(result, out, indent=2, sort_keys=True)
        out.write('\n')


if __name__ == '__main__':
    main()
