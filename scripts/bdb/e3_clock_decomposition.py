#!/usr/bin/env python3
"""E3 clock decomposition audit on the identifier-verified plays of the 2022 BDB join (weeks 1-9).

Scope. The 15,768 plays the coverage join verified on identifiers and context (`status == verified`). The 134 overtime plays and
the 222 plays whose spot side is NA are not in that set; they are excluded and counted here, with the exclusion labelled.

Every derived quantity carries a label and the rule that decided it:
- observed:      read directly from a source value (a tracking frame time, a play-by-play stamp or flag, a BDB score);
- inferred:      computed from observed values by a stated rule (for example a difference of two observed times);
- unresolvable: the sources cannot supply the quantity for this play; the rule code says why.

Rules (codes appear in the CSV):
- R1  snap time: observed, the time of the play's SNAP frame in the tracking files.
- R2  terminal time: observed, the earliest tracking frame at or after the snap whose event label is a play-ending label
      (TERMINAL). Unresolvable (R2u) when no such frame exists.
- R3  in-play duration: inferred, R2 minus R1, in seconds.
- R4  game-clock delta (snap to next snap, game clock): inferred, the play's game_seconds_remaining minus the next play's in the
      same quarter, from the play-by-play stamps. Unresolvable when there is no same-quarter next play (R4u1), when the next row
      is the quarter-end marker so the runoff is censored at the boundary (R4u2), or when the difference is negative (R4u3).
- R5  residual (clock running with no play in progress): inferred, R4 minus R3. Unresolvable (R5u) when either is.
- R6  real snap-to-next-snap: inferred, the next play's R1 minus this play's R1, when the next same-quarter play is itself
      verified and has a snap frame. Unresolvable (R6u) otherwise.
- R7  outcome type: observed, from the play-by-play flags (touchdown, interception, fumble_lost, sack, play_type, complete_pass).
- R8  offense score differential before the snap: observed, from BDB preSnapHomeScore and preSnapVisitorScore, offense-relative.
- R9  stoppage flags: observed, out_of_bounds and timeout from the nflverse 2022 parquet (via the extracted flags CSV), penalty
      from the play-by-play. A blank timeout flag is unresolvable (R9u) and is not read as "no timeout".
- R10 timeouts remaining: unresolvable (no per-play remaining counts in either source).
- R11 penalty clock stop: unresolvable (the penalty flag gives no stoppage duration and no clock-stop mechanics).
- R12 two-minute warning: unresolvable as an event (not identifiable in the play-by-play). The late-half state
      (second or fourth quarter, quarter clock at or below 120 s) is observed.
- R13 quarter, down, distance, possession, quarter clock at the snap: observed; the join verified them against BDB.

Inputs (all read, none written): tracking_week_1..9.csv and plays.csv, games.csv from the BDB directory; the dev database
(mode=ro); the verified-pairs CSV and the nflverse flags CSV under docs/evidence/e3/inputs/. The old pairs set used by the
denominator reconciliation is also an input.

Usage: python3 e3_clock_decomposition.py [--out-dir DIR]
"""
import argparse
import csv
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import nfl_team_codes  # noqa: E402

BDB = Path('/root/nfl-tracking-data/bdb2025/code-data')
DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
INPUTS = ROOT / 'docs' / 'evidence' / 'e3' / 'inputs'
PAIRS = INPUTS / 'e3-tracking-join-pairs-2026-10-24.csv'
OLD_PAIRS = INPUTS / 'bdb2022-join-pairs-2026-10-24.csv'
FLAGS = INPUTS / 'nflverse-2022-w1-9-flags.csv'
WEEKS = (1, 9)
TEAM = nfl_team_codes.PBP_TEAM_CODE_ALIASES
QUARTER = 900
LATE_CLOCK = 120
BOUNDARY_CLOCKS = (0, 900, 1800, 2700)
TERMINAL = ('tackle', 'out_of_bounds', 'touchdown', 'qb_sack', 'qb_slide', 'qb_kneel', 'qb_spike',
            'pass_outcome_incomplete', 'pass_outcome_interception', 'pass_outcome_touchdown', 'touchback',
            'fumble_defense_recovered', 'qb_strip_sack')
