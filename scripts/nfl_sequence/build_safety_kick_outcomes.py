#!/usr/bin/env python3
"""Build the observed safety free-kick outcome pool from nflverse play-by-play, 2022-2025 regular season.

A safety awards two points to the defence. The team scored upon kicks a free kick from its own 20-yard line (rules file
section 5A.2; Rules 6-1-1(b), 6-1-2 and 11-5-2). Each row joins a flagged safety play to the free kick that follows it and
to the first scrimmage snap of the receiving team, so the spot and clock are what the receiving team actually got. Rows that
cannot be classified are kept with a status, so the simulator refuses on them instead of dropping them silently.

The flag is nflverse's own `safety` field on the play that scored it. The LP dev nfl_pbp table has no such field, so this
fixture is built from the raw parquet files, whose SHA-256 sums are checked against SHA256SUMS before they are read.

Run with the parquet environment:
    /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_safety_kick_outcomes.py
"""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEASONS = (2022, 2023, 2024, 2025)
DEFAULT_SOURCE = Path('/root/nflverse-raw')
DEFAULT_OUT = REPO / 'docs/fixtures/e2/safety_kick_outcomes_2022_2025.csv'
KICK_SCAN = 6  # plays searched after the safety for its free kick; penalties, timeouts and no-plays may sit between
SNAP_SCAN = 6  # plays searched after the kick for the receiving team's first scrimmage snap
SCRIMMAGE = ('run', 'pass')
COLUMNS = (
    'safety_play_id', 'kick_play_id', 'receiving_snap_play_id', 'game_id', 'game_date', 'season', 'week', 'quarter',
    'kick_type',
    'kicking_team', 'receiving_team', 'kick_distance', 'touchback', 'return_yards', 'kick_clock_seconds',
    'snap_clock_seconds', 'clock_runoff_seconds', 'receiving_snap_yardline_100', 'receiving_snap_down',
    'receiving_snap_ydstogo', 'status', 'status_note', 'kick_desc', 'source_file', 'source_sha256',
)
READ_COLUMNS = (
    'game_id', 'game_date', 'play_id', 'season', 'season_type', 'week', 'posteam', 'defteam', 'qtr', 'down', 'ydstogo',
    'yardline_100', 'game_seconds_remaining', 'play_type', 'safety', 'kickoff_attempt', 'punt_attempt', 'touchback',
    'kick_distance', 'return_yards', 'desc',
)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_sources(source_dir):
    """The raw files must match the checksum file that came with them, or the fixture is not reproducible."""
    expected = {}
    for line in (source_dir / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        expected[name.strip().lstrip('*')] = digest
    for season in SEASONS:
        name = f'play_by_play_{season}.parquet'
        if name not in expected:
            raise ValueError(f'{name} is not listed in SHA256SUMS')
        if sha256(source_dir / name) != expected[name]:
            raise ValueError(f'{name} does not match SHA256SUMS')
    return {f'play_by_play_{s}.parquet': expected[f'play_by_play_{s}.parquet'] for s in SEASONS}


def _kick_type(kick):
    return 'kickoff' if kick['kickoff_attempt'] == 1 else 'punt'


def _find_kick(plays, index):
    """The free kick after a safety. Scrimmage plays before a kick mean there was no free kick; other plays are skipped."""
    for j in range(index + 1, min(index + 1 + KICK_SCAN, len(plays))):
        q = plays[j]
        if q['kickoff_attempt'] == 1 or q['punt_attempt'] == 1:
            return j
        if q['play_type'] in SCRIMMAGE:
            return None
    return None


def _snap_after(plays, kick_index, kick, receiver):
    """The receiving team's first run or pass after the kick, in the kick's quarter."""
    for j in range(kick_index + 1, min(kick_index + 1 + SNAP_SCAN, len(plays))):
        q = plays[j]
        if q['qtr'] != kick['qtr']:
            return None
        if q['posteam'] == receiver and q['play_type'] in SCRIMMAGE:
            return q
    return None


def build_record(plays, index, source_file, source_hash):
    safety = plays[index]
    base = {
        'safety_play_id': safety['play_id'], 'game_id': safety['game_id'], 'game_date': safety['game_date'],
        'season': safety['season'], 'week': safety['week'], 'quarter': safety['qtr'],
        'kicking_team': safety['posteam'], 'receiving_team': safety['defteam'], 'source_file': source_file,
        'source_sha256': source_hash, 'kick_play_id': '', 'kick_type': '', 'kick_distance': '', 'touchback': '',
        'return_yards': '', 'kick_clock_seconds': '', 'snap_clock_seconds': '', 'clock_runoff_seconds': '',
        'receiving_snap_play_id': '', 'receiving_snap_yardline_100': '', 'receiving_snap_down': '',
        'receiving_snap_ydstogo': '', 'kick_desc': '',
    }

    def refuse(status, note):
        return {**base, 'status': status, 'status_note': note}

    if safety['qtr'] is None or int(safety['qtr']) > 4:
        return refuse('overtime_quarter', 'the safety is in overtime, outside the regulation-only pool')
    kick_index = _find_kick(plays, index)
    if kick_index is None:
        return refuse('no_free_kick_found', 'no kickoff or punt before the next scrimmage play')
    kick = plays[kick_index]
    kick_type = _kick_type(kick)
    receiver, kicker = safety['defteam'], safety['posteam']
    base.update({'kick_play_id': kick['play_id'], 'kick_type': kick_type, 'kick_desc': kick['desc'] or '',
                 'kick_distance': '' if kick['kick_distance'] is None else int(kick['kick_distance']),
                 'touchback': '' if kick['touchback'] is None else int(kick['touchback']),
                 'return_yards': '' if kick['return_yards'] is None else int(kick['return_yards']),
                 'kick_clock_seconds': '' if kick['game_seconds_remaining'] is None else int(kick['game_seconds_remaining'])})
    # nflverse puts the receiving team on a kickoff row and the kicking team on a punt row.
    expected_team = receiver if kick_type == 'kickoff' else kicker
    if kick['posteam'] != expected_team:
        return refuse('kick_team_inconsistent', f'{kick_type} row posteam {kick["posteam"]} is not {expected_team}')
    if kick['qtr'] != safety['qtr']:
        return refuse('kick_in_later_quarter', 'the free kick is in a later quarter than the safety')
    snap = _snap_after(plays, kick_index, kick, receiver)
    if snap is None:
        return refuse('no_receiving_snap_same_quarter', 'no receiving-team run or pass before the quarter ends')
    base.update({'receiving_snap_play_id': snap['play_id'], 'receiving_snap_down': '' if snap['down'] is None else int(snap['down']),
                 'receiving_snap_ydstogo': '' if snap['ydstogo'] is None else int(snap['ydstogo']),
                 'snap_clock_seconds': '' if snap['game_seconds_remaining'] is None else int(snap['game_seconds_remaining'])})
    if kick['game_seconds_remaining'] is None or snap['game_seconds_remaining'] is None:
        return refuse('clock_missing', 'the kick or the receiving snap has no game clock')
    runoff = int(round(kick['game_seconds_remaining'] - snap['game_seconds_remaining']))
    base['clock_runoff_seconds'] = runoff
    if runoff < 0:
        return refuse('impossible_runoff', f'clock runs backwards by {-runoff} seconds')
    if snap['yardline_100'] is None or not 1 <= int(snap['yardline_100']) <= 99:
        return refuse('spot_missing', 'the receiving snap has no usable field position')
    base['receiving_snap_yardline_100'] = int(snap['yardline_100'])
    return {**base, 'status': 'usable', 'status_note': ''}


def _quantiles(values):
    if not values:
        return None
    ordered = sorted(values)

    def at(q):
        return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]
    return {'n': len(ordered), 'min': ordered[0], 'p10': at(0.10), 'p25': at(0.25), 'median': at(0.50),
            'p75': at(0.75), 'p90': at(0.90), 'max': ordered[-1], 'mean': round(sum(ordered) / len(ordered), 2)}


