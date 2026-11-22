#!/usr/bin/env python3
"""Team timeout decisions after the whistle: how often each team calls a timeout before the next snap.

Run with the pyarrow venv: /root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/build_timeout_decisions.py

nflverse writes a team timeout as its own `no_play` row between two snaps, not as a flag on the play before it. For every
run, pass, punt or field-goal snap that is followed by another scrimmage snap in the same quarter, this records one
observation per team (the offense and the defense at the next snap): did that team call a timeout in between? A team
with no timeouts left cannot call one and is not counted. Snaps followed by a kickoff or a try (a score) and snaps
followed by a quarter change are skipped and counted.

The key describes only what is known at the whistle: the period, the quarter clock at the snap, whether the clock is
running after the play, the score from the team's side, the team's timeouts left, and whether it has the ball next.

Not covered, and counted in the manifest: timeouts before a kickoff or a try, after a kneel, spike, kickoff or try,
and between quarters. They are about a quarter of all team timeouts.

Input: play_by_play_2022..2025.parquet in --source-dir (the same files as build_play_extras.py; SHA-256 in the
manifest). Output: docs/fixtures/e2/timeout_decisions_2022_2025.csv (one row per key with its counts) and a manifest.
Only the E2 window is used (regular season, week <= 18).
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEASONS = (2022, 2023, 2024, 2025)
SNAPS = ('run', 'pass', 'punt', 'field_goal')
NEXT_SCRIMMAGE = SNAPS + ('qb_kneel', 'qb_spike')
SOURCE_COLUMNS = ['game_id', 'play_id', 'season', 'week', 'season_type', 'qtr', 'quarter_seconds_remaining',
                  'play_type', 'posteam', 'defteam', 'home_team', 'away_team', 'timeout', 'timeout_team',
                  'home_timeouts_remaining', 'away_timeouts_remaining', 'total_home_score', 'total_away_score',
                  'incomplete_pass', 'out_of_bounds', 'interception', 'fumble_lost']
KEY = ('period', 'clock', 'clock_state', 'score', 'timeouts_left', 'role')
COLUMNS = KEY + ('team_snaps', 'timeouts_called')
DEFAULT_OUT = REPO / 'docs' / 'fixtures' / 'e2' / 'timeout_decisions_2022_2025.csv'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def period(quarter):
    return {1: 'q1_q3', 3: 'q1_q3', 2: 'q2', 4: 'q4'}.get(quarter, 'overtime')


def clock_bucket(quarter_seconds):
    if quarter_seconds > 300:
        return 'over_5:00'
    return '2:01_to_5:00' if quarter_seconds > 120 else '2:00_or_less'


def score_bucket(margin):
    """The score from the deciding team's side: positive is leading."""
    if margin == 0:
        return 'tied'
    side = 'leading' if margin > 0 else 'trailing'
    return f'{side}_9_plus' if abs(margin) >= 9 else f'{side}_1_to_8'


def clock_state(play_type, incomplete, out_of_bounds, turnover):
    """Running after the play unless it is a kick, an incompletion, a turnover or a play that ends out of bounds."""
    if play_type in ('punt', 'field_goal') or incomplete or out_of_bounds or turnover:
        return 'stopped'
    return 'running'


