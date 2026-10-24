#!/usr/bin/env python3
"""Independent legality checker for E2 game records.

Reads a game record (the engine's dict, as in docs/fixtures/e2/e2-game-seed1.json) and checks it against the rules as
restated here. It imports nothing from the engine (game_state, rules_matrix, e1_drive, game_stats): the checks read the
record's own event, state and drive fields and nothing else.

A record is legal when every check returns no findings. A blocked record is never a complete game. Checks that need a
complete game are skipped only for blocked records, and then the blocked status itself is checked.

Usage: python3 legality_check.py RECORD.json
"""
import json
import sys

TEAMS = ('A', 'B')
QUARTERS = (1, 2, 3, 4)
DOWNS = (1, 2, 3, 4, None)
MAX_TIMEOUTS = 3
FULL_QUARTER = 900
def plays_of(record):
    for d in record['drives']:
        for p in d['plays']:
            yield d, p


def check_blocked(record):
    findings = []
    if record.get('status') == 'blocked' and (record.get('complete_regulation') or record.get('complete_game')):
        findings.append(f'blocked record ({record.get("blocker")}) marked as a complete game')
    if record.get('valid_full_game') is True:
        findings.append('valid_full_game is true; E2 never claims a valid full game')
    return findings


def check_completion(record):
    if not record.get('complete_regulation'):
        return []
    findings = []
    if record.get('final_quarter') != 4 or record.get('final_clock_seconds') != 0:
        findings.append(f'complete regulation ends in Q{record.get("final_quarter")} with {record.get("final_clock_seconds")} s')
    quarters = {s['quarter'] for _, p in plays_of(record) for s in (p['state_before'],)}
    missing = [q for q in QUARTERS if q not in quarters]
    if missing:
        findings.append(f'complete regulation with no plays in quarter(s) {missing}')
    return findings


def check_points(record):
    scored = {t: 0 for t in TEAMS}
    for d in record['drives']:
        pts = d.get('points_scored_on_drive') or {}
        if pts:
            scored[pts['team']] += pts['points']
    findings = []
    for t in TEAMS:
        if scored[t] != record['points'].get(t, 0):
            findings.append(f'team {t}: points on drives {scored[t]} != record points {record["points"].get(t, 0)}')
    return findings


def check_drives(record):
    findings = []
    indices = [d['index'] for d in record['drives']]
    if indices != list(range(1, len(indices) + 1)):
        findings.append(f'drive indices are not 1..{len(indices)}: {indices[:6]}')
    for d in record['drives']:
        if d['offense_team'] not in TEAMS:
            findings.append(f'drive {d["index"]}: offense {d["offense_team"]!r} is not A or B')
        for p in d['plays']:
            if p['state_before'].get('drive_index') != d['index'] or p['state_after'].get('drive_index') != d['index']:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: drive_index does not match the drive')
    return findings


def check_clock_and_quarter(record):
    findings = []
    for d in record['drives']:
        seq = d['plays']
        for i, p in enumerate(seq):
            s = p['state_before']
            if not 0 <= s['clock_seconds'] <= FULL_QUARTER:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: clock {s["clock_seconds"]} outside 0..900')
            if s['quarter'] not in QUARTERS:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: quarter {s["quarter"]} is not 1..4')
            if i + 1 < len(seq):
                nxt = seq[i + 1]['state_before']
                if nxt['quarter'] < s['quarter']:
                    findings.append(f'drive {d["index"]}: quarter falls from {s["quarter"]} to {nxt["quarter"]}')
                elif nxt['quarter'] == s['quarter'] and nxt['clock_seconds'] > s['clock_seconds']:
                    findings.append(f'drive {d["index"]}: clock rises from {s["clock_seconds"]} to {nxt["clock_seconds"]} '
                                    f'inside Q{s["quarter"]}')
    return findings


def check_state_continuity(record):
    findings = []
    for d in record['drives']:
        for p in d['plays']:
            before, after = p['state_before'], p['state_after']
            if after['clock_seconds'] > before['clock_seconds'] and after['quarter'] == before['quarter']:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: state_after clock rises inside the quarter')
            if after['quarter'] < before['quarter']:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: state_after quarter falls')
    for d, nxt_d in zip(record['drives'], record['drives'][1:]):
        last = d['plays'][-1] if d['plays'] else None
        if last is None:
            continue
        if nxt_d['plays']:
            first_next = nxt_d['plays'][0]['state_before']
            if first_next['quarter'] == last['state_after']['quarter'] and first_next['clock_seconds'] > last['state_after']['clock_seconds']:
                findings.append(f'drive {nxt_d["index"]}: clock rises at the start of the drive')
    return findings


