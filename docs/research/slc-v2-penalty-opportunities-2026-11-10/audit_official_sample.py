"""Cross-check selected 2025 PBP penalty rows against an NFL GSIS gamebook.

The hand-labeled cases are a validation sample, not a corpus-wide adjudication.
Only source keys, event classifications, and state fields are written; no gamebook
text is copied into the output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq


PBP_SHA256 = {
    '2016': '95eba04e2145e3c1c8ca502f2a3a76cfb0a5990680c3fb480f02a74a45f54a3b',
    '2025': 'c6ecedd6d678cc37ed316b23ef84ee1ec6abb69c514bb11868a7ebd5a367df29',
}
SCHEDULE_SHA256 = 'd07a0e7c18f03cd23e25f295eb322a708602f0e372f6ac4bd597dfeb25cda90c'
SCHEDULE_FIELDS = ('game_id', 'season', 'week', 'gameday', 'away_team',
                   'home_team', 'old_game_id', 'gsis')
STATE_FIELDS = ('qtr', 'game_seconds_remaining', 'posteam', 'down', 'ydstogo',
                'yardline_100', 'play_type')
PENALTY_FIELDS = ('penalty', 'penalty_type', 'penalty_team', 'penalty_yards',
                  'first_down_penalty', 'play_deleted')
PBP_FIELDS = ('game_id', 'play_id', 'order_sequence', *STATE_FIELDS,
              *PENALTY_FIELDS, 'desc')

CASES = (
    {
        'season': 2025, 'game_id': '2025_07_TB_DET', 'gsis_id': 59949,
        'gamebook_url': 'https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf',
        'play_id': 161, 'order_sequence': 161, 'page': 8, 'clock': '12:54',
        'official_events': [
            {'team': 'TB', 'type': 'Illegal Contact', 'disposition': 'accepted',
             'yards': 5}],
        'official_result': 'Third-down pass is nullified; defensive penalty awards a first down.',
        'next_order_sequence': 195,
        'expected_next': {'qtr': 1, 'game_seconds_remaining': 3467, 'posteam': 'DET',
                          'down': 1, 'ydstogo': 10, 'yardline_100': 30,
                          'play_type': 'run'},
    },
    {
        'season': 2025, 'game_id': '2025_07_TB_DET', 'gsis_id': 59949,
        'gamebook_url': 'https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf',
        'play_id': 510, 'order_sequence': 510, 'page': 8, 'clock': '7:42',
        'official_events': [
            {'team': 'TB', 'type': 'False Start', 'disposition': 'accepted', 'yards': 5}],
        'official_result': 'Pre-snap foul repeats first down and increases distance by five.',
        'next_order_sequence': 553,
        'expected_next': {'qtr': 1, 'game_seconds_remaining': 3162, 'posteam': 'TB',
                          'down': 1, 'ydstogo': 15, 'yardline_100': 65,
                          'play_type': 'pass'},
    },
    {
        'season': 2025, 'game_id': '2025_07_TB_DET', 'gsis_id': 59949,
        'gamebook_url': 'https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf',
        'play_id': 938, 'order_sequence': 938, 'page': 10, 'clock': '15:00',
        'official_events': [
            {'team': 'DET', 'type': 'Defensive Pass Interference',
             'disposition': 'accepted', 'yards': 23},
            {'team': 'DET', 'type': 'Defensive Holding',
             'disposition': 'declined', 'yards': None},
        ],
        'official_result': 'Two fouls on one opportunity have different dispositions; next state is first-and-10.',
        'next_order_sequence': 989,
        'expected_next': {'qtr': 2, 'game_seconds_remaining': 2693, 'posteam': 'TB',
                          'down': 1, 'ydstogo': 10, 'yardline_100': 60,
                          'play_type': 'run'},
    },
    {
        'season': 2025, 'game_id': '2025_07_TB_DET', 'gsis_id': 59949,
        'gamebook_url': 'https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf',
        'play_id': 1734, 'order_sequence': 1734, 'page': 10, 'clock': '3:37',
        'official_events': [
            {'team': 'DET', 'type': 'Offensive Pass Interference',
             'disposition': 'accepted', 'yards': 8}],
        'official_result': 'The apparent completion is nullified and second down repeats at a longer distance.',
        'next_order_sequence': 1781,
        'expected_next': {'qtr': 2, 'game_seconds_remaining': 1995, 'posteam': 'DET',
                          'down': 2, 'ydstogo': 15, 'yardline_100': 91,
                          'play_type': 'pass'},
    },
    {
        'season': 2025, 'game_id': '2025_07_TB_DET', 'gsis_id': 59949,
        'gamebook_url': 'https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf',
        'play_id': 2956, 'order_sequence': 2956, 'page': 12, 'clock': '2:59',
        'official_events': [
            {'team': 'TB', 'type': 'Player Out of Bounds on Kick',
             'disposition': 'accepted', 'yards': 5}],
        'official_result': 'Penalty is enforced after the punt; DET starts at its own 30.',
        'next_order_sequence': 2986,
        'expected_next': {'qtr': 3, 'game_seconds_remaining': 1071, 'posteam': 'DET',
                          'down': 1, 'ydstogo': 10, 'yardline_100': 70,
                          'play_type': 'pass'},
    },
    {
        'season': 2025, 'game_id': '2025_07_TB_DET', 'gsis_id': 59949,
        'gamebook_url': 'https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf',
        'play_id': 3358, 'order_sequence': 3358, 'page': 13, 'clock': '11:40',
        'official_events': [
            {'team': 'TB', 'type': 'Illegal Shift', 'disposition': 'declined',
             'yards': None}],
        'official_result': 'Declined foul is described, but the source penalty flag is zero; the next down remains fourth.',
        'next_order_sequence': 3392,
        'expected_next': {'qtr': 4, 'game_seconds_remaining': 696, 'posteam': 'TB',
                          'down': 4, 'ydstogo': 4, 'yardline_100': 63,
                          'play_type': 'pass'},
    },
    {
        'season': 2016, 'game_id': '2016_01_CAR_DEN', 'gsis_id': 56901,
        'gamebook_url': 'https://www.nflgsis.com/2016/REG/01/56901/Gamebook.pdf',
        'play_id': 2098, 'order_sequence': 2098, 'page': 11, 'clock': '10:09',
        'official_events': [
            {'team': 'CAR', 'type': 'Defensive Pass Interference',
             'disposition': 'accepted', 'yards': 15}],
        'official_result': 'Defensive penalty nullifies an incomplete pass and awards a first down.',
        'next_order_sequence': 2131,
        'expected_next': {'qtr': 3, 'game_seconds_remaining': 1505, 'posteam': 'DEN',
                          'down': 1, 'ydstogo': 10, 'yardline_100': 40,
                          'play_type': 'run'},
    },
    {
        'season': 2016, 'game_id': '2016_01_CAR_DEN', 'gsis_id': 56901,
        'gamebook_url': 'https://www.nflgsis.com/2016/REG/01/56901/Gamebook.pdf',
        'play_id': 1826, 'order_sequence': 1826, 'page': 9, 'clock': '0:07',
        'official_events': [
            {'team': 'DEN', 'type': 'Defensive Offside',
             'disposition': 'declined', 'yards': None}],
        'official_result': 'Declined foul does not change the made field goal; source penalty flag is zero.',
        'next_order_sequence': 1857,
        'expected_next': {'qtr': 2, 'game_seconds_remaining': 1803, 'posteam': 'DEN',
                          'down': None, 'ydstogo': 0, 'yardline_100': 35,
                          'play_type': 'kickoff'},
    },
    {
        'season': 2016, 'game_id': '2016_01_CAR_DEN', 'gsis_id': 56901,
        'gamebook_url': 'https://www.nflgsis.com/2016/REG/01/56901/Gamebook.pdf',
        'play_id': 3812, 'order_sequence': 3812, 'page': 13, 'clock': '0:42',
        'official_events': [
            {'team': 'DEN', 'type': 'Roughing the Passer',
             'disposition': 'offsetting', 'yards': None},
            {'team': 'CAR', 'type': 'Intentional Grounding',
             'disposition': 'offsetting', 'yards': None},
        ],
        'official_result': 'Two offsetting fouls leave second-and-10 unchanged; source penalty status is null.',
        'next_order_sequence': 3845,
        'expected_next': {'qtr': 4, 'game_seconds_remaining': 36, 'posteam': 'CAR',
                          'down': 2, 'ydstogo': 10, 'yardline_100': 53,
                          'play_type': 'pass'},
    },
    {
        'season': 2016, 'game_id': '2016_01_CAR_DEN', 'gsis_id': 56901,
        'gamebook_url': 'https://www.nflgsis.com/2016/REG/01/56901/Gamebook.pdf',
        'play_id': 3673, 'order_sequence': 3673, 'page': 13, 'clock': '2:00',
        'official_events': [
            {'team': 'DEN', 'type': 'Illegal Use of Hands',
             'disposition': 'accepted', 'yards': 5}],
        'official_result': 'Fourth-down defensive foul awards a new first down.',
        'next_order_sequence': 3706,
        'expected_next': {'qtr': 4, 'game_seconds_remaining': 114, 'posteam': 'CAR',
                          'down': 1, 'ydstogo': 10, 'yardline_100': 66,
                          'play_type': 'run'},
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def as_int(value):
    return None if value is None else int(value)


def state(row):
    return {field: (as_int(row[field]) if field in {
        'qtr', 'game_seconds_remaining', 'down', 'ydstogo', 'yardline_100'}
                    else row[field]) for field in STATE_FIELDS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--schedule', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    pbp_hashes = {}
    pbp_paths = {}
    for season, expected_hash in PBP_SHA256.items():
        item = manifest['seasons'][season]
        pbp_path = Path(item['source_path'])
        actual_hash = sha256(pbp_path)
        if actual_hash != expected_hash or item['source_sha256'] != expected_hash:
            raise ValueError(f'{season} PBP source hash mismatch: {pbp_path}')
        pbp_hashes[season] = actual_hash
        pbp_paths[season] = pbp_path
    schedule_hash = sha256(args.schedule)
    if schedule_hash != SCHEDULE_SHA256:
        raise ValueError(f'schedule source hash mismatch: {args.schedule}')

    schedule = pq.read_table(args.schedule, columns=list(SCHEDULE_FIELDS))
    schedule_by_game = {row['game_id']: row for row in schedule.to_pylist()}
    by_game = {}
    for game_id in {case['game_id'] for case in CASES}:
        game_cases = [case for case in CASES if case['game_id'] == game_id]
        game = schedule_by_game.get(game_id)
        if game is None:
            raise ValueError(f'missing schedule row for {game_id}')
        if any(game['gsis'] != case['gsis_id'] or game['season'] != case['season']
               for case in game_cases):
            raise ValueError(f'schedule-to-official-gamebook identity mismatch for {game_id}')
        table = pq.read_table(pbp_paths[str(game['season'])], columns=list(PBP_FIELDS),
                              filters=[('game_id', '=', game_id)])
        rows = sorted(table.to_pylist(), key=lambda row: row['order_sequence'])
        by_game[game_id] = ({as_int(row['order_sequence']): row for row in rows}, game)
    results = []
    for case in CASES:
        by_order, game = by_game[case['game_id']]
        row = by_order.get(case['order_sequence'])
        if row is None or as_int(row['play_id']) != case['play_id']:
            raise ValueError(f"source row identity mismatch for play {case['play_id']}")
        following = by_order.get(case['next_order_sequence'])
        if following is None or state(following) != case['expected_next']:
            raise ValueError(f"source next-state mismatch for play {case['play_id']}")
        results.append({
            'game': {key: game[key] for key in SCHEDULE_FIELDS},
            'official_gamebook_url': case['gamebook_url'],
            'play_id': case['play_id'],
            'order_sequence': case['order_sequence'],
            'official_page': case['page'],
            'official_clock': case['clock'],
            'official_events': case['official_events'],
            'official_result': case['official_result'],
            'source_row': {
                'play_id': as_int(row['play_id']),
                'order_sequence': as_int(row['order_sequence']),
                'state_before': state(row),
                'penalty_fields': {field: row[field] for field in PENALTY_FIELDS},
                'description_mentions_penalty': 'penalt' in (row['desc'] or '').lower(),
            },
            'next_source_state': state(following),
        })

    result = {
        'sample_type': 'manual official-record cross-check across two games; not a representative or corpus-wide adjudication',
        'source_manifest_sha256': sha256(args.manifest),
        'pbp_sha256_by_season': pbp_hashes,
        'schedule_sha256': schedule_hash,
        'cases': results,
        'limitations': [
            'All sampled plays come from two games, in 2016 and 2025, and do not establish field semantics across all eras.',
            'Official foul labels were manually read from the linked GSIS gamebook at the listed page and clock.',
            'The sample validates selected PBP mappings and adjacent source states; it is not model training data.',
        ],
    }
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(f"validated {len(results)} official gamebook cases; output: {args.output}")


if __name__ == '__main__':
    main()
