#!/usr/bin/env python3
"""Build the observed regular-season overtime drive pool from nflverse play-by-play, 2022-2025.

Rule 16, Article 3 (regular season) gives one 10-minute period. Each row here is one observed overtime drive: its offense,
its start spot and clock, how it ended (touchdown, field goal, punt, turnover, turnover on downs, period end, ...), the
points each side scored on it, and the other team's next start. The engine samples these records the way it samples blocked
kicks: a record is drawn only when it fits the state, a record it cannot classify is kept with a status and refused by name.
The Rule 16 possession and winner logic in game_state.py checks each draw; it does not supply the outcome.

Raw files are read only after their SHA-256 sums match SHA256SUMS.

Run with the parquet environment:
    /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_overtime_drives.py
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
DEFAULT_OUT = REPO / 'docs/fixtures/e2/overtime_drives_2022_2025.csv'
OVERTIME_QUARTER = 5
SCRIMMAGE = ('run', 'pass', 'punt', 'field_goal', 'qb_kneel', 'qb_spike')
RESULT_OUTCOME = {
    'Touchdown': 'touchdown', 'Opp touchdown': 'defense_touchdown', 'Field goal': 'field_goal_made',
    'Missed field goal': 'field_goal_missed', 'Punt': 'punt', 'Turnover': 'turnover',
    'Turnover on downs': 'turnover_on_downs', 'End of half': 'period_end',
}
COLUMNS = (
    'game_id', 'game_date', 'season', 'week', 'drive', 'offense', 'defense', 'start_yardline_100', 'start_clock_seconds',
    'end_clock_seconds', 'duration_seconds', 'plays', 'fixed_drive_result', 'outcome', 'points_offense', 'points_defense',
    'try_kind', 'try_made', 'try_team', 'turnover_kind',
    'next_offense', 'next_start_yardline_100', 'next_start_clock_seconds', 'status', 'status_note', 'source_file',
    'source_sha256',
)
READ_COLUMNS = (
    'game_id', 'game_date', 'season', 'season_type', 'week', 'qtr', 'drive', 'play_id', 'posteam', 'defteam', 'play_type',
    'yardline_100', 'game_seconds_remaining', 'fixed_drive_result', 'touchdown', 'td_team', 'field_goal_result',
    'safety', 'interception', 'fumble_lost', 'posteam_score', 'posteam_score_post', 'defteam_score', 'defteam_score_post',
    'kickoff_attempt', 'extra_point_attempt', 'two_point_attempt', 'two_point_conv_result', 'extra_point_result', 'desc',
)


def score_change(first_row, last_row, team):
    """Points a team scored between a drive's first and last row, read from whichever side of the score it holds."""
    def score(row, post):
        if row['posteam'] == team:
            return row['posteam_score_post' if post else 'posteam_score']
        if row['defteam'] == team:
            return row['defteam_score_post' if post else 'defteam_score']
        return None
    before, after = score(first_row, False), score(last_row, True)
    return None if before is None or after is None else int(after - before)


def try_points(kind, made):
    return ({'extra_point': 1, 'two_point': 2}[kind] if made else 0)


def turnover_kind(rows):
    """How the ball changed hands on a drive, from the play rows: an interception, a lost fumble, or neither."""
    if any(r['interception'] == 1 for r in rows):
        return 'interception'
    if any(r['fumble_lost'] == 1 for r in rows):
        return 'fumble'
    return 'other'