def check_downs_and_field(record):
    findings = []
    for d, p in plays_of(record):
        for side in ('state_before', 'state_after'):
            s = p[side]
            if s.get('down') not in DOWNS:
                findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: down {s.get("down")!r} is not 1..4')
            if s.get('down') is not None and (s.get('yards_to_go') is None or s['yards_to_go'] < 0):
                findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: yards to go {s.get("yards_to_go")} invalid')
            yl = s.get('yardline_100')
            if yl is not None and not 1 <= yl <= 99:
                findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: yardline_100 {yl} outside 1..99')
    return findings


def check_timeouts(record):
    """Counts stay in 0..3, never rise inside a half, and are three for each side when the second half begins."""
    findings = []
    previous = None  # (quarter, home, away) of the last play's state_before
    for d, p in plays_of(record):
        for side in ('state_before', 'state_after'):
            s = p[side]
            for key in ('home_timeouts', 'away_timeouts'):
                if not 0 <= s[key] <= MAX_TIMEOUTS:
                    findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: {key} {s[key]} outside 0..3')
        s = p['state_before']
        if previous is not None:
            prev_q, prev_home, prev_away = previous
            if prev_q == 2 and s['quarter'] == 3:
                if s['home_timeouts'] != MAX_TIMEOUTS or s['away_timeouts'] != MAX_TIMEOUTS:
                    findings.append(f'drive {d["index"]} play {p["sequence"]}: timeouts do not reset to three at halftime')
            elif (prev_q <= 2) == (s['quarter'] <= 2):
                if s['home_timeouts'] > prev_home or s['away_timeouts'] > prev_away:
                    findings.append(f'drive {d["index"]} play {p["sequence"]}: a team gained timeouts inside a half')
        previous = (s['quarter'], s['home_timeouts'], s['away_timeouts'])
    return findings


def check_possession(record):
    """The side with the next drive is the side the record says has the ball.

    At halftime the next drive is the receiver of the second-half kickoff. After a score or a made field goal it is the
    receiver of the kickoff recorded after that drive. After a punt, a turnover or a missed field goal it is the side on
    the ball in the last play's state_after. A drive with no such record (for example a skipped post-score kickoff at a
    quarter end) is not checked, and the record does not say who gets the ball there.
    """
    findings = []
    drives = record['drives']
    halftime_after = {b['drive_index'] for b in record['boundaries'] if b['kind'] == 'halftime'}
    half_start = {k['quarter']: k for k in record['kickoffs'] if k['kind'] == 'half_start'}
    kick_after = {k['after_drive']: k for k in record['kickoffs'] if k['kind'] != 'half_start'}
    for d, nxt in zip(drives, drives[1:]):
        want = None
        if d['index'] in halftime_after and 3 in half_start:
            want = half_start[3]['receiving_team']
        elif d['index'] in kick_after:
            want = kick_after[d['index']]['receiving_team']
        elif d['terminal'] == 'field_goal_attempt' and d['field_goal_made'] is False:
            want = 'B' if d['offense_team'] == 'A' else 'A'  # a missed kick: the other side takes over at the kick spot
        elif d['terminal'] in ('punt', 'turnover', 'turnover_on_downs'):
            want = d['plays'][-1]['state_after']['offense_team']
        if want is not None and nxt['offense_team'] != want:
            findings.append(f'drive {d["index"]} ends {d["terminal"]}: the next drive is {nxt["offense_team"]}, '
                            f'the record gives the ball to {want}')
    return findings


def check_events(record):
    findings = []
    for d in record['drives']:
        for i, p in enumerate(d['plays']):
            ev = p['event_type']
            if ev == 'punt' and d['terminal'] != 'punt':
                findings.append(f'drive {d["index"]}: a punt play in a drive that ends {d["terminal"]}')
            if ev == 'field_goal_attempt' and (i != len(d['plays']) - 1 or d['terminal'] != 'field_goal_attempt'):
                findings.append(f'drive {d["index"]}: a field goal attempt that is not the last play of the drive')
            if p['outcome'].get('touchdown') and d['terminal'] != 'touchdown':
                findings.append(f'drive {d["index"]}: a touchdown play in a drive that ends {d["terminal"]}')
    for d in record['drives']:
        if d['terminal'] == 'touchdown' and (d.get('points_scored_on_drive') or {}).get('points', 0) < 6:
            findings.append(f'drive {d["index"]}: a touchdown with fewer than six points')
    return findings


CHECKS = (check_blocked, check_completion, check_points, check_drives, check_clock_and_quarter,
          check_state_continuity, check_downs_and_field, check_timeouts, check_possession, check_events)


def run(record):
    """{check name: findings} for every check."""
    return {fn.__name__: fn(record) for fn in CHECKS}


def legal(record):
    return all(not findings for findings in run(record).values())


def main():
    with open(sys.argv[1]) as f:
        record = json.load(f)
    record = record.get('record', record)
    results = run(record)
    failed = {k: v for k, v in results.items() if v}
    print(json.dumps({'legal': not failed, 'checks': len(results), 'failed': failed}, indent=1))
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
