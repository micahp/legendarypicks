#!/usr/bin/env python3
"""Audit the 2022-2025 out-of-bounds rows against Model D's snap-state restart rule."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import clock_d

REPO = Path(__file__).resolve().parents[2]
SEASONS = (2022, 2023, 2024, 2025)
COLUMNS = (
    'season_type', 'week', 'game_id', 'play_id', 'qtr', 'game_seconds_remaining',
    'out_of_bounds', 'timeout', 'play_type', 'complete_pass', 'sack', 'interception',
    'fumble_lost', 'touchdown', 'safety',
)
EXTRAS = REPO / 'docs' / 'fixtures' / 'e2' / 'play_extras_2022_2025.csv'
EXTRAS_MANIFEST = Path(str(EXTRAS) + '.manifest.json')


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def audit(source_dir):
    import pyarrow.parquet as pq

    manifest_bytes = EXTRAS_MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    extras_sha = sha256(EXTRAS)
    if extras_sha != manifest['output']['sha256']:
        raise ValueError('the pinned play-extras CSV does not match its manifest')

    by_season = defaultdict(Counter)
    source_hashes = {}
    for season in SEASONS:
        path = Path(source_dir) / f'play_by_play_{season}.parquet'
        digest = sha256(path)
        expected = manifest['sources'][path.name]
        if digest != expected:
            raise ValueError(f'{path.name} SHA-256 differs from the pinned play-extras manifest')
        source_hashes[path.name] = digest

        table = pq.read_table(path, columns=list(COLUMNS))
        data = table.to_pydict()
        for index in range(table.num_rows):
            if data['season_type'][index] != 'REG' or (data['week'][index] or 0) > 18:
                continue
            is_oob = data['out_of_bounds'][index] == 1
            is_timeout = data['timeout'][index] == 1
            if not is_oob and not is_timeout:
                continue

            counts = by_season[season]
            counts['extras_union_rows'] += 1
            counts['timeout_rows'] += int(is_timeout)
            counts['out_of_bounds_rows'] += int(is_oob)
            counts['out_of_bounds_timeout_overlap'] += int(is_oob and is_timeout)
            counts['manifest_out_of_bounds_priority_rows'] += int(is_oob and not is_timeout)
            if not is_oob:
                continue

            quarter = data['qtr'][index]
            game_seconds = data['game_seconds_remaining'][index]
            if quarter is None or game_seconds is None or int(quarter) not in (1, 2, 3, 4):
                counts['outside_modelled_regulation_state'] += 1
                continue

            quarter = int(quarter)
            qsr = int(round(game_seconds - (4 - quarter) * clock_d.QUARTER_LENGTH))
            event, terminal = _event(data, index)
            stop = clock_d.stop_class(event, True, quarter, qsr, terminal)
            counts[f'clock_class_{stop}'] += 1
            if quarter == 4 and 120 < qsr < 300:
                counts['q4_121_to_299_oob_rows'] += 1
                counts[f'q4_121_to_299_class_{stop}'] += 1
                if stop == 'oob_snap':
                    counts['q4_121_to_299_reclassified_as_snap_restart'] += 1

    expected_oob_priority_by_season = {
        season: int(manifest['rows'][f'{season}|out_of_bounds']) for season in SEASONS
    }
    actual_oob_priority_by_season = {
        season: by_season[season]['manifest_out_of_bounds_priority_rows'] for season in SEASONS
    }
    expected_timeout_by_season = {
        season: int(manifest['rows'][f'{season}|timeout']) for season in SEASONS
    }
    actual_timeout_by_season = {
        season: by_season[season]['timeout_rows'] for season in SEASONS
    }
    if actual_oob_priority_by_season != expected_oob_priority_by_season:
        raise ValueError('out-of-bounds priority counts differ from the pinned manifest')
    if actual_timeout_by_season != expected_timeout_by_season:
        raise ValueError('timeout counts differ from the pinned manifest')

    output = {
        'source_window': 'regular season, 2022-2025, weeks 1-18; overtime rows excluded by Model D',
        'rule': 'NFL 2026 Rule 4-3-2(a): Q2 after the two-minute warning and Q4 inside the final five minutes restart on the snap; otherwise restart on the referee ready signal, except after a change of possession.',
        'out_of_bounds_rows': sum(by_season[season]['out_of_bounds_rows'] for season in SEASONS),
        'out_of_bounds_timeout_overlap_rows': sum(
            by_season[season]['out_of_bounds_timeout_overlap'] for season in SEASONS
        ),
        'extras_union_rows': sum(by_season[season]['extras_union_rows'] for season in SEASONS),
        'q4_121_to_299_oob_rows': sum(
            by_season[season]['q4_121_to_299_oob_rows'] for season in SEASONS
        ),
        'q4_121_to_299_reclassified_as_snap_restart': sum(
            by_season[season]['q4_121_to_299_reclassified_as_snap_restart'] for season in SEASONS
        ),
        'by_season': {str(season): dict(sorted(by_season[season].items())) for season in SEASONS},
        'input_hashes': {
            'play_extras_csv_sha256': extras_sha,
            'play_extras_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'play_by_play_parquet_sha256': source_hashes,
            'clock_d_py_sha256': sha256(Path(clock_d.__file__)),
            'audit_script_sha256': sha256(Path(__file__)),
            'local_nfl_rules_reference_sha256': sha256(
                REPO / 'docs' / 'rules' / 'NFL-2026-GAME-STATE-RULES.md'
            ),
        },
    }
    return output


def _event(data, index):
    """Map the source play into the clock D event families needed for precedence counts."""
    if data['safety'][index] == 1:
        return 'run', 'safety'
    if data['touchdown'][index] == 1:
        return 'run', 'touchdown'
    play_type = data['play_type'][index]
    if play_type == 'field_goal':
        return 'field_goal_attempt', None
    if play_type in ('punt', 'kickoff', 'extra_point'):
        return play_type, None
    if data['interception'][index] == 1:
        return 'interception', None
    if data['fumble_lost'][index] == 1:
        return 'fumble_lost', None
    if play_type == 'pass':
        if data['sack'][index] == 1:
            return 'sack', None
        if data['complete_pass'][index] == 1:
            return 'pass_complete', None
        return 'pass_incomplete', None
    if play_type == 'run':
        return 'run', None
    return 'unsupported', None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', default='/root/nflverse-raw')
    parser.add_argument('--out')
    args = parser.parse_args()
    result = json.dumps(audit(args.source_dir), indent=1, sort_keys=True) + '\n'
    if args.out:
        Path(args.out).write_text(result)
    print(result, end='')


if __name__ == '__main__':
    main()