def main():
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', type=Path, default=DEFAULT_SOURCE)
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    source_hashes = verify_sources(args.source_dir)
    records = []
    safeties = 0
    for season in SEASONS:
        name = f'play_by_play_{season}.parquet'
        data = pq.read_table(args.source_dir / name, columns=list(READ_COLUMNS)).to_pydict()
        rows = [{key: data[key][i] for key in READ_COLUMNS} for i in range(len(data['game_id']))]
        by_game = defaultdict(list)
        for row in rows:
            by_game[row['game_id']].append(row)
        for game_rows in by_game.values():
            game_rows.sort(key=lambda r: r['play_id'])
            for index, row in enumerate(game_rows):
                if row['safety'] != 1 or row['season_type'] != 'REG' or (row['week'] or 0) > 18:
                    continue
                safeties += 1
                records.append(build_record(game_rows, index, name, source_hashes[name]))
    records.sort(key=lambda r: (r['season'], r['game_id'], int(r['safety_play_id'])))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    usable = [r for r in records if r['status'] == 'usable']
    manifest = {
        'generator': str(Path(__file__).relative_to(REPO)), 'generator_sha256': sha256(__file__),
        'window': '2022-2025 regular season, week <= 18', 'source_dataset': 'nflverse play_by_play parquet',
        'sources': source_hashes, 'columns': list(COLUMNS), 'safety_plays': safeties,
        'record_count': len(records), 'usable_count': len(usable),
        'status_counts': dict(sorted(Counter(r['status'] for r in records).items())),
        'usable_by_kick_type': dict(sorted(Counter(r['kick_type'] for r in usable).items())),
        'usable_spot_yardline_100': _quantiles([r['receiving_snap_yardline_100'] for r in usable]),
        'usable_clock_runoff_seconds': _quantiles([r['clock_runoff_seconds'] for r in usable]),
        'output': {'path': str(args.out.relative_to(REPO)) if args.out.is_relative_to(REPO) else str(args.out),
                   'sha256': sha256(args.out)},
    }
    args.out.with_suffix(args.out.suffix + '.manifest.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'safety_plays': safeties, 'records': len(records), 'usable': len(usable),
                      'status_counts': manifest['status_counts'], 'sha256': manifest['output']['sha256']}, indent=2))


if __name__ == '__main__':
    main()