def observations(rows, counts):
    """(key, called) per team for one game's rows in play order."""
    snaps = [i for i, r in enumerate(rows) if r['play_type'] in NEXT_SCRIMMAGE or r['play_type'] in ('kickoff', 'extra_point')]
    for here, there in zip(snaps, snaps[1:]):
        row, nxt = rows[here], rows[there]
        if row['play_type'] not in SNAPS:
            continue
        if nxt['play_type'] not in NEXT_SCRIMMAGE:
            counts['skipped: next snap is a kickoff or a try'] += 1
            continue
        if nxt['qtr'] != row['qtr']:
            counts['skipped: next snap is in another quarter'] += 1
            continue
        timeout_rows = [r for r in rows[here + 1:there] if r['timeout'] == 1 and r['play_type'] == 'no_play']
        callers = Counter(r['timeout_team'] for r in timeout_rows)
        unattributed = callers.pop(None, 0) + callers.pop('', 0)
        counts['timeouts with no team (excluded)'] += unattributed
        home, away = row['home_team'], row['away_team']
        # nflverse writes a team's timeouts remaining on the play before a timeout already net of that timeout, so a
        # caller's count before its call is the count on its first timeout row plus one.
        left = {home: row['home_timeouts_remaining'], away: row['away_timeouts_remaining']}
        for team, side in ((home, 'home'), (away, 'away')):
            first = next((r for r in timeout_rows if r['timeout_team'] == team), None)
            if first is not None and first[f'{side}_timeouts_remaining'] is not None:
                left[team] = first[f'{side}_timeouts_remaining'] + 1
        score = {home: nxt['total_home_score'] - nxt['total_away_score'], away: nxt['total_away_score'] - nxt['total_home_score']}
        state = clock_state(row['play_type'], row['incomplete_pass'] == 1, row['out_of_bounds'] == 1,
                            row['interception'] == 1 or row['fumble_lost'] == 1)
        for team, role in ((nxt['posteam'], 'offense'), (nxt['defteam'], 'defense')):
            if team not in left or left[team] is None:
                counts['skipped team: no timeout count'] += 1
                continue
            if left[team] <= 0:
                counts['skipped team: no timeouts left'] += 1
                continue
            called = callers.get(team, 0)
            counts['timeouts called'] += called
            yield ((period(row['qtr']), clock_bucket(row['quarter_seconds_remaining']), state, score_bucket(score[team]),
                    str(int(left[team])), role), min(called, 1))
        stray = set(callers) - {nxt['posteam'], nxt['defteam']}
        counts['timeouts by a team not in the game (excluded)'] += sum(callers[t] for t in stray)


def main():
    import pyarrow.parquet as pq

    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', default='/root/nflverse-raw')
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    args = ap.parse_args()
    src, out = Path(args.source_dir), Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'generator': 'scripts/nfl_sequence/build_timeout_decisions.py', 'generator_sha256': sha256(__file__),
                'key': list(KEY), 'window': 'season 2022-2025, season_type REG, week <= 18', 'sources': {}}
    cells, counts = {}, Counter()
    for season in SEASONS:
        path = src / f'play_by_play_{season}.parquet'
        manifest['sources'][path.name] = sha256(path)
        data = pq.read_table(path, columns=SOURCE_COLUMNS).to_pylist()
        games = {}
        for r in data:
            if r['season_type'] == 'REG' and (r['week'] or 0) <= 18:
                games.setdefault(r['game_id'], []).append(r)
        for rows in games.values():
            rows.sort(key=lambda r: r['play_id'])
            for key, called in observations(rows, counts):
                cell = cells.setdefault(key, [0, 0])
                cell[0] += 1
                cell[1] += called
        counts[f'games {season}'] = len(games)
    with open(out, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for key in sorted(cells):
            writer.writerow(key + tuple(cells[key]))
    manifest['counts'] = dict(sorted(counts.items()))
    manifest['output'] = {'path': str(out.relative_to(REPO)), 'sha256': sha256(out), 'cells': len(cells),
                          'team_snaps': sum(c[0] for c in cells.values()),
                          'timeouts_called': sum(c[1] for c in cells.values())}
    Path(str(out) + '.manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    games = sum(v for k, v in counts.items() if k.startswith('games '))
    print(f'wrote {out}: {len(cells)} cells, {manifest["output"]["team_snaps"]} team snaps, '
          f'{manifest["output"]["timeouts_called"]} timeouts over {games} games '
          f'({manifest["output"]["timeouts_called"] / games:.2f} per game)')
    for k, v in sorted(counts.items()):
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