SCRIMMAGE = ('run', 'pass', 'qb_kneel', 'qb_spike')
ELIGIBLE = ('run', 'pass', 'punt', 'field_goal')
COLUMNS = ['bdb_gameId', 'bdb_playId', 'lp_game_id', 'lp_play_id', 'week', 'quarter', 'down', 'distance', 'offense', 'defense',
           'outcome_type', 'offense_score_diff_pre_snap', 'quarter_clock_at_snap_s', 'late_half_snap',
           'snap_time', 'terminal_event', 'terminal_time',
           'in_play_s', 'in_play_label', 'in_play_rule',
           'game_clock_delta_s', 'game_clock_delta_label', 'game_clock_delta_rule',
           'residual_s', 'residual_label', 'residual_rule',
           'real_snap_to_next_snap_s', 'real_snap_label', 'real_snap_rule',
           'flag_out_of_bounds', 'flag_timeout', 'flag_penalty', 'stoppage_context', 'stoppage_label', 'stoppage_rule',
           'timeouts_remaining', 'timeouts_label', 'timeouts_rule',
           'penalty_clock_stop', 'penalty_label', 'penalty_rule',
           'two_minute_warning_event', 'warning_label', 'warning_rule']


def lp_team(abbr):
    return nfl_team_codes.to_pbp_team_code(abbr) if abbr else None


def parse_time(text):
    return datetime.strptime(text, '%Y-%m-%d %H:%M:%S.%f' if '.' in text else '%Y-%m-%d %H:%M:%S')


def bdb_clock(mmss):
    m, s = mmss.split(':')
    return int(m) * 60 + int(s)


def is_marker(row):
    return row['play_type'] is None and row['gsr'] in BOUNDARY_CLOCKS


def outcome_type(r):
    if r['touchdown'] == 1:
        return 'touchdown'
    if r['interception'] == 1:
        return 'interception'
    if r['fumble_lost'] == 1:
        return 'fumble'
    if r['sack'] == 1:
        return 'sack'
    if r['play_type'] == 'run':
        return 'run'
    if r['play_type'] == 'pass':
        return 'pass_complete' if r['complete_pass'] == 1 else 'pass_incomplete'
    if r['play_type'] == 'punt':
        return 'punt'
    return 'other'


def summarise(values):
    if not values:
        return {'n': 0}
    s = sorted(values)
    return {'n': len(values), 'median': round(statistics.median(values), 2),
            'p10': round(s[int(0.10 * (len(s) - 1))], 2), 'p90': round(s[int(0.90 * (len(s) - 1))], 2)}


def load_lp():
    con = sqlite3.connect(DB, uri=True)
    try:
        rows = con.execute(
            "SELECT game_id, play_id, season, week, away_team, home_team, qtr, down, ydstogo, posteam, defteam, "
            "yardline_100, game_seconds_remaining, play_type, touchdown, interception, fumble_lost, sack, complete_pass, "
            "penalty, drive FROM nfl_pbp WHERE season = 2022 AND week BETWEEN ? AND ? ORDER BY game_id, play_id",
            WEEKS).fetchall()
    finally:
        con.close()
    keys = ('game_id', 'play_id', 'season', 'week', 'away_team', 'home_team', 'qtr', 'down', 'ydstogo', 'posteam',
            'defteam', 'yardline_100', 'gsr', 'play_type', 'touchdown', 'interception', 'fumble_lost', 'sack',
            'complete_pass', 'penalty', 'drive')
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d['play_id'] = int(d['play_id'])
        d['qtr'] = None if d['qtr'] is None else int(d['qtr'])
        d['gsr'] = None if d['gsr'] is None else float(d['gsr'])
        out.append(d)
    return out


def load_games():
    games = {}
    with open(BDB / 'games.csv', newline='') as f:
        for g in csv.DictReader(f):
            games[g['gameId']] = {'home': lp_team(g['homeTeamAbbr']), 'away': lp_team(g['visitorTeamAbbr'])}
    return games