def _int(value):
    return None if value is None else int(value)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_sources(source_dir):
    """The raw files must match the checksum file that came with them, or the pool is not reproducible."""
    expected = {}
    for line in (source_dir / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        expected[name.strip().lstrip('*')] = digest
    out = {}
    for season in SEASONS:
        name = f'play_by_play_{season}.parquet'
        if name not in expected:
            raise ValueError(f'{name} is not listed in SHA256SUMS')
        if sha256(source_dir / name) != expected[name]:
            raise ValueError(f'{name} does not match SHA256SUMS')
        out[name] = expected[name]
    return out


def classify(drive, offense, defense):
    """The observed ending of one drive. Anything the publisher does not label is unclassified and refused."""
    results = drive['results']
    result = next(iter(results)) if len(results) == 1 else None
    scored_by = {p['td_team'] for p in drive['plays'] if p['touchdown'] == 1 and p['td_team']}
    if any(p['field_goal_result'] == 'blocked' for p in drive['plays']):
        return 'unclassified', 'blocked field goal or punt in overtime is not classified'
    if any(p['safety'] == 1 for p in drive['plays']):
        return 'safety', 'defense scored a safety'
    if result is None or result not in RESULT_OUTCOME:
        return 'unclassified', f'publisher drive results {sorted(results)} are not one recognised ending'
    outcome = RESULT_OUTCOME[result]
    if outcome == 'touchdown' and scored_by and offense not in scored_by:
        return 'unclassified', 'touchdown result but the scoring team is not the offense'
    if outcome == 'defense_touchdown' and defense not in scored_by and scored_by:
        return 'unclassified', 'defense touchdown result but the scoring team is not the defense'
    return outcome, ''


def build_drives(game_rows, season, source_file, source_hash):
    """The regular-season overtime drives of one game, each with the other team's next start."""
    by_drive = defaultdict(list)
    for row in game_rows:
        if row['qtr'] == OVERTIME_QUARTER and row['drive'] is not None:
            by_drive[row['drive']].append(row)
    ordered = []
    for drive_id in sorted(by_drive, key=lambda d: min(r['play_id'] for r in by_drive[d])):
        rows = sorted(by_drive[drive_id], key=lambda r: r['play_id'])
        offense = next((r['posteam'] for r in rows if r['play_type'] in SCRIMMAGE and r['posteam']), None)
        plays = [r for r in rows if r['play_type'] in SCRIMMAGE]
        if offense is None or not plays:
            continue
        defense = plays[0]['defteam']
        ordered.append({'drive': drive_id, 'offense': offense, 'defense': defense, 'plays': plays, 'rows': rows,
                        'results': {r['fixed_drive_result'] for r in rows if r['fixed_drive_result']}})
    records = []
    for index, drive in enumerate(ordered):
        first, last = drive['plays'][0], drive['plays'][-1]
        all_rows = drive['rows']
        nxt = ordered[index + 1] if index + 1 < len(ordered) else None
        outcome, note = classify({'results': set(drive['results']), 'plays': drive['plays']}, drive['offense'], drive['defense'])
        start_clock = first['game_seconds_remaining']
        end_clock = last['game_seconds_remaining']
        scored_rows = [r for r in all_rows if r['posteam'] and r['defteam']]
        first_row, last_row = scored_rows[0], scored_rows[-1]
        points_offense = score_change(first_row, last_row, drive['offense'])
        points_defense = score_change(first_row, last_row, drive['defense'])
        pat = [r for r in all_rows if r['extra_point_attempt'] == 1 or r['two_point_attempt'] == 1]
        try_kind = try_made = try_team = None
        if pat:
            try_kind = 'two_point' if pat[-1]['two_point_attempt'] == 1 else 'extra_point'
            try_made = (pat[-1]['two_point_conv_result'] == 'success' if try_kind == 'two_point'
                        else pat[-1]['extra_point_result'] == 'good')
            try_team = pat[-1]['posteam']
        status, status_note = 'usable', ''
        scorer_points = {'touchdown': drive['offense'], 'defense_touchdown': drive['defense']}
        if outcome in scorer_points:
            # The drive's own score is six. A point after seen in the drive is removed, so the pool records six points and the
            # engine draws the try from the regulation try rates. A walk-off touchdown (2022-2024) shows no point after.
            points_for_scorer = points_offense if outcome == 'touchdown' else points_defense
            if try_kind is not None and try_team != scorer_points[outcome]:
                outcome, status_note = 'unclassified', 'the observed point after is not the scorer\'s'
            elif points_for_scorer - (try_points(try_kind, try_made) if try_kind else 0) != 6:
                outcome, status_note = 'unclassified', 'the touchdown does not score six before its point after'
            if outcome in scorer_points:
                points_offense, points_defense = ((6 if outcome == 'touchdown' else 0), (0 if outcome == 'touchdown' else 6))
        if outcome == 'field_goal_made' and points_offense != 3:
            outcome, status_note = 'unclassified', 'a made field goal with other than three points'
        if outcome == 'unclassified':
            status, status_note = 'unclassified', status_note or note
        elif start_clock is None or end_clock is None or start_clock < end_clock:
            status, status_note = 'clock_missing', 'the drive has no usable clock'
        elif nxt is None and outcome in ('punt', 'turnover', 'turnover_on_downs', 'field_goal_missed'):
            status, status_note = 'no_next_start', 'the other team has no later drive in this game'
        elif points_offense is None or points_defense is None:
            status, status_note = 'unclassified', 'the score is missing at the drive boundary'
        records.append({
            'game_id': first['game_id'], 'game_date': first['game_date'], 'season': season, 'week': _int(first['week']),
            'drive': drive['drive'], 'offense': drive['offense'], 'defense': drive['defense'],
            'start_yardline_100': _int(first['yardline_100']), 'start_clock_seconds': _int(start_clock),
            'end_clock_seconds': _int(end_clock),
            'duration_seconds': None if start_clock is None or end_clock is None else _int(start_clock - end_clock),
            'plays': len(drive['plays']), 'fixed_drive_result': ';'.join(sorted(drive['results'])),
            'outcome': outcome, 'points_offense': _int(points_offense), 'points_defense': _int(points_defense),
            'next_offense': nxt['offense'] if nxt else '',
            'next_start_yardline_100': _int(nxt['plays'][0]['yardline_100']) if nxt else '',
            'next_start_clock_seconds': _int(nxt['plays'][0]['game_seconds_remaining']) if nxt else '',
            'try_kind': try_kind or '', 'try_made': '' if try_made is None else int(try_made),
            'try_team': try_team or '', 'turnover_kind': turnover_kind(drive['rows']),
            'status': status, 'status_note': status_note, 'source_file': source_file, 'source_sha256': source_hash,
        })
    return records


def main():
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', type=Path, default=DEFAULT_SOURCE)
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    hashes = verify_sources(args.source_dir)
    records = []
    for season in SEASONS:
        name = f'play_by_play_{season}.parquet'
        data = pq.read_table(args.source_dir / name, columns=list(READ_COLUMNS)).to_pydict()
        rows = [{key: data[key][i] for key in READ_COLUMNS} for i in range(len(data['game_id']))]
        games = defaultdict(list)
        for row in rows:
            if row['season_type'] == 'REG' and (row['week'] or 0) <= 18:
                games[row['game_id']].append(row)
        for game_rows in games.values():
            if not any(r['qtr'] == OVERTIME_QUARTER for r in game_rows):
                continue
            game_rows.sort(key=lambda r: r['play_id'])
            records.extend(build_drives(game_rows, season, name, hashes[name]))
    records.sort(key=lambda r: (r['season'], r['game_id'], r['start_clock_seconds'] or 0), reverse=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    usable = [r for r in records if r['status'] == 'usable']
    manifest = {
        'generator': str(Path(__file__).relative_to(REPO)), 'generator_sha256': sha256(__file__),
        'window': '2022-2025 regular season, week <= 18, overtime quarter', 'rule': 'Rule 16, Article 3 (regular season)',
        'engine_assumptions': [
            'first possession: seeded uniform draw, the toss winner receives; the toss and the kick-or-receive choice are not in play-by-play, so the choice is not modelled',
            'touchdowns are recorded at six points; a point after shown in the drive rows is used, otherwise a labelled draw from the regulation try rates',
            'a touchdown that decides the game (sudden death from a tie) takes no try; a touchdown that leaves the game going takes one',
            'current (2025+) overtime rules: a first-possession touchdown does not end the game; 2022-2024 walk-off endings are used for their drive outcome only',
            'Article 5(a) is modelled for an interception or fumble after the first team has scored: the down runs out, and a return touchdown counts with its try',
            'the two-minute warning does not apply in overtime (rules file Section 41 names the second and fourth periods only)',
            'the last drive of each game is never drawn: no next start is observed for it'],
        'source_dataset': 'nflverse play_by_play parquet', 'sources': hashes, 'columns': list(COLUMNS),
        'games_with_overtime': len({r['game_id'] for r in records}), 'drive_count': len(records),
        'usable_count': len(usable), 'status_counts': dict(sorted(Counter(r['status'] for r in records).items())),
        'usable_outcome_counts': dict(sorted(Counter(r['outcome'] for r in usable).items())),
        'output': {'path': str(args.out.relative_to(REPO)) if args.out.is_relative_to(REPO) else str(args.out),
                   'sha256': sha256(args.out)},
    }
    args.out.with_suffix(args.out.suffix + '.manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'games_with_overtime': manifest['games_with_overtime'], 'drives': len(records),
                      'usable': len(usable), 'status_counts': manifest['status_counts'],
                      'usable_outcome_counts': manifest['usable_outcome_counts'], 'sha256': manifest['output']['sha256']},
                     indent=2))


if __name__ == '__main__':
    main()