def load_bdb_plays():
    plays = {}
    with open(BDB / 'plays.csv', newline='') as f:
        for p in csv.DictReader(f):
            plays[(p['gameId'], str(int(p['playId'])))] = p
    return plays


def load_flags():
    flags = {}
    with open(FLAGS, newline='') as f:
        for r in csv.DictReader(f):
            flags[(r['game_id'], int(float(r['play_id'])))] = r
    return flags


def stream_tracking(keys):
    """SNAP frame time, ball_snap label time, and play-ending events, for the verified plays only."""
    snap, ball_snap, terminal, labels = {}, {}, defaultdict(list), Counter()
    for week in range(WEEKS[0], WEEKS[1] + 1):
        with open(BDB / f'tracking_week_{week}.csv', newline='') as f:
            reader = csv.reader(f)
            next(reader)
            for r in reader:
                key = (r[0], str(int(r[1])))
                if key not in keys:
                    continue
                if r[5] == 'SNAP' and key not in snap:
                    snap[key] = parse_time(r[6])
                event = r[-1]
                if event == 'ball_snap' and key not in ball_snap:
                    ball_snap[key] = parse_time(r[6])
                if event in TERMINAL:
                    terminal[key].append((parse_time(r[6]), event))
                    labels[event] += 1
    return snap, ball_snap, terminal, labels


def next_row(seq, i):
    """(index, status, runoff_s): the next same-quarter row and the runoff rule R4 decides."""
    row = seq[i]
    if i + 1 >= len(seq):
        return None, 'R4u1 no same-quarter next row', None
    nxt = seq[i + 1]
    if nxt['qtr'] != row['qtr']:
        return None, 'R4u1 no same-quarter next row', None
    if is_marker(nxt):
        return i + 1, 'R4u2 quarter-end marker: runoff censored at the boundary', None
    if row['gsr'] is None or nxt['gsr'] is None:
        return i + 1, 'R4u1 missing clock stamp', None
    runoff = round(row['gsr'] - nxt['gsr'], 2)
    if runoff < 0:
        return i + 1, 'R4u3 negative runoff', None
    return i + 1, 'R4 inferred', runoff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default=str(ROOT / 'docs' / 'evidence' / 'e3'))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs = list(csv.DictReader(open(PAIRS, newline='')))
    status = Counter(p['status'] for p in pairs)
    verified = [p for p in pairs if p['status'] == 'verified']
    verified_keys = {(p['bdb_gameId'], str(int(p['bdb_playId']))) for p in verified}
    lp_to_bdb = {(p['lp_game_id'], int(float(p['lp_play_id']))): (p['bdb_gameId'], str(int(p['bdb_playId'])))
                 for p in verified}

    lp_rows = load_lp()
    lp_index = {(r['game_id'], r['play_id']): i for i, r in enumerate(lp_rows)}
    games = load_games()
    bdb_plays = load_bdb_plays()
    flags = load_flags()
    snap, ball_snap, terminal, terminal_labels = stream_tracking(verified_keys)
    consistency = Counter()
    for key in verified_keys:
        if key in snap and key in ball_snap:
            gap = abs((snap[key] - ball_snap[key]).total_seconds())
            consistency['SNAP frame and ball_snap label agree (both present)'] += int(gap == 0)
            consistency['SNAP frame and ball_snap label both present'] += 1
            consistency['largest SNAP vs ball_snap gap, seconds x100'] = max(
                consistency.get('largest SNAP vs ball_snap gap, seconds x100', 0), int(round(gap * 100)))
        elif key in snap:
            consistency['SNAP frame with no ball_snap label'] += 1

    # the per-game sequences, for the next-row rules
    seq_by_game = defaultdict(list)
    for r in lp_rows:
        seq_by_game[r['game_id']].append(r)
    position = {}
    for gid, seq in seq_by_game.items():
        for i, r in enumerate(seq):
            position[(gid, r['play_id'])] = (gid, i)

    rows, label_counts, unresolvable = [], defaultdict(Counter), defaultdict(Counter)

    def note(column, label, rule):
        label_counts[column][label] += 1
        if label == 'unresolvable':
            unresolvable[column][rule] += 1

    for p in verified:
        bkey = (p['bdb_gameId'], str(int(p['bdb_playId'])))
        lkey = (p['lp_game_id'], int(float(p['lp_play_id'])))
        gid, i = position[lkey]
        seq = seq_by_game[gid]
        lp = seq[i]
        bdb = bdb_plays[bkey]
        game = games[bkey[0]]
        offense = lp_team(bdb['possessionTeam'])
        qsr = int(lp['gsr'] - (4 - lp['qtr']) * QUARTER) if lp['gsr'] is not None else None
        late = lp['qtr'] in (2, 4) and qsr is not None and qsr <= LATE_CLOCK
        diff = (int(bdb['preSnapHomeScore']) - int(bdb['preSnapVisitorScore'])) * (1 if offense == game['home'] else -1)
        row = {'bdb_gameId': bkey[0], 'bdb_playId': bkey[1], 'lp_game_id': lkey[0], 'lp_play_id': lkey[1],
               'week': lp['week'], 'quarter': lp['qtr'], 'down': lp['down'], 'distance': lp['ydstogo'],
               'offense': offense, 'defense': lp_team(bdb['defensiveTeam']), 'outcome_type': outcome_type(lp),
               'offense_score_diff_pre_snap': diff, 'quarter_clock_at_snap_s': qsr,
               'late_half_snap': int(late)}
        consistency['clock agrees with BDB'] += int(bdb_clock(bdb['gameClock']) == qsr)
        consistency['quarter agrees with BDB'] += int(int(bdb['quarter']) == lp['qtr'])

        # R1 snap, R2 terminal, R3 in-play
        s = snap.get(bkey)
        if s is None:
            row.update(snap_time='', terminal_event='', terminal_time='', in_play_s='')
            in_play_label, in_play_rule = 'unresolvable', 'R2u no snap frame'
        else:
            ends = sorted((t, e) for t, e in terminal.get(bkey, []) if t >= s)
            row['snap_time'] = s.isoformat(sep=' ')
            if not ends:
                row.update(terminal_event='', terminal_time='', in_play_s='')
                in_play_label, in_play_rule = 'unresolvable', 'R2u no play-ending event at or after the snap'
            else:
                t, e = ends[0]
                row.update(terminal_event=e, terminal_time=t.isoformat(sep=' '),
                           in_play_s=round((t - s).total_seconds(), 2))
                in_play_label, in_play_rule = 'inferred', 'R3 inferred: R2 minus R1'
        row.update(in_play_label=in_play_label, in_play_rule=in_play_rule)
        note('in_play_s', in_play_label, in_play_rule.split(':')[0].split(' ')[0])

        # R4 game-clock delta, R5 residual
        _, rule4, runoff = next_row(seq, i)
        if runoff is None:
            row.update(game_clock_delta_s='', game_clock_delta_label='unresolvable', game_clock_delta_rule=rule4)
            note('game_clock_delta_s', 'unresolvable', rule4.split(' ')[0])
        else:
            row.update(game_clock_delta_s=runoff, game_clock_delta_label='inferred',
                       game_clock_delta_rule='R4 inferred: game_seconds_remaining minus the next same-quarter play')
            note('game_clock_delta_s', 'inferred', 'R4')
        if runoff is not None and in_play_label == 'inferred':
            residual = round(runoff - row['in_play_s'], 2)
            row.update(residual_s=residual, residual_label='inferred', residual_rule='R5 inferred: R4 minus R3')
            note('residual_s', 'inferred', 'R5')
        else:
            reason = 'R5u' + (' (R4 unresolvable)' if runoff is None else ' (R3 unresolvable)')
            row.update(residual_s='', residual_label='unresolvable', residual_rule=reason)
            note('residual_s', 'unresolvable', 'R5u')

        # R6 real snap-to-next-snap, from the next same-quarter play when it is verified
        nxt_index, _, _ = next_row(seq, i)
        real = ''
        if nxt_index is None or is_marker(seq[nxt_index]):
            rule6 = 'R6u no same-quarter next play'
        else:
            nkey = (gid, seq[nxt_index]['play_id'])
            bnext = lp_to_bdb.get(nkey)
            if bnext is None or snap.get(bnext) is None or s is None:
                rule6 = 'R6u next play is not a verified tracked play'
            else:
                real = round((snap[bnext] - s).total_seconds(), 2)
                rule6 = 'R6 inferred: next verified play R1 minus R1'
        row.update(real_snap_to_next_snap_s=real,
                   real_snap_label='inferred' if real != '' else 'unresolvable',
                   real_snap_rule=rule6)
        note('real_snap_to_next_snap_s', 'inferred' if real != '' else 'unresolvable', rule6.split(' ')[0])

        # R9 stoppage flags and context
        f = flags.get(lkey)
        oob = None if f is None or f['out_of_bounds'] == '' else int(float(f['out_of_bounds']))
        timeout = None if f is None or f['timeout'] == '' else int(float(f['timeout']))
        penalty = None if lp['penalty'] is None else int(lp['penalty'])
        row.update(flag_out_of_bounds='' if oob is None else oob, flag_timeout='' if timeout is None else timeout,
                   flag_penalty='' if penalty is None else penalty)
        if penalty == 1:
            context = 'penalty'
        elif timeout == 1:
            context = 'timeout'
        elif oob == 1:
            context = 'out_of_bounds'
        elif outcome_type(lp) == 'pass_incomplete':
            context = 'incomplete_pass'
        elif outcome_type(lp) == 'touchdown':
            context = 'touchdown'
        elif outcome_type(lp) in ('interception', 'fumble'):
            context = 'turnover'
        elif outcome_type(lp) == 'sack':
            context = 'sack'
        else:
            context = 'none_observed'
        if timeout is None and context == 'none_observed':
            stop_label, stop_rule = 'unresolvable', 'R9u timeout flag blank: a stoppage cannot be ruled out'
        else:
            stop_label, stop_rule = 'observed', 'R9 observed: flags from the nflverse parquet and the play-by-play'
        row.update(stoppage_context=context, stoppage_label=stop_label, stoppage_rule=stop_rule)
        note('stoppage_context', stop_label, stop_rule.split(' ')[0])

        # R10, R11, R12: unresolvable by construction, recorded per row
        row.update(timeouts_remaining='', timeouts_label='unresolvable',
                   timeouts_rule='R10u no per-play remaining counts in either source')
        note('timeouts_remaining', 'unresolvable', 'R10u')
        row.update(penalty_clock_stop='', penalty_label='unresolvable',
                   penalty_rule='R11u the penalty flag gives no stoppage duration or clock-stop mechanics')
        note('penalty_clock_stop', 'unresolvable', 'R11u')
        row.update(two_minute_warning_event='', warning_label='unresolvable',
                   warning_rule='R12u the warning is not identifiable in the play-by-play; the late-half state is observed')
        note('two_minute_warning_event', 'unresolvable', 'R12u')

        rows.append(row)

    consistency['verified plays'] = len(rows)
    stoppage_counts = Counter(r['stoppage_context'] for r in rows)
    late_counts = Counter(r['late_half_snap'] for r in rows)

    # summaries
    by_outcome = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for field in ('in_play_s', 'game_clock_delta_s', 'residual_s', 'real_snap_to_next_snap_s'):
            if r[field] != '':
                by_outcome[r['outcome_type']][field].append(float(r[field]))
    outcome_summary = {o: {f: summarise(v) for f, v in fields.items()} for o, fields in sorted(by_outcome.items())}
    terminal_used = Counter(r['terminal_event'] for r in rows if r['terminal_event'])
    paired = defaultdict(list)
    for r in rows:
        if r['real_snap_to_next_snap_s'] != '' and r['game_clock_delta_s'] != '':
            paired[r['outcome_type']].append(float(r['real_snap_to_next_snap_s']) - float(r['game_clock_delta_s']))
    paired_summary = {}
    for o, diffs in sorted(paired.items()):
        s_ = sorted(diffs)
        paired_summary[o] = {'n': len(diffs), 'median_real_minus_clock_s': round(statistics.median(diffs), 2),
                             'p10': round(s_[int(0.10 * (len(s_) - 1))], 2),
                             'p90': round(s_[int(0.90 * (len(s_) - 1))], 2),
                             'share_real_exceeds_clock_by_over_5s': round(sum(1 for x in diffs if x > 5) / len(diffs), 3),
                             'share_clock_exceeds_real_by_over_5s': round(sum(1 for x in diffs if x < -5) / len(diffs), 3)}

    # denominator reconciliation: the earlier 3,091, reproduced from the LP rows
    lp_groups = {(r['game_id'], r['drive']) for r in lp_rows if r['season'] == 2022}
    null_groups = {g for g in lp_groups if g[1] is None}
    lp_eligible = defaultdict(list)
    for r in lp_rows:
        lp_eligible[(r['game_id'], r['drive'])].append(r)
    eligible = {k for k, plays in lp_eligible.items() if any(p['play_type'] in ELIGIBLE for p in plays)}
    old_pairs = list(csv.DictReader(open(OLD_PAIRS, newline='')))
    old_tracked = {(p['lp_game_id'], int(float(p['lp_play_id']))) for p in old_pairs}
    new_tracked = {(r['lp_game_id'], r['lp_play_id']) for r in rows}

    def classify(tracked, keys):
        counts = Counter()
        for k in keys:
            plays = lp_eligible[k]
            pool = [(p['game_id'], p['play_id']) in tracked for p in plays if p['play_type'] in ELIGIBLE]
            counts['complete' if all(pool) else ('partial' if any(pool) else 'none')] += 1
        return dict(counts)

    denominator = {
        'lp_game_drive_groups_including_null_drive': len(lp_groups),
        'null_drive_groups (one per game)': len(null_groups),
        'real_drives (drive not null)': len(lp_groups) - len(null_groups),
        'groups_with_a_run_pass_punt_or_fg': len(eligible),
        'of_which_null_drive_groups': len([g for g in eligible if g[1] is None]),
        'earlier_classified_total_2849_reproduced_with_old_pairs_including_null':
            classify(old_tracked, eligible),
        'earlier_classified_total_without_null_groups_old_pairs':
            classify(old_tracked, [g for g in eligible if g[1] is not None]),
        'current_verified_set_real_drives_only': classify(new_tracked, [g for g in eligible if g[1] is not None]),
        'old_pairs': len(old_pairs), 'current_verified': len(rows),
    }

    exclusions = {'overtime (quarter 5), not in the verified set': status.get('overtime_unverified', 0),
                  'spot side NA, not in the verified set': status.get('unverified', 0),
                  'included': len(rows)}
    result = {
        'scope': exclusions, 'pairs_input': {'file': 'docs/evidence/e3/inputs/e3-tracking-join-pairs-2026-10-24.csv',
                                             'rows_by_status': dict(status)},
        'labels': {c: dict(label_counts[c]) for c in label_counts},
        'unresolvable_by_rule': {c: dict(unresolvable[c]) for c in unresolvable},
        'outcome_summary_seconds': outcome_summary,
        'terminal_events_used': dict(terminal_used),
        'paired_real_snap_gap_minus_game_clock_delta': paired_summary,
        'tracking_label_counts_for_terminal_events': dict(terminal_labels),
        'consistency': dict(consistency),
        'stoppage_context_counts': dict(stoppage_counts),
        'late_half_snap_counts': {'late half (second or fourth quarter, quarter clock at or below 120 s)': late_counts[1],
                                  'otherwise': late_counts[0]},
        'denominator_reconciliation': denominator,
    }
    csv_path = out_dir / 'e3-clock-decomposition-2026-10-24.csv'
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / 'e3-clock-decomposition-2026-10-24.json').write_text(
        json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: result[k] for k in ('scope', 'labels', 'unresolvable_by_rule', 'denominator_reconciliation')},
                     indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
